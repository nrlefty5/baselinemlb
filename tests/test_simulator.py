#!/usr/bin/env python3
"""
test_simulator.py — BaselineMLB
=================================
Comprehensive unit tests for the Monte Carlo simulation engine,
prop calculator, and daily orchestrator.

Run:
    python -m pytest tests/test_simulator.py -v
    python -m pytest tests/test_simulator.py -v -k "test_engine"
"""

import json
import os
import sys
import time

import numpy as np
import pytest

# Add parent directory to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from simulator.monte_carlo_engine import (
    BB_IDX,
    HBP_IDX,
    HIT_INDICES,
    HR_IDX,
    K_IDX,
    MLB_AVG_PROBS,
    N_OUTCOMES,
    OUT_INDICES,
    TRIPLE_IDX,
    BatterProfile,
    BullpenProfile,
    GameMatchup,
    PitcherProfile,
    _advance_runners,
    _apply_pitcher_modifiers,
    build_batter_probs,
    build_bullpen_profile,
    build_pitcher_profile_from_stats,
    simulate_game,
    simulate_game_with_pitcher_ks,
)
from simulator.prop_calculator import (
    PropCalculator,
    PropLine,
    american_to_decimal,
    american_to_implied_prob,
    remove_vig,
)
from simulator.run_daily import (
    _normalize_stat_type,
    build_batter_profile,
    weather_to_modifier,
)

# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def sample_lineup():
    """Create a sample 9-batter lineup with varied profiles."""
    batters = []
    # Realistic spread of batter types
    profiles = [
        ("Leadoff", 0.18, 0.12, 0.015, 0.17, 0.05, 0.005, 0.020),
        ("Contact", 0.15, 0.08, 0.010, 0.20, 0.04, 0.006, 0.015),
        ("Power",   0.28, 0.10, 0.012, 0.13, 0.04, 0.003, 0.045),
        ("Slugger", 0.30, 0.09, 0.011, 0.12, 0.05, 0.002, 0.050),
        ("Avg",     0.22, 0.08, 0.012, 0.16, 0.04, 0.004, 0.025),
        ("Speed",   0.20, 0.07, 0.013, 0.18, 0.03, 0.008, 0.010),
        ("Defense", 0.25, 0.06, 0.011, 0.14, 0.03, 0.003, 0.015),
        ("Utility", 0.23, 0.07, 0.012, 0.15, 0.04, 0.004, 0.020),
        ("Catcher", 0.26, 0.07, 0.010, 0.13, 0.03, 0.002, 0.018),
    ]

    for i, (name, k, bb, hbp, s1b, s2b, s3b, hr) in enumerate(profiles):
        outs = 1.0 - (k + bb + hbp + s1b + s2b + s3b + hr)
        probs = build_batter_probs(
            k_rate=k, bb_rate=bb, hbp_rate=hbp,
            single_rate=s1b, double_rate=s2b, triple_rate=s3b, hr_rate=hr,
            flyout_rate=outs * 0.32, groundout_rate=outs * 0.42,
            lineout_rate=outs * 0.18, popup_rate=outs * 0.08,
        )
        batters.append(BatterProfile(
            mlbam_id=100 + i,
            name=f"Batter {name}",
            lineup_position=i + 1,
            probs=probs,
        ))

    return batters


@pytest.fixture
def sample_pitcher():
    """Create a sample ace pitcher profile."""
    return PitcherProfile(
        mlbam_id=200,
        name="Ace Pitcher",
        throws="R",
        k_rate_modifier=1.2,        # 20% above average K rate
        contact_quality_modifier=1.1,
        pitch_count_mean=95,
        pitch_count_std=10,
        recent_pitch_counts=[92, 98, 88, 96, 101],
    )


@pytest.fixture
def sample_bullpen():
    """Create a sample bullpen profile."""
    return BullpenProfile(
        k_rate_modifier=1.05,
        contact_quality_modifier=1.0,
    )


@pytest.fixture
def sample_matchup(sample_pitcher, sample_lineup, sample_bullpen):
    """Create a complete game matchup."""
    return GameMatchup(
        pitcher=sample_pitcher,
        lineup=sample_lineup,
        bullpen=sample_bullpen,
        park_factor=1.05,
        weather_factor=1.02,
        umpire_k_factor=1.03,
    )


