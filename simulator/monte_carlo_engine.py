"""
monte_carlo_engine.py — Core Monte Carlo game simulation engine
===============================================================

Runs 3 000+ full MLB game simulations per call using vectorised NumPy
random sampling.  Each simulation tracks every plate appearance outcome
and produces per-batter / per-pitcher stat arrays that downstream modules
consume for probability-distribution analysis.

Design notes
------------
- Outcome probabilities are supplied as dicts keyed by outcome token
  (e.g. ``{"K": 0.22, "BB": 0.08, "1B": 0.18, ...}``).
- Runner advancement follows simplified but realistic rules; see
  ``_advance_runners`` for details.
- Pitcher fatigue degrades strikeout probability linearly after a
  configurable batter-faced threshold.
- All random draws use a seeded ``numpy.random.Generator`` for
  reproducibility.
- Target wall-clock: 3 000 simulations of a full nine-inning game in
  under 10 seconds on a modern laptop.
"""

from __future__ import annotations

import argparse
import logging
import time
from dataclasses import dataclass, field
from typing import Any

import numpy as np

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Outcome tokens (ordered for numpy searchsorted vectorisation)
# ---------------------------------------------------------------------------
OUTCOMES: list[str] = ["K", "BB", "HBP", "1B", "2B", "3B", "HR", "OUT"]

# Bases as integer flags: 0=empty, 1=runner present
FIRST = 0
SECOND = 1
THIRD = 2


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class SimulationConfig:
    """Hyper-parameters that control a simulation run.

    Attributes
    ----------
    n_simulations:
        Number of full-game Monte Carlo iterations.
    innings:
        Regulation innings per game (9 for MLB).
    dh_rule:
        If True, apply universal designated-hitter rule (pitcher does not bat).
    lineup_size:
        Number of batters in the lineup (always 9 in MLB).
    fatigue_threshold:
        Batters faced before pitcher fatigue begins affecting strikeout rate.
    fatigue_k_decay:
        Fractional reduction in K-probability per batter faced above threshold.
    random_seed:
        Seed for ``numpy.random.default_rng``; ``None`` for non-deterministic.
    max_extras:
        Maximum extra-inning half-frames to simulate before forcing a tie result.
    """

    n_simulations: int = 3_000
    innings: int = 9
    dh_rule: bool = True
    lineup_size: int = 9
    fatigue_threshold: int = 25
    fatigue_k_decay: float = 0.02
    random_seed: int | None = 42
    max_extras: int = 6


@dataclass
class PlateAppearanceResult:
    """The resolved outcome of a single plate appearance.

    Attributes
    ----------
    outcome:
        One of the OUTCOMES tokens.
    total_bases:
        Bases earned by the batter (0 for K/BB/HBP/OUT, 1-4 for hits/HR).
    is_hit:
        True for 1B, 2B, 3B, HR.
    is_walk:
        True for BB or HBP.
    is_strikeout:
        True for K.
    """

    outcome: str
    total_bases: int
    is_hit: bool
    is_walk: bool
    is_strikeout: bool


@dataclass
class GameState:
    """Mutable game state for a single simulation iteration.

    Attributes
    ----------
    inning:
        Current inning number (1-indexed).
    half:
        ``"top"`` or ``"bottom"``.
    outs:
        Outs recorded in the current half-inning (0-2).
    runners:
        Three-element list: ``[first, second, third]``, each 0 or 1.
    score:
        ``[away_score, home_score]``.
    batting_order_idx:
        Current position in the nine-batter lineup (0-8).
    pitcher_batters_faced:
        Running count of batters faced by the current pitcher.
    """

    inning: int = 1
    half: str = "top"  # "top" = away bats, "bottom" = home bats
    outs: int = 0
    runners: list[int] = field(default_factory=lambda: [0, 0, 0])
    score: list[int] = field(default_factory=lambda: [0, 0])
    batting_order_idx: int = 0
    pitcher_batters_faced: int = 0

    def reset_half_inning(self) -> None:
        """Clear runners and outs for the start of a new half-inning."""
        self.outs = 0
        self.runners = [0, 0, 0]

    def runs_scored(self) -> int:
        """Return the number of runners currently on base (convenience)."""
        return sum(self.runners)


@dataclass
class SimulationResult:
    """Raw per-simulation stat arrays for a single game.

    All arrays have shape ``(n_simulations,)`` unless otherwise noted.

    Attributes
    ----------
    home_scores:
        Home team run total for each simulation.
    away_scores:
        Away team run total for each simulation.
    batter_hits:
        Dict keyed by batter_id -> array of hit counts.
    batter_total_bases:
        Dict keyed by batter_id -> array of total-bases counts.
    batter_walks:
        Dict keyed by batter_id -> array of walk counts.
    batter_strikeouts:
        Dict keyed by batter_id -> array of strikeout counts.
    batter_rbis:
        Dict keyed by batter_id -> array of RBI counts.
    batter_runs:
        Dict keyed by batter_id -> array of run counts.
    pitcher_strikeouts:
        Dict keyed by pitcher_id -> array of strikeout counts.
    pitcher_walks:
        Dict keyed by pitcher_id -> array of walk (BB+HBP) counts.
    pitcher_hits_allowed:
        Dict keyed by pitcher_id -> array of hits-allowed counts.
    pitcher_innings:
        Dict keyed by pitcher_id -> array of innings-pitched (float).
    pitcher_pitches:
        Dict keyed by pitcher_id -> array of estimated pitch counts.
    """

    home_scores: np.ndarray = field(default_factory=lambda: np.array([]))
    away_scores: np.ndarray = field(default_factory=lambda: np.array([]))
    batter_hits: dict[str, np.ndarray] = field(default_factory=dict)
    batter_total_bases: dict[str, np.ndarray] = field(default_factory=dict)
    batter_walks: dict[str, np.ndarray] = field(default_factory=dict)
    batter_strikeouts: dict[str, np.ndarray] = field(default_factory=dict)
    batter_rbis: dict[str, np.ndarray] = field(default_factory=dict)
    batter_runs: dict[str, np.ndarray] = field(default_factory=dict)
    pitcher_strikeouts: dict[str, np.ndarray] = field(default_factory=dict)
    pitcher_walks: dict[str, np.ndarray] = field(default_factory=dict)
    pitcher_hits_allowed: dict[str, np.ndarray] = field(default_factory=dict)
    pitcher_innings: dict[str, np.ndarray] = field(default_factory=dict)
    pitcher_pitches: dict[str, np.ndarray] = field(default_factory=dict)


@dataclass
class StatSummary:
    """Descriptive statistics for a single player-stat distribution.

    Attributes
    ----------
    mean / median / std:
        Central-tendency and spread measures.
    p10 / p25 / p75 / p90:
        Percentile values.
    min / max:
        Extreme values observed across simulations.
    """

    mean: float = 0.0
    median: float = 0.0
    std: float = 0.0
    p10: float = 0.0
    p25: float = 0.0
    p75: float = 0.0
    p90: float = 0.0
    min: float = 0.0
    max: float = 0.0

    def prob_over(self, threshold: float) -> float:
        """Return the empirical probability that the stat exceeds *threshold*.

        Note: this method is populated post-hoc by ``SimulationSummary``
        using the underlying raw array; it is a placeholder on the
        dataclass itself.
        """
        raise NotImplementedError(
            "Call SimulationSummary.prob_over(player_id, stat, threshold) instead."
        )


