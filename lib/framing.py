"""
lib/framing.py — Shared umpire/catcher framing logic
======================================================

Centralises all framing-related factor computation for both the
pipeline (generate_projections.py) and the simulator (monte_carlo_engine.py).

Supabase ``umpire_framing`` table columns used:
  umpire_name, catcher_id, game_date, game_pk,
  composite_score, extra_strikes, framing_runs, strike_rate

MLB calibration constants
--------------------------
- MLB_AVG_STRIKE_RATE  = 0.32  (average called-strike rate per game)
- MLB_AVG_COMPOSITE    = 0.20  (average catcher composite_score)

Factor semantics
-----------------
- K  factor > 1.0  → more strikeouts expected  (generous ump / good framer)
- K  factor < 1.0  → fewer strikeouts expected  (tight ump / poor framer)
- BB factor > 1.0  → more walks expected        (tight ump / poor framer)
- BB factor < 1.0  → fewer walks expected       (generous ump / good framer)
"""

from __future__ import annotations

import logging
import os
from typing import Any

import requests

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Supabase connection helpers (mirrors the pattern in generate_projections.py)
# ---------------------------------------------------------------------------

SUPABASE_URL = os.environ.get("SUPABASE_URL", "").strip()
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_KEY", "").strip()

# MLB calibration baselines
MLB_AVG_STRIKE_RATE: float = 0.32
MLB_AVG_COMPOSITE: float = 0.20

# Clamp bounds
_CATCHER_K_MIN: float = 0.95
_CATCHER_K_MAX: float = 1.05
_CATCHER_BB_MIN: float = 0.97
_CATCHER_BB_MAX: float = 1.03
_UMPIRE_BB_MIN: float = 0.90
_UMPIRE_BB_MAX: float = 1.10

# Minimum sample size before trusting the data
_MIN_SAMPLE: int = 5


def _sb_headers() -> dict[str, str]:
    return {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
    }


def _sb_get(table: str, params: dict[str, str]) -> list[dict[str, Any]]:
    """Execute a Supabase REST GET and return the JSON list."""
    url = f"{SUPABASE_URL}/rest/v1/{table}"
    r = requests.get(url, headers=_sb_headers(), params=params, timeout=10)
    r.raise_for_status()
    return r.json()


# ---------------------------------------------------------------------------
# Data-fetch helpers
# ---------------------------------------------------------------------------


def fetch_umpire_framing_data(
    umpire_name: str,
    lookback_games: int = 30,
) -> dict[str, Any]:
    """Query ``umpire_framing`` for a trailing sample of an umpire's games.

    Parameters
    ----------
    umpire_name:
        Full name of the home-plate umpire as stored in Supabase.
    lookback_games:
        Maximum number of recent games to include.

    Returns
    -------
    dict with keys:
        ``strike_rate_avg``, ``composite_score_avg``, ``extra_strikes_avg``,
        ``framing_runs_avg``, ``sample_size``.
        All numeric values are ``None`` when fewer than ``_MIN_SAMPLE`` rows
        are found.
    """
    empty: dict[str, Any] = {
        "strike_rate_avg": None,
        "composite_score_avg": None,
        "extra_strikes_avg": None,
        "framing_runs_avg": None,
        "sample_size": 0,
    }

    if not umpire_name:
        return empty

    try:
        rows = _sb_get(
            "umpire_framing",
            {
                "umpire_name": f"eq.{umpire_name}",
                "select": "strike_rate,composite_score,extra_strikes,framing_runs",
                "order": "game_date.desc",
                "limit": str(lookback_games),
            },
        )
    except Exception as exc:
        log.debug("fetch_umpire_framing_data failed for %s: %s", umpire_name, exc)
        return empty

    n = len(rows)
    if n < _MIN_SAMPLE:
        return {**empty, "sample_size": n}

    def _avg(key: str) -> float | None:
        vals = [r[key] for r in rows if r.get(key) is not None]
        return round(sum(vals) / len(vals), 6) if vals else None

    return {
        "strike_rate_avg": _avg("strike_rate"),
        "composite_score_avg": _avg("composite_score"),
        "extra_strikes_avg": _avg("extra_strikes"),
        "framing_runs_avg": _avg("framing_runs"),
        "sample_size": n,
    }


