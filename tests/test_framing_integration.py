"""
tests/test_framing_integration.py
==================================
Verify that the framing helpers in ``lib/framing.py`` work correctly
with mocked Supabase responses and that adjustments stay within bounds.
"""

from __future__ import annotations

import os
import sys
from unittest.mock import patch

# Ensure project root is on sys.path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from lib.framing import (
    get_catcher_adjustment,
    get_catcher_composite,
    get_umpire_adjustment,
    get_umpire_strike_rate,
)

# ---------------------------------------------------------------------------
# Fixtures: mock Supabase responses
# ---------------------------------------------------------------------------

MOCK_UMPIRE_ROWS_GENEROUS = [
    {"strike_rate": 0.34, "game_date": "2025-09-01"},
    {"strike_rate": 0.35, "game_date": "2025-08-30"},
    {"strike_rate": 0.33, "game_date": "2025-08-28"},
]

MOCK_UMPIRE_ROWS_TIGHT = [
    {"strike_rate": 0.29, "game_date": "2025-09-01"},
    {"strike_rate": 0.30, "game_date": "2025-08-30"},
]

MOCK_CATCHER_ROWS_ELITE = [
    {"composite_score": 0.65, "game_date": "2025-09-01"},
    {"composite_score": 0.62, "game_date": "2025-08-30"},
]

MOCK_CATCHER_ROWS_POOR = [
    {"composite_score": 0.35, "game_date": "2025-09-01"},
    {"composite_score": 0.38, "game_date": "2025-08-30"},
]


# ---------------------------------------------------------------------------
# Tests: umpire strike rate
# ---------------------------------------------------------------------------

@patch("lib.framing._sb_get")
def test_umpire_strike_rate_generous(mock_get):
    """Generous umpire should return mean strike rate."""
    mock_get.return_value = MOCK_UMPIRE_ROWS_GENEROUS
    # Force re-import of function with mock
    import lib.framing as framing
    framing._sb_get = mock_get

    rate = get_umpire_strike_rate("Angel Hernandez")
    assert rate is not None
    assert abs(rate - 0.34) < 0.01  # mean of 0.34, 0.35, 0.33


@patch("lib.framing._sb_get")
def test_umpire_strike_rate_no_data(mock_get):
    """No data should return None."""
    mock_get.return_value = []
    import lib.framing as framing
    framing._sb_get = mock_get

    rate = get_umpire_strike_rate("Unknown Ump")
    assert rate is None


# ---------------------------------------------------------------------------
# Tests: catcher composite
# ---------------------------------------------------------------------------

@patch("lib.framing._sb_get")
def test_catcher_composite_elite(mock_get):
    """Elite framer should return high composite."""
    mock_get.return_value = MOCK_CATCHER_ROWS_ELITE
    import lib.framing as framing
    framing._sb_get = mock_get

    score = get_catcher_composite(12345)
    assert score is not None
    assert score > 0.6


@patch("lib.framing._sb_get")
def test_catcher_composite_no_data(mock_get):
    """No data should return None."""
    mock_get.return_value = []
    import lib.framing as framing
    framing._sb_get = mock_get

    score = get_catcher_composite(99999)
    assert score is None


# ---------------------------------------------------------------------------
# Tests: umpire adjustment multiplier
# ---------------------------------------------------------------------------

@patch("lib.framing._sb_get")
def test_umpire_adjustment_generous(mock_get):
    """Generous umpire → multiplier > 1.0."""
    mock_get.return_value = MOCK_UMPIRE_ROWS_GENEROUS
    import lib.framing as framing
    framing._sb_get = mock_get

    adj = get_umpire_adjustment("Generous Ump")
    assert adj > 1.0
    assert adj <= 1.05  # capped at 5%


@patch("lib.framing._sb_get")
def test_umpire_adjustment_tight(mock_get):
    """Tight umpire → multiplier < 1.0."""
    mock_get.return_value = MOCK_UMPIRE_ROWS_TIGHT
    import lib.framing as framing
    framing._sb_get = mock_get

    adj = get_umpire_adjustment("Tight Ump")
    assert adj < 1.0
    assert adj >= 0.95  # capped at -5%


@patch("lib.framing._sb_get")
def test_umpire_adjustment_no_data(mock_get):
    """No data → neutral 1.0."""
    mock_get.return_value = []
    import lib.framing as framing
    framing._sb_get = mock_get

    adj = get_umpire_adjustment("Nobody")
    assert adj == 1.0


# ---------------------------------------------------------------------------
# Tests: catcher adjustment multiplier
# ---------------------------------------------------------------------------

@patch("lib.framing._sb_get")
def test_catcher_adjustment_elite(mock_get):
    """Elite framer → multiplier > 1.0."""
    mock_get.return_value = MOCK_CATCHER_ROWS_ELITE
    import lib.framing as framing
    framing._sb_get = mock_get

    adj = get_catcher_adjustment(12345)
    assert adj > 1.0
    assert adj <= 1.06  # capped at 6%


@patch("lib.framing._sb_get")
def test_catcher_adjustment_poor(mock_get):
    """Poor framer → multiplier < 1.0."""
    mock_get.return_value = MOCK_CATCHER_ROWS_POOR
    import lib.framing as framing
    framing._sb_get = mock_get

    adj = get_catcher_adjustment(12345)
    assert adj < 1.0
    assert adj >= 0.94  # capped at -6%


@patch("lib.framing._sb_get")
def test_catcher_adjustment_no_data(mock_get):
    """No data → neutral 1.0."""
    mock_get.return_value = []
    import lib.framing as framing
    framing._sb_get = mock_get

    adj = get_catcher_adjustment(99999)
    assert adj == 1.0


# ---------------------------------------------------------------------------
# Bounds checking
# ---------------------------------------------------------------------------

@patch("lib.framing._sb_get")
def test_adjustments_bounded(mock_get):
    """Even extreme data should stay within bounds."""
    # Extreme umpire: strike rate of 0.50 (way above average)
    mock_get.return_value = [{"strike_rate": 0.50, "game_date": "2025-09-01"}]
    import lib.framing as framing
    framing._sb_get = mock_get

    adj = get_umpire_adjustment("Extreme Ump")
    assert 0.95 <= adj <= 1.05

    # Extreme catcher: composite of 0.95
    mock_get.return_value = [{"composite_score": 0.95, "game_date": "2025-09-01"}]
    framing._sb_get = mock_get

    adj = get_catcher_adjustment(11111)
    assert 0.94 <= adj <= 1.06
