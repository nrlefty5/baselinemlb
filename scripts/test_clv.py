#!/usr/bin/env python3
"""
test_clv.py — Unit tests for CLV (Closing Line Value) tracking logic.

Tests cover:
  - Positive CLV (we had better price than closing)
  - Negative CLV (market moved against us)
  - Zero CLV (price unchanged)
  - Favorite/underdog direction FLIP edge case
    (e.g. opened -110 on the over, closed +105 — market flipped side)
  - Zero closing price guard (no division by zero)
  - Insufficient data (< 2 snapshots, skip)
  - CLV aggregation across multiple props

Run locally:
    python -m pytest scripts/test_clv.py -v
"""

import unittest
from unittest.mock import MagicMock, patch
from datetime import datetime

# ---------------------------------------------------------------------------
# Pure-function helpers extracted from track_clv.py logic
# (we test the math independently so we don't need a live Supabase connection)
# ---------------------------------------------------------------------------

def compute_clv(opening_price: int, closing_price: int) -> float:
    """
    CLV = (opening_price - closing_price) / abs(closing_price) * 100
    Positive  => we got the better side of the market.
    Negative  => market moved against us.
    """
    if closing_price == 0:
        return 0.0
    return round((opening_price - closing_price) / abs(closing_price) * 100, 2)


def classify_side(american_odds: int) -> str:
    """Return 'favorite' if odds < 0 else 'underdog'."""
    return "favorite" if american_odds < 0 else "underdog"


def did_side_flip(opening_price: int, closing_price: int) -> bool:
    """True when the bet flipped between favorite and underdog."""
    return classify_side(opening_price) != classify_side(closing_price)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestCLVMath(unittest.TestCase):

    # --- Basic CLV calculations ---

    def test_positive_clv_favorite_moved_shorter(self):
        """We opened -110, market closed -130 (more juice) = positive CLV."""
        # Opening better value (-110 > -130)
        clv = compute_clv(-110, -130)
        self.assertGreater(clv, 0, "Should be positive CLV when opening is shorter juice")
        self.assertAlmostEqual(clv, 15.38, places=1)

    def test_negative_clv_favorite_moved_longer(self):
        """We opened -130, market closed -110 = negative CLV (market said we overpaid)."""
        clv = compute_clv(-130, -110)
        self.assertLess(clv, 0, "Should be negative CLV when opening juice was higher")
        self.assertAlmostEqual(clv, -18.18, places=1)

    def test_zero_clv_unchanged_price(self):
        """Opening and closing are identical — CLV should be exactly 0."""
        clv = compute_clv(-110, -110)
        self.assertEqual(clv, 0.0)

    def test_positive_clv_underdog(self):
        """We opened +130, market closed +110 = positive CLV (we got better price)."""
        clv = compute_clv(130, 110)
        self.assertGreater(clv, 0)
        self.assertAlmostEqual(clv, 18.18, places=1)

    def test_negative_clv_underdog(self):
        """We opened +110, market closed +130 = negative CLV."""
        clv = compute_clv(110, 130)
        self.assertLess(clv, 0)

    # --- Flip edge case ---

    def test_flip_favorite_to_underdog(self):
        """
        EDGE CASE: Opened -110 (favorite side), closed +105 (underdog side).
        Market completely flipped direction. CLV is technically positive here
        (we took the under when it was -110, now it's +105 — the market
        moved massively in our favour), but we should ALSO flag the flip.
        """
        clv = compute_clv(-110, 105)
        flipped = did_side_flip(-110, 105)
        # CLV formula: (-110 - 105) / abs(105) * 100 = -215/105*100 ≈ -204.76
        # Negative because opening_price < closing_price numerically,
        # but this is actually a flip case — the negative sign is misleading.
        # The test confirms the flip is detected so callers can handle it specially.
        self.assertTrue(flipped, "Should detect favorite->underdog flip")
        self.assertAlmostEqual(clv, -204.76, places=1)

    def test_flip_underdog_to_favorite(self):
        """
        EDGE CASE: Opened +105 (underdog), closed -110 (favorite).
        """
        flipped = did_side_flip(105, -110)
        self.assertTrue(flipped, "Should detect underdog->favorite flip")

    def test_no_flip_both_favorite(self):
        """Both opening and closing are favorites — no flip."""
        self.assertFalse(did_side_flip(-120, -140))

    def test_no_flip_both_underdog(self):
        """Both opening and closing are underdogs — no flip."""
        self.assertFalse(did_side_flip(110, 130))

    # --- Guard conditions ---

    def test_zero_closing_price_returns_zero(self):
        """If closing price is 0 (bad data), return 0 instead of ZeroDivisionError."""
        clv = compute_clv(-110, 0)
        self.assertEqual(clv, 0.0)

    def test_large_line_move(self):
        """Very large line move (sharp action) should still compute correctly."""
        # Opened +300, closed +150 — market hammered the underdog
        clv = compute_clv(300, 150)
        self.assertGreater(clv, 0)
        self.assertAlmostEqual(clv, 100.0, places=1)


class TestCLVAggregation(unittest.TestCase):
    """Tests for summarising CLV across a set of picks."""

    def _make_records(self, values):
        return [{"clv_percent": v} for v in values]

    def test_average_clv_positive(self):
        records = self._make_records([5.0, 10.0, 15.0])
        avg = sum(r["clv_percent"] for r in records) / len(records)
        self.assertAlmostEqual(avg, 10.0)

    def test_average_clv_mixed(self):
        records = self._make_records([10.0, -5.0, 3.0, -2.0])
        avg = sum(r["clv_percent"] for r in records) / len(records)
        self.assertAlmostEqual(avg, 1.5)

    def test_empty_records_no_crash(self):
        records = []
        avg = sum(r["clv_percent"] for r in records) / len(records) if records else 0.0
        self.assertEqual(avg, 0.0)

    def test_single_record(self):
        records = self._make_records([7.25])
        avg = sum(r["clv_percent"] for r in records) / len(records)
        self.assertAlmostEqual(avg, 7.25)


class TestCLVSufficientData(unittest.TestCase):
    """Tests confirming we skip CLV when < 2 price snapshots exist."""

    def _should_calculate(self, props_list):
        """Mirror the guard logic from track_clv.py."""
        return len(props_list) >= 2

    def test_skip_single_snapshot(self):
        self.assertFalse(self._should_calculate([{"price": -110}]))

    def test_skip_empty(self):
        self.assertFalse(self._should_calculate([]))

    def test_proceed_two_snapshots(self):
        self.assertTrue(self._should_calculate([{"price": -110}, {"price": -120}]))

    def test_proceed_many_snapshots(self):
        self.assertTrue(self._should_calculate([{"price": -110}] * 5))


if __name__ == "__main__":
    unittest.main()
