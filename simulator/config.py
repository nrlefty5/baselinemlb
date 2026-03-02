"""
config.py -- BaselineMLB Monte Carlo Simulator
Central configuration module.

All tuning parameters, feature definitions, park factors, league averages,
and environment-backed secrets live here. Import from this module to keep
the rest of the codebase free of magic numbers.
"""

from __future__ import annotations

import logging
import os
import sys
from dataclasses import dataclass
from enum import Enum
from typing import Dict, List, Optional

# ---------------------------------------------------------------------------
# Attempt to load .env file if python-dotenv is available
# ---------------------------------------------------------------------------
try:
    from dotenv import load_dotenv  # type: ignore

    load_dotenv()
except ImportError:
    pass  # dotenv is optional; fall back to real environment variables


# ===========================================================================
# 1. SimulationConfig dataclass
# ====================================================================================


@dataclass
class SimulationConfig:
    """
    Central knob-panel for the Monte Carlo simulator.

    All numeric constants that influence simulation behaviour live here so
    that callers can override individual fields without touching module-level
    globals.

    Example
    -------
    >>> cfg = SimulationConfig(NUM_SIMULATIONS=500, RANDOM_SEED=42)
    """

    # ------------------------------------------------------------------
    # Simulation controls
    # ------------------------------------------------------------------
    NUM_SIMULATIONS: int = 2500
    """Number of Monte Carlo trials per game."""

    RANDOM_SEED: Optional[int] = None
    """
    Set to an integer for reproducible runs (testing / CI).
    Use ``None`` in production for true randomness.
    """

    # ------------------------------------------------------------------
    # Model artefact paths
    # ------------------------------------------------------------------
    MODEL_PATH: str = "models/matchup_model.joblib"
    """Path to the serialised matchup classifier."""

    SCALER_PATH: str = "models/feature_scaler.joblib"
    """Path to the fitted feature scaler."""

    # ------------------------------------------------------------------
    # Sample-size / regression parameters
    # ------------------------------------------------------------------
    MIN_PA_THRESHOLD: int = 50
    """Minimum plate appearances required before trusting individual stats."""

    REGRESSION_PA: int = 200
    """
    Effective PA used to weight individual stats against the league average
    during Bayesian / shrinkage regression for small samples.

    player_rate = (player_pa * player_rate + REGRESSION_PA * lg_avg) /
                  (player_pa + REGRESSION_PA)
    """

    # ------------------------------------------------------------------
    # Recent-form vs. career weighting
    # ------------------------------------------------------------------
    RECENT_DAYS: int = 14
    """Look-back window (calendar days) for the recent-form slice."""

    CAREER_DAYS: int = 365
    """Look-back window (calendar days) for the career-stats slice."""

    RECENT_WEIGHT: float = 0.6
    """Weight applied to recent-form rates when blending with career rates."""

    CAREER_WEIGHT: float = 0.4
    """Weight applied to career rates when blending with recent-form rates."""

    def __post_init__(self) -> None:
        if abs(self.RECENT_WEIGHT + self.CAREER_WEIGHT - 1.0) > 1e-9:
            raise ValueError(
                f"RECENT_WEIGHT + CAREER_WEIGHT must equal 1.0, "
                f"got {self.RECENT_WEIGHT + self.CAREER_WEIGHT}"
            )
        if self.NUM_SIMULATIONS < 1:
            raise ValueError("NUM_SIMULATIONS must be a positive integer.")

    # ------------------------------------------------------------------
    # Pitcher workload model
    # ------------------------------------------------------------------
    PITCH_COUNT_MEAN: int = 92
    """Expected starter pitch count (league average, 2024)."""

    PITCH_COUNT_STD: int = 12
    """Standard deviation of starter pitch counts."""

    PITCHES_PER_PA: float = 3.95
    """League-average pitches per plate appearance -- used to estimate IP."""

    # ------------------------------------------------------------------
    # Betting / edge parameters
    # ------------------------------------------------------------------
    EV_THRESHOLD: float = 0.03
    """Minimum positive expected value (edge) required to flag a bet."""

    KELLY_FRACTION: float = 0.25
    """Fractional Kelly multiplier (quarter-Kelly by default)."""

    MAX_KELLY_BET: float = 0.05
    """Hard cap on any single wager as a fraction of bankroll (5 %)."""


# ===========================================================================
# 2. PA_OUTCOMES
# ===========================================================================


class PAOutcome(str, Enum):
    """Enumeration of every possible plate-appearance result tracked in the sim."""

    STRIKEOUT = "strikeout"
    WALK = "walk"
    HBP = "hbp"
    SINGLE = "single"
    DOUBLE = "double"
    TRIPLE = "triple"
    HOME_RUN = "home_run"
    FIELD_OUT = "field_out"
    GROUND_OUT = "ground_out"
    FLY_OUT = "fly_out"
    LINE_OUT = "line_out"
    POP_OUT = "pop_out"
    DOUBLE_PLAY = "double_play"
    SAC_FLY = "sac_fly"
    SAC_BUNT = "sac_bunt"
    FIELDERS_CHOICE = "fielders_choice"