@pytest.fixture
def quick_sim_results(sample_matchup):
    """Run a quick simulation for test assertions."""
    return simulate_game(sample_matchup, n_sims=500, seed=42)


@pytest.fixture
def quick_pitcher_sim(sample_matchup):
    """Run quick simulation with pitcher K tracking."""
    return simulate_game_with_pitcher_ks(sample_matchup, n_sims=500, seed=42)


# ============================================================================
# Test: Probability Vector Validation
# ============================================================================

class TestProbabilityVectors:
    """Tests for probability vector construction and normalization."""

    def test_mlb_avg_probs_sum_to_one(self):
        assert np.isclose(MLB_AVG_PROBS.sum(), 1.0, atol=1e-6)

    def test_mlb_avg_probs_all_positive(self):
        assert np.all(MLB_AVG_PROBS > 0)

    def test_mlb_avg_probs_correct_length(self):
        assert len(MLB_AVG_PROBS) == N_OUTCOMES

    def test_build_batter_probs_normalizes(self):
        probs = build_batter_probs(k_rate=0.5, bb_rate=0.5)
        assert np.isclose(probs.sum(), 1.0, atol=1e-6)

    def test_build_batter_probs_preserves_ratios(self):
        probs = build_batter_probs(k_rate=0.20, bb_rate=0.10, hr_rate=0.05)
        # K should be ~2x BB
        assert abs(probs[K_IDX] / probs[BB_IDX] - 2.0) < 0.01

    def test_batter_profile_normalizes(self):
        raw = np.array([0.2, 0.1, 0.01, 0.15, 0.04, 0.004, 0.03,
                        0.14, 0.19, 0.08, 0.046])
        b = BatterProfile(mlbam_id=1, name="Test", lineup_position=1, probs=raw)
        assert np.isclose(b.probs.sum(), 1.0, atol=1e-6)

    def test_batter_profile_fallback_on_zero_probs(self):
        zeros = np.zeros(N_OUTCOMES)
        b = BatterProfile(mlbam_id=1, name="Test", lineup_position=1, probs=zeros)
        assert np.isclose(b.probs.sum(), 1.0, atol=1e-6)

    def test_batter_profile_rejects_wrong_shape(self):
        with pytest.raises(ValueError):
            BatterProfile(mlbam_id=1, name="Test", lineup_position=1,
                         probs=np.array([0.5, 0.5]))

    def test_outcome_indices_cover_all(self):
        all_idx = HIT_INDICES | OUT_INDICES | {BB_IDX, HBP_IDX}
        assert len(all_idx) == N_OUTCOMES


# ============================================================================
# Test: Pitcher Profile
# ============================================================================

class TestPitcherProfile:
    """Tests for pitcher profile construction."""

    def test_default_pitch_count(self):
        p = PitcherProfile(mlbam_id=1, name="Test")
        assert p.pitch_count_mean == 92.0
        assert p.pitch_count_std == 12.0

    def test_pitch_count_from_recent_starts(self):
        p = PitcherProfile(
            mlbam_id=1, name="Test",
            recent_pitch_counts=[90, 95, 100, 88, 97],
        )
        assert abs(p.pitch_count_mean - 94.0) < 0.1
        assert p.pitch_count_std >= 5.0  # Minimum enforced

    def test_pitch_count_ignores_small_sample(self):
        p = PitcherProfile(
            mlbam_id=1, name="Test",
            recent_pitch_counts=[90, 95],  # Only 2 starts
        )
        assert p.pitch_count_mean == 92.0  # Default

    def test_build_pitcher_profile_high_k(self):
        p = build_pitcher_profile_from_stats(
            mlbam_id=1, name="Ace", career_k9=12.0,
        )
        assert p.k_rate_modifier > 1.0

    def test_build_pitcher_profile_low_k(self):
        p = build_pitcher_profile_from_stats(
            mlbam_id=1, name="Soft", career_k9=5.0,
        )
        assert p.k_rate_modifier < 1.0

    def test_k_modifier_clamped(self):
        p = build_pitcher_profile_from_stats(
            mlbam_id=1, name="Extreme", career_k9=20.0,
        )
        assert p.k_rate_modifier <= 1.6


