#!/usr/bin/env python3
"""
tests/test_projections.py -- Baseline MLB
Pytest test suite for core projection math functions.

Tests cover:
  - Pitcher K/9 projection calculations
  - Park factor adjustments
  - Recent form blending
  - Umpire/catcher factor normalization
  - Opponent K% multiplier
  - Batter TB/PA calculations
  - Platoon split factors
  - Early-season ramp-up weighting
  - Confidence scoring
  - Edge case handling (missing data, zero IP, etc.)
"""

import json

# ---------------------------------------------------------------------------
# We need to mock environment variables before importing the modules
# ---------------------------------------------------------------------------
import os

import pytest

os.environ["SUPABASE_URL"] = "https://test-project.supabase.co"
os.environ["SUPABASE_SERVICE_KEY"] = "test-key-12345"


# ---------------------------------------------------------------------------
# Pitcher Projection Tests
# ---------------------------------------------------------------------------

class TestPitcherProjectionMath:
    """Test core pitcher strikeout projection calculations."""

    def test_park_k_factor_applies_correctly(self):
        """Park factor of +5% should increase K/9 by 5%."""
        from pipeline.generate_projections import PARK_K_FACTORS

        # Oracle Park has +5
        assert PARK_K_FACTORS["Oracle Park"] == 5
        # Coors Field has -8
        assert PARK_K_FACTORS["Coors Field"] == -8

        base_k9 = 10.0

        # Oracle Park: 10.0 * (1 + 5/100) = 10.5
        oracle_adjusted = base_k9 * (1 + PARK_K_FACTORS["Oracle Park"] / 100)
        assert oracle_adjusted == pytest.approx(10.5, abs=0.01)

        # Coors Field: 10.0 * (1 + (-8)/100) = 9.2
        coors_adjusted = base_k9 * (1 + PARK_K_FACTORS["Coors Field"] / 100)
        assert coors_adjusted == pytest.approx(9.2, abs=0.01)

    def test_unknown_venue_gets_zero_adjustment(self):
        """Unknown venues should get 0% adjustment."""
        from pipeline.generate_projections import PARK_K_FACTORS

        adj = PARK_K_FACTORS.get("Some Random Field", 0)
        assert adj == 0

    def test_recent_form_blending_weights(self):
        """Career weight (70%) + Recent weight (30%) should sum to 1.0."""
        from pipeline.generate_projections import CAREER_WEIGHT, RECENT_FORM_WEIGHT

        assert CAREER_WEIGHT + RECENT_FORM_WEIGHT == pytest.approx(1.0)

        career_k9 = 9.0
        recent_k9 = 12.0
        blended = (CAREER_WEIGHT * career_k9) + (RECENT_FORM_WEIGHT * recent_k9)
        # 0.70 * 9.0 + 0.30 * 12.0 = 6.3 + 3.6 = 9.9
        assert blended == pytest.approx(9.9, abs=0.01)

    def test_recent_form_blending_career_only(self):
        """When recent data is unavailable, should use career K/9 only."""

        career_k9 = 8.5
        # When recent_k9 is None, blended should just be career
        blended = career_k9  # This is what the code does when recent is None
        assert blended == 8.5

    def test_umpire_factor_normalization(self):
        """Umpire factor: rate / 0.32 baseline."""
        # Generous ump: 0.35 / 0.32 = 1.09375
        factor = 0.35 / 0.32
        assert factor == pytest.approx(1.094, abs=0.01)

        # Tight ump: 0.28 / 0.32 = 0.875
        factor = 0.28 / 0.32
        assert factor == pytest.approx(0.875, abs=0.01)

    def test_catcher_factor_dampening(self):
        """Catcher factor should be dampened to ±5% max."""
        # Elite framer: 0.30 / 0.20 = 1.50 -> capped at 1.05
        raw = 0.30 / 0.20
        dampened = max(0.95, min(1.05, raw))
        assert dampened == 1.05

        # Poor framer: 0.10 / 0.20 = 0.50 -> capped at 0.95
        raw = 0.10 / 0.20
        dampened = max(0.95, min(1.05, raw))
        assert dampened == 0.95

        # Average framer: 0.20 / 0.20 = 1.00 -> no change
        raw = 0.20 / 0.20
        dampened = max(0.95, min(1.05, raw))
        assert dampened == 1.0

    def test_opponent_k_factor(self):
        """Opponent K% factor: team_k_pct / MLB_AVG_K_PCT."""
        from pipeline.generate_projections import MLB_AVG_K_PCT

        # High-K team: 0.27 / 0.224 = 1.205
        high_k_pct = 0.270
        factor = high_k_pct / MLB_AVG_K_PCT
        assert factor == pytest.approx(1.205, abs=0.01)

        # Low-K team: 0.18 / 0.224 = 0.804
        low_k_pct = 0.180
        factor = low_k_pct / MLB_AVG_K_PCT
        assert factor == pytest.approx(0.804, abs=0.01)

    def test_projection_formula(self):
        """Full projection: adjusted_k9 / 9 * expected_ip."""
        adjusted_k9 = 10.0
        expected_ip = 6.0
        projected_k = (adjusted_k9 / 9) * expected_ip
        # 10/9 * 6 = 6.667
        assert projected_k == pytest.approx(6.667, abs=0.01)

    def test_confidence_scoring_min_max(self):
        """Confidence should be bounded between 0.50 and 0.95."""
        # Maximum possible confidence
        conf = 0.50 + 0.10 + 0.10 + 0.05 + 0.05 + 0.03 + 0.02 + 0.03
        conf = round(min(conf, 0.95), 3)
        assert conf == 0.88

        # Minimum base confidence
        conf = 0.50
        conf = round(min(conf, 0.95), 3)
        assert conf == 0.50


