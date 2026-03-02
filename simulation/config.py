"""
config.py — BaselineMLB Monte Carlo Simulator
=============================================
Central configuration constants for the simulation engine.

All magic numbers that influence simulation behaviour are
defined here so they can be found and tweaked in one place.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

# ===========================================================================
# Simulation meta
# ===========================================================================

#: Default number of Monte Carlo iterations per game
DEFAULT_N_SIMS: int = 10_000

#: Seed used when reproducibility is requested (None = fully random)
DEFAULT_SEED: Optional[int] = None

#: Number of innings in a regulation game
INNINGS_PER_GAME: int = 9

#: Maximum extra innings before simulation declares a tie
MAX_EXTRA_INNINGS: int = 10

#: Outs per inning
OUTS_PER_INNING: int = 3

#: Size of the batting lineup
LINEUP_SIZE: int = 9

# ===========================================================================
# League-average rates (2024 MLB season)
# ===========================================================================

#: League-average strikeout percentage
MLB_AVG_K_PCT: float = 0.224

#: League-average walk percentage
MLB_AVG_BB_PCT: float = 0.085

#: League-average hit-by-pitch percentage
MLB_AVG_HBP_PCT: float = 0.009

#: League-average batting average on balls in play
MLB_AVG_BABIP: float = 0.300

#: League-average batting average
MLB_AVG_BA: float = 0.243

#: League-average on-base percentage
MLB_AVG_OBP: float = 0.315

#: League-average slugging percentage
MLB_AVG_SLG: float = 0.392

#: League-average home-run-per-fly-ball rate
MLB_AVG_HR_PER_FB: float = 0.138

#: League-average fly-ball percentage
MLB_AVG_FB_PCT: float = 0.360

#: League-average ground-ball percentage
MLB_AVG_GB_PCT: float = 0.440

#: League-average line-drive percentage
MLB_AVG_LD_PCT: float = 0.200

#: League-average hard-hit percentage on balls in play
MLB_AVG_HARD_HIT_PCT: float = 0.380

#: League-average K/9 for starters
MLB_AVG_STARTER_K9: float = 8.5

#: Typical starter expected innings pitched
MLB_AVG_STARTER_IP: float = 5.5

# ===========================================================================
# Park factors
# ===========================================================================

# Strikeout adjustment per ballpark (percentage points, ± from league average)
# Positive = park suppresses contact / boosts Ks
PARK_K_FACTORS: dict[str, int] = {
    "Coors Field": -8,
    "Yankee Stadium": 3,
    "Oracle Park": 5,
    "Petco Park": 4,
    "Truist Park": 2,
    "Globe Life Field": 2,
    "Chase Field": 1,
    "T-Mobile Park": 3,
    "Guaranteed Rate Field": 0,
    "loanDepot park": 1,
    "Great American Ball Park": -2,
    "PNC Park": 1,
    "Minute Maid Park": 2,
    "Dodger Stadium": 4,
    "Angel Stadium": 0,
    "Fenway Park": -1,
    "Wrigley Field": -3,
    "Busch Stadium": 1,
    "Citizens Bank Park": -2,
}

# Run-scoring park factor (1.0 = neutral, >1 = hitter-friendly)
PARK_RUN_FACTORS: dict[str, float] = {
    "Coors Field": 1.28,
    "Yankee Stadium": 1.09,
    "Oracle Park": 0.91,
    "Petco Park": 0.94,
    "Truist Park": 1.01,
    "Globe Life Field": 1.06,
    "Chase Field": 1.05,
    "T-Mobile Park": 0.96,
    "Guaranteed Rate Field": 1.02,
    "loanDepot park": 0.97,
    "Great American Ball Park": 1.08,
    "PNC Park": 0.98,
    "Minute Maid Park": 1.03,
    "Dodger Stadium": 0.96,
    "Angel Stadium": 0.99,
    "Fenway Park": 1.04,
    "Wrigley Field": 1.00,
    "Busch Stadium": 0.97,
    "Citizens Bank Park": 1.01,
}

# ===========================================================================
# Probability tables
# ===========================================================================

# Base hit probability given a ball is put in play, by contact type
HIT_PROB_BY_CONTACT: dict[str, float] = {
    "ground_ball": 0.238,
    "fly_ball": 0.185,
    "line_drive": 0.685,
    "popup": 0.020,
}

# Extra-base-hit probability given a hit occurred, keyed by contact type then base
XBH_PROB_BY_CONTACT: dict[str, dict[str, float]] = {
    "ground_ball": {"2B": 0.05, "3B": 0.01, "HR": 0.00},
    "fly_ball":    {"2B": 0.08, "3B": 0.01, "HR": 0.20},
    "line_drive":  {"2B": 0.30, "3B": 0.03, "HR": 0.05},
    "popup":       {"2B": 0.00, "3B": 0.00, "HR": 0.00},
}

# Sacrifice-fly probability for a fly-ball out with runner on 3B (< 2 outs)
SAC_FLY_PROB: float = 0.10

# Wild-pitch / passed-ball probability per pitch
WILD_PITCH_PROB: float = 0.003

# Stolen-base attempt rate per opportunity (runner on 1B or 2B)
SB_ATTEMPT_RATE: float = 0.10

# Stolen-base success probability (conditional on attempt)
SB_SUCCESS_PROB: float = 0.79

# ===========================================================================
# Pitcher fatigue / stamina model
# ===========================================================================

# Pitch count at which a starter's performance begins to degrade
STAMINA_THRESHOLD: int = 90

# Rate of K-rate decline per pitch above the threshold
FATIGUE_K_DECLINE_PER_PITCH: float = 0.002

# Rate of BB-rate increase per pitch above the threshold
FATIGUE_BB_INCREASE_PER_PITCH: float = 0.001

# Maximum pitch count before an automatic pull
MAX_PITCH_COUNT: int = 120

# ===========================================================================
# Bullpen / relief model
# ===========================================================================

# Flat K% boost for relievers vs starters (relievers throw harder)
BULLPEN_K_BOOST: float = 0.025

# Flat BB% for relievers (slightly higher due to higher stuff, wilder)
BULLPEN_BB_ADJ: float = 0.005

# HR/FB rate for relievers
BULLPEN_HR_PER_FB: float = 0.150

# ===========================================================================
# Confidence / scoring weights
# ===========================================================================

# Minimum sample size (PA) to trust a player's rate stats
MIN_SAMPLE_PA: int = 100

# Weight of recent (14-day) form vs career stats
RECENT_FORM_WEIGHT: float = 0.30
CAREER_WEIGHT: float = 0.70

# Maximum confidence score achievable
MAX_CONFIDENCE: float = 0.95

# Minimum confidence score (floor)
MIN_CONFIDENCE: float = 0.40

# ===========================================================================
# Structured config dataclass (optional convenience wrapper)
# ===========================================================================


@dataclass
class SimConfig:
    """Convenience dataclass wrapping the top-level constants."""

    n_sims: int = DEFAULT_N_SIMS
    seed: Optional[int] = DEFAULT_SEED
    innings: int = INNINGS_PER_GAME
    max_extra_innings: int = MAX_EXTRA_INNINGS
    park_k_factors: dict[str, int] = field(default_factory=lambda: dict(PARK_K_FACTORS))
    park_run_factors: dict[str, float] = field(default_factory=lambda: dict(PARK_RUN_FACTORS))
    stamina_threshold: int = STAMINA_THRESHOLD
    max_pitch_count: int = MAX_PITCH_COUNT
    fatigue_k_decline: float = FATIGUE_K_DECLINE_PER_PITCH
    fatigue_bb_increase: float = FATIGUE_BB_INCREASE_PER_PITCH
    bullpen_k_boost: float = BULLPEN_K_BOOST
    bullpen_bb_adj: float = BULLPEN_BB_ADJ
    recent_form_weight: float = RECENT_FORM_WEIGHT
    career_weight: float = CAREER_WEIGHT
    min_sample_pa: int = MIN_SAMPLE_PA

    def park_k_factor(self, venue: str) -> int:
        """Return the K-factor for *venue*, defaulting to 0."""
        return self.park_k_factors.get(venue, 0)

    def park_run_factor(self, venue: str) -> float:
        """Return the run-factor for *venue*, defaulting to 1.0."""
        return self.park_run_factors.get(venue, 1.0)