@dataclass
class SimulationSummary:
    """Aggregated distributions across all Monte Carlo iterations.

    Attributes
    ----------
    n_simulations:
        Number of iterations used to build this summary.
    home_score:
        Score distribution summary for the home team.
    away_score:
        Score distribution summary for the away team.
    batter_stats:
        Nested dict: ``batter_id -> stat_name -> StatSummary``.
    pitcher_stats:
        Nested dict: ``pitcher_id -> stat_name -> StatSummary``.
    raw:
        Reference to the underlying ``SimulationResult`` for ad-hoc queries.
    """

    n_simulations: int = 0
    home_score: StatSummary = field(default_factory=StatSummary)
    away_score: StatSummary = field(default_factory=StatSummary)
    batter_stats: dict[str, dict[str, StatSummary]] = field(default_factory=dict)
    pitcher_stats: dict[str, dict[str, StatSummary]] = field(default_factory=dict)
    raw: SimulationResult | None = None

    def prob_over(self, player_id: str, stat: str, threshold: float) -> float:
        """Return P(stat > threshold) for a player across all simulations.

        Parameters
        ----------
        player_id:
            Batter or pitcher identifier.
        stat:
            Stat key, e.g. ``"strikeouts"`` or ``"hits"``.
        threshold:
            The line to compare against.

        Returns
        -------
        float
            Probability in [0, 1].
        """
        arr = self._get_raw_array(player_id, stat)
        if arr is None:
            return 0.0
        return float(np.mean(arr > threshold))

    def prob_under(self, player_id: str, stat: str, threshold: float) -> float:
        """Return P(stat < threshold) for a player across all simulations."""
        arr = self._get_raw_array(player_id, stat)
        if arr is None:
            return 0.0
        return float(np.mean(arr < threshold))

    def _get_raw_array(self, player_id: str, stat: str) -> np.ndarray | None:
        """Retrieve the raw simulation array for *player_id* / *stat*."""
        if self.raw is None:
            return None
        batter_map: dict[str, dict[str, np.ndarray]] = {
            "hits": self.raw.batter_hits,
            "total_bases": self.raw.batter_total_bases,
            "walks": self.raw.batter_walks,
            "strikeouts": self.raw.batter_strikeouts,
            "rbis": self.raw.batter_rbis,
            "runs": self.raw.batter_runs,
        }
        pitcher_map: dict[str, dict[str, np.ndarray]] = {
            "strikeouts": self.raw.pitcher_strikeouts,
            "walks": self.raw.pitcher_walks,
            "hits_allowed": self.raw.pitcher_hits_allowed,
            "innings": self.raw.pitcher_innings,
            "pitches": self.raw.pitcher_pitches,
        }
        if stat in batter_map and player_id in batter_map[stat]:
            return batter_map[stat][player_id]
        if stat in pitcher_map and player_id in pitcher_map[stat]:
            return pitcher_map[stat][player_id]
        return None


# ---------------------------------------------------------------------------
# Helper utilities
# ---------------------------------------------------------------------------


def _normalise_probs(prob_dict: dict[str, float]) -> dict[str, float]:
    """Ensure outcome probabilities sum to 1.0 (re-normalise if needed).

    Parameters
    ----------
    prob_dict:
        Raw probability dict from the matchup model.

    Returns
    -------
    dict[str, float]
        Normalised dict; missing outcomes are filled with 0.
    """
    full: dict[str, float] = {o: prob_dict.get(o, 0.0) for o in OUTCOMES}
    total = sum(full.values())
    if total <= 0:
        # Fallback to league-average distribution
        full = {
            "K": 0.225,
            "BB": 0.085,
            "HBP": 0.010,
            "1B": 0.155,
            "2B": 0.050,
            "3B": 0.005,
            "HR": 0.035,
            "OUT": 0.435,
        }
        total = 1.0
    return {k: v / total for k, v in full.items()}


def _summarise_array(arr: np.ndarray) -> StatSummary:
    """Compute descriptive statistics over a 1-D array.

    Parameters
    ----------
    arr:
        1-D NumPy array of simulation outcomes.

    Returns
    -------
    StatSummary
    """
    return StatSummary(
        mean=float(np.mean(arr)),
        median=float(np.median(arr)),
        std=float(np.std(arr)),
        p10=float(np.percentile(arr, 10)),
        p25=float(np.percentile(arr, 25)),
        p75=float(np.percentile(arr, 75)),
        p90=float(np.percentile(arr, 90)),
        min=float(np.min(arr)),
        max=float(np.max(arr)),
    )


# ---------------------------------------------------------------------------
# Plate appearance resolver
# ---------------------------------------------------------------------------


class PlateAppearance:
    """Resolve a single plate appearance outcome given matchup probabilities.

    Parameters
    ----------
    rng:
        Shared ``numpy.random.Generator`` instance.
    """

    _TOTAL_BASES: dict[str, int] = {
        "K": 0,
        "BB": 0,
        "HBP": 0,
        "1B": 1,
        "2B": 2,
        "3B": 3,
        "HR": 4,
        "OUT": 0,
    }

    def __init__(self, rng: np.random.Generator) -> None:
        """Initialise with a shared RNG."""
        self._rng = rng

    def resolve(
        self,
        pitcher_id: str,  # noqa: ARG002  (kept for API clarity / future use)
        batter_id: str,  # noqa: ARG002
        matchup_probs: dict[str, float],
        fatigue_factor: float = 1.0,
    ) -> PlateAppearanceResult:
        """Draw one outcome from the matchup probability distribution.

        Parameters
        ----------
        pitcher_id:
            Pitcher identifier (reserved for logging / SHAP).
        batter_id:
            Batter identifier (reserved for logging / SHAP).
        matchup_probs:
            Dict of outcome -> probability (need not sum to exactly 1.0).
        fatigue_factor:
            Multiplier applied to the K probability before re-normalising;
            < 1.0 reduces K rate to model pitcher fatigue.

        Returns
        -------
        PlateAppearanceResult
        """
        probs = _normalise_probs(matchup_probs)

        # Apply fatigue to K probability
        if fatigue_factor != 1.0:
            k_raw = probs["K"] * fatigue_factor
            reduction = probs["K"] - k_raw
            # Redistribute the reduction proportionally to non-K outcomes
            non_k_total = sum(v for k, v in probs.items() if k != "K")
            probs = {
                o: (k_raw if o == "K" else v + reduction * v / non_k_total)
                for o, v in probs.items()
            }

        # Build cumulative distribution in OUTCOMES order
        cum_probs = np.cumsum([probs[o] for o in OUTCOMES])
        draw = self._rng.random()
        idx = int(np.searchsorted(cum_probs, draw))
        idx = min(idx, len(OUTCOMES) - 1)
        outcome = OUTCOMES[idx]

        return PlateAppearanceResult(
            outcome=outcome,
            total_bases=self._TOTAL_BASES[outcome],
            is_hit=outcome in ("1B", "2B", "3B", "HR"),
            is_walk=outcome in ("BB", "HBP"),
            is_strikeout=outcome == "K",
        )


# ---------------------------------------------------------------------------
# Runner advancement
# ---------------------------------------------------------------------------


def _advance_runners(
    runners: list[int],
    outcome: str,
    score_side: int,
    score: list[int],
) -> tuple[list[int], int]:
    """Update base state and score given a plate appearance outcome.

    Parameters
    ----------
    runners:
        Current ``[first, second, third]`` base occupancy (0/1).
    outcome:
        PA outcome token.
    score_side:
        Index into *score* list (0=away, 1=home).
    score:
        Mutable ``[away, home]`` list updated in-place.

    Returns
    -------
    tuple[list[int], int]
        Updated runners list and RBI count for this PA.
    """
    new_runners = list(runners)
    rbis = 0

    if outcome == "K" or outcome == "OUT":
        # No runner movement
        pass

    elif outcome in ("BB", "HBP"):
        # Force-advance: batter takes first; push runners only if forced
        if new_runners[FIRST]:
            if new_runners[SECOND]:
                if new_runners[THIRD]:
                    # Bases loaded -> run scores
                    score[score_side] += 1
                    rbis += 1
                new_runners[THIRD] = new_runners[SECOND]
            new_runners[SECOND] = new_runners[FIRST]
        new_runners[FIRST] = 1

    elif outcome == "1B":
        # Third scores, second advances to third, first advances to second
        if new_runners[THIRD]:
            score[score_side] += 1
            rbis += 1
        new_runners[THIRD] = new_runners[SECOND]
        new_runners[SECOND] = new_runners[FIRST]
        new_runners[FIRST] = 1

    elif outcome == "2B":
        # All runners score; batter to second
        runs = sum(new_runners)
        score[score_side] += runs
        rbis += runs
        new_runners = [0, 1, 0]

    elif outcome == "3B":
        # All runners score; batter to third
        runs = sum(new_runners)
        score[score_side] += runs
        rbis += runs
        new_runners = [0, 0, 1]

    elif outcome == "HR":
        # Everyone scores including batter
        runs = sum(new_runners) + 1
        score[score_side] += runs
        rbis += runs
        new_runners = [0, 0, 0]

    return new_runners, rbis


# ---------------------------------------------------------------------------
# Core simulator
# ---------------------------------------------------------------------------