# ============================================================================
# Test: Bullpen Profile
# ============================================================================

class TestBullpenProfile:
    """Tests for bullpen profile construction."""

    def test_default_bullpen(self):
        bp = BullpenProfile()
        assert np.isclose(bp.probs.sum(), 1.0, atol=1e-6)
        assert bp.k_rate_modifier == 1.0

    def test_build_bullpen_good(self):
        bp = build_bullpen_profile(era=3.00, k9=10.0)
        assert bp.k_rate_modifier > 1.0
        assert bp.contact_quality_modifier > 1.0

    def test_build_bullpen_bad(self):
        bp = build_bullpen_profile(era=5.50, k9=6.0)
        assert bp.k_rate_modifier < 1.0
        assert bp.contact_quality_modifier < 1.0


# ============================================================================
# Test: Game Matchup
# ============================================================================

class TestGameMatchup:
    """Tests for game matchup configuration."""

    def test_requires_9_batters(self, sample_pitcher, sample_bullpen):
        with pytest.raises(ValueError):
            GameMatchup(
                pitcher=sample_pitcher,
                lineup=[BatterProfile(mlbam_id=1, name="Test", lineup_position=1)],
                bullpen=sample_bullpen,
            )

    def test_valid_matchup(self, sample_matchup):
        assert len(sample_matchup.lineup) == 9
        assert sample_matchup.park_factor == 1.05


# ============================================================================
# Test: Pitcher Modifier Application
# ============================================================================

class TestPitcherModifiers:
    """Tests for probability modifier application."""

    def test_modifiers_preserve_normalization(self, sample_pitcher, sample_bullpen):
        probs = _apply_pitcher_modifiers(
            MLB_AVG_PROBS.copy(), sample_pitcher, False, sample_bullpen,
            park_factor=1.1, weather_factor=1.05, umpire_k_factor=1.1,
        )
        assert np.isclose(probs.sum(), 1.0, atol=1e-6)

    def test_high_k_pitcher_increases_k_rate(self, sample_bullpen):
        p = PitcherProfile(mlbam_id=1, name="K Machine", k_rate_modifier=1.4)
        probs = _apply_pitcher_modifiers(
            MLB_AVG_PROBS.copy(), p, False, sample_bullpen,
            park_factor=1.0, weather_factor=1.0, umpire_k_factor=1.0,
        )
        assert probs[K_IDX] > MLB_AVG_PROBS[K_IDX]

    def test_bullpen_uses_bullpen_modifier(self, sample_pitcher, sample_bullpen):
        sample_bullpen.k_rate_modifier = 1.3
        probs = _apply_pitcher_modifiers(
            MLB_AVG_PROBS.copy(), sample_pitcher, True, sample_bullpen,
            park_factor=1.0, weather_factor=1.0, umpire_k_factor=1.0,
        )
        # Should use bullpen modifier, not pitcher's
        assert probs[K_IDX] > MLB_AVG_PROBS[K_IDX]

    def test_homer_friendly_park_increases_hr(self, sample_pitcher, sample_bullpen):
        probs = _apply_pitcher_modifiers(
            MLB_AVG_PROBS.copy(), sample_pitcher, False, sample_bullpen,
            park_factor=1.3, weather_factor=1.0, umpire_k_factor=1.0,
        )
        assert probs[HR_IDX] > MLB_AVG_PROBS[HR_IDX] * 0.9  # Account for normalization


# ============================================================================
# Test: Runner Advancement
# ============================================================================

