"""
game_engine.py — BaselineMLB Monte Carlo Game Simulation Engine

Simulates complete MLB games plate-appearance by plate-appearance, tracking all
game state and collecting full probability distributions for every player stat.

Designed to run ~2,500 simulations per game with 60-80 PAs per simulated game.

Imports:
    simulation.config   -> SimulationConfig, GameData
    simulation.matchup_model -> MatchupModel
"""

from __future__ import annotations

import concurrent.futures
import json
import logging
import math
from collections import Counter, defaultdict
from copy import deepcopy
from typing import Any, Dict, List, Optional

import numpy as np

# ---------------------------------------------------------------------------
# Conditional imports from sibling modules — gracefully handle missing modules
# during standalone testing.
# ---------------------------------------------------------------------------
try:
    from simulation.config import GameData, SimulationConfig
except ImportError:  # pragma: no cover
    SimulationConfig = None  # type: ignore[assignment,misc]
    GameData = None          # type: ignore[assignment,misc]

try:
    from simulation.matchup_model import MatchupModel
except ImportError:  # pragma: no cover
    MatchupModel = None  # type: ignore[assignment,misc]

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Plate-appearance outcome labels (must match MatchupModel output keys)
PA_OUTCOMES = [
    "strikeout",
    "walk",
    "hbp",
    "single",
    "double",
    "triple",
    "home_run",
    "out",          # generic ground/fly/pop out (non-strikeout, non-HR)
]

# Average pitches thrown per plate appearance (used to track pitch counts)
AVG_PITCHES_PER_PA = 4.0

# Default starter pitch count distribution parameters (mean, std)
DEFAULT_PC_MEAN = 88.0
DEFAULT_PC_STD = 12.0

# Probability that a ground-ball out becomes a GDP when runner is on 1B with <2 outs
DEFAULT_GDP_RATE = 0.12

# Baserunner advancement probabilities
# Single: runner on 1B -> 2B (70%) or 3B (30%)
SINGLE_R1_TO_3B = 0.30
# Single: runner on 2B -> scores (65%) or 3B (35%)
SINGLE_R2_SCORE = 0.65
# Single: runner on 3B -> scores (95%)
SINGLE_R3_SCORE = 0.95
# Double: runner on 1B -> 3B (80%) or scores (20%)
DOUBLE_R1_SCORE = 0.20

# Maximum innings before the game is considered complete (safety cap)
MAX_INNINGS = 25

# Common betting lines used to compute p_over in projections
PROP_LINES: Dict[str, List[float]] = {
    "strikeouts":      [3.5, 4.5, 5.5, 6.5, 7.5, 8.5],
    "walks":           [0.5, 1.5],
    "hits":            [0.5, 1.5, 2.5],
    "total_bases":     [0.5, 1.5, 2.5, 3.5],
    "home_runs":       [0.5],
    "doubles":         [0.5],
    "triples":         [0.5],
    "hbp":             [0.5],
    "rbis":            [0.5, 1.5, 2.5],
    "runs_scored":     [0.5, 1.5],
    "pa":              [1.5, 2.5, 3.5, 4.5],
    "outs_recorded":   [14.5, 15.5, 16.5, 17.5, 18.5],  # pitcher stat
}


# ---------------------------------------------------------------------------
# GameState
# ---------------------------------------------------------------------------