class GameSimulator:
    """Run Monte Carlo simulations of a full MLB game.

    Parameters
    ----------
    config:
        Default ``SimulationConfig``; can be overridden per call to
        ``simulate_game``.
    """

    def __init__(self, config: SimulationConfig | None = None) -> None:
        """Initialise with optional default configuration."""
        self._default_config = config or SimulationConfig()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def simulate_game(
        self,
        home_lineup: list[str],
        away_lineup: list[str],
        home_pitcher_probs: dict[str, dict[str, float]],
        away_pitcher_probs: dict[str, dict[str, float]],
        config: SimulationConfig | None = None,
        home_pitcher_id: str | None = None,
        away_pitcher_id: str | None = None,
    ) -> SimulationResult:
        """Simulate *n_simulations* full games and return raw stat arrays.

        Parameters
        ----------
        home_lineup:
            Ordered list of batter IDs for the home team (length 9).
        away_lineup:
            Ordered list of batter IDs for the away team (length 9).
        home_pitcher_probs:
            ``{batter_id: {outcome: prob}}`` -- home pitcher vs. each
            away batter.  Keys must cover every batter in *away_lineup*.
        away_pitcher_probs:
            ``{batter_id: {outcome: prob}}`` -- away pitcher vs. each
            home batter.
        config:
            Override default simulation parameters.
        home_pitcher_id:
            MLBAM player ID for the home starting pitcher.  Used as the
            key in pitcher stat accumulators so downstream consumers
            (prop calculator, Supabase) can match on real player IDs.
            Falls back to a generated opaque key when *None*.
        away_pitcher_id:
            Same as above for the away starting pitcher.

        Returns
        -------
        SimulationResult
            Per-simulation stat arrays for every player.
        """
        cfg = config or self._default_config
        rng = np.random.default_rng(cfg.random_seed)
        pa_resolver = PlateAppearance(rng)

        n = cfg.n_simulations

        # Initialise accumulator arrays
        home_scores = np.zeros(n, dtype=np.int32)
        away_scores = np.zeros(n, dtype=np.int32)

        all_batters = list(set(home_lineup + away_lineup))
        # Use real pitcher IDs when provided, else generate opaque keys
        home_pitcher_id = home_pitcher_id or f"home_sp_{id(home_pitcher_probs)}"
        away_pitcher_id = away_pitcher_id or f"away_sp_{id(away_pitcher_probs)}"

        b_hits = {b: np.zeros(n, dtype=np.int32) for b in all_batters}
        b_tb = {b: np.zeros(n, dtype=np.int32) for b in all_batters}
        b_bb = {b: np.zeros(n, dtype=np.int32) for b in all_batters}
        b_k = {b: np.zeros(n, dtype=np.int32) for b in all_batters}
        b_rbi = {b: np.zeros(n, dtype=np.int32) for b in all_batters}
        b_runs = {b: np.zeros(n, dtype=np.int32) for b in all_batters}

        p_k = {p: np.zeros(n, dtype=np.int32) for p in [home_pitcher_id, away_pitcher_id]}
        p_bb = {p: np.zeros(n, dtype=np.int32) for p in [home_pitcher_id, away_pitcher_id]}
        p_ha = {p: np.zeros(n, dtype=np.int32) for p in [home_pitcher_id, away_pitcher_id]}
        p_ip = {p: np.zeros(n, dtype=np.float32) for p in [home_pitcher_id, away_pitcher_id]}
        p_pc = {p: np.zeros(n, dtype=np.int32) for p in [home_pitcher_id, away_pitcher_id]}

        logger.info(
            "Starting %d simulations (home=%d batters, away=%d batters)",
            n,
            len(home_lineup),
            len(away_lineup),
        )
        t0 = time.perf_counter()

        for sim_idx in range(n):
            self._run_single_game(
                sim_idx=sim_idx,
                home_lineup=home_lineup,
                away_lineup=away_lineup,
                home_pitcher_probs=home_pitcher_probs,
                away_pitcher_probs=away_pitcher_probs,
                home_pitcher_id=home_pitcher_id,
                away_pitcher_id=away_pitcher_id,
                cfg=cfg,
                pa_resolver=pa_resolver,
                home_scores=home_scores,
                away_scores=away_scores,
                b_hits=b_hits,
                b_tb=b_tb,
                b_bb=b_bb,
                b_k=b_k,
                b_rbi=b_rbi,
                b_runs=b_runs,
                p_k=p_k,
                p_bb=p_bb,
                p_ha=p_ha,
                p_ip=p_ip,
                p_pc=p_pc,
            )

        elapsed = time.perf_counter() - t0
        logger.info("Completed %d simulations in %.2fs (%.1f sims/sec)", n, elapsed, n / elapsed)

        return SimulationResult(
            home_scores=home_scores,
            away_scores=away_scores,
            batter_hits=b_hits,
            batter_total_bases=b_tb,
            batter_walks=b_bb,
            batter_strikeouts=b_k,
            batter_rbis=b_rbi,
            batter_runs=b_runs,
            pitcher_strikeouts=p_k,
            pitcher_walks=p_bb,
            pitcher_hits_allowed=p_ha,
            pitcher_innings=p_ip,
            pitcher_pitches=p_pc,
        )

    # ------------------------------------------------------------------
    # Internal simulation loop
    # ------------------------------------------------------------------

    def _run_single_game(  # noqa: PLR0913  (many params needed for perf)
        self,
        sim_idx: int,
        home_lineup: list[str],
        away_lineup: list[str],
        home_pitcher_probs: dict[str, dict[str, float]],
        away_pitcher_probs: dict[str, dict[str, float]],
        home_pitcher_id: str,
        away_pitcher_id: str,
        cfg: SimulationConfig,
        pa_resolver: PlateAppearance,
        home_scores: np.ndarray,
        away_scores: np.ndarray,
        b_hits: dict[str, np.ndarray],
        b_tb: dict[str, np.ndarray],
        b_bb: dict[str, np.ndarray],
        b_k: dict[str, np.ndarray],
        b_rbi: dict[str, np.ndarray],
        b_runs: dict[str, np.ndarray],
        p_k: dict[str, np.ndarray],
        p_bb: dict[str, np.ndarray],
        p_ha: dict[str, np.ndarray],
        p_ip: dict[str, np.ndarray],
        p_pc: dict[str, np.ndarray],
    ) -> None:
        """Simulate one full game and accumulate stats into preallocated arrays.

        Parameters
        ----------
        sim_idx:
            Index into result arrays for this simulation.
        All other parameters mirror ``simulate_game``; see that method.
        """
        state = GameState()

        # Per-pitcher outs tracker (to compute IP)
        home_pitcher_outs = 0
        away_pitcher_outs = 0
        home_pitcher_bf = 0
        away_pitcher_bf = 0

        # Batting-order cursors (persist across innings)
        away_order_idx = 0
        home_order_idx = 0

        # Runners on base at end of each PA (for run-scored credit)

        max_innings = cfg.innings + cfg.max_extras

        for inning in range(1, max_innings + 1):
            for half in ("top", "bottom"):
                # top = away bats vs home pitcher
                # bottom = home bats vs away pitcher
                if half == "top":
                    batting_lineup = away_lineup
                    pitcher_probs = home_pitcher_probs
                    pitcher_id = home_pitcher_id
                    score_side = 0  # away
                    order_cursor = away_order_idx
                    pitcher_bf_ref = home_pitcher_bf
                else:
                    batting_lineup = home_lineup
                    pitcher_probs = away_pitcher_probs
                    pitcher_id = away_pitcher_id
                    score_side = 1  # home
                    order_cursor = home_order_idx
                    pitcher_bf_ref = away_pitcher_bf

                outs = 0
                runners: list[int] = [0, 0, 0]
                on_base_ids: list[str | None] = [None, None, None]
                score = state.score

                while outs < 3:
                    batter_id = batting_lineup[order_cursor % cfg.lineup_size]
                    order_cursor += 1

                    # Compute fatigue factor
                    excess = max(0, pitcher_bf_ref - cfg.fatigue_threshold)
                    fatigue = max(0.5, 1.0 - excess * cfg.fatigue_k_decay)

                    probs = pitcher_probs.get(batter_id, {})
                    pa_result = pa_resolver.resolve(
                        pitcher_id, batter_id, probs, fatigue_factor=fatigue
                    )
                    pitcher_bf_ref += 1

                    # Estimate pitches (simplified: K=5, BB=6, HBP=3, hit=4, out=3.5)
                    pitch_est = {
                        "K": 5, "BB": 6, "HBP": 3,
                        "1B": 4, "2B": 4, "3B": 4, "HR": 4, "OUT": 3,
                    }.get(pa_result.outcome, 4)
                    if pitcher_id == home_pitcher_id:
                        p_pc[pitcher_id][sim_idx] += pitch_est
                    else:
                        p_pc[pitcher_id][sim_idx] += pitch_est

                    # Batter stats
                    if pa_result.is_hit:
                        b_hits[batter_id][sim_idx] += 1
                        b_tb[batter_id][sim_idx] += pa_result.total_bases
                        p_ha[pitcher_id][sim_idx] += 1
                    if pa_result.is_walk:
                        b_bb[batter_id][sim_idx] += 1
                        p_bb[pitcher_id][sim_idx] += 1
                    if pa_result.is_strikeout:
                        b_k[batter_id][sim_idx] += 1
                        p_k[pitcher_id][sim_idx] += 1

                    if pa_result.outcome == "K" or pa_result.outcome == "OUT":
                        outs += 1
                    else:
                        # Advance runners; check which runner IDs scored
                        prev_score = score[score_side]
                        runners, rbis = _advance_runners(
                            runners, pa_result.outcome, score_side, score
                        )
                        b_rbi[batter_id][sim_idx] += rbis
                        score[score_side] - prev_score

                        # Credit runs to the batters who were on base
                        if pa_result.outcome == "HR":
                            b_runs[batter_id][sim_idx] += 1  # batter scores too
                            for slot, occ in enumerate(on_base_ids):
                                if occ is not None and runners[slot] == 0:
                                    b_runs[occ][sim_idx] += 1

                        # Update runner IDs on base
                        if pa_result.outcome == "1B":
                            on_base_ids[SECOND] = on_base_ids[FIRST]
                            on_base_ids[FIRST] = batter_id
                            on_base_ids[THIRD] = None  # simplified: was on 2nd, scored
                        elif pa_result.outcome == "2B":
                            on_base_ids = [None, batter_id, None]
                        elif pa_result.outcome == "3B":
                            on_base_ids = [None, None, batter_id]
                        elif pa_result.outcome in ("BB", "HBP"):
                            on_base_ids[SECOND] = on_base_ids[FIRST]
                            on_base_ids[FIRST] = batter_id

                # End of half-inning -- record IP
                if half == "top":
                    home_pitcher_outs += outs
                    home_pitcher_bf = pitcher_bf_ref
                    away_order_idx = order_cursor
                    p_ip[home_pitcher_id][sim_idx] = home_pitcher_outs / 3.0
                else:
                    away_pitcher_outs += outs
                    away_pitcher_bf = pitcher_bf_ref
                    home_order_idx = order_cursor
                    p_ip[away_pitcher_id][sim_idx] = away_pitcher_outs / 3.0

                # Check walk-off / game-over conditions
                if inning >= cfg.innings and half == "bottom":
                    if score[1] != score[0]:  # home team either wins or loses
                        break

            # After each full inning past regulation, check for tie resolution
            if inning >= cfg.innings and state.score[0] != state.score[1]:
                break

        home_scores[sim_idx] = state.score[1]
        away_scores[sim_idx] = state.score[0]

    # ------------------------------------------------------------------
    # Summarisation
    # ------------------------------------------------------------------

    def summarise(self, result: SimulationResult) -> SimulationSummary:
        """Aggregate raw per-simulation arrays into a ``SimulationSummary``.

        Parameters
        ----------
        result:
            Output from ``simulate_game``.

        Returns
        -------
        SimulationSummary
        """
        n = len(result.home_scores)

        batter_stat_maps: dict[str, dict[str, np.ndarray]] = {
            "hits": result.batter_hits,
            "total_bases": result.batter_total_bases,
            "walks": result.batter_walks,
            "strikeouts": result.batter_strikeouts,
            "rbis": result.batter_rbis,
            "runs": result.batter_runs,
        }
        pitcher_stat_maps: dict[str, dict[str, np.ndarray]] = {
            "strikeouts": result.pitcher_strikeouts,
            "walks": result.pitcher_walks,
            "hits_allowed": result.pitcher_hits_allowed,
            "innings": result.pitcher_innings,
            "pitches": result.pitcher_pitches,
        }

        batter_stats: dict[str, dict[str, StatSummary]] = {}
        for stat, player_dict in batter_stat_maps.items():
            for pid, arr in player_dict.items():
                batter_stats.setdefault(pid, {})[stat] = _summarise_array(arr)

        pitcher_stats: dict[str, dict[str, StatSummary]] = {}
        for stat, player_dict in pitcher_stat_maps.items():
            for pid, arr in player_dict.items():
                pitcher_stats.setdefault(pid, {})[stat] = _summarise_array(arr)

        return SimulationSummary(
            n_simulations=n,
            home_score=_summarise_array(result.home_scores),
            away_score=_summarise_array(result.away_scores),
            batter_stats=batter_stats,
            pitcher_stats=pitcher_stats,
            raw=result,
        )


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def _build_demo_game(
    n_batters: int = 9,
) -> tuple[list[str], list[str], dict[str, dict[str, float]], dict[str, dict[str, float]]]:
    """Build synthetic lineups and matchup probabilities for demonstration."""
    home_lineup = [f"home_b{i}" for i in range(n_batters)]
    away_lineup = [f"away_b{i}" for i in range(n_batters)]

    default_probs: dict[str, float] = {
        "K": 0.225, "BB": 0.085, "HBP": 0.010,
        "1B": 0.155, "2B": 0.050, "3B": 0.005,
        "HR": 0.035, "OUT": 0.435,
    }

    home_pitcher_probs = {b: dict(default_probs) for b in away_lineup}
    away_pitcher_probs = {b: dict(default_probs) for b in home_lineup}
    return home_lineup, away_lineup, home_pitcher_probs, away_pitcher_probs


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Run a demo Monte Carlo MLB game simulation."
    )
    parser.add_argument(
        "--n-sims", type=int, default=3_000, help="Number of simulations (default: 3000)"
    )
    parser.add_argument(
        "--seed", type=int, default=42, help="Random seed (default: 42)"
    )
    parser.add_argument(
        "--quiet", action="store_true", help="Suppress INFO logs"
    )
    args = parser.parse_args()

    if args.quiet:
        logging.getLogger().setLevel(logging.WARNING)

    home_l, away_l, hp_probs, ap_probs = _build_demo_game()
    sim_cfg = SimulationConfig(n_simulations=args.n_sims, random_seed=args.seed)
    engine = GameSimulator(sim_cfg)

    t_start = time.perf_counter()
    sim_result = engine.simulate_game(home_l, away_l, hp_probs, ap_probs, sim_cfg)
    summary = engine.summarise(sim_result)
    t_total = time.perf_counter() - t_start

    print(f"\n{'='*60}")
    print(f"  Demo: {args.n_sims} simulations completed in {t_total:.2f}s")
    print(f"  Home avg score : {summary.home_score.mean:.2f} (std {summary.home_score.std:.2f})")
    print(f"  Away avg score : {summary.away_score.mean:.2f} (std {summary.away_score.std:.2f})")
    first_batter = home_l[0]
    b = summary.batter_stats.get(first_batter, {})
    print(f"  {first_batter} avg hits: {b.get('hits', StatSummary()).mean:.3f}")
    print(f"{'='*60}\n")