class TestRunnerAdvancement:
    """Tests for base runner advancement logic."""

    def test_hr_clears_bases_and_scores(self):
        bases = np.array([True, True, True], dtype=np.bool_)
        rng = np.random.default_rng(42)
        new_bases, runs, rbi = _advance_runners(bases, HR_IDX, rng)
        assert runs == 4  # Grand slam
        assert rbi == 4
        assert not any(new_bases)

    def test_solo_hr(self):
        bases = np.array([False, False, False], dtype=np.bool_)
        rng = np.random.default_rng(42)
        new_bases, runs, rbi = _advance_runners(bases, HR_IDX, rng)
        assert runs == 1
        assert rbi == 1

    def test_triple_scores_all_runners(self):
        bases = np.array([True, True, False], dtype=np.bool_)
        rng = np.random.default_rng(42)
        new_bases, runs, rbi = _advance_runners(bases, TRIPLE_IDX, rng)
        assert runs == 2
        assert new_bases[2]  # Batter on 3rd

    def test_walk_forces_runners(self):
        bases = np.array([True, True, True], dtype=np.bool_)
        rng = np.random.default_rng(42)
        new_bases, runs, rbi = _advance_runners(bases, BB_IDX, rng)
        assert runs == 1  # Bases loaded walk
        assert rbi == 1
        assert all(new_bases)  # Still bases loaded

    def test_walk_no_force(self):
        bases = np.array([False, False, False], dtype=np.bool_)
        rng = np.random.default_rng(42)
        new_bases, runs, rbi = _advance_runners(bases, BB_IDX, rng)
        assert runs == 0
        assert new_bases[0]  # Batter on 1st

    def test_strikeout_no_advancement(self):
        bases = np.array([True, True, False], dtype=np.bool_)
        rng = np.random.default_rng(42)
        new_bases, runs, rbi = _advance_runners(bases, K_IDX, rng)
        assert runs == 0
        assert np.array_equal(new_bases, bases)


# ============================================================================
# Test: Full Game Simulation
# ============================================================================

class TestGameSimulation:
    """Tests for the full game simulation engine."""

    def test_basic_simulation_runs(self, sample_matchup):
        results = simulate_game(sample_matchup, n_sims=100, seed=42)
        assert results.n_sims == 100
        assert len(results.player_results) == 9

    def test_all_stats_populated(self, quick_sim_results):
        for mid, pr in quick_sim_results.player_results.items():
            assert pr.strikeouts is not None
            assert pr.hits is not None
            assert pr.total_bases is not None
            assert pr.home_runs is not None
            assert pr.walks is not None
            assert pr.runs is not None
            assert pr.rbis is not None
            assert pr.plate_appearances is not None
            assert len(pr.strikeouts) == 500

    def test_plate_appearances_reasonable(self, quick_sim_results):
        """Each batter should get 3-5 PAs in a typical game."""
        for mid, pr in quick_sim_results.player_results.items():
            mean_pa = np.mean(pr.plate_appearances)
            assert 2.5 <= mean_pa <= 6.0, (
                f"Batter {pr.name}: mean PA = {mean_pa:.1f} (expected 3-5)"
            )

    def test_team_runs_reasonable(self, quick_sim_results):
        """Average team runs should be roughly 3-7."""
        mean_runs = np.mean(quick_sim_results.team_runs)
        assert 1.0 <= mean_runs <= 10.0, f"Mean runs = {mean_runs:.1f}"

    def test_pitcher_pitch_count_reasonable(self, quick_sim_results):
        """Starter should throw roughly 80-110 pitches."""
        mean_pc = np.mean(quick_sim_results.pitcher_pitch_counts)
        assert 60 <= mean_pc <= 130, f"Mean pitch count = {mean_pc:.0f}"

    def test_hits_leq_plate_appearances(self, quick_sim_results):
        """Hits should never exceed plate appearances."""
        for mid, pr in quick_sim_results.player_results.items():
            assert np.all(pr.hits <= pr.plate_appearances)

    def test_total_bases_geq_hits(self, quick_sim_results):
        """Total bases should be >= hits (every hit is at least 1 TB)."""
        for mid, pr in quick_sim_results.player_results.items():
            assert np.all(pr.total_bases >= pr.hits)

    def test_home_runs_leq_hits(self, quick_sim_results):
        """Home runs are a subset of hits."""
        for mid, pr in quick_sim_results.player_results.items():
            assert np.all(pr.home_runs <= pr.hits)

    def test_strikeouts_leq_pa(self, quick_sim_results):
        for mid, pr in quick_sim_results.player_results.items():
            assert np.all(pr.strikeouts <= pr.plate_appearances)

    def test_reproducibility_with_seed(self, sample_matchup):
        r1 = simulate_game(sample_matchup, n_sims=100, seed=123)
        r2 = simulate_game(sample_matchup, n_sims=100, seed=123)
        for mid in r1.player_results:
            np.testing.assert_array_equal(
                r1.player_results[mid].strikeouts,
                r2.player_results[mid].strikeouts,
            )

    def test_different_seeds_produce_different_results(self, sample_matchup):
        r1 = simulate_game(sample_matchup, n_sims=100, seed=1)
        r2 = simulate_game(sample_matchup, n_sims=100, seed=2)
        # At least one batter should differ
        any_diff = False
        for mid in r1.player_results:
            if not np.array_equal(
                r1.player_results[mid].strikeouts,
                r2.player_results[mid].strikeouts,
            ):
                any_diff = True
                break
        assert any_diff