class GameState:
    """
    Tracks the complete mutable state of a single in-progress simulated game.

    Attributes:
        inning (int): Current inning number (1-indexed, can exceed 9 in extras).
        half (str): ``'top'`` (away batting) or ``'bottom'`` (home batting).
        outs (int): Number of outs in the current half-inning (0-2).
        runners (dict): Mapping of base number -> runner_id (int) or ``None``.
            Keys are always 1, 2, 3.
        score (dict): ``{'away': int, 'home': int}``
        lineup_index (dict): ``{'away': int, 'home': int}`` — current position
            in the batting order (0-8), wraps around on next_batter().
        pitcher_pitch_count (dict): ``{'away': int, 'home': int}`` — running
            total of pitches thrown by the current pitcher for each team.
        current_pitcher (dict): ``{'away': dict, 'home': dict}`` — pitcher
            data objects (as supplied by GameData).
        is_starter_pulled (dict): ``{'away': bool, 'home': bool}``
    """

    __slots__ = (
        "inning",
        "half",
        "outs",
        "runners",
        "score",
        "lineup_index",
        "pitcher_pitch_count",
        "current_pitcher",
        "is_starter_pulled",
        "_walkoff_eligible",
    )

    def __init__(self) -> None:
        self.inning: int = 1
        self.half: str = "top"
        self.outs: int = 0
        self.runners: Dict[int, Optional[int]] = {1: None, 2: None, 3: None}
        self.score: Dict[str, int] = {"away": 0, "home": 0}
        self.lineup_index: Dict[str, int] = {"away": 0, "home": 0}
        self.pitcher_pitch_count: Dict[str, int] = {"away": 0, "home": 0}
        self.current_pitcher: Dict[str, Optional[Dict[str, Any]]] = {
            "away": None,
            "home": None,
        }
        self.is_starter_pulled: Dict[str, bool] = {"away": False, "home": False}
        self._walkoff_eligible: bool = False  # set after top-9+ completes

    # ------------------------------------------------------------------
    # Baserunner helpers
    # ------------------------------------------------------------------

    def advance_runners(self, bases: int) -> int:
        """
        Advance all current baserunners by ``bases`` bases deterministically.

        Does *not* handle the batter — that is the caller's responsibility.
        Runners that reach or pass home plate are scored.

        Args:
            bases: Number of bases to advance every baserunner.

        Returns:
            Number of runs scored by baserunners (batter NOT included).
        """
        runs = 0
        new_runners: Dict[int, Optional[int]] = {1: None, 2: None, 3: None}

        for base in (3, 2, 1):  # process in reverse to avoid collisions
            runner = self.runners[base]
            if runner is None:
                continue
            dest = base + bases
            if dest > 3:
                runs += 1  # runner scores
            else:
                new_runners[dest] = runner

        self.runners = new_runners
        self.score["away" if self.half == "top" else "home"] += runs
        return runs

    def advance_runners_probabilistic(
        self,
        outcome: str,
        rng: np.random.Generator,
    ) -> int:
        """
        Advance baserunners according to the probabilistic rules for singles
        and doubles (see module-level constants).  Other outcomes should use
        :meth:`advance_runners` directly.

        Args:
            outcome: ``'single'`` or ``'double'``.
            rng: NumPy random generator (for reproducibility per simulation).

        Returns:
            Number of runs scored by baserunners (batter NOT included).
        """
        runs = 0
        batting_team = "away" if self.half == "top" else "home"

        if outcome == "single":
            new_runners: Dict[int, Optional[int]] = {1: None, 2: None, 3: None}

            # Runner on 3B
            if self.runners[3] is not None:
                if rng.random() < SINGLE_R3_SCORE:
                    runs += 1
                else:
                    new_runners[3] = self.runners[3]

            # Runner on 2B
            if self.runners[2] is not None:
                if rng.random() < SINGLE_R2_SCORE:
                    runs += 1
                else:
                    # goes to 3B — only if 3B isn't already occupied
                    if new_runners[3] is None:
                        new_runners[3] = self.runners[2]
                    else:
                        runs += 1  # forced to score on collision

            # Runner on 1B
            if self.runners[1] is not None:
                if rng.random() < SINGLE_R1_TO_3B:
                    if new_runners[3] is None:
                        new_runners[3] = self.runners[1]
                    elif new_runners[2] is None:
                        new_runners[2] = self.runners[1]
                    else:
                        runs += 1  # bases full, forced score
                else:
                    if new_runners[2] is None:
                        new_runners[2] = self.runners[1]
                    else:
                        # 2B occupied; push to 3B or score
                        if new_runners[3] is None:
                            new_runners[3] = self.runners[1]
                        else:
                            runs += 1

            self.runners = new_runners

        elif outcome == "double":
            new_runners = {1: None, 2: None, 3: None}

            # Runners on 2B and 3B always score on a double
            if self.runners[3] is not None:
                runs += 1
            if self.runners[2] is not None:
                runs += 1

            # Runner on 1B: 80% -> 3B, 20% -> scores
            if self.runners[1] is not None:
                if rng.random() < DOUBLE_R1_SCORE:
                    runs += 1
                else:
                    new_runners[3] = self.runners[1]

            self.runners = new_runners

        else:
            raise ValueError(
                f"advance_runners_probabilistic only handles 'single'/'double', got '{outcome}'"
            )

        self.score[batting_team] += runs
        return runs

    def place_batter_on_base(self, base: int, batter_id: int) -> None:
        """
        Place the batter on the specified base.  If the base is occupied,
        the existing runner is pushed forward (walk-style forced advance) until
        a free base is found.  Runners pushed past 3B score.

        Args:
            base: Target base (1, 2, or 3).
            batter_id: Identifier for the batter.
        """
        batting_team = "away" if self.half == "top" else "home"
        if self.runners[base] is None:
            self.runners[base] = batter_id
            return

        # Push existing runner(s)
        current = batter_id
        for b in range(base, 4):
            occupant = self.runners.get(b)
            self.runners[b] = current
            if occupant is None:
                break
            current = occupant
            if b == 3:
                # occupant is forced home
                self.score[batting_team] += 1

    def force_advance_on_walk(self, batter_id: int) -> int:
        """
        Place batter on 1B with forced advancement (walk / HBP logic).

        Returns:
            Runs scored by any runner(s) forced home.
        """
        batting_team = "away" if self.half == "top" else "home"
        runs = 0

        # Only force if 1B is occupied (and subsequent bases)
        if self.runners[1] is None:
            self.runners[1] = batter_id
            return 0

        # All bases must be checked for force situation
        # Force only propagates when *all* lower bases are occupied
        if self.runners[2] is None:
            self.runners[2] = self.runners[1]
            self.runners[1] = batter_id
            return 0

        if self.runners[3] is None:
            self.runners[3] = self.runners[2]
            self.runners[2] = self.runners[1]
            self.runners[1] = batter_id
            return 0

        # Bases loaded — runner on 3B scores
        runs = 1
        self.score[batting_team] += runs
        self.runners[3] = self.runners[2]
        self.runners[2] = self.runners[1]
        self.runners[1] = batter_id
        return runs

    # ------------------------------------------------------------------
    # Out / inning management
    # ------------------------------------------------------------------

    def record_out(self) -> None:
        """Increment out count (does NOT call switch_sides)."""
        self.outs += 1

    def next_batter(self, team: str) -> None:
        """
        Advance the lineup pointer for *team* to the next batter.

        Args:
            team: ``'away'`` or ``'home'``.
        """
        self.lineup_index[team] = (self.lineup_index[team] + 1) % 9

    def is_game_over(self) -> bool:
        """
        Return ``True`` if the game has ended.

        Conditions:
        * Completed 9+ innings and away team leads after bottom half ends.
        * Walk-off: home team takes lead in bottom of 9th+.
        * Home team leads after top of 9th+ completes AND the bottom half has
          been skipped (walk-off eligible shortcut handled in simulate_game).
        * Safety cap: inning > MAX_INNINGS.
        """
        if self.inning > MAX_INNINGS:
            return True

        # Standard end: completed bottom of at least 9th inning
        if self.inning > 9 or (self.inning == 9 and self.half == "top"):
            # We only reach here after a side switch; check walkoff eligibility
            pass

        # Delegate complex logic to simulate_game; here we just expose a flag
        return False

    def switch_sides(self) -> None:
        """
        Flip the half-inning.  If transitioning from bottom -> top, increment
        the inning counter.  Resets outs and clears bases.
        """
        self.outs = 0
        self.runners = {1: None, 2: None, 3: None}

        if self.half == "top":
            self.half = "bottom"
        else:
            self.half = "top"
            self.inning += 1

    def set_manfred_runner(self) -> None:
        """
        Place a ghost runner on 2B for extra-inning (Manfred rule) play.
        The runner is given a synthetic id of -1 (does not map to a real player).
        """
        self.runners[2] = -1  # synthetic runner; runs not credited to any batter

    @property
    def batting_team(self) -> str:
        """Return ``'away'`` (top) or ``'home'`` (bottom)."""
        return "away" if self.half == "top" else "home"

    @property
    def fielding_team(self) -> str:
        """Return the team currently in the field."""
        return "home" if self.half == "top" else "away"

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"<GameState inning={self.inning} half={self.half} outs={self.outs} "
            f"score={self.score} runners={self.runners}>"
        )