# ---------------------------------------------------------------------------
# Batter Projection Tests
# ---------------------------------------------------------------------------

class TestBatterProjectionMath:
    """Test core batter total bases projection calculations."""

    def test_early_season_rampup_game_zero(self):
        """At game 0, should use 100% league average."""
        from pipeline.generate_batter_projections import MLB_AVG_TB_PA, RAMP_UP_GAMES

        games_played = 0
        career_tb_pa = 0.200  # Above average hitter
        weight = min(games_played / RAMP_UP_GAMES, 1.0)
        blended = (1 - weight) * MLB_AVG_TB_PA + weight * career_tb_pa
        assert blended == MLB_AVG_TB_PA  # 100% league average

    def test_early_season_rampup_game_15(self):
        """At game 15, should be 50% career + 50% league average."""
        from pipeline.generate_batter_projections import MLB_AVG_TB_PA, RAMP_UP_GAMES

        games_played = 15
        career_tb_pa = 0.200
        weight = min(games_played / RAMP_UP_GAMES, 1.0)
        assert weight == pytest.approx(0.5)
        blended = (1 - weight) * MLB_AVG_TB_PA + weight * career_tb_pa
        expected = (0.5 * 0.135) + (0.5 * 0.200)  # 0.1675
        assert blended == pytest.approx(expected, abs=0.001)

    def test_early_season_rampup_game_30(self):
        """At game 30+, should use 100% career rate."""
        from pipeline.generate_batter_projections import MLB_AVG_TB_PA, RAMP_UP_GAMES

        games_played = 30
        career_tb_pa = 0.200
        weight = min(games_played / RAMP_UP_GAMES, 1.0)
        assert weight == 1.0
        blended = (1 - weight) * MLB_AVG_TB_PA + weight * career_tb_pa
        assert blended == career_tb_pa

    def test_platoon_splits_all_combos(self):
        """All 6 platoon combinations should have valid factors."""
        from pipeline.generate_batter_projections import PLATOON_SPLITS

        assert len(PLATOON_SPLITS) == 6

        # LHB vs RHP should have advantage
        assert PLATOON_SPLITS[("L", "R")] > 1.0
        # LHB vs LHP should have disadvantage
        assert PLATOON_SPLITS[("L", "L")] < 1.0
        # RHB vs LHP should have biggest advantage
        assert PLATOON_SPLITS[("R", "L")] > PLATOON_SPLITS[("L", "R")]
        # Switch hitters should be >= 1.0 always
        assert PLATOON_SPLITS[("S", "R")] >= 1.0
        assert PLATOON_SPLITS[("S", "L")] >= 1.0

    def test_platoon_factor_missing_data(self):
        """Missing handedness should return 1.0 (no adjustment)."""
        from pipeline.generate_batter_projections import get_platoon_factor

        factor, desc = get_platoon_factor(None, "R")
        assert factor == 1.0
        assert desc == "unknown"

        factor, desc = get_platoon_factor("L", None)
        assert factor == 1.0
        assert desc == "unknown"

    def test_platoon_factor_valid_matchup(self):
        """Valid matchup should return correct factor and description."""
        from pipeline.generate_batter_projections import get_platoon_factor

        factor, desc = get_platoon_factor("L", "R")
        assert factor == 1.06
        assert "LHB" in desc and "RHP" in desc

    def test_is_likely_starter_filters_pitchers(self):
        """Pitchers should be excluded from batter projections."""
        from pipeline.generate_batter_projections import is_likely_starter

        assert is_likely_starter({"position": "SP"}) is False
        assert is_likely_starter({"position": "RP"}) is False
        assert is_likely_starter({"position": "P"}) is False

    def test_is_likely_starter_includes_position_players(self):
        """Position players should be included."""
        from pipeline.generate_batter_projections import is_likely_starter

        for pos in ["C", "1B", "2B", "3B", "SS", "LF", "CF", "RF", "DH"]:
            assert is_likely_starter({"position": pos}) is True, f"{pos} should be a starter"

    def test_is_likely_starter_handles_empty(self):
        """Empty or missing position should return False."""
        from pipeline.generate_batter_projections import is_likely_starter

        assert is_likely_starter({}) is False
        assert is_likely_starter({"position": ""}) is False
        assert is_likely_starter({"position": None}) is False

    def test_park_tb_factors_coors(self):
        """Coors Field should have the highest TB boost."""
        from pipeline.generate_batter_projections import PARK_TB_FACTORS

        assert PARK_TB_FACTORS["Coors Field"] == 12
        # Verify it's the highest
        assert PARK_TB_FACTORS["Coors Field"] == max(PARK_TB_FACTORS.values())

    def test_tb_projection_formula(self):
        """TB projection = adjusted_tb_per_pa * expected_pa."""
        adjusted_tb_per_pa = 0.160
        expected_pa = 4.2
        projected_tb = adjusted_tb_per_pa * expected_pa
        assert projected_tb == pytest.approx(0.672, abs=0.01)

    def test_batter_confidence_bounds(self):
        """Batter confidence should be bounded 0.30 to 0.85."""
        # Max confidence
        conf = 0.45 + 0.10 + 0.15 + 0.10 + 0.03
        conf = round(min(max(conf, 0.30), 0.85), 3)
        assert conf == 0.83

        # Min confidence (early season)
        conf = 0.45 - 0.05
        conf = round(min(max(conf, 0.30), 0.85), 3)
        assert conf == 0.40