# ===========================================================================
# COMPATIBILITY LAYER -- 11-Outcome Model
# ===========================================================================
# The existing engine above uses 8 outcomes (with "OUT" as a catch-all).
# This section adds the 11-outcome vocabulary expected by tests and new code:
#   K, BB, HBP, 1B, 2B, 3B, HR, flyout, groundout, lineout, popup
# ===========================================================================

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

OUTCOMES_11: list[str] = [
    "K", "BB", "HBP", "1B", "2B", "3B", "HR",
    "flyout", "groundout", "lineout", "popup",
]

N_OUTCOMES: int = 11

# Outcome index constants
K_IDX: int = 0
BB_IDX: int = 1
HBP_IDX: int = 2
SINGLE_IDX: int = 3
DOUBLE_IDX: int = 4
TRIPLE_IDX: int = 5
HR_IDX: int = 6
FLYOUT_IDX: int = 7
GROUNDOUT_IDX: int = 8
# lineout = 9, popup = 10

HIT_INDICES: set[int] = {SINGLE_IDX, DOUBLE_IDX, TRIPLE_IDX, HR_IDX}
OUT_INDICES: set[int] = {K_IDX, FLYOUT_IDX, GROUNDOUT_IDX, 9, 10}  # 9=lineout, 10=popup

