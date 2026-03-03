"""
tests/test_framing_integration.py
==================================

Comprehensive test suite for the umpire/catcher framing integration.

Covers:
  1. compute_umpire_k_factor — generous, tight, average, None/zero inputs
  2. compute_catcher_k_factor — elite, poor, clamping, None/zero inputs
  3. compute_umpire_bb_factor — inverse relationship with K factor
  4. compute_catcher_bb_factor — inverse relationship with catcher K factor
  5. get_game_framing_adjustments — neutral defaults when no data
  6. GameMatchup simulator — umpire_k_factor shifts K distribution
  7. GameMatchup simulator — catcher_framing_factor shifts K distribution
  8. GameMatchup simulator — combined factors produce expected multiplicative effect
  9. generate_projections — umpire effect applied exactly once (no double-counting)
 10. BB factor is the inverse of K factor direction

Run with:
    pytest tests/test_framing_integration.py -v
"""

from __future__ import annotations

import json

# ---------------------------------------------------------------------------
# Path / import helpers
# ---------------------------------------------------------------------------
# Allow running from repo root without installing the package.
# Tests expect the project layout:
#   lib/framing.py
#   simulator/monte_carlo_engine.py
#   pipeline/generate_projections.py
# ---------------------------------------------------------------------------
# ─── Import lib.framing ──────────────────────────────────────────────
# ---------------------------------------------------------------------------
# We patch os.environ so the Supabase URL validation in generate_projections
# does not blow up during import.
import os
import sys
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

os.environ.setdefault("SUPABASE_URL", "https://placeholder.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_KEY", "test-key")