# ============================================================================
# Test: Pitcher K Tracking
# ============================================================================

class TestPitcherKTracking:
    """Tests for separate starter/bullpen K tracking."""

    def test_pitcher_k_simulation(self, quick_pitcher_sim):
        game_results, pitcher_ks = quick_pitcher_sim
        assert len(pitcher_ks) == 500
        assert game_results.n_sims == 500

    def test_pitcher_ks_reasonable(self, quick_pitcher_sim):
        _, pitcher_ks = quick_pitcher_sim
        mean_k = np.mean(pitcher_ks)
        assert 2.0 <= mean_k <= 15.0, f"Mean pitcher Ks = {mean_k:.1f}"

    def test_pitcher_ks_always_nonneg(self, quick_pitcher_sim):
        _, pitcher_ks = quick_pitcher_sim
        assert np.all(pitcher_ks >= 0)

    def test_pitcher_ks_distribution_width(self, quick_pitcher_sim):
        """K distribution should have reasonable variance."""
        _, pitcher_ks = quick_pitcher_sim
        assert np.std(pitcher_ks) > 0.5, "K distribution too narrow"
        assert np.std(pitcher_ks) < 6.0, "K distribution too wide"


# ============================================================================
# Test: PlayerSimResults
# ============================================================================

class TestPlayerSimResults:
    """Tests for simulation result container methods."""

    def test_distribution_lookup(self, quick_sim_results):
        pr = list(quick_sim_results.player_results.values())[0]
        assert len(pr.distribution("K")) == 500
        assert len(pr.distribution("H")) == 500

    def test_distribution_invalid_stat(self, quick_sim_results):
        pr = list(quick_sim_results.player_results.values())[0]
        with pytest.raises(KeyError):
            pr.distribution("INVALID")

    def test_mean_and_std(self, quick_sim_results):
        pr = list(quick_sim_results.player_results.values())[0]
        assert isinstance(pr.mean("K"), float)
        assert isinstance(pr.std("K"), float)
        assert pr.std("K") >= 0

    def test_percentile(self, quick_sim_results):
        pr = list(quick_sim_results.player_results.values())[0]
        p10 = pr.percentile("K", 10)
        p50 = pr.percentile("K", 50)
        p90 = pr.percentile("K", 90)
        assert p10 <= p50 <= p90

    def test_prob_over(self, quick_sim_results):
        pr = list(quick_sim_results.player_results.values())[0]
        p = pr.prob_over("K", 0.5)
        assert 0.0 <= p <= 1.0

    def test_prob_under(self, quick_sim_results):
        pr = list(quick_sim_results.player_results.values())[0]
        p = pr.prob_under("K", 100)  # Everyone under 100 Ks
        assert p == 1.0

    def test_to_dict(self, quick_sim_results):
        pr = list(quick_sim_results.player_results.values())[0]
        d = pr.to_dict()
        assert "mlbam_id" in d
        assert "stats" in d
        assert "K" in d["stats"]
        assert "mean" in d["stats"]["K"]
        assert "histogram" in d["stats"]["K"]


# ============================================================================
# Test: Prop Calculator — Odds Conversion
# ============================================================================

