"""
run_daily.py — Daily orchestrator for the BaselineMLB simulation pipeline
==========================================================================

Drives the full end-to-end simulation workflow for a given MLB game date:

1. Fetch today's games from Supabase ``games`` table.
2. Fetch confirmed lineups (from Supabase ``lineups`` table or
   ``pipeline/fetch_lineups.py``).
3. Fetch weather data (from Supabase ``weather`` table or
   ``pipeline/fetch_weather.py``).
4. Load the trained matchup model from
   ``models/trained/matchup_model.joblib``.
5. For each game, generate per-PA matchup probabilities from the model.
6. Apply weather adjustments to matchup probabilities.
7. Run the Monte Carlo simulation (default 3 000 iterations per game).
8. Calculate prop edges against today's sportsbook lines.
9. Upsert simulation results to Supabase ``sim_results`` table.
10. Upsert prop edges to Supabase ``sim_prop_edges`` table.
11. Print a daily summary report.

CLI usage
---------
Run all games for today::

    python -m simulator.run_daily

Run a specific date with 5 000 simulations::

    python -m simulator.run_daily --date 2026-04-15 --n-sims 5000

Dry-run (no Supabase writes)::

    python -m simulator.run_daily --dry-run

Limit to specific games::

    python -m simulator.run_daily --games 745123,745124

Exit codes
----------
0   All games processed successfully.
1   One or more games failed, or a fatal error occurred.
"""

from __future__ import annotations

import argparse
import importlib
import json
import logging
import os
import sys
import time
from dataclasses import asdict, dataclass
from datetime import date, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .monte_carlo_engine import BatterProfile

import requests

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants / paths
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent
MODELS_DIR = PROJECT_ROOT / "models" / "trained"
MATCHUP_MODEL_PATH = MODELS_DIR / "matchup_model.joblib"

# ---------------------------------------------------------------------------
# Supabase helpers
# ---------------------------------------------------------------------------

_SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
_SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_KEY", "")


def _headers() -> dict[str, str]:
    """Return standard Supabase REST API headers.

    Returns
    -------
    dict[str, str]
        Headers dict with API key, Bearer token, content type, and
        merge-duplicate upsert preference.
    """
    key = os.environ.get("SUPABASE_SERVICE_KEY", _SUPABASE_KEY)
    return {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "Prefer": "resolution=merge-duplicates",
    }