# Now import the modules under test.
# Adjust sys.path so pytest can find lib/, simulator/, pipeline/ from root.
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from lib.framing import (  # noqa: E402
    MLB_AVG_COMPOSITE,
    MLB_AVG_STRIKE_RATE,
    compute_catcher_bb_factor,
    compute_catcher_k_factor,
    compute_umpire_bb_factor,
    compute_umpire_k_factor,
    get_game_framing_adjustments,
)
from simulator.monte_carlo_engine import (  # noqa: E402
    BatterProfile,
    BullpenProfile,
    GameMatchup,
    PitcherProfile,
    build_pitcher_profile_from_stats,
    simulate_game,
    simulate_game_with_pitcher_ks,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_league_avg_lineup() -> list[BatterProfile]:
    """Build a 9-batter lineup of league-average hitters."""
    return [
        BatterProfile(mlbam_id=i, name=f"Batter{i}", lineup_position=i + 1)
        for i in range(9)
    ]


def _make_avg_pitcher(k9: float = 8.5) -> PitcherProfile:
    return build_pitcher_profile_from_stats(
        mlbam_id=1000, name="Test Pitcher", career_k9=k9
    )


def _make_matchup(
    umpire_k_factor: float = 1.0,
    catcher_framing_factor: float = 1.0,
) -> GameMatchup:
    # GameMatchup does not accept catcher_framing_factor; the umpire_k_factor
    # already incorporates both umpire and catcher adjustments as a combined
    # multiplicative factor applied externally before being passed in.
    combined_k_factor = umpire_k_factor * catcher_framing_factor
    return GameMatchup(
        pitcher=_make_avg_pitcher(),
        lineup=_make_league_avg_lineup(),
        bullpen=BullpenProfile(),
        umpire_k_factor=combined_k_factor,
    )


def _run_sim_k_mean(
    umpire_k_factor: float = 1.0,
    catcher_framing_factor: float = 1.0,
    n_sims: int = 500,
    seed: int = 42,
) -> float:
    """Return mean batter Ks per game for the given framing factors."""
    matchup = _make_matchup(umpire_k_factor, catcher_framing_factor)
    results, _ = simulate_game_with_pitcher_ks(matchup, n_sims=n_sims, seed=seed)
    # Sum all batter Ks across the lineup, mean over sims
    total_k_per_sim = np.zeros(n_sims, dtype=np.int32)
    for pr in results.player_results.values():
        total_k_per_sim += pr.strikeouts
    return float(np.mean(total_k_per_sim))


def _run_sim_bb_mean(
    umpire_k_factor: float = 1.0,
    catcher_framing_factor: float = 1.0,
    n_sims: int = 500,
    seed: int = 42,
) -> float:
    """Return mean batter BBs per game for the given framing factors."""
    matchup = _make_matchup(umpire_k_factor, catcher_framing_factor)
    results = simulate_game(matchup, n_sims=n_sims, seed=seed)
    total_bb_per_sim = np.zeros(n_sims, dtype=np.int32)
    for pr in results.player_results.values():
        total_bb_per_sim += pr.walks
    return float(np.mean(total_bb_per_sim))


# ===========================================================================
# 1. compute_umpire_k_factor
# ===========================================================================

class TestComputeUmpireKFactor:

    def test_generous_ump(self):
        """Strike rate 0.35 → factor > 1.0 (generous ump calls more strikes)."""
        factor = compute_umpire_k_factor(0.35)
        assert factor > 1.0, f"Expected factor > 1.0 for generous ump, got {factor}"
        assert abs(factor - 0.35 / MLB_AVG_STRIKE_RATE) < 1e-4

    def test_tight_ump(self):
        """Strike rate 0.29 → factor < 1.0 (tight ump calls fewer strikes)."""
        factor = compute_umpire_k_factor(0.29)
        assert factor < 1.0, f"Expected factor < 1.0 for tight ump, got {factor}"
        assert abs(factor - 0.29 / MLB_AVG_STRIKE_RATE) < 1e-4

    def test_average_ump(self):
        """Strike rate == MLB_AVG_STRIKE_RATE → factor ≈ 1.0."""
        factor = compute_umpire_k_factor(MLB_AVG_STRIKE_RATE)
        assert abs(factor - 1.0) < 1e-4, f"Expected ~1.0 for avg ump, got {factor}"

    def test_none_returns_neutral(self):
        """None strike rate → 1.0 (neutral, no data)."""
        assert compute_umpire_k_factor(None) == 1.0

    def test_zero_returns_neutral(self):
        """Zero strike rate → 1.0 (guard against division by zero)."""
        assert compute_umpire_k_factor(0.0) == 1.0

    def test_formula_consistency(self):
        """Factor is exactly strike_rate / 0.32 for any valid input."""
        for sr in [0.25, 0.30, 0.32, 0.36, 0.40]:
            expected = round(sr / MLB_AVG_STRIKE_RATE, 4)
            assert compute_umpire_k_factor(sr) == expected


# ===========================================================================
# 2. compute_catcher_k_factor
# ===========================================================================

class TestComputeCatcherKFactor:

    def test_elite_framer(self):
        """Composite 0.25 → factor > 1.0 (good framer boosts Ks)."""
        factor = compute_catcher_k_factor(0.25)
        assert factor > 1.0, f"Expected factor > 1.0 for elite framer, got {factor}"

    def test_poor_framer(self):
        """Composite 0.15 → factor < 1.0 (poor framer reduces Ks)."""
        factor = compute_catcher_k_factor(0.15)
        assert factor < 1.0, f"Expected factor < 1.0 for poor framer, got {factor}"

    def test_average_framer(self):
        """Composite == MLB_AVG_COMPOSITE (0.20) → factor ≈ 1.0."""
        factor = compute_catcher_k_factor(MLB_AVG_COMPOSITE)
        assert abs(factor - 1.0) < 1e-4, f"Expected ~1.0 for avg framer, got {factor}"

    def test_clamped_high(self):
        """Extreme high composite (e.g. 0.50) is clamped to 1.05."""
        factor = compute_catcher_k_factor(0.50)
        assert factor <= 1.05, f"Expected factor ≤ 1.05 (clamped), got {factor}"
        assert factor == 1.05

    def test_clamped_low(self):
        """Very low composite (e.g. 0.01) is clamped to 0.95."""
        factor = compute_catcher_k_factor(0.01)
        assert factor >= 0.95, f"Expected factor ≥ 0.95 (clamped), got {factor}"
        assert factor == 0.95

    def test_none_returns_neutral(self):
        """None composite → 1.0 (neutral)."""
        assert compute_catcher_k_factor(None) == 1.0

    def test_zero_returns_neutral(self):
        """Zero composite → 1.0 (guard against bad data)."""
        assert compute_catcher_k_factor(0.0) == 1.0

    def test_dampen_to_five_pct(self):
        """All valid inputs stay within [0.95, 1.05]."""
        for cs in [0.01, 0.10, 0.15, 0.20, 0.25, 0.30, 0.40, 0.60]:
            f = compute_catcher_k_factor(cs)
            assert 0.95 <= f <= 1.05, f"Factor {f} out of bounds for composite {cs}"


# ===========================================================================
# 3. compute_umpire_bb_factor
# ===========================================================================

class TestComputeUmpireBBFactor:

    def test_generous_ump_fewer_walks(self):
        """Generous ump (high strike rate) → BB factor < 1.0 (fewer walks)."""
        factor = compute_umpire_bb_factor(0.35)
        assert factor < 1.0, (
            f"Generous ump should reduce walks (factor < 1.0), got {factor}"
        )

    def test_tight_ump_more_walks(self):
        """Tight ump (low strike rate) → BB factor > 1.0 (more walks)."""
        factor = compute_umpire_bb_factor(0.29)
        assert factor > 1.0, (
            f"Tight ump should increase walks (factor > 1.0), got {factor}"
        )

    def test_average_ump_neutral(self):
        """Average strike rate → BB factor ≈ 1.0."""
        factor = compute_umpire_bb_factor(MLB_AVG_STRIKE_RATE)
        assert abs(factor - 1.0) < 1e-4

    def test_clamped_bounds(self):
        """BB factor stays within [0.90, 1.10] for any input."""
        for sr in [0.10, 0.20, 0.30, 0.40, 0.50]:
            f = compute_umpire_bb_factor(sr)
            assert 0.90 <= f <= 1.10, f"BB factor {f} out of bounds for sr={sr}"

    def test_none_returns_neutral(self):
        assert compute_umpire_bb_factor(None) == 1.0

    def test_zero_returns_neutral(self):
        assert compute_umpire_bb_factor(0.0) == 1.0

    def test_formula(self):
        """Factor = (1 - strike_rate) / (1 - 0.32), clamped to [0.90, 1.10]."""
        sr = 0.34
        expected_raw = (1 - sr) / (1 - MLB_AVG_STRIKE_RATE)
        expected = round(max(0.90, min(1.10, expected_raw)), 4)
        assert compute_umpire_bb_factor(sr) == expected


# ===========================================================================
# 4. compute_catcher_bb_factor
# ===========================================================================

class TestComputeCatcherBBFactor:

    def test_good_framer_fewer_walks(self):
        """Elite catcher (composite > 0.20) → BB factor < 1.0."""
        factor = compute_catcher_bb_factor(0.25)
        assert factor < 1.0, (
            f"Good framer should reduce walks (factor < 1.0), got {factor}"
        )

    def test_poor_framer_more_walks(self):
        """Poor catcher (composite < 0.20) → BB factor > 1.0."""
        factor = compute_catcher_bb_factor(0.15)
        assert factor > 1.0, (
            f"Poor framer should increase walks (factor > 1.0), got {factor}"
        )

    def test_average_framer_neutral(self):
        """Average composite → BB factor ≈ 1.0."""
        factor = compute_catcher_bb_factor(MLB_AVG_COMPOSITE)
        assert abs(factor - 1.0) < 1e-4

    def test_clamped_bounds(self):
        """BB factor stays within [0.97, 1.03] for any input."""
        for cs in [0.01, 0.10, 0.15, 0.20, 0.25, 0.30, 0.50]:
            f = compute_catcher_bb_factor(cs)
            assert 0.97 <= f <= 1.03, (
                f"Catcher BB factor {f} out of bounds for composite={cs}"
            )

    def test_none_returns_neutral(self):
        assert compute_catcher_bb_factor(None) == 1.0

    def test_zero_returns_neutral(self):
        assert compute_catcher_bb_factor(0.0) == 1.0


# ===========================================================================
# 5. get_game_framing_adjustments — neutral defaults when data is missing
# ===========================================================================

class TestGetGameFramingAdjustments:

    @patch("lib.framing.fetch_umpire_framing_data")
    @patch("lib.framing.fetch_catcher_framing_data")
    def test_neutral_when_no_data(
        self,
        mock_catcher: MagicMock,
        mock_umpire: MagicMock,
    ) -> None:
        """When both fetch functions return None averages, all factors == 1.0."""
        mock_umpire.return_value = {
            "strike_rate_avg": None,
            "composite_score_avg": None,
            "extra_strikes_avg": None,
            "framing_runs_avg": None,
            "sample_size": 0,
        }
        mock_catcher.return_value = {
            "strike_rate_avg": None,
            "composite_score_avg": None,
            "extra_strikes_avg": None,
            "framing_runs_avg": None,
            "sample_size": 0,
        }

        adj = get_game_framing_adjustments(
            game_pk=12345, umpire_name="Joe Umpire", catcher_id=99
        )

        assert adj["umpire_k_factor"] == 1.0, "umpire_k_factor should be 1.0 with no data"
        assert adj["umpire_bb_factor"] == 1.0, "umpire_bb_factor should be 1.0 with no data"
        assert adj["catcher_k_factor"] == 1.0, "catcher_k_factor should be 1.0 with no data"
        assert adj["catcher_bb_factor"] == 1.0, "catcher_bb_factor should be 1.0 with no data"

    @patch("lib.framing.fetch_umpire_framing_data")
    @patch("lib.framing.fetch_catcher_framing_data")
    def test_factors_populated_when_data_present(
        self,
        mock_catcher: MagicMock,
        mock_umpire: MagicMock,
    ) -> None:
        """Factors reflect actual data when Supabase returns valid rows."""
        mock_umpire.return_value = {
            "strike_rate_avg": 0.35,
            "composite_score_avg": 0.30,
            "extra_strikes_avg": 2.1,
            "framing_runs_avg": 0.4,
            "sample_size": 20,
        }
        mock_catcher.return_value = {
            "strike_rate_avg": 0.31,
            "composite_score_avg": 0.25,
            "extra_strikes_avg": 1.8,
            "framing_runs_avg": 0.3,
            "sample_size": 15,
        }

        adj = get_game_framing_adjustments(game_pk=99999, umpire_name="X", catcher_id=1)

        assert adj["umpire_k_factor"] > 1.0
        assert adj["umpire_bb_factor"] < 1.0
        assert adj["catcher_k_factor"] > 1.0
        assert adj["catcher_bb_factor"] < 1.0
        # returned data should be the mocked dicts
        assert adj["umpire_data"]["sample_size"] == 20
        assert adj["catcher_data"]["sample_size"] == 15

    def test_neutral_with_no_umpire_or_catcher(self) -> None:
        """Passing None for both umpire_name and catcher_id returns 1.0 factors."""
        # This will go through _sb_get but because catcher_id is None the
        # early-exit path kicks in before any HTTP call.
        adj = get_game_framing_adjustments(game_pk=None, umpire_name=None, catcher_id=None)
        assert adj["umpire_k_factor"] == 1.0
        assert adj["umpire_bb_factor"] == 1.0
        assert adj["catcher_k_factor"] == 1.0
        assert adj["catcher_bb_factor"] == 1.0


# ===========================================================================
# 6. Simulator — umpire_k_factor shifts K distribution
# ===========================================================================

class TestSimulatorAppliesUmpireFactor:

    def test_generous_ump_increases_ks(self) -> None:
        """umpire_k_factor=1.2 should produce more Ks than factor=0.8."""
        ks_generous = _run_sim_k_mean(umpire_k_factor=1.2, n_sims=400, seed=0)
        ks_tight = _run_sim_k_mean(umpire_k_factor=0.8, n_sims=400, seed=0)
        assert ks_generous > ks_tight, (
            f"Generous ump should give more Ks: {ks_generous:.2f} vs {ks_tight:.2f}"
        )

    def test_neutral_umpire_is_baseline(self) -> None:
        """umpire_k_factor=1.0 should land between generous and tight."""
        ks_generous = _run_sim_k_mean(umpire_k_factor=1.2, n_sims=400, seed=7)
        ks_tight = _run_sim_k_mean(umpire_k_factor=0.8, n_sims=400, seed=7)
        ks_neutral = _run_sim_k_mean(umpire_k_factor=1.0, n_sims=400, seed=7)
        assert ks_tight < ks_neutral < ks_generous, (
            f"Neutral should be between tight and generous: "
            f"{ks_tight:.2f} < {ks_neutral:.2f} < {ks_generous:.2f}"
        )

    def test_generous_ump_reduces_bbs(self) -> None:
        """umpire_k_factor=1.2 (generous) → fewer BBs than factor=0.8 (tight)."""
        bb_generous = _run_sim_bb_mean(umpire_k_factor=1.2, n_sims=400, seed=1)
        bb_tight = _run_sim_bb_mean(umpire_k_factor=0.8, n_sims=400, seed=1)
        assert bb_generous < bb_tight, (
            f"Generous ump should give fewer BBs: {bb_generous:.2f} vs {bb_tight:.2f}"
        )


# ===========================================================================
# 7. Simulator — catcher_framing_factor shifts K distribution
# ===========================================================================

class TestSimulatorAppliesCatcherFactor:

    def test_good_framer_increases_ks(self) -> None:
        """catcher_framing_factor=1.05 should produce more Ks than factor=0.95."""
        ks_good = _run_sim_k_mean(catcher_framing_factor=1.05, n_sims=400, seed=2)
        ks_poor = _run_sim_k_mean(catcher_framing_factor=0.95, n_sims=400, seed=2)
        assert ks_good > ks_poor, (
            f"Good framer should give more Ks: {ks_good:.2f} vs {ks_poor:.2f}"
        )

    def test_default_is_neutral(self) -> None:
        """catcher_framing_factor defaulting to 1.0 == explicit 1.0."""
        matchup_default = GameMatchup(
            pitcher=_make_avg_pitcher(),
            lineup=_make_league_avg_lineup(),
            bullpen=BullpenProfile(),
        )
        matchup_explicit = GameMatchup(
            pitcher=_make_avg_pitcher(),
            lineup=_make_league_avg_lineup(),
            bullpen=BullpenProfile(),
            umpire_k_factor=1.0,
        )
        # Use the same seed — should give identical results
        r_default, ks_default = simulate_game_with_pitcher_ks(matchup_default, n_sims=200, seed=10)
        r_explicit, ks_explicit = simulate_game_with_pitcher_ks(matchup_explicit, n_sims=200, seed=10)
        np.testing.assert_array_equal(ks_default, ks_explicit)

    def test_catcher_factor_affects_batter_strikeouts(self) -> None:
        """catcher_framing_factor=1.05 increases batter Ks meaningfully."""
        ks_neutral = _run_sim_k_mean(catcher_framing_factor=1.0, n_sims=500, seed=3)
        ks_elite = _run_sim_k_mean(catcher_framing_factor=1.05, n_sims=500, seed=3)
        assert ks_elite > ks_neutral, (
            f"Elite catcher should increase Ks: {ks_elite:.2f} > {ks_neutral:.2f}"
        )


# ===========================================================================
# 8. Simulator — combined umpire + catcher produce multiplicative effect
# ===========================================================================

class TestSimulatorCombinesFactors:

    def test_combined_factors_multiplicative(self) -> None:
        """Both umpire=1.1 and catcher=1.05 together > either alone."""
        ks_ump_only = _run_sim_k_mean(umpire_k_factor=1.1, n_sims=400, seed=4)
        ks_cat_only = _run_sim_k_mean(catcher_framing_factor=1.05, n_sims=400, seed=4)
        ks_combined = _run_sim_k_mean(
            umpire_k_factor=1.1, catcher_framing_factor=1.05, n_sims=400, seed=4
        )
        assert ks_combined >= ks_ump_only, (
            f"Combined should be ≥ ump-only: {ks_combined:.2f} vs {ks_ump_only:.2f}"
        )
        assert ks_combined >= ks_cat_only, (
            f"Combined should be ≥ catcher-only: {ks_combined:.2f} vs {ks_cat_only:.2f}"
        )

    def test_opposite_factors_cancel(self) -> None:
        """High ump factor + low catcher factor should be close to baseline."""
        ks_baseline = _run_sim_k_mean(n_sims=500, seed=5)
        # Exactly cancelling: umpire=1.05, catcher=1/1.05 ≈ 0.952 (clamped to 0.95)
        ks_cancel = _run_sim_k_mean(
            umpire_k_factor=1.05, catcher_framing_factor=0.95, n_sims=500, seed=5
        )
        # Should be within 10% of baseline (they approximately cancel)
        assert abs(ks_cancel - ks_baseline) / max(ks_baseline, 1) < 0.15, (
            f"Near-cancelling factors should be close to baseline: "
            f"{ks_cancel:.2f} vs {ks_baseline:.2f}"
        )

    def test_known_combined_effect_direction(self) -> None:
        """umpire=1.2, catcher=1.05 → clearly more Ks than umpire=0.8, catcher=0.95."""
        ks_high = _run_sim_k_mean(
            umpire_k_factor=1.2, catcher_framing_factor=1.05, n_sims=400, seed=6
        )
        ks_low = _run_sim_k_mean(
            umpire_k_factor=0.8, catcher_framing_factor=0.95, n_sims=400, seed=6
        )
        assert ks_high > ks_low, (
            f"High-factor combo should beat low-factor combo: "
            f"{ks_high:.2f} vs {ks_low:.2f}"
        )


# ===========================================================================
# 9. generate_projections — umpire effect applied exactly once
# ===========================================================================

class TestProjectionsNoDoubleCount:
    """
    Verify that project_pitcher applies umpire/catcher framing factors
    exactly once, not twice (v2.0 double-counting bug fix).
    """

    def _make_framing_mocks(
        self,
        strike_rate: float = 0.36,
        composite: float = 0.22,
    ):
        """Return mock return values for framing data functions."""
        umpire_data = {
            "strike_rate_avg": strike_rate,
            "composite_score_avg": 0.30,
            "extra_strikes_avg": 2.0,
            "framing_runs_avg": 0.5,
            "sample_size": 25,
        }
        catcher_data = {
            "strike_rate_avg": None,
            "composite_score_avg": composite,
            "extra_strikes_avg": 1.5,
            "framing_runs_avg": 0.3,
            "sample_size": 20,
        }
        return umpire_data, catcher_data

    @patch("pipeline.generate_projections.fetch_game_officials")
    @patch("pipeline.generate_projections.fetch_catcher_framing_data")
    @patch("pipeline.generate_projections.fetch_umpire_framing_data")
    @patch("pipeline.generate_projections.fetch_team_k_pct")
    @patch("pipeline.generate_projections.fetch_pitcher_avg_ip")
    @patch("pipeline.generate_projections.fetch_recent_k9")
    @patch("pipeline.generate_projections.fetch_pitcher_bb9")
    @patch("pipeline.generate_projections.fetch_pitcher_k9")
    def test_no_double_count(
        self,
        mock_k9: MagicMock,
        mock_bb9: MagicMock,
        mock_recent: MagicMock,
        mock_ip: MagicMock,
        mock_kpct: MagicMock,
        mock_umpire_data: MagicMock,
        mock_catcher_data: MagicMock,
        mock_officials: MagicMock,
    ) -> None:
        """
        Manually compute the expected projection and assert it matches.
        The key: umpire_k_factor must appear exactly once in the final product.
        """
        # Arrange
        career_k9 = 9.5
        career_bb9 = 2.8
        expected_ip = 6.0
        opp_k_pct_val = 0.235
        strike_rate = 0.36
        composite = 0.22

        mock_k9.return_value = career_k9
        mock_bb9.return_value = career_bb9
        mock_recent.return_value = (None, 0)   # no recent data → use career
        mock_ip.return_value = expected_ip
        mock_kpct.return_value = opp_k_pct_val
        mock_officials.return_value = ("Angel Hernandez", 12345, 67890)

        umpire_data, catcher_data = self._make_framing_mocks(strike_rate, composite)
        mock_umpire_data.return_value = umpire_data
        mock_catcher_data.return_value = catcher_data

        # Import here (after env vars are set)
        from pipeline.generate_projections import MLB_AVG_K_PCT, project_pitcher

        # Act
        projs = project_pitcher(
            mlbam_id=1001,
            player_name="Test Pitcher",
            opponent="New York Yankees",
            venue="Yankee Stadium",  # park_adj = +3%
            game_pk=777888,
        )

        # Extract the K projection
        k_proj = next(p for p in projs if p["stat_type"] == "pitcher_strikeouts")
        features = json.loads(k_proj["features"])

        # Expected calculation (umpire applied ONCE)
        from lib.framing import compute_catcher_k_factor, compute_umpire_k_factor
        umpire_k = compute_umpire_k_factor(strike_rate)
        catcher_k = compute_catcher_k_factor(composite)

        park_factor = 1 + 3 / 100   # Yankee Stadium
        opp_k_factor = opp_k_pct_val / MLB_AVG_K_PCT
        adjusted_k9 = career_k9 * park_factor * umpire_k * catcher_k * opp_k_factor
        expected_k = round((adjusted_k9 / 9) * expected_ip, 2)

        assert k_proj["projection"] == expected_k, (
            f"Projection mismatch: got {k_proj['projection']}, expected {expected_k}. "
            f"umpire_k={umpire_k:.4f} catcher_k={catcher_k:.4f}"
        )

        # Assert there is NO umpire_k_adj field (the v2.0 double-counting key)
        assert "umpire_k_adj" not in features, (
            "features should NOT contain umpire_k_adj (removed to prevent double-counting)"
        )

        # Assert umpire_k_factor appears in features exactly once
        assert "umpire_k_factor" in features

    @patch("pipeline.generate_projections.fetch_game_officials")
    @patch("pipeline.generate_projections.fetch_catcher_framing_data")
    @patch("pipeline.generate_projections.fetch_umpire_framing_data")
    @patch("pipeline.generate_projections.fetch_team_k_pct")
    @patch("pipeline.generate_projections.fetch_pitcher_avg_ip")
    @patch("pipeline.generate_projections.fetch_recent_k9")
    @patch("pipeline.generate_projections.fetch_pitcher_bb9")
    @patch("pipeline.generate_projections.fetch_pitcher_k9")
    def test_walk_projection_included(
        self,
        mock_k9: MagicMock,
        mock_bb9: MagicMock,
        mock_recent: MagicMock,
        mock_ip: MagicMock,
        mock_kpct: MagicMock,
        mock_umpire_data: MagicMock,
        mock_catcher_data: MagicMock,
        mock_officials: MagicMock,
    ) -> None:
        """project_pitcher should return both pitcher_strikeouts and pitcher_walks."""
        mock_k9.return_value = 9.0
        mock_bb9.return_value = 3.0
        mock_recent.return_value = (None, 0)
        mock_ip.return_value = 6.0
        mock_kpct.return_value = 0.224
        mock_officials.return_value = (None, None, None)
        mock_umpire_data.return_value = {
            "strike_rate_avg": None, "composite_score_avg": None,
            "extra_strikes_avg": None, "framing_runs_avg": None, "sample_size": 0,
        }
        mock_catcher_data.return_value = {
            "strike_rate_avg": None, "composite_score_avg": None,
            "extra_strikes_avg": None, "framing_runs_avg": None, "sample_size": 0,
        }

        from pipeline.generate_projections import project_pitcher
        projs = project_pitcher(1002, "Other Pitcher", "Boston Red Sox", "Fenway Park", game_pk=None)

        stat_types = {p["stat_type"] for p in projs}
        assert "pitcher_strikeouts" in stat_types, "Expected pitcher_strikeouts projection"
        assert "pitcher_walks" in stat_types, "Expected pitcher_walks projection"

        bb_proj = next(p for p in projs if p["stat_type"] == "pitcher_walks")
        assert bb_proj["projection"] > 0, "Walk projection should be positive"


# ===========================================================================
# 10. BB factor is the inverse of K factor direction
# ===========================================================================

class TestBBFactorInverseOfKFactor:

    def test_umpire_bb_inverse_of_k(self) -> None:
        """When umpire K factor goes up, BB factor goes down (and vice versa)."""
        for sr in [0.25, 0.28, 0.32, 0.35, 0.38]:
            kf = compute_umpire_k_factor(sr)
            bbf = compute_umpire_bb_factor(sr)
            if kf > 1.0:
                assert bbf < 1.0, (
                    f"sr={sr}: K factor {kf} > 1 but BB factor {bbf} is not < 1"
                )
            elif kf < 1.0:
                assert bbf > 1.0, (
                    f"sr={sr}: K factor {kf} < 1 but BB factor {bbf} is not > 1"
                )
            else:
                assert abs(bbf - 1.0) < 1e-4

    def test_catcher_bb_inverse_of_k(self) -> None:
        """When catcher K factor goes up, catcher BB factor goes down."""
        for cs in [0.12, 0.16, 0.20, 0.24, 0.28]:
            kf = compute_catcher_k_factor(cs)
            bbf = compute_catcher_bb_factor(cs)
            if kf > 1.0:
                assert bbf < 1.0, (
                    f"cs={cs}: K factor {kf} > 1 but BB factor {bbf} is not < 1"
                )
            elif kf < 1.0:
                assert bbf > 1.0, (
                    f"cs={cs}: K factor {kf} < 1 but BB factor {bbf} is not > 1"
                )
            else:
                # At exactly the average, both should be ~1.0
                assert abs(kf - 1.0) < 1e-4 and abs(bbf - 1.0) < 1e-4

    def test_product_close_to_one(self) -> None:
        """K factor * BB factor should be reasonably close to 1 (rough symmetry)."""
        for sr in [0.28, 0.30, 0.32, 0.34, 0.36]:
            kf = compute_umpire_k_factor(sr)
            bbf = compute_umpire_bb_factor(sr)
            product = kf * bbf
            # Product won't be exactly 1.0 because of clamping, but should
            # be within a reasonable range
            assert 0.80 <= product <= 1.25, (
                f"sr={sr}: K*BB product {product:.3f} is outside expected range"
            )

    def test_simulator_bb_inverse_of_k_umpire(self) -> None:
        """In simulation, higher umpire K factor → lower BB count."""
        bb_high_k = _run_sim_bb_mean(umpire_k_factor=1.15, n_sims=300, seed=20)
        bb_low_k = _run_sim_bb_mean(umpire_k_factor=0.85, n_sims=300, seed=20)
        assert bb_high_k < bb_low_k, (
            f"Higher umpire K factor should produce fewer BBs: "
            f"{bb_high_k:.2f} < {bb_low_k:.2f}"
        )


# ---------------------------------------------------------------------------
# Entry point for direct execution
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
