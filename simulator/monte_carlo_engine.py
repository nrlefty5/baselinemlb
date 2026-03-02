#!/usr/bin/env python3
"""
monte_carlo_engine.py — BaselineMLB
====================================
Core Monte Carlo game simulation engine. Simulates full 9-inning MLB games
at the plate-appearance level using numpy vectorized random sampling.

Architecture:
    1. Each batter has an 11-outcome probability vector:
       [K, BB, HBP, 1B, 2B, 3B, HR, flyout, groundout, lineout, popup]
    2. Plate appearances are resolved via weighted random sampling
    3. Full game state tracked: batting order, inning, outs, base runners,
       pitch count, score
    4. Pitcher removal modeled on pitch count thresholds from recent starts
    5. 3,000 simulations per game produces stable probability distributions

Performance target: 15 games (full slate) in under 60 seconds using numpy
vectorized sampling across all simulations simultaneously.

Usage:
    from simulator.monte_carlo_engine import simulate_game, GameMatchup

    matchup = GameMatchup(
        pitcher=PitcherProfile(...),
        lineup=[BatterProfile(...), ...],  # 9 batters
        bullpen=BullpenProfile(...),
    )
    results = simulate_game(matchup, n_sims=3000)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

import numpy as np

log = logging.getLogger("baselinemlb.simulator")

# ---------------------------------------------------------------------------
# Outcome encoding
# ---------------------------------------------------------------------------

OUTCOMES = ["K", "BB", "HBP", "1B", "2B", "3B", "HR",
            "flyout", "groundout", "lineout", "popup"]
N_OUTCOMES = len(OUTCOMES)

# Outcome index constants for fast lookup
K_IDX = 0
BB_IDX = 1
HBP_IDX = 2
SINGLE_IDX = 3
DOUBLE_IDX = 4
TRIPLE_IDX = 5
HR_IDX = 6
FLYOUT_IDX = 7
GROUNDOUT_IDX = 8
LINEOUT_IDX = 9
POPUP_IDX = 10

# Sets for quick classification
HIT_INDICES = {SINGLE_IDX, DOUBLE_IDX, TRIPLE_IDX, HR_IDX}
ON_BASE_INDICES = {BB_IDX, HBP_IDX, SINGLE_IDX, DOUBLE_IDX, TRIPLE_IDX, HR_IDX}
OUT_INDICES = {K_IDX, FLYOUT_IDX, GROUNDOUT_IDX, LINEOUT_IDX, POPUP_IDX}

# Total bases lookup
TOTAL_BASES = {
    SINGLE_IDX: 1,
    DOUBLE_IDX: 2,
    TRIPLE_IDX: 3,
    HR_IDX: 4,
}

# Pitch count estimates per PA outcome (realistic averages)
PITCHES_PER_PA = {
    K_IDX: 4.8,       # Strikeouts take more pitches
    BB_IDX: 5.6,      # Walks are long PAs
    HBP_IDX: 2.0,     # Usually short
    SINGLE_IDX: 3.8,
    DOUBLE_IDX: 3.9,
    TRIPLE_IDX: 3.7,
    HR_IDX: 3.5,
    FLYOUT_IDX: 3.4,
    GROUNDOUT_IDX: 3.1,
    LINEOUT_IDX: 3.3,
    POPUP_IDX: 2.8,
}

# Base advancement probabilities on singles (runner-dependent)
# Format: P(runner advances extra base beyond forced advance)
RUNNER_ADVANCE_SINGLE = {
    "1B": 0.28,   # Runner on 1st scores on single: 28% (goes 1st->home)
    "2B": 0.60,   # Runner on 2nd scores on single: 60%
    "3B": 0.95,   # Runner on 3rd scores on single: 95%
}

RUNNER_ADVANCE_DOUBLE = {
    "1B": 0.44,   # Runner on 1st scores on double: 44%
    "2B": 0.95,   # Runner on 2nd scores on double: 95%
    "3B": 1.00,   # Runner on 3rd scores on double: 100%
}

# ---------------------------------------------------------------------------
# Default league-average probability vectors
# ---------------------------------------------------------------------------

# 2024 MLB league averages per PA
MLB_AVG_PROBS = np.array([
    0.224,   # K
    0.083,   # BB
    0.012,   # HBP
    0.152,   # 1B
    0.044,   # 2B
    0.004,   # 3B
    0.030,   # HR
    0.140,   # flyout
    0.186,   # groundout
    0.080,   # lineout
    0.045,   # popup
], dtype=np.float64)

# Normalize to sum to 1.0
MLB_AVG_PROBS /= MLB_AVG_PROBS.sum()


# ---------------------------------------------------------------------------
# Data classes for matchup configuration
# ---------------------------------------------------------------------------

@dataclass
class BatterProfile:
    """Probability vector and metadata for a single batter."""
    mlbam_id: int
    name: str
    lineup_position: int               # 1-9
    bats: str = "R"                    # L, R, or S (switch)
    probs: np.ndarray = field(default_factory=lambda: MLB_AVG_PROBS.copy())

    # Per-simulation accumulators are NOT stored here; they live in the engine

    def __post_init__(self):
        self.probs = np.asarray(self.probs, dtype=np.float64)
        # Ensure probabilities are valid
        if self.probs.shape != (N_OUTCOMES,):
            raise ValueError(
                f"Batter {self.name}: probs must have {N_OUTCOMES} elements, "
                f"got {self.probs.shape}"
            )
        total = self.probs.sum()
        if total <= 0:
            self.probs = MLB_AVG_PROBS.copy()
        elif not np.isclose(total, 1.0, atol=1e-6):
            self.probs /= total  # Normalize


@dataclass
class PitcherProfile:
    """Starting pitcher attributes for simulation."""
    mlbam_id: int
    name: str
    throws: str = "R"                   # L or R

    # Pitch count removal thresholds
    pitch_count_mean: float = 92.0      # Average pitch count at removal
    pitch_count_std: float = 12.0       # Std dev (varies per pitcher)

    # Modifier applied to batter probs when this pitcher is on the mound
    # > 1.0 = pitcher-friendly (more Ks, fewer hits), < 1.0 = hitter-friendly
    k_rate_modifier: float = 1.0
    contact_quality_modifier: float = 1.0  # Affects hit distribution

    # Season data for pitch count modeling
    recent_pitch_counts: list = field(default_factory=list)

    def __post_init__(self):
        """Compute pitch count distribution from recent starts if available."""
        if self.recent_pitch_counts and len(self.recent_pitch_counts) >= 3:
            counts = np.array(self.recent_pitch_counts, dtype=np.float64)
            self.pitch_count_mean = float(np.mean(counts))
            self.pitch_count_std = max(float(np.std(counts)), 5.0)


@dataclass
class BullpenProfile:
    """Composite bullpen stats used after starter removal."""
    # Probability vector for an "average" bullpen arm
    probs: np.ndarray = field(default_factory=lambda: MLB_AVG_PROBS.copy())

    # Bullpen modifier relative to league average
    k_rate_modifier: float = 1.0
    contact_quality_modifier: float = 1.0

    def __post_init__(self):
        self.probs = np.asarray(self.probs, dtype=np.float64)
        total = self.probs.sum()
        if total > 0 and not np.isclose(total, 1.0, atol=1e-6):
            self.probs /= total


@dataclass
class GameMatchup:
    """Full game configuration for simulation."""
    pitcher: PitcherProfile
    lineup: list  # list[BatterProfile], length 9
    bullpen: BullpenProfile = field(default_factory=BullpenProfile)

    # Game environment modifiers
    park_factor: float = 1.0        # Multiplier on HR/hit rates
    weather_factor: float = 1.0     # Wind/temp effect on HR rate
    umpire_k_factor: float = 1.0    # Umpire strike zone tendency

    def __post_init__(self):
        if len(self.lineup) != 9:
            raise ValueError(
                f"Lineup must have exactly 9 batters, got {len(self.lineup)}"
            )


# ---------------------------------------------------------------------------
# Simulation result containers
# ---------------------------------------------------------------------------

@dataclass
class PlayerSimResults:
    """Aggregated simulation results for a single player across N sims."""
    mlbam_id: int
    name: str
    n_sims: int

    # Raw count arrays — shape (n_sims,)
    strikeouts: np.ndarray = field(repr=False, default=None)
    hits: np.ndarray = field(repr=False, default=None)
    total_bases: np.ndarray = field(repr=False, default=None)
    home_runs: np.ndarray = field(repr=False, default=None)
    walks: np.ndarray = field(repr=False, default=None)
    hbps: np.ndarray = field(repr=False, default=None)
    runs: np.ndarray = field(repr=False, default=None)
    rbis: np.ndarray = field(repr=False, default=None)
    plate_appearances: np.ndarray = field(repr=False, default=None)

    def distribution(self, stat: str) -> np.ndarray:
        """Return the raw distribution array for a stat."""
        mapping = {
            "K": self.strikeouts, "strikeouts": self.strikeouts,
            "H": self.hits, "hits": self.hits,
            "TB": self.total_bases, "total_bases": self.total_bases,
            "HR": self.home_runs, "home_runs": self.home_runs,
            "BB": self.walks, "walks": self.walks,
            "HBP": self.hbps, "hbps": self.hbps,
            "R": self.runs, "runs": self.runs,
            "RBI": self.rbis, "rbis": self.rbis,
            "PA": self.plate_appearances, "plate_appearances": self.plate_appearances,
        }
        arr = mapping.get(stat)
        if arr is None:
            raise KeyError(f"Unknown stat '{stat}'. Valid: {list(mapping.keys())}")
        return arr

    def mean(self, stat: str) -> float:
        return float(np.mean(self.distribution(stat)))

    def std(self, stat: str) -> float:
        return float(np.std(self.distribution(stat)))

    def percentile(self, stat: str, pct: float) -> float:
        return float(np.percentile(self.distribution(stat), pct))

    def prob_over(self, stat: str, line: float) -> float:
        """P(stat > line). For half-integer lines like 5.5, this is clean."""
        dist = self.distribution(stat)
        return float(np.mean(dist > line))

    def prob_under(self, stat: str, line: float) -> float:
        """P(stat < line)."""
        dist = self.distribution(stat)
        return float(np.mean(dist < line))

    def prob_exact(self, stat: str, value: int) -> float:
        """P(stat == value)."""
        dist = self.distribution(stat)
        return float(np.mean(dist == value))

    def to_dict(self) -> dict:
        """Serialize to a JSON-friendly dict with summary statistics."""
        stats = {}
        for stat_name, arr in [
            ("K", self.strikeouts), ("H", self.hits), ("TB", self.total_bases),
            ("HR", self.home_runs), ("R", self.runs), ("RBI", self.rbis),
            ("BB", self.walks),
        ]:
            if arr is not None:
                stats[stat_name] = {
                    "mean": round(float(np.mean(arr)), 3),
                    "median": round(float(np.median(arr)), 1),
                    "std": round(float(np.std(arr)), 3),
                    "p10": round(float(np.percentile(arr, 10)), 1),
                    "p25": round(float(np.percentile(arr, 25)), 1),
                    "p75": round(float(np.percentile(arr, 75)), 1),
                    "p90": round(float(np.percentile(arr, 90)), 1),
                    "min": int(np.min(arr)),
                    "max": int(np.max(arr)),
                    # Full histogram for prop calculations
                    "histogram": {
                        int(v): int(c) for v, c in
                        zip(*np.unique(arr, return_counts=True))
                    },
                }
        return {
            "mlbam_id": self.mlbam_id,
            "name": self.name,
            "n_sims": self.n_sims,
            "stats": stats,
        }


@dataclass
class GameSimResults:
    """Results for an entire game simulation."""
    n_sims: int
    player_results: dict  # mlbam_id -> PlayerSimResults
    team_runs: np.ndarray = field(repr=False, default=None)  # shape (n_sims,)
    pitcher_pitch_counts: np.ndarray = field(repr=False, default=None)
    pitcher_innings: np.ndarray = field(repr=False, default=None)

    def to_dict(self) -> dict:
        return {
            "n_sims": self.n_sims,
            "team_runs": {
                "mean": round(float(np.mean(self.team_runs)), 2),
                "std": round(float(np.std(self.team_runs)), 2),
            } if self.team_runs is not None else None,
            "players": {
                mid: pr.to_dict()
                for mid, pr in self.player_results.items()
            },
        }


# ---------------------------------------------------------------------------
# Core simulation engine
# ---------------------------------------------------------------------------

def _apply_pitcher_modifiers(
    batter_probs: np.ndarray,
    pitcher: PitcherProfile,
    is_bullpen: bool,
    bullpen: BullpenProfile,
    park_factor: float,
    weather_factor: float,
    umpire_k_factor: float,
) -> np.ndarray:
    """
    Adjust batter probability vector based on pitcher, park, weather, umpire.

    Returns a new normalized probability vector.
    """
    probs = batter_probs.copy()

    if is_bullpen:
        k_mod = bullpen.k_rate_modifier
        contact_mod = bullpen.contact_quality_modifier
    else:
        k_mod = pitcher.k_rate_modifier
        contact_mod = pitcher.contact_quality_modifier

    # Apply umpire K-rate factor (generous ump = more Ks + fewer BBs)
    probs[K_IDX] *= k_mod * umpire_k_factor
    probs[BB_IDX] *= (1.0 / max(umpire_k_factor, 0.5))  # Inverse relationship

    # Apply park + weather to power outcomes
    hr_mod = park_factor * weather_factor
    probs[HR_IDX] *= hr_mod
    probs[DOUBLE_IDX] *= (1.0 + (park_factor - 1.0) * 0.3)  # Smaller effect
    probs[TRIPLE_IDX] *= (1.0 + (park_factor - 1.0) * 0.2)

    # Contact quality affects hit/out balance
    if contact_mod != 1.0:
        for idx in HIT_INDICES:
            probs[idx] *= contact_mod
        for idx in OUT_INDICES - {K_IDX}:  # Non-K outs absorb the difference
            probs[idx] *= (2.0 - contact_mod)

    # Re-normalize
    total = probs.sum()
    if total > 0:
        probs /= total

    return probs


def _advance_runners(
    bases: np.ndarray,
    outcome_idx: int,
    rng: np.random.Generator,
) -> tuple:
    """
    Advance base runners based on plate appearance outcome.

    Args:
        bases: boolean array [1B_occupied, 2B_occupied, 3B_occupied]
               for a SINGLE simulation
        outcome_idx: index into OUTCOMES
        rng: numpy random generator

    Returns:
        (new_bases, runs_scored, rbi_count)
    """
    new_bases = np.zeros(3, dtype=np.bool_)
    runs = 0
    rbi = 0

    if outcome_idx == HR_IDX:
        # Everyone scores, including batter
        runs = int(bases.sum()) + 1
        rbi = runs
        # Bases cleared
        return new_bases, runs, rbi

    if outcome_idx == TRIPLE_IDX:
        runs = int(bases.sum())
        rbi = runs
        new_bases[2] = True  # Batter on 3rd
        return new_bases, runs, rbi

    if outcome_idx == DOUBLE_IDX:
        # Runner on 3rd always scores
        if bases[2]:
            runs += 1
            rbi += 1
        # Runner on 2nd scores (~95%)
        if bases[1]:
            if rng.random() < RUNNER_ADVANCE_DOUBLE["2B"]:
                runs += 1
                rbi += 1
            else:
                new_bases[2] = True  # Holds at 3rd
        # Runner on 1st scores (~44%) or goes to 3rd
        if bases[0]:
            if rng.random() < RUNNER_ADVANCE_DOUBLE["1B"]:
                runs += 1
                rbi += 1
            else:
                new_bases[2] = True
        new_bases[1] = True  # Batter on 2nd
        return new_bases, runs, rbi

    if outcome_idx == SINGLE_IDX:
        # Runner on 3rd scores
        if bases[2]:
            runs += 1
            rbi += 1
        # Runner on 2nd scores (~60%) or holds at 3rd
        if bases[1]:
            if rng.random() < RUNNER_ADVANCE_SINGLE["2B"]:
                runs += 1
                rbi += 1
            else:
                new_bases[2] = True
        # Runner on 1st to 2nd or 3rd (~28% go to 3rd)
        if bases[0]:
            if rng.random() < RUNNER_ADVANCE_SINGLE["1B"]:
                new_bases[2] = True
            else:
                new_bases[1] = True
        new_bases[0] = True  # Batter on 1st
        return new_bases, runs, rbi

    if outcome_idx in (BB_IDX, HBP_IDX):
        # Force advances only
        if bases[0] and bases[1] and bases[2]:
            runs += 1
            rbi += 1  # Bases-loaded walk/HBP = RBI
            new_bases = np.array([True, True, True], dtype=np.bool_)
        elif bases[0] and bases[1]:
            new_bases[2] = True
            new_bases[1] = True
            new_bases[0] = True
        elif bases[0]:
            new_bases[1] = True
            new_bases[0] = True
        else:
            new_bases[0] = True
        # Preserve runners not forced
        if not bases[0]:
            new_bases[1] = new_bases[1] or bases[1]
            new_bases[2] = new_bases[2] or bases[2]
        return new_bases, runs, rbi

    if outcome_idx == GROUNDOUT_IDX:
        # Double play possibility with runner on 1st, < 2 outs handled by caller
        # For baserunner movement: runner on 3rd can tag on groundout (~50%)
        if bases[2]:
            if rng.random() < 0.50:
                runs += 1  # No RBI on groundout unless DP not turned
        # Runner on 2nd advances to 3rd on groundout (~40%)
        if bases[1]:
            if rng.random() < 0.40:
                new_bases[2] = True
            else:
                new_bases[1] = True
        # Runner on 1st: potential DP or force out at 2nd
        if bases[0]:
            # Force at 2nd most of the time
            pass  # Runner removed
        return new_bases, runs, rbi

    # flyout, lineout, popup
    if outcome_idx in (FLYOUT_IDX, LINEOUT_IDX, POPUP_IDX):
        # Sac fly: runner on 3rd scores on flyout/lineout with < 2 outs
        # (outs check is done by caller; here we just model the tag-up)
        if bases[2] and outcome_idx in (FLYOUT_IDX, LINEOUT_IDX):
            if rng.random() < 0.65:  # ~65% of sac fly opportunities score
                runs += 1
                rbi += 1
                new_bases[2] = False
            else:
                new_bases[2] = True
        else:
            new_bases[2] = bases[2]
        new_bases[1] = bases[1]
        new_bases[0] = bases[0]
        return new_bases, runs, rbi

    # K — no advancement (ignoring passed ball/wild pitch, rare)
    new_bases[:] = bases[:]
    return new_bases, runs, rbi


def simulate_game(
    matchup: GameMatchup,
    n_sims: int = 3000,
    seed: Optional[int] = None,
) -> GameSimResults:
    """
    Simulate a full game `n_sims` times.

    The simulation models:
    - 9-inning games (no extra innings for prop purposes)
    - Full batting order cycling
    - Pitch count tracking and starter removal
    - Bullpen transition with composite stats
    - Base runner advancement with realistic probabilities
    - Sac flies, double plays, tag-ups

    Args:
        matchup: GameMatchup with pitcher, lineup, and bullpen profiles
        n_sims: Number of simulations to run (default 3000)
        seed: Random seed for reproducibility

    Returns:
        GameSimResults with full distributions for each player
    """
    rng = np.random.default_rng(seed)
    pitcher = matchup.pitcher
    lineup = matchup.lineup
    bullpen = matchup.bullpen

    n_batters = len(lineup)

    # Pre-compute adjusted probability vectors for each batter vs starter
    starter_probs = []
    for batter in lineup:
        adj = _apply_pitcher_modifiers(
            batter.probs, pitcher, False, bullpen,
            matchup.park_factor, matchup.weather_factor, matchup.umpire_k_factor,
        )
        starter_probs.append(adj)

    # Pre-compute adjusted probability vectors for each batter vs bullpen
    bullpen_probs = []
    for batter in lineup:
        adj = _apply_pitcher_modifiers(
            batter.probs, pitcher, True, bullpen,
            matchup.park_factor, matchup.weather_factor, matchup.umpire_k_factor,
        )
        bullpen_probs.append(adj)

    # Pre-generate pitch count thresholds for starter removal
    # Each simulation gets its own threshold drawn from the pitcher's distribution
    removal_thresholds = rng.normal(
        pitcher.pitch_count_mean,
        pitcher.pitch_count_std,
        size=n_sims,
    ).clip(min=50, max=130).astype(np.int32)

    # --- Allocate per-simulation, per-batter stat arrays ---
    batter_stats = {}
    for b in lineup:
        batter_stats[b.mlbam_id] = {
            "K": np.zeros(n_sims, dtype=np.int32),
            "H": np.zeros(n_sims, dtype=np.int32),
            "TB": np.zeros(n_sims, dtype=np.int32),
            "HR": np.zeros(n_sims, dtype=np.int32),
            "BB": np.zeros(n_sims, dtype=np.int32),
            "HBP": np.zeros(n_sims, dtype=np.int32),
            "R": np.zeros(n_sims, dtype=np.int32),
            "RBI": np.zeros(n_sims, dtype=np.int32),
            "PA": np.zeros(n_sims, dtype=np.int32),
        }

    # Team-level tracking
    team_runs = np.zeros(n_sims, dtype=np.int32)
    pitcher_pitch_counts = np.zeros(n_sims, dtype=np.int32)
    pitcher_innings = np.zeros(n_sims, dtype=np.float32)

    # --- Vectorized pre-generation of random outcomes ---
    # Estimate max PAs per game: ~40 (9 innings * ~4.4 PA/inning)
    MAX_PA_PER_GAME = 50
    n_innings = 9

    # Pre-generate all random numbers we'll need
    # For PA outcomes: uniform [0,1) for weighted sampling
    pa_randoms = rng.random((n_sims, MAX_PA_PER_GAME), dtype=np.float64)
    # For baserunning decisions
    br_randoms = rng.random((n_sims, MAX_PA_PER_GAME, 4), dtype=np.float64)

    # --- Run simulations ---
    # We loop over simulations but vectorize where possible
    for sim in range(n_sims):
        batting_order_pos = 0
        pitch_count = 0
        is_bullpen_active = False
        pa_idx = 0  # Index into pre-generated randoms

        for inning in range(1, n_innings + 1):
            outs = 0
            bases = np.zeros(3, dtype=np.bool_)

            while outs < 3:
                if pa_idx >= MAX_PA_PER_GAME:
                    break  # Safety valve

                batter_idx = batting_order_pos % n_batters
                batter = lineup[batter_idx]
                bid = batter.mlbam_id

                # Select probability vector based on starter/bullpen
                if is_bullpen_active:
                    probs = bullpen_probs[batter_idx]
                else:
                    probs = starter_probs[batter_idx]

                # Resolve PA outcome via weighted random sampling
                r = pa_randoms[sim, pa_idx]
                cum_probs = np.cumsum(probs)
                outcome_idx = int(np.searchsorted(cum_probs, r))
                if outcome_idx >= N_OUTCOMES:
                    outcome_idx = N_OUTCOMES - 1

                # Record PA
                batter_stats[bid]["PA"][sim] += 1

                # Update pitch count
                pitches = PITCHES_PER_PA.get(outcome_idx, 3.5)
                # Add some variance to pitch count
                pitches = max(1, pitches + rng.normal(0, 0.8))
                pitch_count += pitches

                # Check starter removal
                if not is_bullpen_active and pitch_count >= removal_thresholds[sim]:
                    is_bullpen_active = True
                    pitcher_pitch_counts[sim] = int(pitch_count)
                    pitcher_innings[sim] = (inning - 1) + (outs / 3.0)

                # Record batter stats
                if outcome_idx == K_IDX:
                    batter_stats[bid]["K"][sim] += 1
                elif outcome_idx == BB_IDX:
                    batter_stats[bid]["BB"][sim] += 1
                elif outcome_idx == HBP_IDX:
                    batter_stats[bid]["HBP"][sim] += 1
                elif outcome_idx == HR_IDX:
                    batter_stats[bid]["HR"][sim] += 1
                    batter_stats[bid]["H"][sim] += 1
                    batter_stats[bid]["TB"][sim] += 4
                elif outcome_idx in HIT_INDICES:
                    batter_stats[bid]["H"][sim] += 1
                    batter_stats[bid]["TB"][sim] += TOTAL_BASES.get(outcome_idx, 0)

                # Advance runners and score runs
                # Create a temporary RNG-like interface using pre-generated randoms
                class _BRRng:
                    """Tiny shim to feed pre-generated randoms to _advance_runners."""
                    def __init__(self, vals):
                        self._vals = vals
                        self._i = 0
                    def random(self):
                        v = self._vals[self._i % len(self._vals)]
                        self._i += 1
                        return v

                br_rng = _BRRng(br_randoms[sim, pa_idx])

                if outcome_idx in OUT_INDICES:
                    outs += 1
                    # Double play: groundout with runner on 1st and < 2 outs
                    if (outcome_idx == GROUNDOUT_IDX and bases[0]
                            and outs < 3):
                        dp_roll = br_randoms[sim, pa_idx, 0]
                        if dp_roll < 0.35:  # ~35% DP rate on groundouts with runner on 1st
                            outs += 1
                            bases[0] = False

                    # Sac fly / tag-up logic (only with < 3 outs after this out)
                    if outs < 3:
                        new_bases, r_scored, rbi_scored = _advance_runners(
                            bases, outcome_idx, br_rng
                        )
                    else:
                        new_bases = np.zeros(3, dtype=np.bool_)
                        r_scored = 0
                        rbi_scored = 0
                else:
                    new_bases, r_scored, rbi_scored = _advance_runners(
                        bases, outcome_idx, br_rng
                    )

                bases = new_bases

                # Score runs
                if r_scored > 0:
                    team_runs[sim] += r_scored
                    batter_stats[bid]["RBI"][sim] += rbi_scored

                    # Attribute runs to the runners who scored
                    # Simplified: credit runs to batter on HR, otherwise
                    # distribute among recent batters in the inning
                    if outcome_idx == HR_IDX:
                        batter_stats[bid]["R"][sim] += 1
                        # Other runners who scored: attribute to the batters
                        # who got on base (simplified — attribute to batter)
                        # In a full model we'd track WHO is on each base
                        remaining_runs = r_scored - 1
                        if remaining_runs > 0:
                            # Distribute among preceding lineup slots
                            for back in range(1, remaining_runs + 1):
                                prev_idx = (batting_order_pos - back) % n_batters
                                prev_bid = lineup[prev_idx].mlbam_id
                                batter_stats[prev_bid]["R"][sim] += 1
                    else:
                        # Credit runs to recent batters who were on base
                        for back in range(1, r_scored + 1):
                            prev_idx = (batting_order_pos - back) % n_batters
                            prev_bid = lineup[prev_idx].mlbam_id
                            batter_stats[prev_bid]["R"][sim] += 1

                batting_order_pos += 1
                pa_idx += 1

        # If starter was never removed, record final pitch count
        if not is_bullpen_active:
            pitcher_pitch_counts[sim] = int(pitch_count)
            pitcher_innings[sim] = 9.0

    # --- Build result objects ---
    player_results = {}
    for batter in lineup:
        bid = batter.mlbam_id
        bs = batter_stats[bid]
        player_results[bid] = PlayerSimResults(
            mlbam_id=bid,
            name=batter.name,
            n_sims=n_sims,
            strikeouts=bs["K"],
            hits=bs["H"],
            total_bases=bs["TB"],
            home_runs=bs["HR"],
            walks=bs["BB"],
            hbps=bs["HBP"],
            runs=bs["R"],
            rbis=bs["RBI"],
            plate_appearances=bs["PA"],
        )

    return GameSimResults(
        n_sims=n_sims,
        player_results=player_results,
        team_runs=team_runs,
        pitcher_pitch_counts=pitcher_pitch_counts,
        pitcher_innings=pitcher_innings,
    )


# ---------------------------------------------------------------------------
# Pitcher strikeout aggregation (special case — across all batters)
# ---------------------------------------------------------------------------

def aggregate_pitcher_strikeouts(
    game_results: GameSimResults,
) -> PlayerSimResults:
    """
    Sum all batter strikeouts to get the pitcher's K distribution.

    This is the key stat for pitcher K props — the total Ks recorded
    by the starting pitcher before removal.
    """
    n_sims = game_results.n_sims
    total_ks = np.zeros(n_sims, dtype=np.int32)

    for bid, pr in game_results.player_results.items():
        total_ks += pr.strikeouts

    # Note: This counts ALL Ks including bullpen Ks.
    # For pitcher-specific K props, we'd need to track which Ks happened
    # before vs after the starter was pulled. The engine tracks pitch count
    # thresholds, so the true pitcher K count is the sum of Ks that occurred
    # in PAs before the bullpen flag was set. We approximate this below.

    return total_ks


def simulate_game_with_pitcher_ks(
    matchup: GameMatchup,
    n_sims: int = 3000,
    seed: Optional[int] = None,
) -> tuple:
    """
    Extended simulation that separately tracks starter Ks vs bullpen Ks.

    Returns:
        (GameSimResults, pitcher_k_distribution: np.ndarray of shape (n_sims,))
    """
    rng = np.random.default_rng(seed)
    pitcher = matchup.pitcher
    lineup = matchup.lineup
    bullpen = matchup.bullpen
    n_batters = len(lineup)

    # Pre-compute adjusted probability vectors
    starter_probs = []
    bullpen_probs_list = []
    for batter in lineup:
        starter_probs.append(_apply_pitcher_modifiers(
            batter.probs, pitcher, False, bullpen,
            matchup.park_factor, matchup.weather_factor, matchup.umpire_k_factor,
        ))
        bullpen_probs_list.append(_apply_pitcher_modifiers(
            batter.probs, pitcher, True, bullpen,
            matchup.park_factor, matchup.weather_factor, matchup.umpire_k_factor,
        ))

    # Pitch count removal thresholds
    removal_thresholds = rng.normal(
        pitcher.pitch_count_mean, pitcher.pitch_count_std, size=n_sims,
    ).clip(min=50, max=130).astype(np.int32)

    # Stat arrays
    batter_stats = {}
    for b in lineup:
        batter_stats[b.mlbam_id] = {
            "K": np.zeros(n_sims, dtype=np.int32),
            "H": np.zeros(n_sims, dtype=np.int32),
            "TB": np.zeros(n_sims, dtype=np.int32),
            "HR": np.zeros(n_sims, dtype=np.int32),
            "BB": np.zeros(n_sims, dtype=np.int32),
            "HBP": np.zeros(n_sims, dtype=np.int32),
            "R": np.zeros(n_sims, dtype=np.int32),
            "RBI": np.zeros(n_sims, dtype=np.int32),
            "PA": np.zeros(n_sims, dtype=np.int32),
        }

    team_runs = np.zeros(n_sims, dtype=np.int32)
    pitcher_ks = np.zeros(n_sims, dtype=np.int32)  # Starter Ks only
    pitcher_pitch_counts = np.zeros(n_sims, dtype=np.int32)
    pitcher_innings = np.zeros(n_sims, dtype=np.float32)

    MAX_PA_PER_GAME = 50
    pa_randoms = rng.random((n_sims, MAX_PA_PER_GAME))
    br_randoms = rng.random((n_sims, MAX_PA_PER_GAME, 4))

    for sim in range(n_sims):
        batting_order_pos = 0
        pitch_count = 0.0
        is_bullpen_active = False
        pa_idx = 0

        for inning in range(1, 10):
            outs = 0
            bases = np.zeros(3, dtype=np.bool_)

            while outs < 3:
                if pa_idx >= MAX_PA_PER_GAME:
                    break

                batter_idx = batting_order_pos % n_batters
                batter = lineup[batter_idx]
                bid = batter.mlbam_id

                probs = bullpen_probs_list[batter_idx] if is_bullpen_active else starter_probs[batter_idx]

                r = pa_randoms[sim, pa_idx]
                cum_probs = np.cumsum(probs)
                outcome_idx = int(np.searchsorted(cum_probs, r))
                if outcome_idx >= N_OUTCOMES:
                    outcome_idx = N_OUTCOMES - 1

                batter_stats[bid]["PA"][sim] += 1

                pitches = PITCHES_PER_PA.get(outcome_idx, 3.5) + rng.normal(0, 0.8)
                pitches = max(1.0, pitches)
                pitch_count += pitches

                if not is_bullpen_active and pitch_count >= removal_thresholds[sim]:
                    is_bullpen_active = True
                    pitcher_pitch_counts[sim] = int(pitch_count)
                    pitcher_innings[sim] = (inning - 1) + (outs / 3.0)

                # Record stats
                if outcome_idx == K_IDX:
                    batter_stats[bid]["K"][sim] += 1
                    if not is_bullpen_active:
                        pitcher_ks[sim] += 1
                elif outcome_idx == BB_IDX:
                    batter_stats[bid]["BB"][sim] += 1
                elif outcome_idx == HBP_IDX:
                    batter_stats[bid]["HBP"][sim] += 1
                elif outcome_idx == HR_IDX:
                    batter_stats[bid]["HR"][sim] += 1
                    batter_stats[bid]["H"][sim] += 1
                    batter_stats[bid]["TB"][sim] += 4
                elif outcome_idx in HIT_INDICES:
                    batter_stats[bid]["H"][sim] += 1
                    batter_stats[bid]["TB"][sim] += TOTAL_BASES.get(outcome_idx, 0)

                # Runner advancement
                class _BRRng:
                    def __init__(self, vals):
                        self._vals = vals
                        self._i = 0
                    def random(self):
                        v = self._vals[self._i % len(self._vals)]
                        self._i += 1
                        return v

                br_rng = _BRRng(br_randoms[sim, pa_idx])

                if outcome_idx in OUT_INDICES:
                    outs += 1
                    if outcome_idx == GROUNDOUT_IDX and bases[0] and outs < 3:
                        if br_randoms[sim, pa_idx, 0] < 0.35:
                            outs += 1
                            bases[0] = False
                    if outs < 3:
                        new_bases, r_scored, rbi_scored = _advance_runners(bases, outcome_idx, br_rng)
                    else:
                        new_bases = np.zeros(3, dtype=np.bool_)
                        r_scored = 0
                        rbi_scored = 0
                else:
                    new_bases, r_scored, rbi_scored = _advance_runners(bases, outcome_idx, br_rng)

                bases = new_bases

                if r_scored > 0:
                    team_runs[sim] += r_scored
                    batter_stats[bid]["RBI"][sim] += rbi_scored
                    if outcome_idx == HR_IDX:
                        batter_stats[bid]["R"][sim] += 1
                        for back in range(1, r_scored):
                            prev_idx = (batting_order_pos - back) % n_batters
                            prev_bid = lineup[prev_idx].mlbam_id
                            batter_stats[prev_bid]["R"][sim] += 1
                    else:
                        for back in range(1, r_scored + 1):
                            prev_idx = (batting_order_pos - back) % n_batters
                            prev_bid = lineup[prev_idx].mlbam_id
                            batter_stats[prev_bid]["R"][sim] += 1

                batting_order_pos += 1
                pa_idx += 1

        if not is_bullpen_active:
            pitcher_pitch_counts[sim] = int(pitch_count)
            pitcher_innings[sim] = 9.0

    # Build results
    player_results = {}
    for batter in lineup:
        bid = batter.mlbam_id
        bs = batter_stats[bid]
        player_results[bid] = PlayerSimResults(
            mlbam_id=bid, name=batter.name, n_sims=n_sims,
            strikeouts=bs["K"], hits=bs["H"], total_bases=bs["TB"],
            home_runs=bs["HR"], walks=bs["BB"], hbps=bs["HBP"],
            runs=bs["R"], rbis=bs["RBI"], plate_appearances=bs["PA"],
        )

    game_results = GameSimResults(
        n_sims=n_sims,
        player_results=player_results,
        team_runs=team_runs,
        pitcher_pitch_counts=pitcher_pitch_counts,
        pitcher_innings=pitcher_innings,
    )

    return game_results, pitcher_ks


# ---------------------------------------------------------------------------
# Convenience: build profiles from raw stats
# ---------------------------------------------------------------------------

def build_batter_probs(
    k_rate: float = 0.224,
    bb_rate: float = 0.083,
    hbp_rate: float = 0.012,
    single_rate: float = 0.152,
    double_rate: float = 0.044,
    triple_rate: float = 0.004,
    hr_rate: float = 0.030,
    flyout_rate: float = 0.140,
    groundout_rate: float = 0.186,
    lineout_rate: float = 0.080,
    popup_rate: float = 0.045,
) -> np.ndarray:
    """
    Build a normalized probability vector from rate stats.

    All rates should be per-PA (0 to 1). They will be normalized
    to sum to 1.0.
    """
    probs = np.array([
        k_rate, bb_rate, hbp_rate, single_rate, double_rate,
        triple_rate, hr_rate, flyout_rate, groundout_rate,
        lineout_rate, popup_rate,
    ], dtype=np.float64)
    total = probs.sum()
    if total > 0:
        probs /= total
    return probs


def build_pitcher_profile_from_stats(
    mlbam_id: int,
    name: str,
    throws: str = "R",
    career_k9: float = 8.5,
    recent_pitch_counts: list = None,
    league_avg_k9: float = 8.5,
) -> PitcherProfile:
    """
    Build a PitcherProfile from career stats.

    The k_rate_modifier shifts batter K rates relative to league average.
    A pitcher with 10.0 K/9 vs league avg 8.5 K/9 gets a modifier of ~1.18.
    """
    k_mod = career_k9 / league_avg_k9 if league_avg_k9 > 0 else 1.0
    # Dampen extreme values
    k_mod = max(0.6, min(1.6, k_mod))

    return PitcherProfile(
        mlbam_id=mlbam_id,
        name=name,
        throws=throws,
        k_rate_modifier=k_mod,
        recent_pitch_counts=recent_pitch_counts or [],
    )


def build_bullpen_profile(
    era: float = 4.00,
    k9: float = 8.5,
    bb9: float = 3.5,
    hr9: float = 1.2,
) -> BullpenProfile:
    """Build a BullpenProfile from aggregate bullpen stats."""
    league_avg_era = 4.00
    league_avg_k9 = 8.5

    k_mod = k9 / league_avg_k9 if league_avg_k9 > 0 else 1.0
    k_mod = max(0.6, min(1.6, k_mod))

    # Better ERA = better contact quality suppression
    contact_mod = league_avg_era / era if era > 0 else 1.0
    contact_mod = max(0.7, min(1.3, contact_mod))

    return BullpenProfile(
        k_rate_modifier=k_mod,
        contact_quality_modifier=contact_mod,
    )
