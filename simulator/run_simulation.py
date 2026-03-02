"""
run_simulation.py -- BaselineMLB Monte Carlo Simulator CLI Entry Point
=======================================================================

Orchestrates the full daily simulation pipeline:
  1. Fetch today's MLB games from the Stats API
  2. Prepare game data (Statcast metrics, lineups, umpires, weather)
  3. Run Monte Carlo simulations for each game
  4. Fetch prop lines from Supabase (or a local file)
  5. Analyze props and identify edges
  6. Output results in JSON / Markdown / CSV / Supabase / Twitter format
  7. Print a summary of top edges with glass-box explanations

Backtest Mode
-------------
Pass ``--backtest`` to simulate a historical date using only pre-game data,
then compare projections to actual boxscore results and compute accuracy metrics.

GitHub Actions Integration
---------------------------
Add the following job to your ``.github/workflows/pipelines.yml``:

.. code-block:: yaml

    simulation:
      runs-on: ubuntu-latest
      steps:
        - uses: actions/checkout@v4
        - uses: actions/setup-python@v5
          with:
            python-version: '3.11'
        - run: pip install -r requirements.txt
        - run: python -m simulation.run_simulation --upload --output json markdown
          env:
            SUPABASE_URL: ${{ secrets.SUPABASE_URL }}
            SUPABASE_KEY: ${{ secrets.SUPABASE_SERVICE_KEY }}

Usage Examples
--------------
::

    # Run today's games with all outputs (default)
    python -m simulation.run_simulation

    # Specific date, 5000 simulations, JSON only
    python -m simulation.run_simulation --date 2025-07-04 --simulations 5000 --output json

    # Single game, verbose, dry run
    python -m simulation.run_simulation --game-pk 746395 --verbose --dry-run

    # Upload results to Supabase and post Twitter summary
    python -m simulation.run_simulation --upload --twitter

    # Backtest a past date
    python -m simulation.run_simulation --backtest --backtest-date 2025-06-01
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import math
import os
import sys
import time
import traceback
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

# ---------------------------------------------------------------------------
# Internal imports (graceful fallbacks so CI can import the module even if
# optional deps are missing)
# ---------------------------------------------------------------------------
try:
    from simulator.config import (
        DEFAULT_CONFIG,
        SimulationConfig,
        configure_logging,
    )
except ImportError:  # pragma: no cover
    DEFAULT_CONFIG = None  # type: ignore[assignment]
    SimulationConfig = None  # type: ignore[assignment,misc]

    def configure_logging(level=logging.INFO, **_kw):  # type: ignore[misc]
        logging.basicConfig(level=level)
        return logging.getLogger("baselinemlb")


try:
    from simulator.data_prep import (
        DataPrepPipeline,
        GameData,
        MLBApiClient,
        SupabaseReader,
    )
    _DATA_PREP_AVAILABLE = True
except ImportError:  # pragma: no cover
    _DATA_PREP_AVAILABLE = False
    DataPrepPipeline = None  # type: ignore[assignment,misc]
    GameData = None  # type: ignore[assignment,misc]
    MLBApiClient = None  # type: ignore[assignment,misc]
    SupabaseReader = None  # type: ignore[assignment,misc]

try:
    from simulator.game_engine import GameSimulator, SimulationResult
    _ENGINE_AVAILABLE = True
except ImportError:  # pragma: no cover
    _ENGINE_AVAILABLE = False
    GameSimulator = None  # type: ignore[assignment,misc]
    SimulationResult = None  # type: ignore[assignment,misc]

try:
    from simulator.matchup_model import MatchupModel
    _MODEL_AVAILABLE = True
except ImportError:  # pragma: no cover
    _MODEL_AVAILABLE = False
    MatchupModel = None  # type: ignore[assignment,misc]

logger = logging.getLogger("baselinemlb.run_simulation")

# ---------------------------------------------------------------------------
# Lightweight progress bar (no third-party deps required)
# ---------------------------------------------------------------------------

def _progress_bar(current: int, total: int, width: int = 40, prefix: str = "") -> None:
    """Print an in-place ASCII progress bar to stderr."""
    if total == 0:
        return
    pct = current / total
    filled = int(width * pct)
    bar = "#" * filled + "." * (width - filled)
    label = f"{prefix}[{bar}] {current}/{total} ({pct:.0%})"
    print(f"\r{label}", end="", flush=True, file=sys.stderr)
    if current >= total:
        print(file=sys.stderr)  # newline at completion


# ---------------------------------------------------------------------------
# PropAnalysis dataclass
# ---------------------------------------------------------------------------

@dataclass
class PropAnalysis:
    """Encapsulates the edge analysis for a single player prop."""

    game_pk: int
    player_id: int
    player_name: str
    team: str
    stat: str
    line: float
    book_over_odds: int        # American odds, e.g. -115
    book_under_odds: int       # American odds, e.g. -105
    sim_p_over: float          # probability > line from simulation
    sim_mean: float
    sim_std: float
    ev_over: float             # expected value on the over
    ev_under: float            # expected value on the under
    edge: float                # max(ev_over, ev_under)
    recommendation: str        # 'OVER', 'UNDER', or 'PASS'
    explanation: str           # glass-box text
    game_date: str = ""
    away_team: str = ""
    home_team: str = ""

    # Convenience -------------------------------------------------------

    @property
    def has_edge(self) -> bool:
        return self.edge > 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "game_pk": self.game_pk,
            "game_date": self.game_date,
            "away_team": self.away_team,
            "home_team": self.home_team,
            "player_id": self.player_id,
            "player_name": self.player_name,
            "team": self.team,
            "stat": self.stat,
            "line": self.line,
            "book_over_odds": self.book_over_odds,
            "book_under_odds": self.book_under_odds,
            "sim_p_over": round(self.sim_p_over, 4),
            "sim_mean": round(self.sim_mean, 4),
            "sim_std": round(self.sim_std, 4),
            "ev_over": round(self.ev_over, 4),
            "ev_under": round(self.ev_under, 4),
            "edge": round(self.edge, 4),
            "recommendation": self.recommendation,
            "explanation": self.explanation,
        }


# ---------------------------------------------------------------------------
# PropAnalyzer
# ---------------------------------------------------------------------------

class PropAnalyzer:
    """
    Compares simulation-derived probabilities against sportsbook prop lines
    to identify edges.

    Parameters
    ----------
    config : SimulationConfig
        Used for EV_THRESHOLD, KELLY_FRACTION, MAX_KELLY_BET.
    matchup_model : MatchupModel | None
        If provided, used to generate glass-box explanations via
        ``explain_prediction()``.
    """

    def __init__(
        self,
        config: Optional[Any] = None,
        matchup_model: Optional[Any] = None,
    ) -> None:
        self._cfg = config or DEFAULT_CONFIG
        self._model = matchup_model

    # ------------------------------------------------------------------
    # American-odds helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _implied_prob(american_odds: int) -> float:
        """Convert American odds to implied probability (no-vig NOT removed)."""
        if american_odds > 0:
            return 100 / (american_odds + 100)
        return abs(american_odds) / (abs(american_odds) + 100)

    @staticmethod
    def _ev(sim_prob: float, american_odds: int) -> float:
        """
        Expected value per $1 wagered given a simulation probability
        and sportsbook American odds.
        """
        if american_odds > 0:
            profit_if_win = american_odds / 100
        else:
            profit_if_win = 100 / abs(american_odds)

        return sim_prob * profit_if_win - (1 - sim_prob) * 1.0

    # ------------------------------------------------------------------
    # Core analysis
    # ------------------------------------------------------------------

    def analyze_prop(
        self,
        game_pk: int,
        player_id: int,
        player_name: str,
        team: str,
        stat: str,
        line: float,
        book_over_odds: int,
        book_under_odds: int,
        sim_result: "SimulationResult",
        game_data: Optional[Any] = None,
    ) -> Optional[PropAnalysis]:
        """
        Analyse a single prop line against the simulation result.

        Returns
        -------
        PropAnalysis | None
            None if the player was not simulated or the stat is unavailable.
        """
        try:
            ps_obj = sim_result.player_results.get(player_id)
            if ps_obj is None:
                logger.debug(
                    "PropAnalyzer: player %s (%s) not found in sim results for game %s",
                    player_id, player_name, game_pk,
                )
                return None

            if not ps_obj.stat_counts.get(stat):
                logger.debug(
                    "PropAnalyzer: stat '%s' not recorded for player %s in game %s",
                    stat, player_id, game_pk,
                )
                return None

            sim_p_over = ps_obj.get_p_over(stat, line)
            sim_p_under = 1.0 - sim_p_over
            sim_mean = ps_obj.get_mean(stat)
            sim_std = ps_obj.get_std(stat)

            ev_over = self._ev(sim_p_over, book_over_odds)
            ev_under = self._ev(sim_p_under, book_under_odds)

            edge = max(ev_over, ev_under)
            getattr(self._cfg, "EV_THRESHOLD", 0.03) if self._cfg else 0.03

            if ev_over >= ev_under and ev_over > 0:
                recommendation = "OVER"
            elif ev_under > ev_over and ev_under > 0:
                recommendation = "UNDER"
            else:
                recommendation = "PASS"

            # Glass-box explanation
            explanation = self._build_explanation(
                player_name=player_name,
                stat=stat,
                line=line,
                sim_p_over=sim_p_over,
                sim_mean=sim_mean,
                book_over_odds=book_over_odds,
                book_under_odds=book_under_odds,
                ev_over=ev_over,
                ev_under=ev_under,
                recommendation=recommendation,
                game_data=game_data,
            )

            game_info = sim_result.game_info
            return PropAnalysis(
                game_pk=game_pk,
                player_id=player_id,
                player_name=player_name,
                team=team,
                stat=stat,
                line=line,
                book_over_odds=book_over_odds,
                book_under_odds=book_under_odds,
                sim_p_over=sim_p_over,
                sim_mean=sim_mean,
                sim_std=sim_std,
                ev_over=ev_over,
                ev_under=ev_under,
                edge=edge,
                recommendation=recommendation,
                explanation=explanation,
                game_date=game_info.get("game_date", ""),
                away_team=game_info.get("away_team", ""),
                home_team=game_info.get("home_team", ""),
            )

        except Exception as exc:
            logger.warning(
                "PropAnalyzer.analyze_prop failed for player %s stat %s: %s",
                player_id, stat, exc,
            )
            return None

    def analyze_game(
        self,
        sim_result: "SimulationResult",
        prop_lines: List[Dict[str, Any]],
        game_data: Optional[Any] = None,
    ) -> List[PropAnalysis]:
        """
        Analyse all prop lines for a single game's simulation result.

        Parameters
        ----------
        sim_result : SimulationResult
            The simulation output for this game.
        prop_lines : list of dict
            Each dict must have keys: player_id, player_name, team, stat,
            line, over_odds, under_odds.
        game_data : GameData | None
            Optional game context for richer explanations.

        Returns
        -------
        list of PropAnalysis
        """
        analyses: List[PropAnalysis] = []
        game_pk = sim_result.game_info.get("game_pk", 0)

        for prop in prop_lines:
            analysis = self.analyze_prop(
                game_pk=game_pk,
                player_id=prop.get("player_id", 0),
                player_name=prop.get("player_name", "Unknown"),
                team=prop.get("team", ""),
                stat=prop.get("stat", ""),
                line=float(prop.get("line", 0.5)),
                book_over_odds=int(prop.get("over_odds", -110)),
                book_under_odds=int(prop.get("under_odds", -110)),
                sim_result=sim_result,
                game_data=game_data,
            )
            if analysis is not None:
                analyses.append(analysis)

        return analyses

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _build_explanation(
        self,
        *,
        player_name: str,
        stat: str,
        line: float,
        sim_p_over: float,
        sim_mean: float,
        book_over_odds: int,
        book_under_odds: int,
        ev_over: float,
        ev_under: float,
        recommendation: str,
        game_data: Optional[Any],
    ) -> str:
        """Build a concise, human-readable glass-box explanation."""
        implied_over = self._implied_prob(book_over_odds)
        implied_under = self._implied_prob(book_under_odds)
        p_under = 1.0 - sim_p_over

        lines = [
            f"{player_name} | {stat.upper()} {'OVER' if recommendation == 'OVER' else 'UNDER'} {line}",
            f"  Sim mean: {sim_mean:.2f}  |  Sim P(over {line}): {sim_p_over:.1%}  |  Sim P(under {line}): {p_under:.1%}",
            f"  Book implied over: {implied_over:.1%}  |  Book implied under: {implied_under:.1%}",
            f"  EV over: {ev_over:+.3f}  |  EV under: {ev_under:+.3f}  |  Recommendation: {recommendation}",
        ]

        # Add game-day context if available
        if game_data is not None:
            try:
                venue = getattr(game_data, "venue", "")
                temp = getattr(game_data, "temp_f", None)
                wind = getattr(game_data, "wind_speed_mph", None)
                ump = getattr(getattr(game_data, "umpire", None), "name", None)
                ctx_parts = []
                if venue:
                    ctx_parts.append(f"Venue: {venue}")
                if temp is not None:
                    ctx_parts.append(f"Temp: {temp:.0f}degF")
                if wind is not None:
                    ctx_parts.append(f"Wind: {wind:.0f} mph")
                if ump:
                    ctx_parts.append(f"Umpire: {ump}")
                if ctx_parts:
                    lines.append(f"  Context: {' | '.join(ctx_parts)}")
            except Exception:
                pass

        return "\n".join(lines)


# ---------------------------------------------------------------------------
# OutputWriter
# ---------------------------------------------------------------------------

class OutputWriter:
    """
    Handles all output formats: JSON, Markdown, CSV, Supabase upsert, Twitter.

    Parameters
    ----------
    output_dir : str | Path
        Directory where files will be written (created if needed).
    date_str : str
        Date string used in filenames, e.g. ``'2025-07-04'``.
    """

    def __init__(self, output_dir: str = "output", date_str: str = "") -> None:
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.date_str = date_str or date.today().isoformat()

    # ------------------------------------------------------------------
    # JSON
    # ------------------------------------------------------------------

    def write_json(
        self,
        sim_results: List["SimulationResult"],
        analyses: List[PropAnalysis],
    ) -> Path:
        """
        Write full simulation results + prop analyses to a JSON file.

        Returns the path written.
        """
        path = self.output_dir / f"{self.date_str}_simulation.json"
        try:
            payload: Dict[str, Any] = {
                "generated_at": datetime.utcnow().isoformat() + "Z",
                "date": self.date_str,
                "num_games": len(sim_results),
                "games": [],
                "prop_analyses": [a.to_dict() for a in analyses],
            }

            for result in sim_results:
                try:
                    payload["games"].append(json.loads(result.to_json()))
                except Exception as exc:
                    logger.warning("JSON serialisation failed for game: %s", exc)
                    payload["games"].append({"error": str(exc), "game_info": result.game_info})

            with open(path, "w", encoding="utf-8") as fh:
                json.dump(payload, fh, indent=2, default=str)

            logger.info("JSON output written to %s", path)
        except Exception as exc:
            logger.error("write_json failed: %s", exc)

        return path

    # ------------------------------------------------------------------
    # Markdown
    # ------------------------------------------------------------------

    def write_markdown(
        self,
        sim_results: List["SimulationResult"],
        analyses: List[PropAnalysis],
    ) -> Path:
        """Write a human-readable Markdown report."""
        path = self.output_dir / f"{self.date_str}_report.md"
        try:
            edges = [a for a in analyses if a.has_edge]
            edges.sort(key=lambda a: a.edge, reverse=True)

            lines: List[str] = [
                f"# BaselineMLB Simulation Report -- {self.date_str}",
                f"*Generated: {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}*",
                "",
                "## Summary",
                f"- **Games simulated:** {len(sim_results)}",
                f"- **Props analysed:** {len(analyses)}",
                f"- **Edges found:** {len(edges)}",
                "",
            ]

            # --- Game results ---
            lines += ["## Games", ""]
            for result in sim_results:
                gi = result.game_info
                away = gi.get("away_team", "AWAY")
                home = gi.get("home_team", "HOME")
                n = result.num_simulations
                away_win_pct = result.team_results.get("away", {}).get("wins", 0) / max(n, 1)
                home_win_pct = result.team_results.get("home", {}).get("wins", 0) / max(n, 1)
                lines += [
                    f"### {away} @ {home}",
                    f"| Metric | {away} | {home} |",
                    "|--------|--------|--------|",
                    f"| Win % | {away_win_pct:.1%} | {home_win_pct:.1%} |",
                    "",
                ]

                # Top pitcher projection
                for side, label in [("away", away), ("home", home)]:
                    gi.get("pitchers", {})
                    # Try to find pitcher ids stored in game_info
                    p_id_key = f"{side}_pitcher_id"
                    p_id = gi.get(p_id_key)
                    if p_id and p_id in result.player_results:
                        ps = result.player_results[p_id]
                        k_mean = ps.get_mean("strikeouts")
                        k_p55 = ps.get_p_over("strikeouts", 5.5)
                        k_p45 = ps.get_p_over("strikeouts", 4.5)
                        lines.append(
                            f"**{ps.player_name} ({label} SP):** "
                            f"proj {k_mean:.1f} K | P(K>4.5)={k_p45:.1%} | P(K>5.5)={k_p55:.1%}"
                        )
                lines.append("")

            # --- Edges ---
            if edges:
                lines += ["## Top Edges", ""]
                lines += [
                    "| Player | Stat | Line | Rec | Sim P(Over) | EV | Game |",
                    "|--------|------|------|-----|-------------|-----|------|",
                ]
                for a in edges[:20]:
                    game_label = f"{a.away_team}@{a.home_team}" if a.away_team else str(a.game_pk)
                    ev_val = a.ev_over if a.recommendation == "OVER" else a.ev_under
                    lines.append(
                        f"| {a.player_name} | {a.stat} | {a.line} | **{a.recommendation}** "
                        f"| {a.sim_p_over:.1%} | {ev_val:+.3f} | {game_label} |"
                    )
                lines.append("")

                lines += ["## Edge Details", ""]
                for a in edges[:10]:
                    lines += [f"```\n{a.explanation}\n```", ""]
            else:
                lines += ["## Edges", "", "*No edges found today.*", ""]

            with open(path, "w", encoding="utf-8") as fh:
                fh.write("\n".join(lines))

            logger.info("Markdown report written to %s", path)
        except Exception as exc:
            logger.error("write_markdown failed: %s", exc)

        return path

    # ------------------------------------------------------------------
    # CSV
    # ------------------------------------------------------------------

    def write_csv(self, analyses: List[PropAnalysis]) -> Path:
        """Write a flat CSV table of all prop analyses."""
        path = self.output_dir / f"{self.date_str}_results.csv"
        try:
            if not analyses:
                logger.info("No analyses to write to CSV.")
                path.touch()
                return path

            fieldnames = list(analyses[0].to_dict().keys())
            with open(path, "w", newline="", encoding="utf-8") as fh:
                writer = csv.DictWriter(fh, fieldnames=fieldnames)
                writer.writeheader()
                for a in analyses:
                    writer.writerow(a.to_dict())

            logger.info("CSV output written to %s (%d rows)", path, len(analyses))
        except Exception as exc:
            logger.error("write_csv failed: %s", exc)

        return path

    # ------------------------------------------------------------------
    # Supabase
    # ------------------------------------------------------------------

    def upload_to_supabase(
        self,
        sim_results: List["SimulationResult"],
        analyses: List[PropAnalysis],
    ) -> None:
        """
        Upsert projections and prop analyses to Supabase.

        Tables targeted:
          * ``projections``      -- per-player-stat projection rows
          * ``prop_analyses``    -- edge analysis rows
        """
        try:
            from supabase import Client, create_client  # type: ignore

            url = os.environ.get("SUPABASE_URL", "")
            key = os.environ.get("SUPABASE_KEY", "")
            if not url or not key:
                logger.error(
                    "SUPABASE_URL / SUPABASE_KEY not set -- skipping upload."
                )
                return

            client: Client = create_client(url, key)
            logger.info("Uploading to Supabase...")

            # Projections
            proj_rows: List[Dict[str, Any]] = []
            for result in sim_results:
                try:
                    proj_rows.extend(result.get_all_projections())
                except Exception as exc:
                    logger.warning("get_all_projections failed: %s", exc)

            if proj_rows:
                _supabase_upsert_batched(client, "projections", proj_rows)
                logger.info("Upserted %d projection rows.", len(proj_rows))

            # Prop analyses
            if analyses:
                analysis_rows = [a.to_dict() for a in analyses]
                _supabase_upsert_batched(client, "prop_analyses", analysis_rows)
                logger.info("Upserted %d prop analysis rows.", len(analyses))

        except ImportError:
            logger.error(
                "supabase-py is not installed.  Run: pip install supabase"
            )
        except Exception as exc:
            logger.error("upload_to_supabase failed: %s", exc)

    # ------------------------------------------------------------------
    # Twitter
    # ------------------------------------------------------------------

    def format_twitter(self, analyses: List[PropAnalysis]) -> str:
        """
        Return a Twitter-ready text summary of top edges (<= 280 chars each).
        """
        edges = sorted(
            [a for a in analyses if a.has_edge and a.recommendation != "PASS"],
            key=lambda a: a.edge,
            reverse=True,
        )
        if not edges:
            return f"[baseball] BaselineMLB ({self.date_str}): No strong edges found today. #MLB #Props"

        tweet_lines = [f"[baseball] BaselineMLB Top Edges -- {self.date_str}"]
        up_arrow = "\U0001f53c"
        down_arrow = "\U0001f53d"
        for a in edges[:5]:
            ev_val = a.ev_over if a.recommendation == "OVER" else a.ev_under
            game_label = f"{a.away_team}@{a.home_team}" if a.away_team else f"Game {a.game_pk}"
            arrow = up_arrow if a.recommendation == "OVER" else down_arrow
            tweet_lines.append(
                f"{arrow} "
                f"{a.player_name} {a.stat.upper()} {a.recommendation} {a.line} "
                f"({game_label}) | Sim: {a.sim_p_over:.0%} | EV: {ev_val:+.2f}"
            )
        tweet_lines.append("#MLB #BaseballBetting #Props")
        return "\n".join(tweet_lines)

    def write_twitter(self, analyses: List[PropAnalysis]) -> Path:
        """Write Twitter output to a text file."""
        path = self.output_dir / f"{self.date_str}_twitter.txt"
        try:
            content = self.format_twitter(analyses)
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(content + "\n")
            logger.info("Twitter output written to %s", path)
            print("\n--- Twitter Output ---")
            print(content)
            print("----------------------")
        except Exception as exc:
            logger.error("write_twitter failed: %s", exc)
        return path


# ---------------------------------------------------------------------------
# Supabase batch upsert helper
# ---------------------------------------------------------------------------

def _supabase_upsert_batched(
    client: Any,
    table: str,
    rows: List[Dict[str, Any]],
    batch_size: int = 500,
) -> None:
    """Upsert rows to a Supabase table in batches to stay within request limits."""
    for i in range(0, len(rows), batch_size):
        batch = rows[i : i + batch_size]
        try:
            client.table(table).upsert(batch).execute()
        except Exception as exc:
            logger.error(
                "_supabase_upsert_batched: batch %d-%d to '%s' failed: %s",
                i, i + len(batch), table, exc,
            )


# ---------------------------------------------------------------------------
# BacktestResult
# ---------------------------------------------------------------------------

@dataclass
class BacktestResult:
    """Accuracy metrics for a single backtested date."""

    backtest_date: str
    num_games: int
    num_players: int
    stat_metrics: Dict[str, Dict[str, float]] = field(default_factory=dict)
    roi_estimate: Optional[float] = None

    def summary(self) -> str:
        lines = [
            f"Backtest: {self.backtest_date}  "
            f"({self.num_games} games, {self.num_players} players)",
        ]
        for stat, metrics in self.stat_metrics.items():
            mae = metrics.get("mae", float("nan"))
            rmse = metrics.get("rmse", float("nan"))
            lines.append(f"  {stat}: MAE={mae:.3f}  RMSE={rmse:.3f}")
        if self.roi_estimate is not None:
            lines.append(f"  Estimated ROI (if bets placed): {self.roi_estimate:+.1%}")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main pipeline functions
# ---------------------------------------------------------------------------

def run_daily_simulation(
    sim_date: str,
    n_simulations: int,
    output_formats: List[str],
    output_dir: str,
    game_pk_filter: Optional[int],
    use_ml: bool,
    upload: bool,
    twitter: bool,
    props_file: Optional[str],
    dry_run: bool,
    verbose: bool,
) -> int:
    """
    Run the full daily simulation pipeline.

    Parameters
    ----------
    sim_date : str
        Game date in ``YYYY-MM-DD`` format.
    n_simulations : int
        Number of Monte Carlo iterations per game.
    output_formats : list of str
        Subset of ``['json', 'markdown', 'csv', 'supabase']``.
    output_dir : str
        Directory for output files.
    game_pk_filter : int | None
        If set, only simulate this game.
    use_ml : bool
        Whether to use the trained LightGBM model (falls back to odds-ratio).
    upload : bool
        Whether to upload results to Supabase.
    twitter : bool
        Whether to generate Twitter output.
    props_file : str | None
        Path to offline JSON prop lines file.
    dry_run : bool
        Fetch + show matchups but do not run simulation.
    verbose : bool
        Enable DEBUG logging.

    Returns
    -------
    int
        Exit code (0 = success, 1 = partial failure, 2 = total failure).
    """
    pipeline_start = time.time()
    exit_code = 0

    # -----------------------------------------------------------------------
    # 1. FETCH GAMES
    # -----------------------------------------------------------------------
    logger.info("=== STEP 1: Fetching games for %s ===", sim_date)

    if not _DATA_PREP_AVAILABLE:
        logger.error("data_prep module is not available. Cannot fetch games.")
        return 2

    try:
        mlb_client = MLBApiClient()
        raw_games = mlb_client.get_todays_games(sim_date)
    except Exception as exc:
        logger.error("MLBApiClient.get_todays_games failed: %s", exc)
        if verbose:
            traceback.print_exc()
        return 2

    if not raw_games:
        logger.info("No games found for %s. Nothing to do.", sim_date)
        return 0

    # Apply game filter
    if game_pk_filter is not None:
        raw_games = [g for g in raw_games if g.get("game_pk") == game_pk_filter]
        if not raw_games:
            logger.error("game_pk %s not found in today's schedule.", game_pk_filter)
            return 2

    logger.info("Found %d game(s) for %s.", len(raw_games), sim_date)

    # -----------------------------------------------------------------------
    # 2. PREPARE DATA
    # -----------------------------------------------------------------------
    logger.info("=== STEP 2: Preparing game data ===")

    pipeline = DataPrepPipeline()
    game_data_list: List[Any] = []

    for i, raw_game in enumerate(raw_games):
        try:
            gd = pipeline.prepare_game_data(raw_game)
            away = gd.away_team
            home = gd.home_team
            away_p = getattr(gd.away_pitcher, "name", "TBD") if gd.away_pitcher else "TBD"
            home_p = getattr(gd.home_pitcher, "name", "TBD") if gd.home_pitcher else "TBD"
            logger.info(
                "Prepared data for %s @ %s: %s vs %s", away, home, away_p, home_p
            )
            game_data_list.append(gd)
        except Exception as exc:
            logger.error(
                "DataPrepPipeline.prepare_game_data failed for game %s: %s",
                raw_game.get("game_pk", "?"), exc,
            )
            if verbose:
                traceback.print_exc()
            exit_code = 1  # partial failure -- continue

    if not game_data_list:
        logger.error("All game data preparation failed. Aborting.")
        return 2

    # Dry-run: print matchups and exit
    if dry_run:
        print(f"\n{'='*60}")
        print(f"DRY RUN -- {len(game_data_list)} game(s) for {sim_date}")
        print(f"{'='*60}")
        for gd in game_data_list:
            away_p = getattr(gd.away_pitcher, "name", "TBD") if gd.away_pitcher else "TBD"
            home_p = getattr(gd.home_pitcher, "name", "TBD") if gd.home_pitcher else "TBD"
            print(f"  [{gd.game_pk}] {gd.away_team} ({away_p}) @ {gd.home_team} ({home_p})")
            print(f"         Venue: {gd.venue}  |  Temp: {gd.temp_f:.0f}degF  |  Wind: {gd.wind_speed_mph:.0f} mph")
        print()
        return 0

    # -----------------------------------------------------------------------
    # 3. RUN SIMULATIONS
    # -----------------------------------------------------------------------
    logger.info("=== STEP 3: Running simulations (%d iterations/game) ===", n_simulations)

    if not _ENGINE_AVAILABLE or not _MODEL_AVAILABLE:
        logger.error("game_engine or matchup_model is not available. Cannot simulate.")
        return 2

    cfg = DEFAULT_CONFIG
    if n_simulations != cfg.NUM_SIMULATIONS:
        # Override n_simulations in a new config instance
        from dataclasses import replace as _dc_replace
        cfg = _dc_replace(cfg, NUM_SIMULATIONS=n_simulations)

    try:
        model_path = cfg.MODEL_PATH if use_ml else None
        matchup_model = MatchupModel(model_path=model_path, use_ml=use_ml)
        logger.info("MatchupModel active backend: %s", matchup_model.active_model)
    except Exception as exc:
        logger.error("Failed to initialise MatchupModel: %s", exc)
        return 2

    sim_results: List[Any] = []
    n_games = len(game_data_list)

    for idx, gd in enumerate(game_data_list):
        _progress_bar(idx, n_games, prefix=f"Simulating ({idx}/{n_games}) ")
        sim_start = time.time()
        try:
            simulator = GameSimulator(config=cfg, matchup_model=matchup_model)
            result = simulator.simulate_game(gd)
            elapsed = time.time() - sim_start
            logger.info(
                "Simulated %s @ %s: %d iterations in %.1fs",
                gd.away_team, gd.home_team, n_simulations, elapsed,
            )
            sim_results.append(result)
        except Exception as exc:
            logger.error(
                "GameSimulator.simulate_game failed for %s @ %s: %s",
                gd.away_team, gd.home_team, exc,
            )
            if verbose:
                traceback.print_exc()
            exit_code = 1

    _progress_bar(n_games, n_games, prefix=f"Simulating ({n_games}/{n_games}) ")

    if not sim_results:
        logger.error("All simulations failed. Aborting output.")
        return 2

    # -----------------------------------------------------------------------
    # 4. FETCH PROP LINES
    # -----------------------------------------------------------------------
    logger.info("=== STEP 4: Fetching prop lines ===")

    all_prop_lines: List[Dict[str, Any]] = []

    if props_file:
        try:
            with open(props_file, "r", encoding="utf-8") as fh:
                all_prop_lines = json.load(fh)
            logger.info("Loaded %d prop lines from %s.", len(all_prop_lines), props_file)
        except Exception as exc:
            logger.warning("Failed to load props file %s: %s", props_file, exc)
    else:
        # Attempt Supabase fetch
        try:
            reader = SupabaseReader()
            all_prop_lines = reader.get_prop_lines(game_date=sim_date)
            logger.info("Fetched %d prop lines from Supabase.", len(all_prop_lines))
        except Exception as exc:
            logger.warning(
                "SupabaseReader.get_prop_lines failed (running without props): %s", exc
            )

    # -----------------------------------------------------------------------
    # 5. ANALYZE PROPS
    # -----------------------------------------------------------------------
    logger.info("=== STEP 5: Analysing props ===")

    analyzer = PropAnalyzer(config=cfg, matchup_model=matchup_model)
    all_analyses: List[PropAnalysis] = []

    # Build a lookup: game_pk -> GameData
    game_data_by_pk: Dict[int, Any] = {gd.game_pk: gd for gd in game_data_list}

    for result in sim_results:
        game_pk = result.game_info.get("game_pk", 0)
        game_props = [p for p in all_prop_lines if p.get("game_pk") == game_pk]
        gd = game_data_by_pk.get(game_pk)

        try:
            game_analyses = analyzer.analyze_game(result, game_props, game_data=gd)
            all_analyses.extend(game_analyses)
        except Exception as exc:
            logger.warning("PropAnalyzer.analyze_game failed for game %s: %s", game_pk, exc)
            exit_code = 1

    edges = [a for a in all_analyses if a.has_edge]
    logger.info(
        "Prop analysis complete: %d props analysed, %d edges found.",
        len(all_analyses), len(edges),
    )

    # -----------------------------------------------------------------------
    # 6. OUTPUT RESULTS
    # -----------------------------------------------------------------------
    logger.info("=== STEP 6: Writing outputs ===")

    writer = OutputWriter(output_dir=output_dir, date_str=sim_date)

    if "json" in output_formats or "all" in output_formats:
        writer.write_json(sim_results, all_analyses)

    if "markdown" in output_formats or "all" in output_formats:
        writer.write_markdown(sim_results, all_analyses)

    if "csv" in output_formats or "all" in output_formats:
        writer.write_csv(all_analyses)

    if "supabase" in output_formats or upload:
        writer.upload_to_supabase(sim_results, all_analyses)

    if twitter:
        writer.write_twitter(all_analyses)

    # -----------------------------------------------------------------------
    # 7. SUMMARY
    # -----------------------------------------------------------------------
    elapsed_total = time.time() - pipeline_start
    n_props = len(all_analyses)
    n_edges = len(edges)

    print(f"\n{'='*60}")
    print(
        f"Simulation complete.  {len(sim_results)} game(s)  |  "
        f"{n_props} props analysed  |  {n_edges} edges found  "
        f"[{elapsed_total:.1f}s total]"
    )
    print(f"{'='*60}")

    if edges:
        top_edges = sorted(edges, key=lambda a: a.edge, reverse=True)[:5]
        print("\nTop 5 Edges:")
        for rank, a in enumerate(top_edges, 1):
            ev_val = a.ev_over if a.recommendation == "OVER" else a.ev_under
            game_label = f"{a.away_team}@{a.home_team}" if a.away_team else f"game {a.game_pk}"
            print(
                f"  {rank}. {a.player_name} {a.stat.upper()} "
                f"{a.recommendation} {a.line}  "
                f"({game_label})  EV={ev_val:+.3f}  Sim P(over)={a.sim_p_over:.1%}"
            )
        # Glass-box explanation for the #1 edge
        if top_edges:
            print(f"\n[Glass-box explanation -- #{1} edge]\n")
            print(top_edges[0].explanation)
    else:
        print("\nNo edges found today.")

    print()
    return exit_code


# ---------------------------------------------------------------------------
# Backtest pipeline
# ---------------------------------------------------------------------------

def run_backtest(
    backtest_date: str,
    n_simulations: int,
    output_dir: str,
    use_ml: bool,
    upload: bool,
    verbose: bool,
) -> int:
    """
    Run historical backtest for *backtest_date*.

    Pipeline
    --------
    1. Fetch the schedule for that date.
    2. Run simulation as if it were that morning (pre-game data only).
    3. Fetch actual results from MLB Stats API boxscores.
    4. Compare projected stats to actuals; compute MAE, RMSE, calibration.
    5. If prop lines available, compute would-have-been ROI.

    Returns
    -------
    int
        Exit code.
    """
    logger.info("=== BACKTEST MODE: %s ===", backtest_date)

    if not _DATA_PREP_AVAILABLE or not _ENGINE_AVAILABLE:
        logger.error("Required modules unavailable for backtest.")
        return 2

    # 1 & 2 -- Simulate the date (identical pipeline to daily run but no upload)
    exit_code = run_daily_simulation(
        sim_date=backtest_date,
        n_simulations=n_simulations,
        output_formats=["json"],
        output_dir=output_dir,
        game_pk_filter=None,
        use_ml=use_ml,
        upload=False,
        twitter=False,
        props_file=None,
        dry_run=False,
        verbose=verbose,
    )

    if exit_code == 2:
        return exit_code  # nothing to compare

    # 3 -- Fetch actual results from boxscores
    logger.info("Fetching actual boxscore results for %s...", backtest_date)
    actuals: Dict[int, Dict[str, Any]] = {}  # player_id -> {stat: actual_value}

    try:
        mlb_client = MLBApiClient()
        raw_games = mlb_client.get_todays_games(backtest_date)
        for raw_game in raw_games:
            game_pk = raw_game.get("game_pk")
            if not game_pk:
                continue
            try:
                boxscore = mlb_client.get_boxscore(game_pk)
                _parse_boxscore_actuals(boxscore, actuals)
            except Exception as exc:
                logger.warning("Failed to fetch boxscore for game %s: %s", game_pk, exc)
    except Exception as exc:
        logger.error("Failed to fetch backtest schedule: %s", exc)

    # 4 -- Load projections from the JSON we just wrote
    proj_path = Path(output_dir) / f"{backtest_date}_simulation.json"
    projections: Dict[int, Dict[str, float]] = {}  # player_id -> {stat: projected_mean}

    if proj_path.exists():
        try:
            with open(proj_path, "r", encoding="utf-8") as fh:
                sim_json = json.load(fh)

            for game in sim_json.get("games", []):
                for player_id_str, pdata in game.get("player_projections", {}).items():
                    pid = int(player_id_str)
                    projections[pid] = {
                        stat: sdata["mean"]
                        for stat, sdata in pdata.get("stats", {}).items()
                    }
        except Exception as exc:
            logger.error("Failed to load simulation JSON for comparison: %s", exc)

    # 5 -- Compute accuracy metrics
    stat_errors: Dict[str, List[float]] = {}  # stat -> [error, ...]

    for player_id, actual_stats in actuals.items():
        if player_id not in projections:
            continue
        for stat, actual_val in actual_stats.items():
            projected_val = projections[player_id].get(stat)
            if projected_val is None:
                continue
            error = projected_val - actual_val
            stat_errors.setdefault(stat, []).append(error)

    stat_metrics: Dict[str, Dict[str, float]] = {}
    for stat, errors in stat_errors.items():
        if not errors:
            continue
        mae = sum(abs(e) for e in errors) / len(errors)
        rmse = math.sqrt(sum(e ** 2 for e in errors) / len(errors))
        stat_metrics[stat] = {"mae": mae, "rmse": rmse, "n": len(errors)}

    bt_result = BacktestResult(
        backtest_date=backtest_date,
        num_games=len(actuals),
        num_players=len(projections),
        stat_metrics=stat_metrics,
    )

    print("\n" + bt_result.summary())

    # Write backtest metrics JSON
    metrics_path = Path(output_dir) / f"{backtest_date}_backtest_metrics.json"
    try:
        with open(metrics_path, "w", encoding="utf-8") as fh:
            json.dump(
                {
                    "backtest_date": backtest_date,
                    "num_games": bt_result.num_games,
                    "num_players": bt_result.num_players,
                    "stat_metrics": stat_metrics,
                },
                fh,
                indent=2,
            )
        logger.info("Backtest metrics written to %s", metrics_path)
    except Exception as exc:
        logger.warning("Failed to write backtest metrics: %s", exc)

    return 0


def _parse_boxscore_actuals(
    boxscore: Dict[str, Any],
    actuals: Dict[int, Dict[str, Any]],
) -> None:
    """
    Parse an MLB Stats API boxscore dict into the *actuals* mapping.

    Handles both pitcher and batter stats sections.
    """
    for side in ("home", "away"):
        try:
            side_data = boxscore.get("teams", {}).get(side, {})
            players = side_data.get("players", {})
            for _key, player_data in players.items():
                pid = player_data.get("person", {}).get("id")
                if pid is None:
                    continue
                stats = player_data.get("stats", {})

                player_actuals: Dict[str, Any] = {}

                # Batting stats
                batting = stats.get("batting", {})
                if batting:
                    player_actuals.update({
                        "hits": batting.get("hits", 0),
                        "home_runs": batting.get("homeRuns", 0),
                        "strikeouts": batting.get("strikeOuts", 0),
                        "walks": batting.get("baseOnBalls", 0),
                        "total_bases": batting.get("totalBases", 0),
                        "rbis": batting.get("rbi", 0),
                        "runs_scored": batting.get("runs", 0),
                    })

                # Pitching stats
                pitching = stats.get("pitching", {})
                if pitching:
                    ip_str = str(pitching.get("inningsPitched", "0.0"))
                    try:
                        inn, thirds = ip_str.split(".")
                        outs = int(inn) * 3 + int(thirds)
                    except Exception:
                        outs = 0
                    player_actuals.update({
                        "outs_recorded": outs,
                        "strikeouts": pitching.get("strikeOuts", 0),
                        "walks": pitching.get("baseOnBalls", 0),
                    })

                if player_actuals:
                    actuals[int(pid)] = player_actuals
        except Exception as exc:
            logger.debug("_parse_boxscore_actuals error for side %s: %s", side, exc)


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    """Build and return the argument parser."""
    parser = argparse.ArgumentParser(
        prog="python -m simulation.run_simulation",
        description="BaselineMLB Monte Carlo Simulator -- CLI Entry Point",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    parser.add_argument(
        "--date",
        default=date.today().isoformat(),
        metavar="YYYY-MM-DD",
        help="Game date to simulate (default: today).",
    )
    parser.add_argument(
        "--simulations",
        type=int,
        default=DEFAULT_CONFIG.NUM_SIMULATIONS if DEFAULT_CONFIG else 2500,
        metavar="N",
        help="Number of Monte Carlo iterations per game (default: %(default)s).",
    )
    parser.add_argument(
        "--output",
        nargs="+",
        default=["all"],
        choices=["json", "markdown", "csv", "supabase", "all"],
        metavar="FORMAT",
        help="Output format(s): json, markdown, csv, supabase, all (default: all).",
    )
    parser.add_argument(
        "--output-dir",
        default="output",
        metavar="DIR",
        help="Directory for output files (default: 'output/').",
    )
    parser.add_argument(
        "--game-pk",
        type=int,
        default=None,
        metavar="GAME_PK",
        help="Simulate only this game_pk (optional).",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable DEBUG-level logging.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Fetch data and show matchups but skip simulation.",
    )
    parser.add_argument(
        "--backtest",
        action="store_true",
        help="Run in historical backtest mode.",
    )
    parser.add_argument(
        "--backtest-date",
        default=None,
        metavar="YYYY-MM-DD",
        help="Date to backtest (required when --backtest is set).",
    )
    parser.add_argument(
        "--use-ml",
        dest="use_ml",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Use trained ML model when available (default: True).",
    )
    parser.add_argument(
        "--upload",
        action="store_true",
        help="Upload results to Supabase (requires SUPABASE_URL/SUPABASE_KEY env vars).",
    )
    parser.add_argument(
        "--twitter",
        action="store_true",
        help="Generate Twitter-ready output.",
    )
    parser.add_argument(
        "--props-file",
        default=None,
        metavar="FILE",
        help="Path to a local JSON prop lines file (skips Supabase fetch).",
    )
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    """
    Main CLI entry point.

    Parameters
    ----------
    argv : list of str | None
        Command-line arguments (defaults to sys.argv[1:]).

    Returns
    -------
    int
        Exit code (0 = success).
    """
    parser = build_parser()
    args = parser.parse_args(argv)

    # Configure logging
    log_level = logging.DEBUG if args.verbose else logging.INFO
    configure_logging(level=log_level)

    logger.debug("Arguments: %s", vars(args))

    # Validate date formats
    for date_arg, label in [(args.date, "--date"), (args.backtest_date, "--backtest-date")]:
        if date_arg is not None:
            try:
                datetime.strptime(date_arg, "%Y-%m-%d")
            except ValueError:
                logger.error(
                    "Invalid date format for %s: '%s'. Expected YYYY-MM-DD.",
                    label, date_arg,
                )
                return 2

    # Backtest mode
    if args.backtest:
        bt_date = args.backtest_date
        if not bt_date:
            logger.error("--backtest requires --backtest-date YYYY-MM-DD.")
            return 2
        return run_backtest(
            backtest_date=bt_date,
            n_simulations=args.simulations,
            output_dir=args.output_dir,
            use_ml=args.use_ml,
            upload=args.upload,
            verbose=args.verbose,
        )

    # Daily simulation mode
    return run_daily_simulation(
        sim_date=args.date,
        n_simulations=args.simulations,
        output_formats=args.output,
        output_dir=args.output_dir,
        game_pk_filter=args.game_pk,
        use_ml=args.use_ml,
        upload=args.upload,
        twitter=args.twitter,
        props_file=args.props_file,
        dry_run=args.dry_run,
        verbose=args.verbose,
    )


if __name__ == "__main__":
    sys.exit(main())