# League-average probabilities for the 11-outcome model (must sum to 1.0)
MLB_AVG_PROBS: np.ndarray = np.array(
    [0.22, 0.08, 0.01, 0.15, 0.045, 0.004, 0.03, 0.14, 0.19, 0.08, 0.051],
    dtype=np.float64,
)
# Normalise in case of floating-point drift
MLB_AVG_PROBS = MLB_AVG_PROBS / MLB_AVG_PROBS.sum()

# Total-bases lookup for the 11-outcome model
_TB_11: np.ndarray = np.array([0, 0, 0, 1, 2, 3, 4, 0, 0, 0, 0], dtype=np.int32)


# ---------------------------------------------------------------------------
# Runner advancement -- new interface for 11-outcome model
#
# Signature expected by tests:
#   _advance_runners(bases: np.ndarray[bool], outcome_idx: int,
#                    rng: np.random.Generator)
#       -> tuple[np.ndarray[bool], int, int]   (new_bases, runs, rbis)
#
# The OLD _advance_runners above takes (runners, outcome_str, score_side, score)
# and is kept intact. We redefine the name here with the new interface.
# ---------------------------------------------------------------------------

def _advance_runners(  # type: ignore[override]
    bases: np.ndarray,
    outcome_idx: int,
    rng: "np.random.Generator",  # noqa: F821 - rng is accepted but not used in deterministic rules
) -> tuple[np.ndarray, int, int]:
    """Advance base runners given an 11-outcome index and return (bases, runs, rbis).

    Parameters
    ----------
    bases:
        Boolean array of shape (3,) -- [first, second, third].
    outcome_idx:
        Index into OUTCOMES_11.
    rng:
        Random generator (accepted for API compatibility; not used in
        deterministic advancement rules).

    Returns
    -------
    tuple[np.ndarray, int, int]
        (new_bases, runs_scored, rbis)
    """
    new_bases = np.array(bases, dtype=np.bool_)
    runs = 0
    rbis = 0

    if outcome_idx == K_IDX or outcome_idx in (FLYOUT_IDX, GROUNDOUT_IDX, 9, 10):
        # Out -- no runner movement
        pass

    elif outcome_idx in (BB_IDX, HBP_IDX):
        # Walk / HBP -- force-advance
        if new_bases[0]:  # runner on first
            if new_bases[1]:  # and second
                if new_bases[2]:  # and third -- bases loaded walk scores a run
                    runs += 1
                    rbis += 1
                new_bases[2] = new_bases[1]
            new_bases[1] = new_bases[0]
        new_bases[0] = True

    elif outcome_idx == SINGLE_IDX:
        # Third scores, second -> third, first -> second, batter -> first
        if new_bases[2]:
            runs += 1
            rbis += 1
        new_bases[2] = new_bases[1]
        new_bases[1] = new_bases[0]
        new_bases[0] = True

    elif outcome_idx == DOUBLE_IDX:
        # All runners score
        runs = int(new_bases.sum())
        rbis = runs
        new_bases[:] = False
        new_bases[1] = True  # batter on second

    elif outcome_idx == TRIPLE_IDX:
        # All runners score
        runs = int(new_bases.sum())
        rbis = runs
        new_bases[:] = False
        new_bases[2] = True  # batter on third

    elif outcome_idx == HR_IDX:
        # Batter + all runners score
        runs = int(new_bases.sum()) + 1
        rbis = runs
        new_bases[:] = False

    return new_bases, runs, rbis


# ---------------------------------------------------------------------------
# Probability construction helpers
# ---------------------------------------------------------------------------


def build_batter_probs(
    k_rate: float = 0.22,
    bb_rate: float = 0.08,
    hbp_rate: float = 0.01,
    single_rate: float = 0.15,
    double_rate: float = 0.045,
    triple_rate: float = 0.004,
    hr_rate: float = 0.03,
    flyout_rate: float | None = None,
    groundout_rate: float | None = None,
    lineout_rate: float | None = None,
    popup_rate: float | None = None,
) -> np.ndarray:
    """Build and normalise an 11-element probability vector for a batter.

    If flyout/groundout/lineout/popup rates are not supplied, the remaining
    probability after all explicit outcomes is distributed proportionally
    among those four using MLB-average weights (0.32 / 0.42 / 0.18 / 0.08).

    Parameters
    ----------
    k_rate, bb_rate, ... :
        Raw rate for each outcome.  Need not sum to 1.0 -- the result is
        always normalised.

    Returns
    -------
    np.ndarray
        Normalised 11-element probability vector.
    """
    explicit = np.array(
        [k_rate, bb_rate, hbp_rate, single_rate, double_rate, triple_rate, hr_rate],
        dtype=np.float64,
    )
    explicit_total = explicit.sum()

    out_rates_provided = [flyout_rate, groundout_rate, lineout_rate, popup_rate]
    all_provided = all(r is not None for r in out_rates_provided)

    if all_provided:
        out_arr = np.array(
            [flyout_rate, groundout_rate, lineout_rate, popup_rate], dtype=np.float64
        )
    else:
        # Distribute remaining probability among the four out subtypes
        remaining = max(0.0, 1.0 - explicit_total)
        weights = np.array([0.32, 0.42, 0.18, 0.08], dtype=np.float64)
        # If any sub-types were explicitly supplied, use them and only fill gaps
        out_arr = np.zeros(4, dtype=np.float64)
        defaults = weights * remaining
        for i, v in enumerate(out_rates_provided):
            out_arr[i] = float(v) if v is not None else defaults[i]

    probs = np.concatenate([explicit, out_arr])
    total = probs.sum()
    if total <= 0:
        return MLB_AVG_PROBS.copy()
    return probs / total


# ---------------------------------------------------------------------------
# Profile classes
# ---------------------------------------------------------------------------


class BatterProfile:
    """Batter probability profile for the 11-outcome model.

    Parameters
    ----------
    mlbam_id:
        MLB Advanced Media player ID.
    name:
        Player display name.
    lineup_position:
        Batting-order position (1-9).
    probs:
        11-element probability vector.  If ``None``, falls back to
        ``MLB_AVG_PROBS``.  If all-zeros, falls back to ``MLB_AVG_PROBS``.
        If wrong shape, raises ``ValueError``.
    """

    def __init__(
        self,
        mlbam_id: int,
        name: str,
        lineup_position: int,
        probs: np.ndarray | None = None,
    ) -> None:
        self.mlbam_id = mlbam_id
        self.name = name
        self.lineup_position = lineup_position

        if probs is None:
            self.probs = MLB_AVG_PROBS.copy()
            return

        probs = np.asarray(probs, dtype=np.float64)
        if probs.shape != (N_OUTCOMES,):
            raise ValueError(
                f"BatterProfile probs must have shape ({N_OUTCOMES},), "
                f"got {probs.shape}"
            )
        if probs.sum() == 0.0:
            self.probs = MLB_AVG_PROBS.copy()
        else:
            self.probs = probs / probs.sum()


class PitcherProfile:
    """Starting pitcher profile.

    Parameters
    ----------
    mlbam_id:
        MLB Advanced Media player ID.
    name:
        Player display name.
    throws:
        Handedness (``"R"`` or ``"L"``).
    k_rate_modifier:
        Multiplier applied to the K probability of opposing batters.
    contact_quality_modifier:
        Multiplier that adjusts hit probability distribution.
    pitch_count_mean:
        Expected total pitch count (default 92).
    pitch_count_std:
        Std dev of pitch count distribution (default 12).
    recent_pitch_counts:
        If at least 3 entries, ``pitch_count_mean`` and
        ``pitch_count_std`` are derived from them (min std = 5.0).
    """

    def __init__(
        self,
        mlbam_id: int,
        name: str,
        throws: str = "R",
        k_rate_modifier: float = 1.0,
        contact_quality_modifier: float = 1.0,
        pitch_count_mean: float = 92.0,
        pitch_count_std: float = 12.0,
        recent_pitch_counts: list[float] | None = None,
    ) -> None:
        self.mlbam_id = mlbam_id
        self.name = name
        self.throws = throws
        self.k_rate_modifier = k_rate_modifier
        self.contact_quality_modifier = contact_quality_modifier

        if recent_pitch_counts is not None and len(recent_pitch_counts) >= 3:
            arr = np.array(recent_pitch_counts, dtype=np.float64)
            self.pitch_count_mean = float(arr.mean())
            self.pitch_count_std = float(max(5.0, arr.std()))
        else:
            self.pitch_count_mean = pitch_count_mean
            self.pitch_count_std = pitch_count_std