# Flat list alias for code that iterates over outcome strings directly.
PA_OUTCOMES: List[str] = [o.value for o in PAOutcome]


# ===========================================================================
# 3. Outcome groups
# ===========================================================================


OUTCOME_GROUPS: Dict[str, List[str]] = {
    "strikeout": ["strikeout", "strikeout_double_play"],
    "walk": ["walk"],
    "hbp": ["hit_by_pitch"],
    "single": ["single"],
    "double": ["double"],
    "triple": ["triple"],
    "home_run": ["home_run"],
    "out": [
        "field_out",
        "grounded_into_double_play",
        "force_out",
        "sac_fly",
        "sac_bunt",
        "fielders_choice",
        "double_play",
        "sac_fly_double_play",
        "triple_play",
    ],
}

MODEL_OUTCOMES: List[str] = [
    "strikeout",
    "walk",
    "hbp",
    "single",
    "double",
    "triple",
    "home_run",
    "out",
]


# ===========================================================================
# 4. League-average outcome rates (2024 season)
# ===========================================================================


LEAGUE_AVG_RATES: Dict[str, float] = {
    "strikeout": 0.224,
    "walk": 0.082,
    "hbp": 0.012,
    "single": 0.145,
    "double": 0.044,
    "triple": 0.004,
    "home_run": 0.032,
    "out": 0.457,
}

_lg_sum = sum(LEAGUE_AVG_RATES.values())
assert abs(_lg_sum - 1.0) < 1e-6, (
    f"LEAGUE_AVG_RATES do not sum to 1.0 (got {_lg_sum:.6f}). "
    "Adjust the 'out' bucket to compensate."
)


# ===========================================================================
# 5. Park factors
# ===========================================================================

PARK_FACTORS: Dict[str, Dict[str, float]] = {
    # National League
    "Truist Park": {"hr": 1.05, "h": 1.02, "k": 0.99, "bb": 1.00, "2b": 1.04, "3b": 0.80},
    "Wrigley Field": {"hr": 1.08, "h": 1.03, "k": 0.97, "bb": 1.01, "2b": 1.05, "3b": 0.85},
    "Great American Ball Park": {"hr": 1.18, "h": 1.04, "k": 0.96, "bb": 1.02, "2b": 1.06, "3b": 0.78},
    "Coors Field": {"hr": 1.30, "h": 1.18, "k": 0.88, "bb": 1.05, "2b": 1.22, "3b": 1.55},
    "Chase Field": {"hr": 1.10, "h": 1.03, "k": 0.98, "bb": 1.01, "2b": 1.04, "3b": 0.90},
    "Dodger Stadium": {"hr": 0.95, "h": 0.97, "k": 1.02, "bb": 0.99, "2b": 0.96, "3b": 0.88},
    "Petco Park": {"hr": 0.85, "h": 0.95, "k": 1.03, "bb": 0.98, "2b": 0.94, "3b": 0.90},
    "Oracle Park": {"hr": 0.78, "h": 0.96, "k": 1.04, "bb": 0.99, "2b": 1.00, "3b": 1.10},
    "loanDepot park": {"hr": 0.92, "h": 0.98, "k": 1.01, "bb": 0.99, "2b": 0.95, "3b": 0.85},
    "American Family Field": {"hr": 1.12, "h": 1.02, "k": 0.98, "bb": 1.00, "2b": 1.03, "3b": 0.80},
    "Citi Field": {"hr": 0.90, "h": 0.97, "k": 1.02, "bb": 1.00, "2b": 0.98, "3b": 0.85},
    "Citizens Bank Park": {"hr": 1.15, "h": 1.04, "k": 0.97, "bb": 1.01, "2b": 1.05, "3b": 0.82},
    "PNC Park": {"hr": 0.95, "h": 0.99, "k": 1.00, "bb": 0.99, "2b": 1.02, "3b": 1.05},
    "Busch Stadium": {"hr": 0.96, "h": 0.99, "k": 1.01, "bb": 0.99, "2b": 1.00, "3b": 0.92},
    # American League
    "Oriole Park at Camden Yards": {"hr": 1.14, "h": 1.03, "k": 0.98, "bb": 1.00, "2b": 1.04, "3b": 0.78},
    "Fenway Park": {"hr": 1.08, "h": 1.07, "k": 0.97, "bb": 1.01, "2b": 1.18, "3b": 0.82},
    "Guaranteed Rate Field": {"hr": 1.10, "h": 1.01, "k": 0.99, "bb": 1.00, "2b": 1.02, "3b": 0.80},
    "Progressive Field": {"hr": 0.97, "h": 1.00, "k": 1.00, "bb": 1.00, "2b": 1.03, "3b": 0.85},
    "Comerica Park": {"hr": 0.88, "h": 0.98, "k": 1.02, "bb": 1.00, "2b": 1.00, "3b": 0.90},
    "Kauffman Stadium": {"hr": 0.93, "h": 1.00, "k": 1.00, "bb": 0.99, "2b": 1.01, "3b": 1.00},
    "Target Field": {"hr": 1.00, "h": 1.00, "k": 1.00, "bb": 1.00, "2b": 1.02, "3b": 0.88},
    "Yankee Stadium": {"hr": 1.22, "h": 1.02, "k": 0.98, "bb": 1.01, "2b": 1.00, "3b": 0.72},
    "Oakland Coliseum": {"hr": 0.80, "h": 0.94, "k": 1.04, "bb": 0.98, "2b": 0.92, "3b": 0.88},
    "T-Mobile Park": {"hr": 0.90, "h": 0.97, "k": 1.02, "bb": 1.00, "2b": 0.97, "3b": 0.90},
    "Tropicana Field": {"hr": 0.94, "h": 0.98, "k": 1.01, "bb": 0.99, "2b": 0.96, "3b": 0.85},
    "Globe Life Field": {"hr": 1.05, "h": 1.01, "k": 0.99, "bb": 1.00, "2b": 1.02, "3b": 0.82},
    "Rogers Centre": {"hr": 1.15, "h": 1.03, "k": 0.97, "bb": 1.01, "2b": 1.04, "3b": 0.78},
    "Minute Maid Park": {"hr": 1.10, "h": 1.02, "k": 0.98, "bb": 1.00, "2b": 1.05, "3b": 0.80},
    "neutral": {"hr": 1.00, "h": 1.00, "k": 1.00, "bb": 1.00, "2b": 1.00, "3b": 1.00},
}