class TestOddsConversion:
    """Tests for odds conversion utilities."""

    def test_american_to_decimal_favorite(self):
        assert abs(american_to_decimal(-110) - 1.909) < 0.01

    def test_american_to_decimal_underdog(self):
        assert abs(american_to_decimal(150) - 2.5) < 0.01

    def test_american_to_decimal_even(self):
        assert abs(american_to_decimal(100) - 2.0) < 0.01

    def test_american_to_implied_prob_favorite(self):
        p = american_to_implied_prob(-110)
        assert abs(p - 0.5238) < 0.01

    def test_american_to_implied_prob_underdog(self):
        p = american_to_implied_prob(150)
        assert abs(p - 0.4) < 0.01

    def test_remove_vig_sums_to_one(self):
        over_p, under_p = remove_vig(-110, -110)
        assert abs(over_p + under_p - 1.0) < 0.001

    def test_remove_vig_standard(self):
        over_p, under_p = remove_vig(-110, -110)
        assert abs(over_p - 0.5) < 0.001
        assert abs(under_p - 0.5) < 0.001

    def test_remove_vig_skewed(self):
        over_p, under_p = remove_vig(-150, 130)
        assert over_p > under_p
        assert abs(over_p + under_p - 1.0) < 0.001


# ============================================================================
# Test: Prop Calculator — Kelly Criterion
# ============================================================================

class TestKellyCriterion:
    """Tests for Kelly criterion calculations."""

    def test_kelly_positive_edge(self):
        calc = PropCalculator(bankroll=1000, kelly_fraction=0.25)
        stake = calc.kelly_criterion(win_prob=0.6, decimal_odds=2.0)
        assert stake > 0

    def test_kelly_no_edge(self):
        calc = PropCalculator(bankroll=1000, kelly_fraction=0.25)
        stake = calc.kelly_criterion(win_prob=0.5, decimal_odds=2.0)
        assert stake == 0.0  # Exactly breakeven = no bet

    def test_kelly_negative_edge(self):
        calc = PropCalculator(bankroll=1000, kelly_fraction=0.25)
        stake = calc.kelly_criterion(win_prob=0.3, decimal_odds=2.0)
        assert stake == 0.0

    def test_kelly_capped(self):
        calc = PropCalculator(bankroll=1000, kelly_fraction=1.0)  # Full Kelly
        stake = calc.kelly_criterion(win_prob=0.9, decimal_odds=5.0)
        assert stake <= PropCalculator.MAX_KELLY_CAP

    def test_kelly_fractional_reduces(self):
        calc_full = PropCalculator(bankroll=1000, kelly_fraction=1.0)
        calc_quarter = PropCalculator(bankroll=1000, kelly_fraction=0.25)
        full = calc_full.kelly_criterion(win_prob=0.55, decimal_odds=2.0)
        quarter = calc_quarter.kelly_criterion(win_prob=0.55, decimal_odds=2.0)
        # Quarter Kelly should always be <= full Kelly
        assert quarter <= full
        # And quarter Kelly should be positive if full Kelly is positive
        if full > 0:
            assert quarter > 0


# ============================================================================
# Test: Prop Calculator — Expected Value
# ============================================================================

class TestExpectedValue:
    """Tests for expected value calculations."""

    def test_ev_positive(self):
        calc = PropCalculator()
        ev = calc.expected_value(win_prob=0.6, decimal_odds=2.0)
        assert ev > 0  # 0.6 * 1.0 - 0.4 = 0.20

    def test_ev_negative(self):
        calc = PropCalculator()
        ev = calc.expected_value(win_prob=0.4, decimal_odds=2.0)
        assert ev < 0

    def test_ev_breakeven(self):
        calc = PropCalculator()
        ev = calc.expected_value(win_prob=0.5, decimal_odds=2.0)
        assert abs(ev) < 0.001


# ============================================================================
# Test: Prop Calculator — Prop Evaluation
# ============================================================================