def fetch_catcher_framing_data(
    catcher_id: int | str,
    lookback_games: int = 30,
) -> dict[str, Any]:
    """Query ``umpire_framing`` for a trailing sample of a catcher's games.

    Parameters
    ----------
    catcher_id:
        MLBAM player ID of the catcher.
    lookback_games:
        Maximum number of recent games to include.

    Returns
    -------
    Same shape as :func:`fetch_umpire_framing_data`.
    """
    empty: dict[str, Any] = {
        "strike_rate_avg": None,
        "composite_score_avg": None,
        "extra_strikes_avg": None,
        "framing_runs_avg": None,
        "sample_size": 0,
    }

    if not catcher_id:
        return empty

    try:
        rows = _sb_get(
            "umpire_framing",
            {
                "catcher_id": f"eq.{catcher_id}",
                "select": "strike_rate,composite_score,extra_strikes,framing_runs",
                "order": "game_date.desc",
                "limit": str(lookback_games),
            },
        )
    except Exception as exc:
        log.debug("fetch_catcher_framing_data failed for %s: %s", catcher_id, exc)
        return empty

    n = len(rows)
    if n < _MIN_SAMPLE:
        return {**empty, "sample_size": n}

    def _avg(key: str) -> float | None:
        vals = [r[key] for r in rows if r.get(key) is not None]
        return round(sum(vals) / len(vals), 6) if vals else None

    return {
        "strike_rate_avg": _avg("strike_rate"),
        "composite_score_avg": _avg("composite_score"),
        "extra_strikes_avg": _avg("extra_strikes"),
        "framing_runs_avg": _avg("framing_runs"),
        "sample_size": n,
    }


# ---------------------------------------------------------------------------
# Factor-computation functions
# ---------------------------------------------------------------------------


def compute_umpire_k_factor(strike_rate_avg: float | None) -> float:
    """Convert a umpire's average called-strike rate to a K multiplier.

    MLB average called-strike rate is ~0.32.

    Parameters
    ----------
    strike_rate_avg:
        Average called-strike rate from ``fetch_umpire_framing_data``.
        Pass ``None`` to receive a neutral 1.0 factor.

    Returns
    -------
    float
        ``strike_rate_avg / 0.32``.
        e.g. 0.35 → 1.094 (generous ump); 0.29 → 0.906 (tight ump).
    """
    if strike_rate_avg is None or strike_rate_avg <= 0:
        return 1.0
    return round(strike_rate_avg / MLB_AVG_STRIKE_RATE, 4)


def compute_catcher_k_factor(composite_score_avg: float | None) -> float:
    """Convert a catcher's average composite framing score to a K multiplier.

    MLB average composite_score is ~0.20.  The raw ratio is dampened to
    a maximum of ±5% (clamped to [0.95, 1.05]).

    Parameters
    ----------
    composite_score_avg:
        Average composite framing score from ``fetch_catcher_framing_data``.
        Pass ``None`` for a neutral 1.0 factor.

    Returns
    -------
    float
        Dampened catcher K factor in [0.95, 1.05].
        e.g. composite 0.25 → raw 1.25, clamped to 1.05.
    """
    if composite_score_avg is None or composite_score_avg <= 0:
        return 1.0
    raw = composite_score_avg / MLB_AVG_COMPOSITE
    return round(max(_CATCHER_K_MIN, min(_CATCHER_K_MAX, raw)), 4)


def compute_umpire_bb_factor(strike_rate_avg: float | None) -> float:
    """Convert a umpire's called-strike rate to a walk (BB) multiplier.

    Generous ump calls more strikes → fewer walks (factor < 1).
    Tight ump calls fewer strikes → more walks (factor > 1).

    Formula: ``(1 - strike_rate) / (1 - 0.32)``, clamped to [0.90, 1.10].

    Parameters
    ----------
    strike_rate_avg:
        Average called-strike rate.  Pass ``None`` for a neutral 1.0.

    Returns
    -------
    float
        Umpire BB factor in [0.90, 1.10].
    """
    if strike_rate_avg is None or strike_rate_avg <= 0:
        return 1.0
    raw = (1.0 - strike_rate_avg) / (1.0 - MLB_AVG_STRIKE_RATE)
    return round(max(_UMPIRE_BB_MIN, min(_UMPIRE_BB_MAX, raw)), 4)