class BullpenProfile:
    """Bullpen aggregate profile.

    Parameters
    ----------
    k_rate_modifier:
        Multiplier on K probability when the bullpen is pitching.
    contact_quality_modifier:
        Multiplier on contact quality.
    probs:
        Base 11-element probability vector.  Defaults to ``MLB_AVG_PROBS``.
    """

    def __init__(
        self,
        k_rate_modifier: float = 1.0,
        contact_quality_modifier: float = 1.0,
        probs: np.ndarray | None = None,
    ) -> None:
        self.k_rate_modifier = k_rate_modifier
        self.contact_quality_modifier = contact_quality_modifier
        self.probs = MLB_AVG_PROBS.copy() if probs is None else np.asarray(probs, dtype=np.float64)


class GameMatchup:
    """Full game matchup configuration.

    Parameters
    ----------
    pitcher:
        Starting ``PitcherProfile``.
    lineup:
        List of exactly 9 ``BatterProfile`` objects.
    bullpen:
        ``BullpenProfile`` for relief appearances.
    park_factor:
        Multiplicative park HR factor (1.0 = neutral).
    weather_factor:
        Multiplicative weather modifier (1.0 = neutral).
    umpire_k_factor:
        Multiplicative umpire strikeout tendency (1.0 = neutral).
    catcher_framing_factor:
        Multiplicative catcher framing modifier (1.0 = neutral).
        Values > 1.0 mean elite framer (more called strikes / Ks),
        values < 1.0 mean poor framer.

    Raises
    ------
    ValueError
        If *lineup* does not contain exactly 9 batters.
    """

    def __init__(
        self,
        pitcher: PitcherProfile,
        lineup: list[BatterProfile],
        bullpen: BullpenProfile,
        park_factor: float = 1.0,
        weather_factor: float = 1.0,
        umpire_k_factor: float = 1.0,
        catcher_framing_factor: float = 1.0,
    ) -> None:
        if len(lineup) != 9:
            raise ValueError(
                f"GameMatchup lineup must contain exactly 9 batters; "
                f"got {len(lineup)}."
            )
        self.pitcher = pitcher
        self.lineup = lineup
        self.bullpen = bullpen
        self.park_factor = park_factor
        self.weather_factor = weather_factor
        self.umpire_k_factor = umpire_k_factor
        self.catcher_framing_factor = catcher_framing_factor


# ---------------------------------------------------------------------------
# Result containers
# ---------------------------------------------------------------------------

_STAT_ALIASES: dict[str, str] = {
    "K": "strikeouts",
    "H": "hits",
    "TB": "total_bases",
    "HR": "home_runs",
    "BB": "walks",
    "R": "runs",
    "RBI": "rbis",
    "PA": "plate_appearances",
    # full names pass through
    "strikeouts": "strikeouts",
    "hits": "hits",
    "total_bases": "total_bases",
    "home_runs": "home_runs",
    "walks": "walks",
    "runs": "runs",
    "rbis": "rbis",
    "plate_appearances": "plate_appearances",
}


class PlayerSimResults:
    """Per-player simulation results container.

    All stat arrays have length ``n_sims``.

    Parameters
    ----------
    mlbam_id : int
    name : str
    n_sims : int
    strikeouts, hits, total_bases, home_runs, walks, runs, rbis,
    plate_appearances : np.ndarray
    """

    def __init__(
        self,
        mlbam_id: int,
        name: str,
        n_sims: int,
        strikeouts: np.ndarray,
        hits: np.ndarray,
        total_bases: np.ndarray,
        home_runs: np.ndarray,
        walks: np.ndarray,
        runs: np.ndarray,
        rbis: np.ndarray,
        plate_appearances: np.ndarray,
    ) -> None:
        self.mlbam_id = mlbam_id
        self.name = name
        self.n_sims = n_sims
        self.strikeouts = strikeouts
        self.hits = hits
        self.total_bases = total_bases
        self.home_runs = home_runs
        self.walks = walks
        self.runs = runs
        self.rbis = rbis
        self.plate_appearances = plate_appearances

        self._arrays: dict[str, np.ndarray] = {
            "strikeouts": strikeouts,
            "hits": hits,
            "total_bases": total_bases,
            "home_runs": home_runs,
            "walks": walks,
            "runs": runs,
            "rbis": rbis,
            "plate_appearances": plate_appearances,
        }

    def _resolve(self, stat_name: str) -> np.ndarray:
        key = _STAT_ALIASES.get(stat_name)
        if key is None or key not in self._arrays:
            raise KeyError(f"Unknown stat '{stat_name}'")
        return self._arrays[key]

    def distribution(self, stat_name: str) -> np.ndarray:
        """Return the raw simulation array for *stat_name*."""
        return self._resolve(stat_name)

    def mean(self, stat_name: str) -> float:
        """Return the mean of *stat_name* across all simulations."""
        return float(np.mean(self._resolve(stat_name)))

    def std(self, stat_name: str) -> float:
        """Return the std dev of *stat_name*."""
        return float(np.std(self._resolve(stat_name)))

    def percentile(self, stat_name: str, pct: float) -> float:
        """Return the *pct*-th percentile of *stat_name*."""
        return float(np.percentile(self._resolve(stat_name), pct))

    def prob_over(self, stat_name: str, line: float) -> float:
        """Return P(stat > line)."""
        return float(np.mean(self._resolve(stat_name) > line))

    def prob_under(self, stat_name: str, line: float) -> float:
        """Return P(stat < line)."""
        return float(np.mean(self._resolve(stat_name) < line))

    def to_dict(self) -> dict:
        """Return a JSON-serialisable dict representation."""
        stats_dict: dict[str, Any] = {}
        for short, full in [
            ("K", "strikeouts"), ("H", "hits"), ("TB", "total_bases"),
            ("HR", "home_runs"), ("BB", "walks"), ("R", "runs"),
            ("RBI", "rbis"), ("PA", "plate_appearances"),
        ]:
            arr = self._arrays[full]
            counts, edges = np.histogram(arr, bins=max(1, int(arr.max()) + 2 if arr.max() > 0 else 2), range=(0, max(1, int(arr.max()) + 1)))
            stats_dict[short] = {
                "mean": float(np.mean(arr)),
                "std": float(np.std(arr)),
                "median": float(np.median(arr)),
                "p10": float(np.percentile(arr, 10)),
                "p90": float(np.percentile(arr, 90)),
                "histogram": counts.tolist(),
                "bin_edges": edges.tolist(),
            }
        return {
            "mlbam_id": self.mlbam_id,
            "name": self.name,
            "n_sims": self.n_sims,
            "stats": stats_dict,
        }


class GameSimResults:
    """Full-game simulation results container.

    Parameters
    ----------
    n_sims : int
    player_results : dict[int, PlayerSimResults]
        Keyed by ``mlbam_id``.
    team_runs : np.ndarray
        Total runs scored per simulation.
    pitcher_pitch_counts : np.ndarray
        Starting-pitcher pitch count per simulation.
    """

    def __init__(
        self,
        n_sims: int,
        player_results: dict[int, PlayerSimResults],
        team_runs: np.ndarray,
        pitcher_pitch_counts: np.ndarray,
    ) -> None:
        self.n_sims = n_sims
        self.player_results = player_results
        self.team_runs = team_runs
        self.pitcher_pitch_counts = pitcher_pitch_counts

    def to_dict(self) -> dict:
        """Return a JSON-serialisable dict."""
        return {
            "n_sims": self.n_sims,
            "players": {
                str(mid): pr.to_dict()
                for mid, pr in self.player_results.items()
            },
            "team_runs": {
                "mean": float(np.mean(self.team_runs)),
                "std": float(np.std(self.team_runs)),
                "values": self.team_runs.tolist(),
            },
            "pitcher_pitch_counts": {
                "mean": float(np.mean(self.pitcher_pitch_counts)),
                "std": float(np.std(self.pitcher_pitch_counts)),
                "values": self.pitcher_pitch_counts.tolist(),
            },
        }


# ---------------------------------------------------------------------------
# Builder helpers
# ---------------------------------------------------------------------------