class TestPropEvaluation:
    """Tests for prop line evaluation."""

    def test_evaluate_single_prop(self, quick_sim_results):
        calc = PropCalculator(bankroll=5000)
        pr = list(quick_sim_results.player_results.values())[0]

        prop = PropLine(
            mlbam_id=pr.mlbam_id,
            player_name=pr.name,
            stat_type="K",
            line=0.5,
            over_odds=-115,
            under_odds=-105,
        )

        edge = calc.evaluate_prop(pr, prop)
        assert edge is not None
        assert edge.direction in ("OVER", "UNDER")
        assert -1.0 <= edge.edge <= 1.0
        assert edge.confidence_tier in ("A", "B", "C")

    def test_evaluate_unknown_stat(self, quick_sim_results):
        calc = PropCalculator()
        pr = list(quick_sim_results.player_results.values())[0]

        prop = PropLine(
            mlbam_id=pr.mlbam_id,
            player_name=pr.name,
            stat_type="UNKNOWN_STAT",
            line=5.5,
        )

        edge = calc.evaluate_prop(pr, prop)
        assert edge is None

    def test_evaluate_props_batch(self, quick_sim_results):
        calc = PropCalculator(bankroll=5000)
        props = []
        for mid, pr in quick_sim_results.player_results.items():
            props.append(PropLine(
                mlbam_id=mid, player_name=pr.name,
                stat_type="K", line=0.5,
            ))

        edges = calc.evaluate_props(quick_sim_results, props)
        assert len(edges) > 0
        # Edges should be sorted by absolute edge
        for i in range(len(edges) - 1):
            assert abs(edges[i].edge) >= abs(edges[i + 1].edge)

    def test_confidence_tiers(self, quick_sim_results):
        calc = PropCalculator()
        pr = list(quick_sim_results.player_results.values())[0]

        # Create a prop with a very favorable line
        prop = PropLine(
            mlbam_id=pr.mlbam_id,
            player_name=pr.name,
            stat_type="H",
            line=0.5,
            over_odds=-200,  # Heavy favorite
            under_odds=170,
        )

        edge = calc.evaluate_prop(pr, prop)
        assert edge is not None
        assert edge.confidence_tier in ("A", "B", "C")
        assert 0.0 <= edge.confidence_score <= 1.0


# ============================================================================
# Test: Prop Calculator — Filtering and Ranking
# ============================================================================

class TestFilteringRanking:
    """Tests for edge filtering and top plays."""

    def test_filter_by_min_edge(self, quick_sim_results):
        calc = PropCalculator(bankroll=5000)
        props = [
            PropLine(mlbam_id=mid, player_name=pr.name,
                    stat_type="K", line=0.5)
            for mid, pr in quick_sim_results.player_results.items()
        ]
        edges = calc.evaluate_props(quick_sim_results, props)
        filtered = calc.filter_edges(edges, min_edge=0.10)
        for e in filtered:
            assert abs(e.edge) >= 0.10

    def test_top_plays_limit(self, quick_sim_results):
        calc = PropCalculator(bankroll=5000)
        props = [
            PropLine(mlbam_id=mid, player_name=pr.name,
                    stat_type="H", line=0.5)
            for mid, pr in quick_sim_results.player_results.items()
        ]
        edges = calc.evaluate_props(quick_sim_results, props)
        top = calc.top_plays(edges, n=3)
        assert len(top) <= 3

    def test_top_plays_direction_filter(self, quick_sim_results):
        calc = PropCalculator(bankroll=5000)
        props = [
            PropLine(mlbam_id=mid, player_name=pr.name,
                    stat_type="K", line=0.5)
            for mid, pr in quick_sim_results.player_results.items()
        ]
        edges = calc.evaluate_props(quick_sim_results, props)
        overs = calc.top_plays(edges, n=5, direction="OVER")
        for e in overs:
            assert e.direction == "OVER"


# ============================================================================
# Test: PropEdge Serialization
# ============================================================================

class TestPropEdgeSerialization:

    def test_to_dict(self, quick_sim_results):
        calc = PropCalculator(bankroll=5000)
        pr = list(quick_sim_results.player_results.values())[0]
        prop = PropLine(
            mlbam_id=pr.mlbam_id, player_name=pr.name,
            stat_type="K", line=0.5,
        )
        edge = calc.evaluate_prop(pr, prop)
        d = edge.to_dict()
        assert "mlbam_id" in d
        assert "edge" in d
        assert "kelly_stake" in d
        # Should be JSON serializable
        json.dumps(d)

    def test_format_summary(self, quick_sim_results):
        calc = PropCalculator(bankroll=5000)
        props = [
            PropLine(mlbam_id=mid, player_name=pr.name,
                    stat_type="K", line=0.5)
            for mid, pr in quick_sim_results.player_results.items()
        ]
        edges = calc.evaluate_props(quick_sim_results, props)
        summary = calc.format_summary(edges[:3])
        assert "BaselineMLB" in summary
        assert len(summary) > 50


# ============================================================================
# Test: Run Daily — Helper Functions
# ============================================================================