def compute_catcher_bb_factor(composite_score_avg: float | None) -> float:
    """Convert a catcher's composite framing score to a walk (BB) multiplier.

    Good framer (high composite) → fewer walks (factor < 1).
    Poor framer (low composite)  → more walks (factor > 1).

    The inverse is dampened to max ±3% (clamped to [0.97, 1.03]).

    Parameters
    ----------
    composite_score_avg:
        Average composite framing score.  Pass ``None`` for a neutral 1.0.

    Returns
    -------
    float
        Catcher BB factor in [0.97, 1.03].
    """
    if composite_score_avg is None or composite_score_avg <= 0:
        return 1.0
    # Inverse: good framer → composite > 0.20 → raw_k > 1 → bb factor < 1
    raw_k = composite_score_avg / MLB_AVG_COMPOSITE
    raw_bb = 1.0 / raw_k if raw_k > 0 else 1.0
    return round(max(_CATCHER_BB_MIN, min(_CATCHER_BB_MAX, raw_bb)), 4)


# ---------------------------------------------------------------------------
# Convenience aggregator
# ---------------------------------------------------------------------------


def get_game_framing_adjustments(
    game_pk: int | str | None,
    umpire_name: str | None = None,
    catcher_id: int | str | None = None,
    lookback_games: int = 30,
) -> dict[str, Any]:
    """Fetch all framing data for a game and return computed adjustment factors.

    This is the primary entry point for both the pipeline and the simulator.

    Parameters
    ----------
    game_pk:
        Supabase game PK (used only for logging; lookups are by name/ID).
    umpire_name:
        Home-plate umpire full name.
    catcher_id:
        MLBAM ID of the relevant catcher.
    lookback_games:
        Trailing-game window for both lookups.

    Returns
    -------
    dict with keys:
        ``umpire_k_factor``   (float)  — K multiplier from umpire tendencies
        ``umpire_bb_factor``  (float)  — BB multiplier from umpire tendencies
        ``catcher_k_factor``  (float)  — K multiplier from catcher framing
        ``catcher_bb_factor`` (float)  — BB multiplier from catcher framing
        ``umpire_name``       (str | None)
        ``catcher_id``        (int | str | None)
        ``umpire_data``       (dict)   — raw data from fetch_umpire_framing_data
        ``catcher_data``      (dict)   — raw data from fetch_catcher_framing_data
    """
    umpire_data = fetch_umpire_framing_data(umpire_name, lookback_games)
    catcher_data = fetch_catcher_framing_data(catcher_id, lookback_games)

    umpire_k_factor = compute_umpire_k_factor(umpire_data.get("strike_rate_avg"))
    umpire_bb_factor = compute_umpire_bb_factor(umpire_data.get("strike_rate_avg"))
    catcher_k_factor = compute_catcher_k_factor(catcher_data.get("composite_score_avg"))
    catcher_bb_factor = compute_catcher_bb_factor(catcher_data.get("composite_score_avg"))

    log.debug(
        "game_pk=%s umpire=%s ukf=%.3f ubbf=%.3f catcher=%s ckf=%.3f cbbf=%.3f",
        game_pk,
        umpire_name,
        umpire_k_factor,
        umpire_bb_factor,
        catcher_id,
        catcher_k_factor,
        catcher_bb_factor,
    )

    return {
        "umpire_k_factor": umpire_k_factor,
        "umpire_bb_factor": umpire_bb_factor,
        "catcher_k_factor": catcher_k_factor,
        "catcher_bb_factor": catcher_bb_factor,
        "umpire_name": umpire_name,
        "catcher_id": catcher_id,
        "umpire_data": umpire_data,
        "catcher_data": catcher_data,
    }