def build_pitcher_profile_from_stats(
    mlbam_id: int,
    name: str,
    career_k9: float = 8.5,
    throws: str = "R",
    recent_pitch_counts: list[float] | None = None,
) -> PitcherProfile:
    """Construct a ``PitcherProfile`` from aggregate stats.

    Parameters
    ----------
    mlbam_id, name, throws:
        Passed through to ``PitcherProfile``.
    career_k9:
        Career strikeouts per 9 innings.  Used to derive ``k_rate_modifier``
        (clamped to [0.5, 1.6]) and ``contact_quality_modifier``.
    recent_pitch_counts:
        If 3+ entries, overrides pitch-count distribution.
    """
    k_rate_modifier = float(np.clip(career_k9 / 8.5, 0.5, 1.6))
    # Higher K9 -> higher contact quality (harder to square up)
    contact_quality_modifier = float(np.clip(0.8 + (career_k9 - 8.5) * 0.02, 0.7, 1.3))
    return PitcherProfile(
        mlbam_id=mlbam_id,
        name=name,
        throws=throws,
        k_rate_modifier=k_rate_modifier,
        contact_quality_modifier=contact_quality_modifier,
        recent_pitch_counts=recent_pitch_counts,
    )


def build_bullpen_profile(era: float = 4.0, k9: float = 8.5) -> BullpenProfile:
    """Construct a ``BullpenProfile`` from ERA and K/9.

    Parameters
    ----------
    era:
        Earned run average (lower = better bullpen).
    k9:
        Strikeouts per 9 innings.
    """
    # k_rate_modifier: higher K/9 -> boost K rate
    k_rate_modifier = float(np.clip(k9 / 8.5, 0.5, 1.6))
    # contact_quality_modifier: lower ERA -> better suppression of quality contact
    contact_quality_modifier = float(np.clip(4.0 / max(era, 0.5), 0.6, 1.5))
    return BullpenProfile(
        k_rate_modifier=k_rate_modifier,
        contact_quality_modifier=contact_quality_modifier,
    )


# ---------------------------------------------------------------------------
# Modifier application
# ---------------------------------------------------------------------------


def _apply_pitcher_modifiers(
    base_probs: np.ndarray,
    pitcher: PitcherProfile,
    is_bullpen: bool,
    bullpen: BullpenProfile,
    park_factor: float,
    weather_factor: float,
    umpire_k_factor: float,
    catcher_framing_factor: float = 1.0,
) -> np.ndarray:
    """Apply pitcher / park / weather / umpire / catcher modifiers to a probability vector.

    Parameters
    ----------
    base_probs:
        11-element batter probability vector (will not be mutated).
    pitcher:
        Starting pitcher profile (used when ``is_bullpen=False``).
    is_bullpen:
        If True, use ``bullpen`` modifiers instead of ``pitcher``.
    bullpen:
        Bullpen profile.
    park_factor, weather_factor, umpire_k_factor:
        Scalar multipliers.
    catcher_framing_factor:
        Multiplicative catcher framing modifier (1.0 = neutral).

    Returns
    -------
    np.ndarray
        Modified and re-normalised 11-element probability vector.
    """
    probs = base_probs.copy()

    k_mod = bullpen.k_rate_modifier if is_bullpen else pitcher.k_rate_modifier
    cq_mod = (
        bullpen.contact_quality_modifier
        if is_bullpen
        else pitcher.contact_quality_modifier
    )

    # --- Strikeout modifier ---
    effective_k_mod = k_mod * umpire_k_factor * catcher_framing_factor
    probs[K_IDX] *= effective_k_mod

    # --- HR modifier (park + weather) ---
    probs[HR_IDX] *= park_factor * weather_factor

    # --- Contact quality: reduce hit probabilities when cq > 1 ---
    # (better pitcher = less quality contact = fewer hits, more outs)
    if cq_mod != 1.0:
        for idx in HIT_INDICES:
            probs[idx] /= cq_mod
        # Redistribute to outs proportionally
        # (handled by normalisation below)

    # Re-normalise
    total = probs.sum()
    if total <= 0:
        return MLB_AVG_PROBS.copy()
    return probs / total


# ---------------------------------------------------------------------------
# Core simulation engine (11-outcome)
# ---------------------------------------------------------------------------

# Pitches-per-PA estimates by outcome index
_PITCHES_PER_PA: np.ndarray = np.array(
    [5, 6, 3, 4, 4, 4, 4, 3, 3, 3, 3], dtype=np.float64
)


def _simulate_game_single(
    matchup: GameMatchup,
    rng: np.random.Generator,
    n_innings: int = 9,
) -> tuple[
    dict[int, dict[str, np.ndarray]],  # per-batter stat accumulators (1 game)
    float,  # team runs
    float,  # pitcher pitch count
    int,  # pitcher Ks
]:
    """Simulate one game and return per-batter stat counts, team runs,
    pitcher pitch count, and pitcher K total.

    This is the inner loop -- called n_sims times.
    """
    # Per-batter stat accumulators (single game)
    n_batters = 9
    lineup = matchup.lineup
    pitcher = matchup.pitcher

    b_k = np.zeros(n_batters, dtype=np.int32)
    b_h = np.zeros(n_batters, dtype=np.int32)
    b_tb = np.zeros(n_batters, dtype=np.int32)
    b_hr = np.zeros(n_batters, dtype=np.int32)
    b_bb = np.zeros(n_batters, dtype=np.int32)
    b_r = np.zeros(n_batters, dtype=np.int32)
    b_rbi = np.zeros(n_batters, dtype=np.int32)
    b_pa = np.zeros(n_batters, dtype=np.int32)

    # Pitcher pitch count threshold drawn from Normal
    pc_threshold = rng.normal(pitcher.pitch_count_mean, pitcher.pitch_count_std)
    pc_threshold = max(50.0, pc_threshold)  # sanity floor

    # Who is pitching this game: starter vs. bullpen (by pitch count)
    pitcher_pitches = 0.0   # total pitches by starter only
    total_pitches = 0.0     # cumulative (starter + bullpen) for switch check
    pitcher_ks = 0

    order_idx = 0  # persistent across innings
    team_runs = 0

    for inning in range(n_innings):
        outs = 0
        bases = np.zeros(3, dtype=np.bool_)
        # track which lineup slot is on which base for run credit
        runner_slots = [None, None, None]  # None or int (batter slot idx)

        while outs < 3:
            slot = order_idx % n_batters
            order_idx += 1
            batter = lineup[slot]
            b_pa[slot] += 1

            # Determine pitcher context
            using_bullpen = total_pitches >= pc_threshold

            # Build modified probability vector
            mod_probs = _apply_pitcher_modifiers(
                batter.probs,
                pitcher=pitcher,
                is_bullpen=using_bullpen,
                bullpen=matchup.bullpen,
                park_factor=matchup.park_factor,
                weather_factor=matchup.weather_factor,
                umpire_k_factor=matchup.umpire_k_factor,
                catcher_framing_factor=matchup.catcher_framing_factor,
            )

            # Draw outcome
            draw = rng.random()
            cum = np.cumsum(mod_probs)
            outcome_idx = int(np.searchsorted(cum, draw))
            outcome_idx = min(outcome_idx, N_OUTCOMES - 1)

            # Estimate pitches used
            pa_pitches = float(_PITCHES_PER_PA[outcome_idx])
            total_pitches += pa_pitches
            if not using_bullpen:
                pitcher_pitches += pa_pitches  # starter-only pitch count

            # --- Accumulate stats ---
            if outcome_idx == K_IDX:
                b_k[slot] += 1
                outs += 1
                if not using_bullpen:
                    pitcher_ks += 1

            elif outcome_idx in OUT_INDICES:
                outs += 1

            elif outcome_idx in (BB_IDX, HBP_IDX):
                b_bb[slot] += 1
                new_bases, runs, rbis = _advance_runners(bases, outcome_idx, rng)
                # Credit runs to runners who scored
                if runs > 0:
                    _credit_runs(runner_slots, bases, new_bases, b_r, slot if False else None)
                team_runs += runs
                b_rbi[slot] += rbis
                # Update runner tracking
                _push_runner_walk(runner_slots, slot)
                bases = new_bases

            elif outcome_idx in HIT_INDICES:
                b_h[slot] += 1
                tb = int(_TB_11[outcome_idx])
                b_tb[slot] += tb
                if outcome_idx == HR_IDX:
                    b_hr[slot] += 1

                new_bases, runs, rbis = _advance_runners(bases, outcome_idx, rng)
                team_runs += runs
                b_rbi[slot] += rbis

                # Credit runs to runners who scored
                if runs > 0:
                    # For HR: batter also scores
                    if outcome_idx == HR_IDX:
                        b_r[slot] += 1
                        runs -= 1  # already credited batter
                    _credit_runs_advanced(runner_slots, bases, new_bases, b_r, runs)

                # Update runner slots
                if outcome_idx == SINGLE_IDX:
                    runner_slots[1] = runner_slots[0]
                    runner_slots[0] = slot
                    runner_slots[2] = None  # simplified (was on 2nd -> scored)
                elif outcome_idx == DOUBLE_IDX:
                    runner_slots = [None, slot, None]
                elif outcome_idx == TRIPLE_IDX:
                    runner_slots = [None, None, slot]
                elif outcome_idx == HR_IDX:
                    runner_slots = [None, None, None]

                bases = new_bases

    # Encode per-batter stats into a dict for return
    stats = {
        "k": b_k, "h": b_h, "tb": b_tb, "hr": b_hr,
        "bb": b_bb, "r": b_r, "rbi": b_rbi, "pa": b_pa,
    }
    return stats, float(team_runs), float(pitcher_pitches), pitcher_ks