# ===========================================================================
# 6. Feature columns
# ===========================================================================


FEATURE_COLUMNS: List[str] = [
    "pitcher_k_rate",
    "pitcher_bb_rate",
    "pitcher_hr_rate",
    "pitcher_whiff_pct",
    "pitcher_csw_pct",
    "pitcher_zone_pct",
    "pitcher_swstr_pct",
    "pitcher_avg_velo",
    "pitcher_chase_rate",
    "pitcher_iz_contact_pct",
    "batter_k_rate",
    "batter_bb_rate",
    "batter_hr_rate",
    "batter_xba",
    "batter_xslg",
    "batter_barrel_pct",
    "batter_hard_hit_pct",
    "batter_chase_rate",
    "batter_whiff_pct",
    "batter_contact_pct",
    "platoon_advantage",
    "is_home",
    "park_hr_factor",
    "park_k_factor",
    "park_h_factor",
    "umpire_k_factor",
    "catcher_framing_score",
    "pitcher_recent_k_rate",
    "batter_recent_ba",
    "game_total_line",
    "temp_f",
    "wind_speed_mph",
    "wind_out",
]


# ===========================================================================
# 7. Supabase configuration
# ===========================================================================


SUPABASE_URL: str = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY: str = os.environ.get("SUPABASE_KEY", "")


# ===========================================================================
# 8. Logging configuration
# ===========================================================================


def configure_logging(
    level: int = logging.INFO,
    log_file: Optional[str] = None,
    fmt: str = "%(asctime)s  %(levelname)-8s  %(name)s -- %(message)s",
    datefmt: str = "%Y-%m-%d %H:%M:%S",
) -> logging.Logger:
    """
    Configure the root logger and return the ``baselinemlb`` application logger.
    """
    formatter = logging.Formatter(fmt=fmt, datefmt=datefmt)

    console_handler = logging.StreamHandler(stream=sys.stdout)
    console_handler.setFormatter(formatter)
    console_handler.setLevel(level)

    handlers: List[logging.Handler] = [console_handler]

    if log_file:
        from logging.handlers import RotatingFileHandler

        file_handler = RotatingFileHandler(
            log_file,
            maxBytes=10 * 1024 * 1024,
            backupCount=5,
            encoding="utf-8",
        )
        file_handler.setFormatter(formatter)
        file_handler.setLevel(level)
        handlers.append(file_handler)

    root = logging.getLogger()
    if not root.handlers:
        root.setLevel(level)
        for h in handlers:
            root.addHandler(h)
    else:
        root.setLevel(min(root.level, level))

    return logging.getLogger("baselinemlb")


logger: logging.Logger = configure_logging()


# ===========================================================================
# Convenience: module-level default config instance
# ===========================================================================

DEFAULT_CONFIG: SimulationConfig = SimulationConfig()
"""
A ready-to-use ``SimulationConfig`` with production defaults.

Import and use directly::

    from simulator.config import DEFAULT_CONFIG
    n = DEFAULT_CONFIG.NUM_SIMULATIONS  # 2500
"""