def _get(endpoint: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Perform a Supabase REST GET request.

    Parameters
    ----------
    endpoint:
        Table path, e.g. ``"/games"``.
    params:
        PostgREST query parameters.

    Returns
    -------
    list[dict[str, Any]]
        Parsed JSON response.

    Raises
    ------
    RuntimeError
        On non-2xx status or missing SUPABASE_URL.
    """
    base = os.environ.get("SUPABASE_URL", _SUPABASE_URL)
    if not base:
        raise RuntimeError("SUPABASE_URL is not set.")
    url = f"{base}/rest/v1{endpoint}"
    resp = requests.get(url, headers=_headers(), params=params, timeout=30)
    if not resp.ok:
        raise RuntimeError(f"GET {endpoint} failed [{resp.status_code}]: {resp.text[:400]}")
    return resp.json()  # type: ignore[return-value]


def _upsert(endpoint: str, rows: list[dict[str, Any]]) -> None:
    """Perform a Supabase REST upsert (POST with merge-duplicate preference).

    Parameters
    ----------
    endpoint:
        Table path, e.g. ``"/sim_results"``.
    rows:
        Records to upsert.

    Raises
    ------
    RuntimeError
        On non-2xx HTTP status.
    """
    if not rows:
        return
    base = os.environ.get("SUPABASE_URL", _SUPABASE_URL)
    if not base:
        raise RuntimeError("SUPABASE_URL is not set.")
    url = f"{base}/rest/v1{endpoint}"
    resp = requests.post(url, headers=_headers(), json=rows, timeout=60)
    if not resp.ok:
        raise RuntimeError(f"UPSERT {endpoint} failed [{resp.status_code}]: {resp.text[:400]}")
    logger.info("Upserted %d rows to %s", len(rows), endpoint)


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class GameRecord:
    """Minimal game record fetched from Supabase.

    Attributes
    ----------
    game_pk:
        MLB statsapi game identifier.
    game_date:
        ISO date string.
    home_team_id:
        Home team identifier.
    away_team_id:
        Away team identifier.
    venue_id:
        Venue / ballpark identifier (used for weather & park factors).
    status:
        Game status string from the MLB API (e.g. ``"Scheduled"``).
    """

    game_pk: int
    game_date: str
    home_team_id: int
    away_team_id: int
    venue_id: int
    status: str


@dataclass
class PipelineResult:
    """Outcome summary for a single-game pipeline run.

    Attributes
    ----------
    game_pk:
        Game identifier.
    success:
        Whether the game completed without errors.
    error:
        Error message if unsuccessful.
    elapsed_seconds:
        Wall-clock seconds for this game's pipeline.
    n_simulations:
        Number of Monte Carlo iterations run.
    n_prop_edges:
        Number of props with positive edge found.
    home_score_mean:
        Simulated home-team run average.
    away_score_mean:
        Simulated away-team run average.
    sim_result_id:
        Supabase row ID of the upserted simulation result (if any).
    """

    game_pk: int
    success: bool
    error: str = ""
    elapsed_seconds: float = 0.0
    n_simulations: int = 0
    n_prop_edges: int = 0
    home_score_mean: float = 0.0
    away_score_mean: float = 0.0
    sim_result_id: str = ""


# ---------------------------------------------------------------------------
# Data-fetch helpers
# ---------------------------------------------------------------------------


def fetch_todays_games(game_date: str, game_pks: list[int] | None = None) -> list[GameRecord]:
    """Fetch scheduled games from the Supabase ``games`` table.

    Parameters
    ----------
    game_date:
        ISO date string (e.g. ``"2026-04-01"``).
    game_pks:
        Optional list of specific game IDs to filter.

    Returns
    -------
    list[GameRecord]
        Parsed game records.
    """
    params: dict[str, Any] = {
        "select": "game_pk,game_date,home_team_id,away_team_id,venue_id,status",
        "game_date": f"eq.{game_date}",
    }
    if game_pks:
        params["game_pk"] = f"in.({','.join(str(pk) for pk in game_pks)})"

    logger.info("Fetching games for %s...", game_date)
    rows = _get("/games", params=params)
    games = [
        GameRecord(
            game_pk=int(r["game_pk"]),
            game_date=str(r.get("game_date", game_date)),
            home_team_id=int(r.get("home_team_id", 0)),
            away_team_id=int(r.get("away_team_id", 0)),
            venue_id=int(r.get("venue_id", 0)),
            status=str(r.get("status", "")),
        )
        for r in rows
    ]
    logger.info("Found %d game(s) for %s", len(games), game_date)
    return games


def fetch_lineups(game_pk: int, game_date: str) -> dict[str, Any]:
    """Fetch confirmed lineup data for a single game.

    First attempts to import ``pipeline.fetch_lineups`` and call
    ``get_lineups(game_pk)``.  Falls back to Supabase ``lineups`` table.

    Parameters
    ----------
    game_pk:
        Game identifier.
    game_date:
        ISO date string.

    Returns
    -------
    dict[str, Any]
        Keys: ``"home_lineup"`` (list[str]), ``"away_lineup"`` (list[str]),
        ``"home_pitcher_id"`` (str), ``"away_pitcher_id"`` (str).
    """
    # Try pipeline module first
    try:
        fetch_mod = importlib.import_module("pipeline.fetch_lineups")
        return fetch_mod.get_lineups(game_pk)  # type: ignore[no-any-return]
    except (ImportError, AttributeError):
        logger.debug("pipeline.fetch_lineups unavailable; falling back to Supabase.")

    # Fallback: Supabase lineups table
    rows = _get(
        "/lineups",
        params={"game_pk": f"eq.{game_pk}", "select": "*"},
    )
    home_rows = [r for r in rows if r.get("side") == "home"]
    away_rows = [r for r in rows if r.get("side") == "away"]
    home_lineup = sorted(home_rows, key=lambda r: r.get("batting_order", 99))
    away_lineup = sorted(away_rows, key=lambda r: r.get("batting_order", 99))
    home_pitcher = next((r for r in home_rows if r.get("is_pitcher")), {})
    away_pitcher = next((r for r in away_rows if r.get("is_pitcher")), {})
    return {
        "home_lineup": [str(r["player_id"]) for r in home_lineup if not r.get("is_pitcher")],
        "away_lineup": [str(r["player_id"]) for r in away_lineup if not r.get("is_pitcher")],
        "home_pitcher_id": str(home_pitcher.get("player_id", "home_sp")),
        "away_pitcher_id": str(away_pitcher.get("player_id", "away_sp")),
    }


def fetch_weather(game_pk: int, venue_id: int) -> dict[str, Any]:
    """Fetch weather data for a game venue.

    First attempts to import ``pipeline.fetch_weather`` and call
    ``get_weather(game_pk, venue_id)``.  Falls back to Supabase
    ``weather`` table.

    Parameters
    ----------
    game_pk:
        Game identifier.
    venue_id:
        Ballpark venue identifier.

    Returns
    -------
    dict[str, Any]
        Keys include: ``"temp_f"``, ``"wind_mph"``, ``"wind_dir"``,
        ``"humidity_pct"``, ``"precip_in"``.
    """
    try:
        weather_mod = importlib.import_module("pipeline.fetch_weather")
        return weather_mod.get_weather(game_pk, venue_id)  # type: ignore[no-any-return]
    except (ImportError, AttributeError):
        logger.debug("pipeline.fetch_weather unavailable; falling back to Supabase.")

    rows = _get("/weather", params={"game_pk": f"eq.{game_pk}", "select": "*"})
    if rows:
        return rows[0]
    logger.warning("No weather data for game_pk=%d; using defaults.", game_pk)
    return {
        "temp_f": 72.0,
        "wind_mph": 0.0,
        "wind_dir": "calm",
        "humidity_pct": 50.0,
        "precip_in": 0.0,
    }


def load_matchup_model(model_path: Path | None = None) -> Any:
    """Load the trained matchup model from disk.

    Parameters
    ----------
    model_path:
        Path to the ``.joblib`` file.  Defaults to
        ``models/trained/matchup_model.joblib`` relative to the project root.

    Returns
    -------
    Any
        The deserialised sklearn / custom model object, or ``None`` if the
        file is not found (caller should fall back to baseline probabilities).
    """
    path = model_path or MATCHUP_MODEL_PATH
    if not path.exists():
        logger.warning("Matchup model not found at %s; using baseline probabilities.", path)
        return None
    try:
        import joblib  # type: ignore[import]
        model = joblib.load(path)
        logger.info("Loaded matchup model from %s", path)
        return model
    except Exception as exc:  # noqa: BLE001
        logger.error("Failed to load matchup model: %s", exc)
        return None


# ---------------------------------------------------------------------------
# Probability generation
# ---------------------------------------------------------------------------

# League-average outcome distribution (used as fallback)
_LEAGUE_AVG_PROBS: dict[str, float] = {
    "K": 0.225,
    "BB": 0.085,
    "HBP": 0.010,
    "1B": 0.155,
    "2B": 0.050,
    "3B": 0.005,
    "HR": 0.035,
    "OUT": 0.435,
}

# Weather adjustment factors per outcome
# Keys: outcome; inner keys: wind_out (blowing out), wind_in, high_temp, high_humidity
_WEATHER_ADJUSTMENTS: dict[str, dict[str, float]] = {
    "HR": {"wind_out": 0.08, "wind_in": -0.08, "high_temp": 0.03, "high_humidity": -0.02},
    "2B": {"wind_out": 0.03, "wind_in": -0.02, "high_temp": 0.01, "high_humidity": -0.01},
    "K": {"wind_out": 0.0, "wind_in": 0.0, "high_temp": -0.01, "high_humidity": 0.01},
    "OUT": {"wind_out": -0.02, "wind_in": 0.02, "high_temp": 0.0, "high_humidity": 0.0},
}


def generate_matchup_probs(
    pitcher_id: str,
    batter_id: str,
    model: Any,
) -> dict[str, float]:
    """Generate per-PA outcome probabilities from the matchup model.

    Parameters
    ----------
    pitcher_id:
        Pitcher identifier.
    batter_id:
        Batter identifier.
    model:
        Loaded matchup model.  If ``None``, returns league-average probs.

    Returns
    -------
    dict[str, float]
        Outcome → probability mapping (sums to ~1.0).
    """
    if model is None:
        return dict(_LEAGUE_AVG_PROBS)
    try:
        # Assumes model has a predict_proba(pitcher_id, batter_id) interface
        # or a feature-extraction wrapper.  Adjust to your actual model API.
        if hasattr(model, "predict_proba_for_matchup"):
            return model.predict_proba_for_matchup(pitcher_id, batter_id)
        # Fallback: use league average if model API is unknown
        return dict(_LEAGUE_AVG_PROBS)
    except Exception as exc:  # noqa: BLE001
        logger.debug("Model prediction failed (%s); using league averages.", exc)
        return dict(_LEAGUE_AVG_PROBS)


def apply_weather_adjustments(
    probs: dict[str, float],
    weather: dict[str, Any],
) -> dict[str, float]:
    """Adjust outcome probabilities based on weather conditions.

    Rules applied:
    - Wind blowing out (towards OF): +8% HR, +3% XBH.
    - Wind blowing in: inverse of above.
    - High temperature (>85 °F): slight HR boost.
    - High humidity (>80%): slight K increase (ball grips differently).

    Parameters
    ----------
    probs:
        Base outcome probabilities from the matchup model.
    weather:
        Weather dict with keys ``temp_f``, ``wind_mph``, ``wind_dir``,
        ``humidity_pct``.

    Returns
    -------
    dict[str, float]
        Adjusted and re-normalised probability dict.
    """
    adjusted = dict(probs)
    wind_mph = float(weather.get("wind_mph", 0))
    wind_dir = str(weather.get("wind_dir", "calm")).lower()
    temp_f = float(weather.get("temp_f", 72))
    humidity = float(weather.get("humidity_pct", 50))

    # Wind-out favours offence
    if wind_mph >= 10 and "out" in wind_dir:
        for outcome, adj in _WEATHER_ADJUSTMENTS.items():
            adjusted[outcome] = adjusted.get(outcome, 0) * (1 + adj.get("wind_out", 0))

    # Wind-in suppresses offence
    elif wind_mph >= 10 and "in" in wind_dir:
        for outcome, adj in _WEATHER_ADJUSTMENTS.items():
            adjusted[outcome] = adjusted.get(outcome, 0) * (1 + adj.get("wind_in", 0))

    # High temperature boost
    if temp_f >= 85:
        for outcome, adj in _WEATHER_ADJUSTMENTS.items():
            adjusted[outcome] = adjusted.get(outcome, 0) * (1 + adj.get("high_temp", 0))

    # High humidity adjustment
    if humidity >= 80:
        for outcome, adj in _WEATHER_ADJUSTMENTS.items():
            adjusted[outcome] = adjusted.get(outcome, 0) * (1 + adj.get("high_humidity", 0))

    # Re-normalise
    total = sum(adjusted.values())
    if total > 0:
        adjusted = {k: v / total for k, v in adjusted.items()}
    return adjusted


def build_pitcher_probs(
    pitcher_id: str,
    lineup: list[str],
    model: Any,
    weather: dict[str, Any],
) -> dict[str, dict[str, float]]:
    """Build a matchup probability dict for every batter in a lineup.

    Parameters
    ----------
    pitcher_id:
        Pitcher identifier.
    lineup:
        Ordered list of batter IDs.
    model:
        Trained matchup model (or ``None`` for league averages).
    weather:
        Weather dict for probability adjustments.

    Returns
    -------
    dict[str, dict[str, float]]
        Mapping of ``batter_id → {outcome: probability}``.
    """
    probs: dict[str, dict[str, float]] = {}
    for batter_id in lineup:
        base_probs = generate_matchup_probs(pitcher_id, batter_id, model)
        adjusted = apply_weather_adjustments(base_probs, weather)
        probs[batter_id] = adjusted
    return probs


# ---------------------------------------------------------------------------
# Supabase output formatters
# ---------------------------------------------------------------------------


def _sim_result_rows(
    game_pk: int,
    game_date: str,
    summary: Any,  # SimulationSummary
    n_sims: int,
) -> list[dict[str, Any]]:
    """Build rows for the ``sim_results`` Supabase table.

    Parameters
    ----------
    game_pk:
        Game identifier.
    game_date:
        ISO date string.
    summary:
        ``SimulationSummary`` from the engine.
    n_sims:
        Number of simulations run.

    Returns
    -------
    list[dict[str, Any]]
        One row per player (batters + pitchers).
    """
    rows: list[dict[str, Any]] = []
    run_at = datetime.utcnow().isoformat()

    def _stat_dict(stat_sum: Any) -> dict[str, float]:
        return {
            "mean": stat_sum.mean,
            "median": stat_sum.median,
            "std": stat_sum.std,
            "p10": stat_sum.p10,
            "p25": stat_sum.p25,
            "p75": stat_sum.p75,
            "p90": stat_sum.p90,
            "min": stat_sum.min,
            "max": stat_sum.max,
        }

    # Score rows
    rows.append({
        "game_pk": game_pk,
        "game_date": game_date,
        "player_id": "home_team",
        "player_type": "team",
        "stat_type": "runs",
        "stats": _stat_dict(summary.home_score),
        "n_simulations": n_sims,
        "run_at": run_at,
    })
    rows.append({
        "game_pk": game_pk,
        "game_date": game_date,
        "player_id": "away_team",
        "player_type": "team",
        "stat_type": "runs",
        "stats": _stat_dict(summary.away_score),
        "n_simulations": n_sims,
        "run_at": run_at,
    })

    # Batter rows
    for player_id, stat_map in summary.batter_stats.items():
        for stat_name, stat_sum in stat_map.items():
            rows.append({
                "game_pk": game_pk,
                "game_date": game_date,
                "player_id": player_id,
                "player_type": "batter",
                "stat_type": stat_name,
                "stats": _stat_dict(stat_sum),
                "n_simulations": n_sims,
                "run_at": run_at,
            })

    # Pitcher rows
    for player_id, stat_map in summary.pitcher_stats.items():
        for stat_name, stat_sum in stat_map.items():
            rows.append({
                "game_pk": game_pk,
                "game_date": game_date,
                "player_id": player_id,
                "player_type": "pitcher",
                "stat_type": stat_name,
                "stats": _stat_dict(stat_sum),
                "n_simulations": n_sims,
                "run_at": run_at,
            })

    return rows


def _prop_edge_rows(
    game_pk: int,
    game_date: str,
    edges: list[Any],  # list[PropEdge]
) -> list[dict[str, Any]]:
    """Build rows for the ``sim_prop_edges`` Supabase table.

    Parameters
    ----------
    game_pk:
        Game identifier.
    game_date:
        ISO date string.
    edges:
        List of ``PropEdge`` objects.

    Returns
    -------
    list[dict[str, Any]]
        One row per edge.
    """
    run_at = datetime.utcnow().isoformat()
    rows: list[dict[str, Any]] = []
    for e in edges:
        row = asdict(e) if hasattr(e, "__dataclass_fields__") else dict(e)
        row["game_pk"] = game_pk
        row["game_date"] = game_date
        row["run_at"] = run_at
        # Flatten explanation to JSON string for Supabase storage
        if isinstance(row.get("explanation"), dict):
            row["explanation"] = json.dumps(row["explanation"], default=str)
        rows.append(row)
    return rows


# ---------------------------------------------------------------------------
# Per-game pipeline
# ---------------------------------------------------------------------------


def run_game_pipeline(
    game: GameRecord,
    model: Any,
    n_sims: int,
    dry_run: bool,
) -> PipelineResult:
    """Run the full simulation pipeline for a single game.

    Parameters
    ----------
    game:
        Game record with metadata.
    model:
        Loaded matchup model.
    n_sims:
        Number of Monte Carlo iterations.
    dry_run:
        If True, skip all Supabase upserts.

    Returns
    -------
    PipelineResult
        Summary of this game's pipeline execution.
    """
    from .monte_carlo_engine import GameSimulator, SimulationConfig
    from .prop_calculator import PropCalculator

    t0 = time.perf_counter()
    logger.info("--- Game %d (%s @ %s) ---", game.game_pk, game.away_team_id, game.home_team_id)

    try:
        # Step 2: Lineups
        t_step = time.perf_counter()
        lineups = fetch_lineups(game.game_pk, game.game_date)
        home_lineup: list[str] = lineups.get("home_lineup", [])
        away_lineup: list[str] = lineups.get("away_lineup", [])
        home_pitcher_id: str = lineups.get("home_pitcher_id", "home_sp")
        away_pitcher_id: str = lineups.get("away_pitcher_id", "away_sp")
        logger.info(
            "  Lineups fetched in %.2fs  (home=%d, away=%d)",
            time.perf_counter() - t_step,
            len(home_lineup),
            len(away_lineup),
        )

        if not home_lineup or not away_lineup:
            raise ValueError(f"Missing lineup data for game_pk={game.game_pk}")

        # Pad lineup to 9 if short (shouldn't happen in production)
        while len(home_lineup) < 9:
            home_lineup.append(f"home_b{len(home_lineup)}")
        while len(away_lineup) < 9:
            away_lineup.append(f"away_b{len(away_lineup)}")

        # Step 3: Weather
        t_step = time.perf_counter()
        weather = fetch_weather(game.game_pk, game.venue_id)
        logger.info(
            "  Weather: %.0f\u00b0F, wind %s mph %s  (%.2fs)",
            weather.get("temp_f", 72),
            weather.get("wind_mph", 0),
            weather.get("wind_dir", "calm"),
            time.perf_counter() - t_step,
        )

        # Steps 5-6: Generate matchup probabilities with weather adjustments
        t_step = time.perf_counter()
        home_pitcher_probs = build_pitcher_probs(home_pitcher_id, away_lineup, model, weather)
        away_pitcher_probs = build_pitcher_probs(away_pitcher_id, home_lineup, model, weather)
        logger.info(
            "  Matchup probs generated in %.2fs", time.perf_counter() - t_step
        )

        # Step 7: Run Monte Carlo simulation
        t_step = time.perf_counter()
        engine = GameSimulator()
        cfg = SimulationConfig(n_simulations=n_sims)
        sim_result = engine.simulate_game(
            home_lineup, away_lineup, home_pitcher_probs, away_pitcher_probs, cfg,
            home_pitcher_id=home_pitcher_id, away_pitcher_id=away_pitcher_id,
        )
        summary = engine.summarise(sim_result)
        sim_elapsed = time.perf_counter() - t_step
        logger.info(
            "  Simulation: home %.2f | away %.2f  (%d sims in %.2fs)",
            summary.home_score.mean,
            summary.away_score.mean,
            n_sims,
            sim_elapsed,
        )

        # Step 8: Prop edges
        t_step = time.perf_counter()
        calc = PropCalculator()
        try:
            props = calc.fetch_todays_props(game.game_date, [game.game_pk])
        except RuntimeError as exc:
            logger.warning("  Props fetch failed: %s — skipping prop edges.", exc)
            props = []
        edges = calc.calculate_prop_edges(summary, props) if props else []
        logger.info(
            "  Prop edges: %d edges found  (%.2fs)",
            len(edges),
            time.perf_counter() - t_step,
        )

        # Steps 9-10: Upsert to Supabase
        if not dry_run:
            t_step = time.perf_counter()
            sim_rows = _sim_result_rows(game.game_pk, game.game_date, summary, n_sims)
            _upsert("/sim_results", sim_rows)

            if edges:
                edge_rows = _prop_edge_rows(game.game_pk, game.game_date, edges)
                _upsert("/sim_prop_edges", edge_rows)
            logger.info("  Upserted %d sim rows + %d edge rows  (%.2fs)",
                        len(sim_rows), len(edges), time.perf_counter() - t_step)
        else:
            logger.info("  [dry-run] Skipping Supabase upserts.")

        elapsed = time.perf_counter() - t0
        return PipelineResult(
            game_pk=game.game_pk,
            success=True,
            elapsed_seconds=round(elapsed, 2),
            n_simulations=n_sims,
            n_prop_edges=len(edges),
            home_score_mean=round(summary.home_score.mean, 3),
            away_score_mean=round(summary.away_score.mean, 3),
        )

    except Exception as exc:  # noqa: BLE001
        elapsed = time.perf_counter() - t0
        logger.error("  FAILED game_pk=%d: %s", game.game_pk, exc, exc_info=True)
        return PipelineResult(
            game_pk=game.game_pk,
            success=False,
            error=str(exc),
            elapsed_seconds=round(elapsed, 2),
        )


# ---------------------------------------------------------------------------
# Daily summary report
# ---------------------------------------------------------------------------


def generate_daily_report(
    game_date: str,
    results: list[PipelineResult],
    total_elapsed: float,
    dry_run: bool,
) -> str:
    """Generate a text summary of the daily pipeline run.

    Parameters
    ----------
    game_date:
        ISO date string.
    results:
        List of per-game pipeline results.
    total_elapsed:
        Total wall-clock seconds for the entire run.
    dry_run:
        Whether this was a dry-run.

    Returns
    -------
    str
        Multi-line plain-text report.
    """
    sep = "=" * 66
    successes = [r for r in results if r.success]
    failures = [r for r in results if not r.success]
    total_sims = sum(r.n_simulations for r in successes)
    total_edges = sum(r.n_prop_edges for r in successes)

    lines = [
        sep,
        f"  BaselineMLB Daily Simulation Report — {game_date}",
        f"  {'[DRY RUN] ' if dry_run else ''}Run at {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC",
        sep,
        f"  Games processed : {len(results)}  ({len(successes)} OK, {len(failures)} failed)",
        f"  Total sims      : {total_sims:,}",
        f"  Prop edges      : {total_edges}",
        f"  Total time      : {total_elapsed:.1f}s",
        sep,
        "  PER-GAME RESULTS:",
    ]
    for r in results:
        status = "OK" if r.success else f"FAIL ({r.error[:50]})"
        lines.append(
            f"    game_pk={r.game_pk:>7}  {status:55s}  "
            f"{r.elapsed_seconds:.1f}s  "
            f"H:{r.home_score_mean:.2f} A:{r.away_score_mean:.2f}  "
            f"edges={r.n_prop_edges}"
        )
    lines.append(sep)
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    """Parse CLI arguments and run the daily pipeline.

    Parameters
    ----------
    argv:
        Command-line argument list (defaults to ``sys.argv[1:]``).

    Returns
    -------
    int
        Exit code: 0 on success, 1 on any failure.
    """
    parser = argparse.ArgumentParser(
        description="Run the BaselineMLB Monte Carlo simulation pipeline for today's games.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--date",
        type=str,
        default=date.today().isoformat(),
        help="Game date in YYYY-MM-DD format (default: today)",
    )
    parser.add_argument(
        "--games",
        type=str,
        default=None,
        help="Comma-separated list of game_pks to process (default: all today's games)",
    )
    parser.add_argument(
        "--n-sims",
        type=int,
        default=3_000,
        help="Number of Monte Carlo simulations per game (default: 3000)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run pipeline but skip all Supabase writes",
    )
    parser.add_argument(
        "--model-path",
        type=str,
        default=None,
        help=f"Path to matchup model .joblib file (default: {MATCHUP_MODEL_PATH})",
    )
    parser.add_argument(
        "--log-level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        default="INFO",
        help="Logging verbosity (default: INFO)",
    )

    args = parser.parse_args(argv)
    logging.getLogger().setLevel(getattr(logging, args.log_level))

    game_date: str = args.date
    game_pks: list[int] | None = (
        [int(pk.strip()) for pk in args.games.split(",") if pk.strip()]
        if args.games
        else None
    )
    n_sims: int = args.n_sims
    dry_run: bool = args.dry_run
    model_path = Path(args.model_path) if args.model_path else None

    logger.info(
        "BaselineMLB daily pipeline starting: date=%s  n_sims=%d  dry_run=%s",
        game_date,
        n_sims,
        dry_run,
    )

    pipeline_start = time.perf_counter()

    # Step 1: Fetch games
    try:
        games = fetch_todays_games(game_date, game_pks)
    except RuntimeError as exc:
        logger.error("Failed to fetch games: %s", exc)
        return 1

    if not games:
        logger.warning("No games found for %s — exiting.", game_date)
        return 0

    # Step 4: Load model (shared across all games)
    model = load_matchup_model(model_path)

    # Process each game
    results: list[PipelineResult] = []
    for game in games:
        result = run_game_pipeline(game, model, n_sims, dry_run)
        results.append(result)

    total_elapsed = time.perf_counter() - pipeline_start

    # Step 11: Daily report
    report = generate_daily_report(game_date, results, total_elapsed, dry_run)
    print("\n" + report + "\n")

    # Exit 1 if any game failed
    any_failed = any(not r.success for r in results)
    if any_failed:
        logger.error("Pipeline completed with errors.")
        return 1

    logger.info("Pipeline completed successfully in %.1fs.", total_elapsed)
    return 0


if __name__ == "__main__":
    sys.exit(main())


# ===========================================================================
# RUN DAILY COMPATIBILITY LAYER
# ===========================================================================
# Functions expected by test_simulator.py
# ===========================================================================


def _normalize_stat_type(raw_stat: str) -> str:
    """Normalise a stat type string to a short internal key.

    Examples
    --------
    >>> _normalize_stat_type("pitcher_strikeouts")
    'K'
    >>> _normalize_stat_type("batter_total_bases")
    'TB'
    """
    _MAP: dict[str, str] = {
        "pitcher_strikeouts": "K",
        "batter_strikeouts": "K",
        "batter_total_bases": "TB",
        "total_bases": "TB",
        "batter_hits": "H",
        "hits": "H",
        "home_runs": "HR",
        "batter_home_runs": "HR",
        "batter_walks": "BB",
        "pitcher_walks": "BB",
        "walks": "BB",
        "rbis": "RBI",
        "batter_rbis": "RBI",
        "batter_runs": "R",
        "runs": "R",
    }
    return _MAP.get(raw_stat, raw_stat)


def weather_to_modifier(weather: dict) -> float:
    """Convert weather dict to a single HR-probability modifier.

    Parameters
    ----------
    weather : dict
        Keys: ``temperature_f`` (or ``temp_f``), ``wind_mph``.

    Returns
    -------
    float
        Modifier in approximately [0.85, 1.15].
    """
    temp_f = float(weather.get("temperature_f", weather.get("temp_f", 72)))
    wind_mph = float(weather.get("wind_mph", 0))

    # Temperature effect: neutral at 72°F, ±0.003 per degree
    temp_mod = 1.0 + (temp_f - 72.0) * 0.003
    # Wind effect: ±0.001 per mph (small effect)
    wind_mod = 1.0 + wind_mph * 0.001

    modifier = temp_mod * wind_mod
    # Clamp to [0.85, 1.15]
    return float(max(0.85, min(1.15, modifier)))


def build_batter_profile(
    mlbam_id: int,
    name: str,
    position: int,
    stats: dict,
    min_pa: int = 50,
) -> "BatterProfile":
    """Build a ``BatterProfile`` from raw season stats.

    Falls back to MLB average probs if fewer than *min_pa* plate appearances.

    Parameters
    ----------
    mlbam_id, name, position:
        Passed through to ``BatterProfile``.
    stats : dict
        Keys (all optional): ``plateAppearances``, ``strikeOuts``,
        ``baseOnBalls``, ``hitByPitch``, ``hits``, ``doubles``,
        ``triples``, ``homeRuns``.
    min_pa : int
        Minimum PA for rate calculations.
    """
    from .monte_carlo_engine import (
        MLB_AVG_PROBS,
        BatterProfile,
        build_batter_probs,
    )

    pa = int(stats.get("plateAppearances", 0))
    if pa < min_pa:
        return BatterProfile(
            mlbam_id=mlbam_id,
            name=name,
            lineup_position=position,
            probs=MLB_AVG_PROBS.copy(),
        )

    k   = int(stats.get("strikeOuts", 0))
    bb  = int(stats.get("baseOnBalls", 0))
    hbp = int(stats.get("hitByPitch", 0))
    h   = int(stats.get("hits", 0))
    d   = int(stats.get("doubles", 0))
    t   = int(stats.get("triples", 0))
    hr  = int(stats.get("homeRuns", 0))
    singles = h - d - t - hr

    probs = build_batter_probs(
        k_rate=k / pa,
        bb_rate=bb / pa,
        hbp_rate=hbp / pa,
        single_rate=max(0.0, singles / pa),
        double_rate=d / pa,
        triple_rate=t / pa,
        hr_rate=hr / pa,
    )
    return BatterProfile(
        mlbam_id=mlbam_id,
        name=name,
        lineup_position=position,
        probs=probs,
    )