# ---------------------------------------------------------------------------
# PlayerStats
# ---------------------------------------------------------------------------

class PlayerStats:
    """
    Accumulates per-player statistics across all Monte Carlo simulation runs.

    Each statistic is stored as a :class:`collections.Counter` mapping observed
    value -> number of simulations in which that value occurred.

    Attributes:
        player_id (int): MLBAM player identifier.
        player_name (str): Display name.
        stat_counts (dict[str, Counter]): Per-stat value distributions.
    """

    # Stat keys tracked for batters
    BATTER_STATS = [
        "pa",
        "hits",
        "singles",
        "doubles",
        "triples",
        "home_runs",
        "walks",
        "hbp",
        "strikeouts",
        "total_bases",
        "rbis",
        "runs_scored",
        "gdp",
    ]

    # Stat keys tracked for pitchers
    PITCHER_STATS = [
        "outs_recorded",
        "strikeouts",
        "walks",
        "hbp",
        "hits_allowed",
        "home_runs_allowed",
        "runs_allowed",
        "earned_runs",
        "pitches",
    ]

    def __init__(self, player_id: int, player_name: str) -> None:
        """
        Args:
            player_id: MLBAM player ID.
            player_name: Human-readable player name.
        """
        self.player_id: int = player_id
        self.player_name: str = player_name
        self.stat_counts: Dict[str, Counter] = defaultdict(Counter)

    # ------------------------------------------------------------------
    # Recording
    # ------------------------------------------------------------------

    def record_pa_outcome(self, outcome: str, **extras: Any) -> None:
        """
        Record a single plate-appearance outcome and any ancillary stats.

        Args:
            outcome: One of the ``PA_OUTCOMES`` strings.
            **extras: Additional keyword stats to increment, e.g.
                ``rbis=2``, ``runs_scored=1``.
        """
        self.stat_counts["pa"][1] += 1

        if outcome == "strikeout":
            self.stat_counts["strikeouts"][1] += 1
        elif outcome == "walk":
            self.stat_counts["walks"][1] += 1
        elif outcome == "hbp":
            self.stat_counts["hbp"][1] += 1
        elif outcome == "single":
            self.stat_counts["hits"][1] += 1
            self.stat_counts["singles"][1] += 1
            self.stat_counts["total_bases"][1] += 1
        elif outcome == "double":
            self.stat_counts["hits"][1] += 1
            self.stat_counts["doubles"][1] += 1
            self.stat_counts["total_bases"][2] += 1
        elif outcome == "triple":
            self.stat_counts["hits"][1] += 1
            self.stat_counts["triples"][1] += 1
            self.stat_counts["total_bases"][3] += 1
        elif outcome == "home_run":
            self.stat_counts["hits"][1] += 1
            self.stat_counts["home_runs"][1] += 1
            self.stat_counts["total_bases"][4] += 1
        elif outcome in ("out", "gdp"):
            if outcome == "gdp":
                self.stat_counts["gdp"][1] += 1

        for key, val in extras.items():
            if val:
                self.stat_counts[key][val] += 1

    def record_pitcher_pa(self, outcome: str, pitches: int = 4) -> None:
        """
        Record the pitching side of a plate appearance.

        Args:
            outcome: The PA outcome (same labels as batter side).
            pitches: Pitches thrown in this PA.
        """
        self.stat_counts["pitches"][pitches] += 1

        if outcome == "strikeout":
            self.stat_counts["outs_recorded"][1] += 1
            self.stat_counts["strikeouts"][1] += 1
        elif outcome == "walk":
            self.stat_counts["walks"][1] += 1
        elif outcome == "hbp":
            self.stat_counts["hbp"][1] += 1
        elif outcome in ("single", "double", "triple", "home_run"):
            self.stat_counts["hits_allowed"][1] += 1
            if outcome == "home_run":
                self.stat_counts["home_runs_allowed"][1] += 1
        elif outcome in ("out", "gdp"):
            self.stat_counts["outs_recorded"][1] += 1

    def finalise_simulation(self, sim_stats: Dict[str, int]) -> None:
        """
        Called at the end of each game simulation to commit the accumulated
        per-simulation totals into the distribution counters.

        Args:
            sim_stats: Mapping of stat_name -> total for this one simulation.
        """
        for stat, total in sim_stats.items():
            self.stat_counts[stat][total] += 1

    # ------------------------------------------------------------------
    # Distribution queries
    # ------------------------------------------------------------------

    def get_distribution(self, stat: str) -> Dict[int, int]:
        """
        Return the raw count distribution for *stat*.

        Args:
            stat: Stat name (e.g. ``'strikeouts'``).

        Returns:
            dict mapping value -> number of simulations with that value.
            Returns an empty dict if the stat has not been recorded.
        """
        return dict(self.stat_counts.get(stat, Counter()))

    def get_mean(self, stat: str) -> float:
        """
        Return the mean value of *stat* across all simulations.

        Args:
            stat: Stat name.

        Returns:
            Mean as a float; 0.0 if no data.
        """
        counts = self.stat_counts.get(stat)
        if not counts:
            return 0.0
        total_value = sum(v * n for v, n in counts.items())
        total_sims = sum(counts.values())
        if total_sims == 0:
            return 0.0
        return total_value / total_sims

    def get_median(self, stat: str) -> float:
        """
        Return the median value of *stat* across all simulations.

        Args:
            stat: Stat name.

        Returns:
            Median as a float; 0.0 if no data.
        """
        counts = self.stat_counts.get(stat)
        if not counts:
            return 0.0
        # Expand into a sorted flat list then take the middle
        total_sims = sum(counts.values())
        if total_sims == 0:
            return 0.0
        sorted_values = sorted(counts.keys())
        cumulative = 0
        for v in sorted_values:
            cumulative += counts[v]
            if cumulative >= total_sims / 2:
                return float(v)
        return float(sorted_values[-1])

    def get_std(self, stat: str) -> float:
        """
        Return the standard deviation of *stat* across all simulations.

        Args:
            stat: Stat name.

        Returns:
            Std dev as a float; 0.0 if fewer than 2 data points.
        """
        counts = self.stat_counts.get(stat)
        if not counts:
            return 0.0
        total_sims = sum(counts.values())
        if total_sims < 2:
            return 0.0
        mean = self.get_mean(stat)
        variance = sum(((v - mean) ** 2) * n for v, n in counts.items()) / total_sims
        return math.sqrt(variance)

    def get_p_over(self, stat: str, line: float) -> float:
        """
        Return the probability of exceeding *line* for *stat*.

        Args:
            stat: Stat name.
            line: The over/under line (e.g., ``4.5``).

        Returns:
            Probability (0.0-1.0) that the stat strictly exceeds *line*.
        """
        counts = self.stat_counts.get(stat)
        if not counts:
            return 0.0
        total_sims = sum(counts.values())
        if total_sims == 0:
            return 0.0
        over_count = sum(n for v, n in counts.items() if v > line)
        return over_count / total_sims

    def __repr__(self) -> str:  # pragma: no cover
        return f"<PlayerStats id={self.player_id} name='{self.player_name}'>"