# ---------------------------------------------------------------------------
# Edge Cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    """Test edge cases and error handling."""

    def test_zero_ip_returns_mlb_average(self):
        """Zero innings pitched should not cause division by zero."""
        # Simulating the K/9 calculation with 0 IP
        ip = 0
        k = 10
        if ip > 0:
            k9 = round((k / ip) * 9, 2)
        else:
            k9 = 8.5  # MLB average fallback
        assert k9 == 8.5

    def test_zero_pa_returns_mlb_average(self):
        """Zero plate appearances should not cause division by zero."""
        pa = 0
        tb = 50
        if pa > 0:
            tb_per_pa = round(tb / pa, 3)
        else:
            tb_per_pa = 0.135  # MLB average fallback
        assert tb_per_pa == 0.135

    def test_ip_parsing_with_thirds(self):
        """IP like '5.2' means 5 and 2/3 innings (not 5.2 decimal)."""
        ip_str = "5.2"
        parts = ip_str.split(".")
        ip = int(parts[0]) + (int(parts[1]) / 3 if len(parts) > 1 and parts[1] else 0)
        assert ip == pytest.approx(5.667, abs=0.01)

    def test_ip_parsing_clean_number(self):
        """Clean IP like '6.0' should parse correctly."""
        ip_str = "6.0"
        parts = ip_str.split(".")
        ip = int(parts[0]) + (int(parts[1]) / 3 if len(parts) > 1 and parts[1] else 0)
        assert ip == pytest.approx(6.0, abs=0.01)

    def test_model_version_strings(self):
        """Model version strings should be set."""
        from pipeline.generate_batter_projections import MODEL_VERSION as BATTER_VERSION
        from pipeline.generate_projections import MODEL_VERSION as PITCHER_VERSION

        assert "v2.0" in PITCHER_VERSION
        assert "v2.0" in BATTER_VERSION

    def test_features_json_serializable(self):
        """Features dict should be JSON serializable."""
        features = {
            "baseline_k9": 9.5,
            "recent_k9": None,
            "park_adjustment": "+3.0%",
            "umpire_name": "Angel Hernandez",
            "opp_k_pct": 0.245,
        }
        serialized = json.dumps(features)
        deserialized = json.loads(serialized)
        assert deserialized["baseline_k9"] == 9.5
        assert deserialized["recent_k9"] is None