def _push_runner_walk(runner_slots: list, batter_slot: int) -> None:
    """Advance runner tracking on a walk (force-advance)."""
    if runner_slots[0] is not None:
        if runner_slots[1] is not None:
            if runner_slots[2] is not None:
                runner_slots[2] = runner_slots[1]  # was on 3rd, stays (scored, but tracking)
            runner_slots[2] = runner_slots[1]
        runner_slots[1] = runner_slots[0]
    runner_slots[0] = batter_slot


def _credit_runs(
    runner_slots: list,
    old_bases: np.ndarray,
    new_bases: np.ndarray,
    b_r: np.ndarray,
    batter_slot,
) -> None:
    """Credit runs to runners who scored (simplified)."""
    for base_idx in range(3):
        if old_bases[base_idx] and not new_bases[base_idx]:
            slot = runner_slots[base_idx]
            if slot is not None:
                b_r[slot] += 1


def _credit_runs_advanced(
    runner_slots: list,
    old_bases: np.ndarray,
    new_bases: np.ndarray,
    b_r: np.ndarray,
    extra_runs: int,
) -> None:
    """Credit runs to runners who cleared the bases."""
    for base_idx in range(3):
        if old_bases[base_idx] and not new_bases[base_idx]:
            slot = runner_slots[base_idx]
            if slot is not None:
                b_r[slot] += 1


def simulate_game(
    matchup: GameMatchup,
    n_sims: int = 3000,
    seed: int | None = None,
) -> GameSimResults:
    """Simulate *n_sims* full games for a given matchup.

    Parameters
    ----------
    matchup:
        Fully populated ``GameMatchup`` object.
    n_sims:
        Number of Monte Carlo iterations.
    seed:
        Random seed for reproducibility.

    Returns
    -------
    GameSimResults
    """
    rng = np.random.default_rng(seed)
    n_batters = 9
    lineup = matchup.lineup

    # Pre-allocate per-batter stat arrays
    b_k   = np.zeros((n_batters, n_sims), dtype=np.int32)
    b_h   = np.zeros((n_batters, n_sims), dtype=np.int32)
    b_tb  = np.zeros((n_batters, n_sims), dtype=np.int32)
    b_hr  = np.zeros((n_batters, n_sims), dtype=np.int32)
    b_bb  = np.zeros((n_batters, n_sims), dtype=np.int32)
    b_r   = np.zeros((n_batters, n_sims), dtype=np.int32)
    b_rbi = np.zeros((n_batters, n_sims), dtype=np.int32)
    b_pa  = np.zeros((n_batters, n_sims), dtype=np.int32)

    team_runs_arr  = np.zeros(n_sims, dtype=np.float64)
    pitcher_pc_arr = np.zeros(n_sims, dtype=np.float64)

    for i in range(n_sims):
        stats, tr, pc, _ = _simulate_game_single(matchup, rng)
        b_k[:, i]   = stats["k"]
        b_h[:, i]   = stats["h"]
        b_tb[:, i]  = stats["tb"]
        b_hr[:, i]  = stats["hr"]
        b_bb[:, i]  = stats["bb"]
        b_r[:, i]   = stats["r"]
        b_rbi[:, i] = stats["rbi"]
        b_pa[:, i]  = stats["pa"]
        team_runs_arr[i]  = tr
        pitcher_pc_arr[i] = pc

    player_results: dict[int, PlayerSimResults] = {}
    for slot, batter in enumerate(lineup):
        player_results[batter.mlbam_id] = PlayerSimResults(
            mlbam_id=batter.mlbam_id,
            name=batter.name,
            n_sims=n_sims,
            strikeouts=b_k[slot],
            hits=b_h[slot],
            total_bases=b_tb[slot],
            home_runs=b_hr[slot],
            walks=b_bb[slot],
            runs=b_r[slot],
            rbis=b_rbi[slot],
            plate_appearances=b_pa[slot],
        )

    return GameSimResults(
        n_sims=n_sims,
        player_results=player_results,
        team_runs=team_runs_arr,
        pitcher_pitch_counts=pitcher_pc_arr,
    )


def simulate_game_with_pitcher_ks(
    matchup: GameMatchup,
    n_sims: int = 3000,
    seed: int | None = None,
) -> tuple[GameSimResults, np.ndarray]:
    """Simulate *n_sims* games and additionally return pitcher K array.

    Parameters
    ----------
    matchup:
        Fully populated ``GameMatchup``.
    n_sims:
        Number of Monte Carlo iterations.
    seed:
        Random seed.

    Returns
    -------
    tuple[GameSimResults, np.ndarray]
        ``(game_results, pitcher_ks_array)`` where ``pitcher_ks_array`` has
        shape ``(n_sims,)``.
    """
    rng = np.random.default_rng(seed)
    n_batters = 9
    lineup = matchup.lineup

    b_k   = np.zeros((n_batters, n_sims), dtype=np.int32)
    b_h   = np.zeros((n_batters, n_sims), dtype=np.int32)
    b_tb  = np.zeros((n_batters, n_sims), dtype=np.int32)
    b_hr  = np.zeros((n_batters, n_sims), dtype=np.int32)
    b_bb  = np.zeros((n_batters, n_sims), dtype=np.int32)
    b_r   = np.zeros((n_batters, n_sims), dtype=np.int32)
    b_rbi = np.zeros((n_batters, n_sims), dtype=np.int32)
    b_pa  = np.zeros((n_batters, n_sims), dtype=np.int32)

    team_runs_arr  = np.zeros(n_sims, dtype=np.float64)
    pitcher_pc_arr = np.zeros(n_sims, dtype=np.float64)
    pitcher_ks_arr = np.zeros(n_sims, dtype=np.int32)

    for i in range(n_sims):
        stats, tr, pc, pks = _simulate_game_single(matchup, rng)
        b_k[:, i]   = stats["k"]
        b_h[:, i]   = stats["h"]
        b_tb[:, i]  = stats["tb"]
        b_hr[:, i]  = stats["hr"]
        b_bb[:, i]  = stats["bb"]
        b_r[:, i]   = stats["r"]
        b_rbi[:, i] = stats["rbi"]
        b_pa[:, i]  = stats["pa"]
        team_runs_arr[i]  = tr
        pitcher_pc_arr[i] = pc
        pitcher_ks_arr[i] = pks

    player_results: dict[int, PlayerSimResults] = {}
    for slot, batter in enumerate(lineup):
        player_results[batter.mlbam_id] = PlayerSimResults(
            mlbam_id=batter.mlbam_id,
            name=batter.name,
            n_sims=n_sims,
            strikeouts=b_k[slot],
            hits=b_h[slot],
            total_bases=b_tb[slot],
            home_runs=b_hr[slot],
            walks=b_bb[slot],
            runs=b_r[slot],
            rbis=b_rbi[slot],
            plate_appearances=b_pa[slot],
        )

    game_results = GameSimResults(
        n_sims=n_sims,
        player_results=player_results,
        team_runs=team_runs_arr,
        pitcher_pitch_counts=pitcher_pc_arr,
    )
    return game_results, pitcher_ks_arr