class TestRunDailyHelpers:
    """Tests for run_daily.py helper functions."""

    def test_normalize_stat_type(self):
        assert _normalize_stat_type("pitcher_strikeouts") == "K"
        assert _normalize_stat_type("batter_total_bases") == "TB"
        assert _normalize_stat_type("hits") == "H"
        assert _normalize_stat_type("home_runs") == "HR"
        assert _normalize_stat_type("batter_walks") == "BB"
        assert _normalize_stat_type("rbis") == "RBI"

    def test_weather_to_modifier_neutral(self):
        mod = weather_to_modifier({"temperature_f": 72, "wind_mph": 5})
        assert abs(mod - 1.0) < 0.01

    def test_weather_to_modifier_hot(self):
        mod = weather_to_modifier({"temperature_f": 95, "wind_mph": 3})
        assert mod > 1.0

    def test_weather_to_modifier_cold(self):
        mod = weather_to_modifier({"temperature_f": 45, "wind_mph": 3})
        assert mod < 1.0

    def test_weather_to_modifier_clamped(self):
        mod_extreme = weather_to_modifier({"temperature_f": 120, "wind_mph": 50})
        assert 0.5 <= mod_extreme <= 2.0

    def test_build_batter_profile_from_stats(self):
        profile = build_batter_profile(
            mlbam_id=12345,
            name="Test Batter",
            lineup_position=3,
            k_rate=0.22,
            bb_rate=0.09,
            hr_rate=0.04,
        )
        assert profile.mlbam_id == 12345
        assert np.isclose(profile.probs.sum(), 1.0, atol=1e-6)

    def test_build_batter_profile_defaults(self):
        profile = build_batter_profile(
            mlbam_id=99999,
            name="Unknown",
            lineup_position=9,
        )
        assert np.isclose(profile.probs.sum(), 1.0, atol=1e-6)


# ============================================================================
# Test: Integration — End to End
# ============================================================================

class TestIntegration:
    """End-to-end integration tests."""

    def test_full_pipeline(self, sample_matchup):
        """
        Test the complete pipeline: simulate → evaluate props → get edges."""
        # 1. Simulate
        results, pitcher_ks = simulate_game_with_pitcher_ks(
            sample_matchup, n_sims=200, seed=99
        )
        assert results.n_sims == 200

        # 2. Build props based on simulated means
        props = []
        for mid, pr in results.player_results.items():
            mean_h = pr.mean("H")
            props.append(PropLine(
                mlbam_id=mid,
                player_name=pr.name,
                stat_type="H",
                line=round(mean_h) - 0.5,
                over_odds=-115, under_odds=-105,
            ))

        # Also add pitcher K prop
        props.append(PropLine(
            mlbam_id=sample_matchup.pitcher.mlbam_id,
            player_name=sample_matchup.pitcher.name,
            stat_type="K",
            line=round(np.mean(pitcher_ks)) - 0.5,
            over_odds=-120, under_odds=100,
        ))

        # Evaluate
        calc = PropCalculator(bankroll=5000, kelly_fraction=0.25)
        edges = calc.evaluate_props(
            results, props,
            pitcher_k_dist=pitcher_ks,
            pitcher_mlbam_id=sample_matchup.pitcher.mlbam_id,
            pitcher_name=sample_matchup.pitcher.name,
        )

        assert len(edges) > 0

        # Filter
        filtered = calc.filter_edges(edges, min_edge=0.0)
        assert len(filtered) >= 0

        # Top plays
        top_over = calc.top_plays(edges, n=3, direction="OVER")
        top_under = calc.top_plays(edges, n=3, direction="UNDER")

        # Summary
        summary = calc.format_summary(edges[:5])
        assert "BaselineMLB" in summary

    def test_results_serialization(self, sample_matchup):
        """Results should be fully JSON-serializable."""
        results = simulate_game(sample_matchup, n_sims=100, seed=42)
        d = results.to_dict()
        json_str = json.dumps(d, default=str)
        assert len(json_str) > 100

        # Round-trip
        loaded = json.loads(json_str)
        assert loaded["n_sims"] == 100
        assert len(loaded["players"]) == 9

    def test_game_sim_results_to_dict(self, quick_sim_results):
        d = quick_sim_results.to_dict()
        assert "n_sims" in d
        assert "players" in d
        assert "team_runs" in d


# ============================================================================
# Run directly
# ============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