# ---------------------------------------------------------------------------
# SimulationResult
# ---------------------------------------------------------------------------

class SimulationResult:
    """
    Holds all aggregated results from a full simulation batch for one game.

    Attributes:
        game_info (dict): Metadata: teams, date, venue, game_pk, etc.
        num_simulations (int): Number of iterations run.
        player_results (dict[int, PlayerStats]): MLBAM id -> :class:`PlayerStats`.
        team_results (dict): Run distributions and win probabilities keyed by
            ``'away'`` and ``'home'``.
    """

    def __init__(
        self,
        game_info: Dict[str, Any],
        num_simulations: int,
    ) -> None:
        """
        Args:
            game_info: Metadata dict (teams, date, venue, ...).
            num_simulations: Total simulations run.
        """
        self.game_info: Dict[str, Any] = game_info
        self.num_simulations: int = num_simulations
        self.player_results: Dict[int, PlayerStats] = {}
        self.team_results: Dict[str, Any] = {
            "away": {
                "run_distribution": Counter(),
                "wins": 0,
            },
            "home": {
                "run_distribution": Counter(),
                "wins": 0,
            },
        }

    # ------------------------------------------------------------------
    # Projection helpers
    # ------------------------------------------------------------------

    def get_player_projection(
        self,
        mlbam_id: int,
        stat: str,
    ) -> Dict[str, Any]:
        """
        Return a projection summary for one player and stat.

        Includes mean, median, std, the full distribution, and p_over for
        all common betting lines defined in :data:`PROP_LINES`.

        Args:
            mlbam_id: MLBAM player ID.
            stat: Stat name (e.g. ``'strikeouts'``).

        Returns:
            Dict with keys: ``player_id``, ``player_name``, ``stat``,
            ``mean``, ``median``, ``std``, ``distribution``, ``p_over``.

        Raises:
            KeyError: If *mlbam_id* is not in ``player_results``.
        """
        ps = self.player_results[mlbam_id]
        lines = PROP_LINES.get(stat, [0.5])
        return {
            "player_id": mlbam_id,
            "player_name": ps.player_name,
            "stat": stat,
            "mean": round(ps.get_mean(stat), 4),
            "median": ps.get_median(stat),
            "std": round(ps.get_std(stat), 4),
            "distribution": ps.get_distribution(stat),
            "p_over": {
                str(line): round(ps.get_p_over(stat, line), 4)
                for line in lines
            },
        }

    def get_all_projections(self) -> List[Dict[str, Any]]:
        """
        Return a flat list of projection dicts for every player x stat
        combination, formatted for insertion into the Supabase
        ``projections`` table.

        Returns:
            List of projection dicts.
        """
        rows: List[Dict[str, Any]] = []
        game_pk = self.game_info.get("game_pk")
        game_date = self.game_info.get("game_date")

        for player_id, ps in self.player_results.items():
            # Determine which stats to export based on player role
            stat_set = (
                PlayerStats.PITCHER_STATS
                if self.game_info.get("pitchers", {}).get(player_id)
                else PlayerStats.BATTER_STATS
            )
            for stat in stat_set:
                if not ps.stat_counts.get(stat):
                    continue
                proj = self.get_player_projection(player_id, stat)
                row: Dict[str, Any] = {
                    "game_pk": game_pk,
                    "game_date": game_date,
                    "player_id": player_id,
                    "player_name": ps.player_name,
                    "stat": stat,
                    "mean": proj["mean"],
                    "median": proj["median"],
                    "std": proj["std"],
                    "distribution_json": json.dumps(proj["distribution"]),
                }
                for line_str, prob in proj["p_over"].items():
                    row[f"p_over_{line_str.replace('.', '_')}"] = prob
                rows.append(row)

        return rows

    def to_json(self) -> str:
        """
        Serialise the full :class:`SimulationResult` to a JSON string.

        Returns:
            JSON-encoded string.
        """
        payload: Dict[str, Any] = {
            "game_info": self.game_info,
            "num_simulations": self.num_simulations,
            "team_results": {
                side: {
                    "run_distribution": {
                        str(k): v
                        for k, v in data["run_distribution"].items()
                    },
                    "wins": data["wins"],
                    "win_pct": round(
                        data["wins"] / max(self.num_simulations, 1), 4
                    ),
                }
                for side, data in self.team_results.items()
            },
            "player_projections": {},
        }

        for player_id, ps in self.player_results.items():
            stat_set = (
                PlayerStats.PITCHER_STATS
                if self.game_info.get("pitchers", {}).get(player_id)
                else PlayerStats.BATTER_STATS
            )
            payload["player_projections"][str(player_id)] = {
                "player_name": ps.player_name,
                "stats": {
                    stat: {
                        "mean": round(ps.get_mean(stat), 4),
                        "median": ps.get_median(stat),
                        "std": round(ps.get_std(stat), 4),
                        "distribution": {
                            str(k): v
                            for k, v in ps.get_distribution(stat).items()
                        },
                    }
                    for stat in stat_set
                    if ps.stat_counts.get(stat)
                },
            }

        return json.dumps(payload, default=str)

    def __repr__(self) -> str:  # pragma: no cover
        away = self.game_info.get("away_team", "?")
        home = self.game_info.get("home_team", "?")
        return (
            f"<SimulationResult {away}@{home} n={self.num_simulations} "
            f"players={len(self.player_results)}>"
        )


# ---------------------------------------------------------------------------
# GameSimulator
# ---------------------------------------------------------------------------

class GameSimulator:
    """
    The core Monte Carlo game simulation engine for BaselineMLB.

    Args:
        matchup_model: A fitted :class:`~simulation.matchup_model.MatchupModel`
            instance with a ``predict_pa_probs(pitcher, batter, context)``
            method.
        config: A :class:`~simulation.config.SimulationConfig` instance
            controlling iteration counts and other tuning parameters.
    """

    def __init__(
        self,
        matchup_model: Any,   # MatchupModel
        config: Any,          # SimulationConfig
    ) -> None:
        self.matchup_model = matchup_model
        self.config = config

        # Pull commonly used config values once
        self._num_sims: int = getattr(config, "NUM_SIMULATIONS", 2500)
        self._pc_mean: float = getattr(config, "pitcher_pc_mean", DEFAULT_PC_MEAN)
        self._pc_std: float = getattr(config, "pitcher_pc_std", DEFAULT_PC_STD)
        self._gdp_rate: float = getattr(config, "gdp_rate", DEFAULT_GDP_RATE)

        logger.info(
            "GameSimulator initialised: num_sims=%d, pc_mean=%.1f, pc_std=%.1f",
            self._num_sims,
            self._pc_mean,
            self._pc_std,
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def simulate_game(self, game_data: Any) -> SimulationResult:
        """
        Run the full Monte Carlo simulation for one game.

        Args:
            game_data: A :class:`~simulation.config.GameData` object providing
                lineups, starting pitchers, bullpen data, park factor, etc.

        Returns:
            :class:`SimulationResult` with full distributions for all players.
        """
        game_info = self._extract_game_info(game_data)

        # Build PlayerStats containers — one per batter per side + pitchers
        player_stats: Dict[int, PlayerStats] = {}

        away_lineup: List[Dict[str, Any]] = game_data.away_lineup  # list of 9 player dicts
        home_lineup: List[Dict[str, Any]] = game_data.home_lineup

        away_starter: Dict[str, Any] = game_data.away_starter
        home_starter: Dict[str, Any] = game_data.home_starter

        away_bullpen: Dict[str, Any] = getattr(game_data, "away_bullpen_composite", {})
        home_bullpen: Dict[str, Any] = getattr(game_data, "home_bullpen_composite", {})

        # Register all players
        for player in away_lineup + home_lineup:
            pid = player["mlbam_id"]
            if pid not in player_stats:
                player_stats[pid] = PlayerStats(pid, player.get("name", str(pid)))

        for pitcher in (away_starter, home_starter):
            pid = pitcher["mlbam_id"]
            if pid not in player_stats:
                player_stats[pid] = PlayerStats(pid, pitcher.get("name", str(pid)))

        result = SimulationResult(game_info, self._num_sims)

        # Mark which player ids are pitchers so get_all_projections can route
        pitcher_ids = {away_starter["mlbam_id"], home_starter["mlbam_id"]}
        game_info["pitchers"] = {pid: True for pid in pitcher_ids}

        rng = np.random.default_rng(
            seed=getattr(self.config, "random_seed", None)
        )

        logger.info(
            "Starting simulation: game_pk=%s, sims=%d",
            game_info.get("game_pk"),
            self._num_sims,
        )

        for sim_idx in range(self._num_sims):
            self._run_single_game(
                rng=rng,
                away_lineup=away_lineup,
                home_lineup=home_lineup,
                away_starter=away_starter,
                home_starter=home_starter,
                away_bullpen=away_bullpen,
                home_bullpen=home_bullpen,
                game_data=game_data,
                player_stats=player_stats,
                result=result,
            )

        result.player_results = player_stats

        logger.info(
            "Simulation complete: game_pk=%s, away_wins=%d, home_wins=%d",
            game_info.get("game_pk"),
            result.team_results["away"]["wins"],
            result.team_results["home"]["wins"],
        )
        return result

    def simulate_batch(
        self,
        games: List[Any],  # list[GameData]
        max_workers: Optional[int] = None,
    ) -> List[SimulationResult]:
        """
        Run :meth:`simulate_game` for each game in *games*.

        Args:
            games: List of :class:`~simulation.config.GameData` objects.
            max_workers: Maximum number of worker threads.

        Returns:
            List of :class:`SimulationResult` objects, one per game, in the
            same order as *games*.
        """
        if not games:
            return []

        workers = max_workers or min(len(games), (max_workers or 4))
        logger.info("simulate_batch: %d games, max_workers=%d", len(games), workers)

        results: List[Optional[SimulationResult]] = [None] * len(games)

        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
            future_to_idx = {
                executor.submit(self.simulate_game, game): idx
                for idx, game in enumerate(games)
            }
            for future in concurrent.futures.as_completed(future_to_idx):
                idx = future_to_idx[future]
                try:
                    results[idx] = future.result()
                except Exception:
                    logger.exception(
                        "simulate_game failed for game index %d", idx
                    )
                    results[idx] = None  # type: ignore[assignment]

        return [r for r in results if r is not None]  # type: ignore[return-value]

    # ------------------------------------------------------------------
    # Internal: single game simulation
    # ------------------------------------------------------------------

    def _run_single_game(
        self,
        rng: np.random.Generator,
        away_lineup: List[Dict[str, Any]],
        home_lineup: List[Dict[str, Any]],
        away_starter: Dict[str, Any],
        home_starter: Dict[str, Any],
        away_bullpen: Dict[str, Any],
        home_bullpen: Dict[str, Any],
        game_data: Any,
        player_stats: Dict[int, PlayerStats],
        result: SimulationResult,
    ) -> Dict[int, Dict[str, int]]:
        """
        Simulate one complete game from first pitch to final out.
        """
        gs = GameState()

        # Initialise pitchers
        gs.current_pitcher["away"] = deepcopy(away_starter)
        gs.current_pitcher["home"] = deepcopy(home_starter)

        # Draw pitch-count limits for each starter from Normal distribution
        away_pc_limit = max(
            int(rng.normal(self._pc_mean, self._pc_std)), 50
        )
        home_pc_limit = max(
            int(rng.normal(self._pc_mean, self._pc_std)), 50
        )
        pc_limits = {"away": away_pc_limit, "home": home_pc_limit}

        # Per-simulation per-player stat accumulators
        # {player_id: {stat: value}}
        sim_totals: Dict[int, Dict[str, int]] = defaultdict(
            lambda: defaultdict(int)
        )

        park_factor: float = getattr(game_data, "park_factor", 1.0)

        # ------------------------------------------------------------------
        # Main game loop
        # ------------------------------------------------------------------
        game_over = False
        while not game_over:
            # Extra innings: place Manfred runner on 2B at start of each half
            if gs.inning > 9:
                gs.set_manfred_runner()

            # Safety valve
            if gs.inning > MAX_INNINGS:
                break

            batting_team = gs.batting_team
            fielding_team = gs.fielding_team
            lineup = away_lineup if batting_team == "away" else home_lineup

            # Half-inning loop
            while gs.outs < 3:
                # Walk-off check: if home leads after top half of 9th+, skip
                if (
                    gs.half == "bottom"
                    and gs.inning >= 9
                    and gs.score["home"] > gs.score["away"]
                    and gs.outs == 0
                    and gs.runners == {1: None, 2: None, 3: None}
                ):
                    game_over = True
                    break

                # Get current batter
                batter_idx = gs.lineup_index[batting_team]
                batter = lineup[batter_idx]
                batter_id = batter["mlbam_id"]

                # Get current pitcher
                pitcher = gs.current_pitcher[fielding_team]
                pitcher_id = pitcher["mlbam_id"]

                # Build context dict for the matchup model
                context = self._build_context(gs, game_data, park_factor)

                # Get PA outcome probabilities from model
                probs_dict = self.matchup_model.predict_pa_probs(
                    pitcher, batter, context
                )
                outcomes = list(probs_dict.keys())
                probs = np.array(list(probs_dict.values()), dtype=np.float64)

                # Normalise (guard against floating point drift)
                prob_sum = probs.sum()
                if prob_sum <= 0:
                    probs = np.ones(len(probs)) / len(probs)
                else:
                    probs /= prob_sum

                # Draw outcome
                outcome: str = outcomes[
                    rng.choice(len(outcomes), p=probs)
                ]

                # Check for GDP
                gdp = False
                if (
                    outcome == "out"
                    and gs.runners[1] is not None
                    and gs.outs < 2
                ):
                    gdp_rate = batter.get("gdp_rate", self._gdp_rate)
                    if rng.random() < gdp_rate:
                        gdp = True

                # Pitches thrown this PA (~Normal around 4, floor 1)
                pitches_this_pa = max(1, int(rng.normal(AVG_PITCHES_PER_PA, 1.2)))
                gs.pitcher_pitch_count[fielding_team] += pitches_this_pa

                # ----------------------------------------------------------
                # Resolve the PA outcome and update game state
                # ----------------------------------------------------------
                runs_on_play = 0

                if outcome == "strikeout":
                    gs.record_out()
                    sim_totals[batter_id]["strikeouts"] += 1
                    sim_totals[pitcher_id]["strikeouts"] += 1

                elif outcome in ("walk", "hbp"):
                    runs_on_play = gs.force_advance_on_walk(batter_id)
                    if outcome == "walk":
                        sim_totals[batter_id]["walks"] += 1
                    else:
                        sim_totals[batter_id]["hbp"] += 1

                elif outcome == "single":
                    runs_on_play = gs.advance_runners_probabilistic("single", rng)
                    gs.runners[1] = batter_id
                    sim_totals[batter_id]["hits"] += 1
                    sim_totals[batter_id]["singles"] += 1
                    sim_totals[batter_id]["total_bases"] += 1
                    sim_totals[pitcher_id]["hits_allowed"] += 1

                elif outcome == "double":
                    runs_on_play = gs.advance_runners_probabilistic("double", rng)
                    gs.runners[2] = batter_id
                    sim_totals[batter_id]["hits"] += 1
                    sim_totals[batter_id]["doubles"] += 1
                    sim_totals[batter_id]["total_bases"] += 2
                    sim_totals[pitcher_id]["hits_allowed"] += 1

                elif outcome == "triple":
                    runs_on_play = gs.advance_runners(3)  # all runners advance 3+
                    gs.runners[3] = batter_id
                    sim_totals[batter_id]["hits"] += 1
                    sim_totals[batter_id]["triples"] += 1
                    sim_totals[batter_id]["total_bases"] += 3
                    sim_totals[pitcher_id]["hits_allowed"] += 1

                elif outcome == "home_run":
                    # All runners score + batter
                    runners_scoring = sum(
                        1 for r in gs.runners.values() if r is not None and r != -1
                    )
                    # Manfred runner counts as a run but not credited to player
                    gs.runners.get(2) == -1
                    runs_on_play = runners_scoring + 1  # +1 for batter

                    # Credit RBIs for actual runners (not Manfred ghost runner)
                    rbi_count = sum(
                        1 for r in gs.runners.values()
                        if r is not None and r != -1
                    ) + 1  # batter himself

                    # Credit runs_scored to actual baserunners
                    for base_num, runner_id in gs.runners.items():
                        if runner_id is not None and runner_id != -1:
                            sim_totals[runner_id]["runs_scored"] += 1

                    gs.runners = {1: None, 2: None, 3: None}
                    batting_side = "away" if gs.half == "top" else "home"
                    gs.score[batting_side] += runs_on_play
                    runs_on_play = 0  # already added above

                    sim_totals[batter_id]["hits"] += 1
                    sim_totals[batter_id]["home_runs"] += 1
                    sim_totals[batter_id]["total_bases"] += 4
                    sim_totals[batter_id]["rbis"] += rbi_count
                    sim_totals[batter_id]["runs_scored"] += 1
                    sim_totals[pitcher_id]["hits_allowed"] += 1
                    sim_totals[pitcher_id]["home_runs_allowed"] += 1
                    sim_totals[pitcher_id]["runs_allowed"] += rbi_count

                elif outcome == "out":
                    if gdp:
                        # Double play: batter and runner on 1B are both out
                        gs.runners[1] = None
                        gs.record_out()  # first out (runner)
                        if gs.outs < 3:
                            gs.record_out()  # second out (batter)
                        sim_totals[batter_id]["gdp"] += 1
                    else:
                        gs.record_out()

                # ----------------------------------------------------------
                # Non-HR runs: credit RBIs and runs_scored
                # ----------------------------------------------------------
                if runs_on_play > 0 and outcome != "home_run":
                    sim_totals[batter_id]["rbis"] += runs_on_play
                    batting_side_r = "away" if gs.half == "top" else "home"
                    gs.score[batting_side_r] += runs_on_play

                # Pitcher stat updates
                if outcome not in ("home_run",):  # HR already handled above
                    if outcome in ("out", "strikeout", "gdp"):
                        sim_totals[pitcher_id]["outs_recorded"] += 1
                        if gdp:
                            sim_totals[pitcher_id]["outs_recorded"] += 1
                    if outcome in ("walk", "hbp"):
                        pass  # already tracked above
                    if outcome in ("single", "double", "triple"):
                        sim_totals[pitcher_id]["runs_allowed"] += runs_on_play
                sim_totals[pitcher_id]["pitches"] += pitches_this_pa
                sim_totals[batter_id]["pa"] += 1

                # ----------------------------------------------------------
                # Walk-off in bottom of 9th+
                # ----------------------------------------------------------
                if (
                    gs.half == "bottom"
                    and gs.inning >= 9
                    and gs.score["home"] > gs.score["away"]
                ):
                    game_over = True
                    break

                # ----------------------------------------------------------
                # Pitcher substitution check
                # ----------------------------------------------------------
                if not gs.is_starter_pulled[fielding_team]:
                    if gs.pitcher_pitch_count[fielding_team] >= pc_limits[fielding_team]:
                        # Switch to bullpen composite
                        bullpen = away_bullpen if fielding_team == "away" else home_bullpen
                        if bullpen:
                            gs.current_pitcher[fielding_team] = bullpen
                            gs.is_starter_pulled[fielding_team] = True
                            logger.debug(
                                "Sim: %s starter pulled after %d pitches (limit %d)",
                                fielding_team,
                                gs.pitcher_pitch_count[fielding_team],
                                pc_limits[fielding_team],
                            )

                if not gdp or gs.outs < 3:
                    gs.next_batter(batting_team)

            # End of half-inning
            if game_over:
                break

            # Check if game ends after top of inning >= 9 with home team leading
            if gs.half == "bottom" and gs.inning >= 9:
                # We just finished the bottom half. Check standard game end.
                if gs.score["away"] != gs.score["home"]:
                    game_over = True
                    break

            if gs.half == "top" and gs.inning >= 9:
                # Top of 9th+ just ended; if home leads, skip bottom
                if gs.score["home"] > gs.score["away"]:
                    game_over = True
                    break

            gs.switch_sides()

        # ------------------------------------------------------------------
        # End of simulation: record team results
        # ------------------------------------------------------------------
        away_runs = gs.score["away"]
        home_runs = gs.score["home"]

        result.team_results["away"]["run_distribution"][away_runs] += 1
        result.team_results["home"]["run_distribution"][home_runs] += 1

        if away_runs > home_runs:
            result.team_results["away"]["wins"] += 1
        elif home_runs > away_runs:
            result.team_results["home"]["wins"] += 1
        # ties (extra-inning safety cap reached) counted as neither win

        # Commit per-simulation totals to shared PlayerStats
        for player_id, stat_map in sim_totals.items():
            if player_id not in player_stats:
                continue  # ghost runner (-1) or unregistered
            ps = player_stats[player_id]
            for stat, val in stat_map.items():
                ps.stat_counts[stat][val] += 1

        return dict(sim_totals)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _build_context(
        gs: GameState,
        game_data: Any,
        park_factor: float,
    ) -> Dict[str, Any]:
        """
        Build the context dict passed to :meth:`MatchupModel.predict_pa_probs`.
        """
        return {
            "inning": gs.inning,
            "half": gs.half,
            "outs": gs.outs,
            "runners": {
                "on_first": gs.runners[1] is not None,
                "on_second": gs.runners[2] is not None,
                "on_third": gs.runners[3] is not None,
            },
            "score_diff": gs.score["away"] - gs.score["home"],
            "batting_team": gs.batting_team,
            "park_factor": park_factor,
            "is_extra_innings": gs.inning > 9,
            "pitcher_pitch_count": gs.pitcher_pitch_count[gs.fielding_team],
            "is_starter": not gs.is_starter_pulled[gs.fielding_team],
        }

    @staticmethod
    def _extract_game_info(game_data: Any) -> Dict[str, Any]:
        """
        Extract a serialisable metadata dict from a :class:`GameData` object.
        """
        return {
            "game_pk": getattr(game_data, "game_pk", None),
            "game_date": getattr(game_data, "game_date", None),
            "away_team": getattr(game_data, "away_team", None),
            "home_team": getattr(game_data, "home_team", None),
            "venue": getattr(game_data, "venue", None),
            "park_factor": getattr(game_data, "park_factor", 1.0),
        }


# ---------------------------------------------------------------------------
# Module-level convenience
# ---------------------------------------------------------------------------

def create_simulator(
    matchup_model: Any,
    config: Any,
) -> GameSimulator:
    """
    Factory function to create a :class:`GameSimulator`.

    Args:
        matchup_model: Fitted :class:`~simulation.matchup_model.MatchupModel`.
        config: :class:`~simulation.config.SimulationConfig` instance.

    Returns:
        Ready-to-use :class:`GameSimulator`.
    """
    return GameSimulator(matchup_model=matchup_model, config=config)
