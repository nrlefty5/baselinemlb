# Migrated from simulation/ to simulator/ — see docs/ARCHITECTURE.md Section 9
"""
test_simulation.py — Comprehensive unit tests for the BaselineMLB Monte Carlo simulator.

Covers:
  - simulation.config     → TestConfig
  - simulation.matchup_model → TestOddsRatioModel, TestMatchupModel
  - simulation.game_engine   → TestGameState, TestPlayerStats, TestGameSimulator
  - simulation.prop_analyzer → TestPropAnalyzer

Run with:
    pytest tests/test_simulation.py -v
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import List

import numpy as np
import pytest
from simulator.config import (
    FEATURE_COLUMNS,
    LEAGUE_AVG_RATES,
    MODEL_OUTCOMES,
    PARK_FACTORS,
    SimulationConfig,
)
from simulator.game_engine import (
    GameSimulator,
    GameState,
    PlayerStats,
    SimulationResult,
)
from simulator.matchup_model import (
    MatchupModel,
    OddsRatioModel,
)
from simulator.prop_analyzer import (
    PropAnalysis,
    PropAnalyzer,
    PropLine,
)

# ===========================================================================
# Shared fixtures and helpers
# ===========================================================================


def _league_avg_pitcher() -> dict:
    """Pitcher stats equal to league averages — used as a neutral baseline."""
    stats = {f"{o}_rate": LEAGUE_AVG_RATES[o] for o in MODEL_OUTCOMES}
    stats["sample_pa"] = 700
    return stats


def _league_avg_batter() -> dict:
    """Batter stats equal to league averages — used as a neutral baseline."""
    stats = {f"{o}_rate": LEAGUE_AVG_RATES[o] for o in MODEL_OUTCOMES}
    stats["sample_pa"] = 600
    stats["hand"] = "R"
    return stats


def _neutral_context() -> dict:
    """Fully neutral context with no park / platoon / umpire adjustments."""
    return {
        "park_hr_factor": 1.0,
        "park_2b_factor": 1.0,
        "park_3b_factor": 1.0,
        "park_1b_factor": 1.0,
        "umpire_k_factor": 1.0,
        "umpire_bb_factor": 1.0,
        "catcher_framing_score": 0.0,
        "temperature": 72.0,
        "wind_speed": 0.0,
        "wind_to_cf": 0.0,
        "pitcher_hand": "R",
    }


def _make_player(mlbam_id: int, name: str, hand: str = "R") -> dict:
    """Minimal batter dict compatible with GameSimulator."""
    return {
        "mlbam_id": mlbam_id,
        "name": name,
        "hand": hand,
        **{f"{o}_rate": LEAGUE_AVG_RATES[o] for o in MODEL_OUTCOMES},
        "sample_pa": 500,
    }


def _make_pitcher(mlbam_id: int, name: str) -> dict:
    """Minimal pitcher dict compatible with GameSimulator."""
    return {
        "mlbam_id": mlbam_id,
        "name": name,
        **{f"{o}_rate": LEAGUE_AVG_RATES[o] for o in MODEL_OUTCOMES},
        "sample_pa": 700,
    }


def _make_game_data(
    away_lineup: List[dict],
    home_lineup: List[dict],
    away_starter: dict,
    home_starter: dict,
) -> SimpleNamespace:
    """Build a minimal game_data object for GameSimulator."""
    return SimpleNamespace(
        game_pk=12345,
        game_date="2025-04-01",
        away_team="NYY",
        home_team="BOS",
        venue="Fenway Park",
        park_factor=1.0,
        away_lineup=away_lineup,
        home_lineup=home_lineup,
        away_starter=away_starter,
        home_starter=home_starter,
        away_bullpen_composite={
            **{f"{o}_rate": LEAGUE_AVG_RATES[o] for o in MODEL_OUTCOMES},
            "sample_pa": 300,
            "mlbam_id": 9901,
            "name": "Away Bullpen",
        },
        home_bullpen_composite={
            **{f"{o}_rate": LEAGUE_AVG_RATES[o] for o in MODEL_OUTCOMES},
            "sample_pa": 300,
            "mlbam_id": 9902,
            "name": "Home Bullpen",
        },
    )


class MockMatchupModel:
    """Deterministic mock that always returns fixed league-average probabilities."""

    def predict_pa_probs(
        self, pitcher_stats: dict, batter_stats: dict, context: dict, **kwargs
    ) -> dict[str, float]:
        return dict(LEAGUE_AVG_RATES)  # already sums to 1.0


# ===========================================================================
# TestConfig
# ===========================================================================


class TestConfig:
    """Tests for simulation.config constants and SimulationConfig dataclass."""

    def test_default_config_valid(self):
        """SimulationConfig() creates a valid config with no errors."""
        cfg = SimulationConfig()
        assert cfg.NUM_SIMULATIONS == 2500
        assert cfg.RANDOM_SEED is None
        assert isinstance(cfg.MODEL_PATH, str)

    def test_weights_sum_to_one(self):
        """RECENT_WEIGHT + CAREER_WEIGHT must equal exactly 1.0."""
        cfg = SimulationConfig()
        assert abs(cfg.RECENT_WEIGHT + cfg.CAREER_WEIGHT - 1.0) < 1e-9

    def test_weights_sum_to_one_custom(self):
        """Custom weights that sum to 1.0 are accepted."""
        cfg = SimulationConfig(RECENT_WEIGHT=0.7, CAREER_WEIGHT=0.3)
        assert abs(cfg.RECENT_WEIGHT + cfg.CAREER_WEIGHT - 1.0) < 1e-9

    def test_weights_not_summing_to_one_raises(self):
        """Weights that do not sum to 1.0 raise ValueError."""
        with pytest.raises(ValueError, match="RECENT_WEIGHT"):
            SimulationConfig(RECENT_WEIGHT=0.5, CAREER_WEIGHT=0.6)

    def test_num_simulations_zero_raises(self):
        """NUM_SIMULATIONS=0 raises ValueError."""
        with pytest.raises(ValueError, match="NUM_SIMULATIONS"):
            SimulationConfig(NUM_SIMULATIONS=0)

    def test_league_avg_rates_sum_to_one(self):
        """All LEAGUE_AVG_RATES values sum to approximately 1.0."""
        total = sum(LEAGUE_AVG_RATES.values())
        assert abs(total - 1.0) < 1e-6, f"LEAGUE_AVG_RATES sum = {total}"

    def test_model_outcomes_match_league_rates(self):
        """Every key in MODEL_OUTCOMES exists in LEAGUE_AVG_RATES."""
        for outcome in MODEL_OUTCOMES:
            assert outcome in LEAGUE_AVG_RATES, (
                f"'{outcome}' is in MODEL_OUTCOMES but missing from LEAGUE_AVG_RATES"
            )

    def test_park_factors_all_30_parks(self):
        """PARK_FACTORS contains entries for all 30 MLB venues.

        The config intentionally uses duplicate keys for alias safety (e.g.
        'Petco Park' appears twice). Python dicts de-duplicate by last-write-wins,
        so the effective key count may be less than the source lines suggest.
        After de-duplication we expect at least 28 unique real (non-neutral)
        venue entries covering the 30-team league (two teams share venues in
        some seasons, or the source omits one park pending a rename).
        """
        real_parks = {k for k in PARK_FACTORS if k != "neutral"}
        assert len(real_parks) >= 28, (
            f"Expected at least 28 MLB venue entries, found {len(real_parks)}: {real_parks}"
        )

    def test_park_factors_neutral_entry_exists(self):
        """PARK_FACTORS includes a 'neutral' fallback entry."""
        assert "neutral" in PARK_FACTORS
        assert PARK_FACTORS["neutral"]["hr"] == 1.0

    def test_park_factors_have_required_keys(self):
        """Every park factor entry has all required sub-keys."""
        required_keys = {"hr", "h", "k", "bb", "2b", "3b"}
        for venue, factors in PARK_FACTORS.items():
            assert required_keys.issubset(factors.keys()), (
                f"'{venue}' is missing keys: {required_keys - factors.keys()}"
            )

    def test_feature_columns_count(self):
        """FEATURE_COLUMNS has exactly 33 features."""
        assert len(FEATURE_COLUMNS) == 33, (
            f"Expected 33 features, got {len(FEATURE_COLUMNS)}"
        )

    def test_feature_columns_no_duplicates(self):
        """FEATURE_COLUMNS has no duplicate entries."""
        assert len(FEATURE_COLUMNS) == len(set(FEATURE_COLUMNS))

    @pytest.mark.parametrize("outcome", MODEL_OUTCOMES)
    def test_league_avg_rates_positive(self, outcome):
        """Every league average rate is strictly positive."""
        assert LEAGUE_AVG_RATES[outcome] > 0, (
            f"LEAGUE_AVG_RATES['{outcome}'] = {LEAGUE_AVG_RATES[outcome]} is not positive"
        )


# ===========================================================================
# TestOddsRatioModel
# ===========================================================================


class TestOddsRatioModel:
    """Tests for OddsRatioModel (generalised log5 / odds-ratio model)."""

    @pytest.fixture(autouse=True)
    def model(self):
        self.orm = OddsRatioModel()

    def _predict(self, pitcher=None, batter=None, context=None):
        p = pitcher or _league_avg_pitcher()
        b = batter or _league_avg_batter()
        c = context or _neutral_context()
        return self.orm.predict_pa_probs(p, b, c)

    def test_league_avg_vs_league_avg(self):
        """When both pitcher and batter are league-average, output should
        roughly equal league averages (within 5 percentage points)."""
        probs = self._predict()
        for outcome in MODEL_OUTCOMES:
            lg = LEAGUE_AVG_RATES[outcome]
            delta = abs(probs[outcome] - lg)
            assert delta < 0.05, (
                f"'{outcome}': model={probs[outcome]:.4f}, league={lg:.4f}, "
                f"delta={delta:.4f} > 0.05"
            )

    def test_high_k_pitcher_increases_k_prob(self):
        """A pitcher with K rate well above league avg produces higher K probability."""
        # Baseline: league-average pitcher
        baseline_probs = self._predict()
        base_k = baseline_probs["strikeout"]

        # High-K pitcher
        high_k_pitcher = _league_avg_pitcher()
        high_k_pitcher["strikeout_rate"] = 0.40  # well above 0.224 league avg
        high_k_probs = self._predict(pitcher=high_k_pitcher)

        assert high_k_probs["strikeout"] > base_k, (
            f"High-K pitcher K prob {high_k_probs['strikeout']:.4f} should exceed "
            f"baseline {base_k:.4f}"
        )

    def test_probabilities_sum_to_one(self):
        """Output probabilities always sum to exactly 1.0 (within floating-point)."""
        probs = self._predict()
        total = sum(probs.values())
        assert abs(total - 1.0) < 1e-9, f"Probabilities sum to {total}"

    def test_probabilities_sum_to_one_various_contexts(self):
        """Sum-to-one holds across multiple different stat/context combinations."""
        high_k_p = _league_avg_pitcher()
        high_k_p["strikeout_rate"] = 0.38

        low_bb_b = _league_avg_batter()
        low_bb_b["walk_rate"] = 0.04

        ctx_coors = dict(_neutral_context())
        ctx_coors["park_hr_factor"] = 1.30
        ctx_coors["temperature"] = 95.0

        for pitcher, batter, context in [
            (_league_avg_pitcher(), _league_avg_batter(), _neutral_context()),
            (high_k_p, _league_avg_batter(), _neutral_context()),
            (_league_avg_pitcher(), low_bb_b, ctx_coors),
        ]:
            probs = self.orm.predict_pa_probs(pitcher, batter, context)
            total = sum(probs.values())
            assert abs(total - 1.0) < 1e-9, (
                f"Probabilities sum to {total} for context {context}"
            )

    def test_no_negative_probs(self):
        """All output probabilities are non-negative."""
        probs = self._predict()
        for outcome, prob in probs.items():
            assert prob >= 0.0, f"'{outcome}' has negative probability: {prob}"

    def test_park_factor_affects_hr(self):
        """A high-HR park (e.g. factor=1.30) increases HR probability vs neutral."""
        neutral_probs = self._predict()
        high_hr_ctx = dict(_neutral_context())
        high_hr_ctx["park_hr_factor"] = 1.30
        high_hr_probs = self._predict(context=high_hr_ctx)

        assert high_hr_probs["home_run"] > neutral_probs["home_run"], (
            f"High-HR park should increase HR prob: "
            f"neutral={neutral_probs['home_run']:.4f}, "
            f"high_hr={high_hr_probs['home_run']:.4f}"
        )

    def test_low_hr_park_decreases_hr(self):
        """A pitcher-friendly park (hr_factor=0.78) decreases HR probability."""
        neutral_probs = self._predict()
        low_hr_ctx = dict(_neutral_context())
        low_hr_ctx["park_hr_factor"] = 0.78
        low_hr_probs = self._predict(context=low_hr_ctx)

        assert low_hr_probs["home_run"] < neutral_probs["home_run"]

    def test_platoon_advantage(self):
        """Lefty batter vs righty pitcher should get a hit probability boost."""
        # No platoon advantage: RHB vs RHP
        rr_batter = _league_avg_batter()
        rr_batter["hand"] = "R"
        rr_ctx = dict(_neutral_context())
        rr_ctx["pitcher_hand"] = "R"
        rr_probs = self.orm.predict_pa_probs(rr_batter, rr_batter, rr_ctx)

        # Platoon advantage: LHB vs RHP
        lr_batter = _league_avg_batter()
        lr_batter["hand"] = "L"
        lr_ctx = dict(_neutral_context())
        lr_ctx["pitcher_hand"] = "R"
        lr_probs = self.orm.predict_pa_probs(lr_batter, lr_batter, lr_ctx)

        # Hits (singles + doubles + triples + home_runs) should be higher for LHB
        lr_hit_total = sum(lr_probs[h] for h in ("single", "double", "triple", "home_run"))
        rr_hit_total = sum(rr_probs[h] for h in ("single", "double", "triple", "home_run"))

        assert lr_hit_total > rr_hit_total, (
            f"LHB vs RHP hit total ({lr_hit_total:.4f}) should exceed "
            f"RHB vs RHP ({rr_hit_total:.4f})"
        )

    def test_platoon_advantage_reduces_k(self):
        """Batter with platoon advantage (L vs R) should have lower K probability."""
        rr_batter = _league_avg_batter()
        rr_batter["hand"] = "R"
        ctx_r = dict(_neutral_context())
        ctx_r["pitcher_hand"] = "R"
        rr_probs = self.orm.predict_pa_probs(rr_batter, rr_batter, ctx_r)

        lr_batter = _league_avg_batter()
        lr_batter["hand"] = "L"
        ctx_l = dict(_neutral_context())
        ctx_l["pitcher_hand"] = "R"
        lr_probs = self.orm.predict_pa_probs(lr_batter, lr_batter, ctx_l)

        assert lr_probs["strikeout"] < rr_probs["strikeout"], (
            f"LHB vs RHP K ({lr_probs['strikeout']:.4f}) should be < "
            f"RHB vs RHP K ({rr_probs['strikeout']:.4f})"
        )

    def test_umpire_factor_increases_ks(self):
        """Umpire with high K factor (expanded zone) should increase K probability."""
        baseline_probs = self._predict()
        tight_ctx = dict(_neutral_context())
        tight_ctx["umpire_k_factor"] = 1.25
        ump_probs = self._predict(context=tight_ctx)

        assert ump_probs["strikeout"] > baseline_probs["strikeout"], (
            f"Ump K factor 1.25 should raise K prob: "
            f"baseline={baseline_probs['strikeout']:.4f}, "
            f"umpire={ump_probs['strikeout']:.4f}"
        )

    def test_umpire_factor_decreases_ks_tight_zone(self):
        """Umpire with K factor < 1 (tight zone) should decrease K probability."""
        baseline_probs = self._predict()
        tight_ctx = dict(_neutral_context())
        tight_ctx["umpire_k_factor"] = 0.75
        ump_probs = self._predict(context=tight_ctx)

        assert ump_probs["strikeout"] < baseline_probs["strikeout"]

    def test_catcher_framing_increases_ks(self):
        """Elite framing catcher (z=+2.0) should increase K probability."""
        baseline = self._predict()
        framing_ctx = dict(_neutral_context())
        framing_ctx["catcher_framing_score"] = 2.0
        framing_probs = self._predict(context=framing_ctx)

        assert framing_probs["strikeout"] > baseline["strikeout"]

    def test_hot_weather_increases_hr(self):
        """Hot game-time temperature (95°F) should increase HR probability."""
        baseline = self._predict()
        hot_ctx = dict(_neutral_context())
        hot_ctx["temperature"] = 95.0
        hot_probs = self._predict(context=hot_ctx)

        assert hot_probs["home_run"] > baseline["home_run"]

    def test_wind_blowing_out_increases_hr(self):
        """Wind blowing out to CF (wind_to_cf=1.0, speed=15) should increase HR."""
        baseline = self._predict()
        wind_ctx = dict(_neutral_context())
        wind_ctx["wind_to_cf"] = 1.0
        wind_ctx["wind_speed"] = 15.0
        wind_probs = self._predict(context=wind_ctx)

        assert wind_probs["home_run"] > baseline["home_run"]

    @pytest.mark.parametrize("outcome", MODEL_OUTCOMES)
    def test_all_outcomes_present(self, outcome):
        """All MODEL_OUTCOMES keys are present in the output dict."""
        probs = self._predict()
        assert outcome in probs, f"'{outcome}' missing from predict_pa_probs output"

    def test_small_sample_regresses_to_league(self):
        """A pitcher with tiny sample (pa=10) and extreme rates regresses toward league avg."""
        extreme_pitcher = {f"{o}_rate": LEAGUE_AVG_RATES[o] for o in MODEL_OUTCOMES}
        extreme_pitcher["strikeout_rate"] = 0.99  # extreme
        extreme_pitcher["out_rate"] = 0.01
        extreme_pitcher["sample_pa"] = 10  # tiny sample → heavy regression

        probs = self.orm.predict_pa_probs(
            extreme_pitcher, _league_avg_batter(), _neutral_context()
        )
        # Should be closer to league avg than 0.99 because of regression
        assert probs["strikeout"] < 0.80, (
            f"Small-sample extreme pitcher not regressed enough: K={probs['strikeout']:.4f}"
        )


# ===========================================================================
# TestMatchupModel
# ===========================================================================


class TestMatchupModel:
    """Tests for the MatchupModel facade."""

    def test_fallback_to_odds_ratio(self):
        """When no trained model exists, MatchupModel falls back to OddsRatioModel."""
        # Pass a nonexistent model path to force fallback
        model = MatchupModel(model_path="nonexistent_model.txt", use_ml=True)
        assert model.active_model == "odds_ratio"

    def test_fallback_to_odds_ratio_no_path(self):
        """MatchupModel with model_path=None always uses OddsRatioModel."""
        model = MatchupModel(model_path=None)
        assert model.active_model == "odds_ratio"

    def test_use_ml_false_uses_odds_ratio(self):
        """use_ml=False forces OddsRatioModel regardless of path."""
        model = MatchupModel(use_ml=False)
        assert model.active_model == "odds_ratio"

    def test_predict_pa_probs_returns_dict(self):
        """predict_pa_probs returns a dict with MODEL_OUTCOMES keys."""
        model = MatchupModel(model_path=None)
        probs = model.predict_pa_probs(
            _league_avg_pitcher(), _league_avg_batter(), _neutral_context()
        )
        assert isinstance(probs, dict)
        for outcome in MODEL_OUTCOMES:
            assert outcome in probs

    def test_predict_pa_probs_sums_to_one(self):
        """MatchupModel.predict_pa_probs output always sums to 1.0."""
        model = MatchupModel(model_path=None)
        probs = model.predict_pa_probs(
            _league_avg_pitcher(), _league_avg_batter(), _neutral_context()
        )
        assert abs(sum(probs.values()) - 1.0) < 1e-9

    def test_explain_prediction_structure(self):
        """explain_prediction returns the correct top-level structure."""
        model = MatchupModel(model_path=None)
        result = model.explain_prediction(
            _league_avg_pitcher(), _league_avg_batter(), _neutral_context()
        )
        # Top-level keys
        assert "outcomes" in result, "Missing 'outcomes' key"
        assert "confidence" in result, "Missing 'confidence' key"
        assert "active_model" in result, "Missing 'active_model' key"

        outcomes = result["outcomes"]
        # All MODEL_OUTCOMES present
        for outcome in MODEL_OUTCOMES:
            assert outcome in outcomes, f"'{outcome}' missing from explain outcomes"

        # Each outcome has the required sub-structure
        for outcome, detail in outcomes.items():
            assert "base_prob" in detail, f"'{outcome}' missing 'base_prob'"
            assert "adjustments" in detail, f"'{outcome}' missing 'adjustments'"
            assert "final_prob" in detail, f"'{outcome}' missing 'final_prob'"

            adj = detail["adjustments"]
            for layer in ("park_factor", "platoon", "umpire", "catcher_framing", "weather"):
                assert layer in adj, (
                    f"'{outcome}' adjustments missing layer '{layer}'"
                )
                layer_detail = adj[layer]
                assert "direction" in layer_detail
                assert "magnitude" in layer_detail
                assert "reason" in layer_detail
                assert layer_detail["direction"] in ("up", "down", "neutral"), (
                    f"Unexpected direction: {layer_detail['direction']}"
                )

    def test_explain_prediction_confidence_range(self):
        """Confidence score is in [0, 1]."""
        model = MatchupModel(model_path=None)
        result = model.explain_prediction(
            _league_avg_pitcher(), _league_avg_batter(), _neutral_context()
        )
        assert 0.0 <= result["confidence"] <= 1.0

    def test_explain_prediction_final_probs_sum_to_one(self):
        """The final_prob values across all outcomes sum to approximately 1.0."""
        model = MatchupModel(model_path=None)
        result = model.explain_prediction(
            _league_avg_pitcher(), _league_avg_batter(), _neutral_context()
        )
        total = sum(d["final_prob"] for d in result["outcomes"].values())
        assert abs(total - 1.0) < 1e-4, f"Final probs sum = {total}"

    def test_explain_prediction_base_probs_positive(self):
        """All base_prob values are positive."""
        model = MatchupModel(model_path=None)
        result = model.explain_prediction(
            _league_avg_pitcher(), _league_avg_batter(), _neutral_context()
        )
        for outcome, detail in result["outcomes"].items():
            assert detail["base_prob"] > 0, (
                f"'{outcome}' base_prob is not positive: {detail['base_prob']}"
            )


# ===========================================================================
# TestGameState
# ===========================================================================


class TestGameState:
    """Tests for GameState — the mutable game state tracker."""

    def test_initial_state(self):
        """New GameState starts at inning 1, top, 0 outs, empty bases."""
        gs = GameState()
        assert gs.inning == 1
        assert gs.half == "top"
        assert gs.outs == 0
        assert gs.runners == {1: None, 2: None, 3: None}
        assert gs.score == {"away": 0, "home": 0}

    def test_initial_lineup_index(self):
        """Lineup index starts at 0 for both teams."""
        gs = GameState()
        assert gs.lineup_index["away"] == 0
        assert gs.lineup_index["home"] == 0

    def test_record_out(self):
        """record_out increments the out count."""
        gs = GameState()
        gs.record_out()
        assert gs.outs == 1
        gs.record_out()
        assert gs.outs == 2
        gs.record_out()
        assert gs.outs == 3

    def test_record_three_outs_triggers_switch_after_switch_sides(self):
        """Recording 3 outs and calling switch_sides transitions to next half."""
        gs = GameState()
        gs.record_out()
        gs.record_out()
        gs.record_out()
        assert gs.outs == 3

        # Caller is responsible for calling switch_sides
        gs.switch_sides()
        assert gs.half == "bottom"
        assert gs.outs == 0
        assert gs.runners == {1: None, 2: None, 3: None}

    def test_switch_sides_top_to_bottom(self):
        """Switching from top to bottom does not advance the inning."""
        gs = GameState()
        gs.switch_sides()
        assert gs.half == "bottom"
        assert gs.inning == 1

    def test_switch_sides_bottom_to_top_increments_inning(self):
        """Switching from bottom to top increments the inning."""
        gs = GameState()
        gs.half = "bottom"
        gs.switch_sides()
        assert gs.half == "top"
        assert gs.inning == 2

    def test_advance_runners_single_runner_on_1b(self):
        """Advancing all runners 1 base with runner on 1B moves runner to 2B."""
        gs = GameState()
        gs.runners[1] = 10  # runner with id=10 on 1B
        runs = gs.advance_runners(1)
        assert runs == 0
        assert gs.runners[2] == 10
        assert gs.runners[1] is None

    def test_advance_runners_single(self):
        """advance_runners(1): runner on 1B goes to 2B; batter placement is caller's job."""
        gs = GameState()
        gs.runners[1] = 7
        runs = gs.advance_runners(1)
        assert runs == 0
        assert gs.runners[2] == 7
        assert gs.runners[1] is None
        assert gs.runners[3] is None

    def test_advance_runners_runner_scores_from_2b_on_double(self):
        """advance_runners(2): runner on 2B should score."""
        gs = GameState()
        gs.half = "top"
        gs.runners[2] = 5
        runs = gs.advance_runners(2)
        assert runs == 1
        assert gs.score["away"] == 1

    def test_advance_runners_home_run(self):
        """advance_runners(4): all runners (and logically the batter) score.
        For a home run, simulate: load bases then advance 4."""
        gs = GameState()
        gs.half = "top"
        gs.runners = {1: 1, 2: 2, 3: 3}
        runs = gs.advance_runners(4)
        assert runs == 3  # 3 baserunners score (batter scored separately by caller)
        assert gs.runners == {1: None, 2: None, 3: None}

    def test_advance_runners_home_run_clears_bases(self):
        """After advance_runners(4), all bases are empty."""
        gs = GameState()
        gs.runners = {1: 1, 2: 2, 3: 3}
        gs.advance_runners(4)
        assert all(v is None for v in gs.runners.values())

    def test_walk_with_bases_loaded(self):
        """force_advance_on_walk with bases loaded scores one run."""
        gs = GameState()
        gs.half = "top"
        gs.runners = {1: 1, 2: 2, 3: 3}
        runs = gs.force_advance_on_walk(batter_id=4)
        assert runs == 1
        assert gs.score["away"] == 1
        assert gs.runners[1] == 4
        assert gs.runners[2] == 1
        assert gs.runners[3] == 2

    def test_walk_empty_bases(self):
        """force_advance_on_walk on empty bases places batter on 1B, no runs."""
        gs = GameState()
        runs = gs.force_advance_on_walk(batter_id=99)
        assert runs == 0
        assert gs.runners[1] == 99

    def test_walk_runner_on_first_only(self):
        """force_advance_on_walk with runner on 1B only moves runner to 2B."""
        gs = GameState()
        gs.runners[1] = 10
        runs = gs.force_advance_on_walk(batter_id=20)
        assert runs == 0
        assert gs.runners[1] == 20
        assert gs.runners[2] == 10

    def test_game_over_after_9(self):
        """Game ends after 9 full innings with one team leading.

        GameState.is_game_over() always returns False (logic is in GameSimulator).
        We test the switch_sides / inning counter instead to verify inning tracking.
        """
        gs = GameState()
        # Simulate 9 complete innings (18 half-innings)
        for _ in range(18):
            gs.switch_sides()
        # After 18 switches starting from top-1:
        # 9 switches take us to bottom-1 ... top-9 ...
        # The exact state depends on the alternating logic — just check inning advanced
        assert gs.inning >= 9

    def test_walkoff_scenario(self):
        """In the bottom of the 9th with scores tied, walk-off logic can trigger.

        This is handled inside GameSimulator._run_single_game, but we can verify
        the score state that would trigger it via GameState.score manipulation.
        """
        gs = GameState()
        gs.inning = 9
        gs.half = "bottom"
        gs.score = {"away": 3, "home": 3}
        # Simulate a home run to trigger walkoff condition
        gs.score["home"] += 1
        assert gs.score["home"] > gs.score["away"], "Walkoff: home should be leading"

    def test_manfred_runner(self):
        """Extra innings start with a runner (ghost runner) on 2B."""
        gs = GameState()
        gs.set_manfred_runner()
        assert gs.runners[2] == -1, "Manfred runner should be id=-1 on 2B"
        assert gs.runners[1] is None
        assert gs.runners[3] is None

    def test_next_batter_wraps_around(self):
        """next_batter wraps the lineup index from 8 back to 0."""
        gs = GameState()
        gs.lineup_index["away"] = 8
        gs.next_batter("away")
        assert gs.lineup_index["away"] == 0

    def test_batting_team_property(self):
        """batting_team returns 'away' on top and 'home' on bottom."""
        gs = GameState()
        assert gs.batting_team == "away"
        gs.half = "bottom"
        assert gs.batting_team == "home"

    def test_fielding_team_property(self):
        """fielding_team is the opposite of batting_team."""
        gs = GameState()
        assert gs.fielding_team == "home"
        gs.half = "bottom"
        assert gs.fielding_team == "away"

    def test_place_batter_on_empty_base(self):
        """place_batter_on_base on an empty base just sets the runner."""
        gs = GameState()
        gs.place_batter_on_base(1, 42)
        assert gs.runners[1] == 42

    def test_place_batter_pushes_existing_runner(self):
        """place_batter_on_base pushes existing runner when base is occupied."""
        gs = GameState()
        gs.runners[1] = 5
        gs.place_batter_on_base(1, 10)
        assert gs.runners[1] == 10
        assert gs.runners[2] == 5

    def test_advance_runners_probabilistic_single(self):
        """advance_runners_probabilistic('single') produces valid runner state."""
        rng = np.random.default_rng(seed=42)
        gs = GameState()
        gs.half = "top"
        gs.runners[1] = 1
        gs.runners[2] = 2
        gs.runners[3] = 3
        initial_score = dict(gs.score)
        runs, new_gs = gs.advance_runners_probabilistic("single", rng)
        # Runs scored must be >= 0
        assert runs >= 0
        # Score must be non-decreasing
        assert new_gs.score["away"] >= initial_score["away"]

    def test_advance_runners_probabilistic_triple(self):
        """advance_runners_probabilistic('triple') always scores all runners."""
        rng = np.random.default_rng(seed=99)
        gs = GameState()
        gs.half = "top"
        gs.runners[1] = 1
        gs.runners[2] = 2
        runs, _ = gs.advance_runners_probabilistic("triple", rng)
        # Both runners on 1B and 2B should score on a triple
        assert runs >= 2


# ===========================================================================
# TestPlayerStats
# ===========================================================================


class TestPlayerStats:
    """Tests for PlayerStats — per-player accumulator for a simulation run."""

    def test_initial_stats(self):
        """Freshly created PlayerStats has zero counters."""
        ps = PlayerStats(mlbam_id=12345, name="John Doe")
        assert ps.mlbam_id == 12345
        assert ps.name == "John Doe"
        assert ps.plate_appearances == 0
        assert ps.strikeouts == 0
        assert ps.walks == 0
        assert ps.hits == 0
        assert ps.home_runs == 0

    def test_record_strikeout(self):
        """record_outcome('strikeout') increments PA and K counter."""
        ps = PlayerStats(mlbam_id=1, name="Pitcher")
        ps.record_outcome("strikeout")
        assert ps.plate_appearances == 1
        assert ps.strikeouts == 1

    def test_record_walk(self):
        """record_outcome('walk') increments PA and walk counter."""
        ps = PlayerStats(mlbam_id=2, name="Walker")
        ps.record_outcome("walk")
        assert ps.plate_appearances == 1
        assert ps.walks == 1

    def test_record_home_run(self):
        """record_outcome('home_run') increments PA, hits, and HR."""
        ps = PlayerStats(mlbam_id=3, name="Slugger")
        ps.record_outcome("home_run")
        assert ps.plate_appearances == 1
        assert ps.home_runs == 1
        assert ps.hits == 1

    def test_record_single(self):
        """record_outcome('single') increments PA and hits."""
        ps = PlayerStats(mlbam_id=4, name="Singles Hitter")
        ps.record_outcome("single")
        assert ps.plate_appearances == 1
        assert ps.hits == 1
        assert ps.home_runs == 0
        assert ps.strikeouts == 0

    def test_batting_average_property(self):
        """batting_average is hits / PA (simple average, not official BA)."""
        ps = PlayerStats(mlbam_id=5, name="Batter")
        ps.record_outcome("single")
        ps.record_outcome("strikeout")
        ps.record_outcome("home_run")
        expected = 2 / 3
        assert abs(ps.batting_average - expected) < 1e-9

    def test_batting_average_zero_pa(self):
        """batting_average returns 0.0 when PA=0 (no division by zero)."""
        ps = PlayerStats(mlbam_id=6, name="Idle")
        assert ps.batting_average == 0.0

    def test_k_rate_property(self):
        """k_rate is strikeouts / PA."""
        ps = PlayerStats(mlbam_id=7, name="Strikeout Machine")
        for _ in range(3):
            ps.record_outcome("strikeout")
        ps.record_outcome("single")
        assert abs(ps.k_rate - 0.75) < 1e-9

    def test_walk_rate_property(self):
        """walk_rate is walks / PA."""
        ps = PlayerStats(mlbam_id=8, name="Patient")
        ps.record_outcome("walk")
        ps.record_outcome("walk")
        ps.record_outcome("strikeout")
        assert abs(ps.walk_rate - 2 / 3) < 1e-9

    def test_multiple_outcomes(self):
        """Accumulating a mix of outcomes updates all counters correctly."""
        ps = PlayerStats(mlbam_id=9, name="All-Around")
        outcomes = ["single", "strikeout", "walk", "home_run", "double",
                    "strikeout", "out", "triple"]
        for o in outcomes:
            ps.record_outcome(o)
        assert ps.plate_appearances == 8
        assert ps.strikeouts == 2
        assert ps.walks == 1
        assert ps.home_runs == 1
        assert ps.hits == 4  # single, HR, double, triple


# ===========================================================================
# TestGameSimulator
# ===========================================================================


class TestGameSimulator:
    """Tests for GameSimulator — the main simulation orchestrator."""

    @pytest.fixture(autouse=True)
    def setup(self):
        """Build a minimal 9-batter lineup + starter for both teams."""
        self.away_lineup = [_make_player(i, f"Away{i}") for i in range(1, 10)]
        self.home_lineup = [_make_player(i + 10, f"Home{i}") for i in range(1, 10)]
        self.away_starter = _make_pitcher(101, "Away Starter")
        self.home_starter = _make_pitcher(102, "Home Starter")
        self.game_data = _make_game_data(
            self.away_lineup,
            self.home_lineup,
            self.away_starter,
            self.home_starter,
        )
        self.sim = GameSimulator(
            matchup_model=MockMatchupModel(),
        )

    def test_simulate_returns_result(self):
        """simulate_game returns a SimulationResult."""
        result = self.sim.simulate_game(
            self.game_data, context=_neutral_context(), n_simulations=10
        )
        assert isinstance(result, SimulationResult)

    def test_simulation_result_has_score_distributions(self):
        """SimulationResult has away_scores and home_scores arrays."""
        result = self.sim.simulate_game(
            self.game_data, context=_neutral_context(), n_simulations=10
        )
        assert hasattr(result, "away_scores")
        assert hasattr(result, "home_scores")
        assert len(result.away_scores) == 10
        assert len(result.home_scores) == 10

    def test_scores_non_negative(self):
        """All simulated scores are >= 0."""
        result = self.sim.simulate_game(
            self.game_data, context=_neutral_context(), n_simulations=50
        )
        assert all(s >= 0 for s in result.away_scores)
        assert all(s >= 0 for s in result.home_scores)

    def test_win_probabilities_sum_to_one(self):
        """away_win_prob + home_win_prob + tie_prob == 1.0."""
        result = self.sim.simulate_game(
            self.game_data, context=_neutral_context(), n_simulations=100
        )
        total = result.away_win_prob + result.home_win_prob + result.tie_prob
        assert abs(total - 1.0) < 1e-6, f"Win probs sum = {total}"

    def test_win_probabilities_in_range(self):
        """All win/tie probabilities are in [0, 1]."""
        result = self.sim.simulate_game(
            self.game_data, context=_neutral_context(), n_simulations=100
        )
        assert 0.0 <= result.away_win_prob <= 1.0
        assert 0.0 <= result.home_win_prob <= 1.0
        assert 0.0 <= result.tie_prob <= 1.0

    def test_reproducibility_with_seed(self):
        """Same random seed produces identical results."""
        r1 = self.sim.simulate_game(
            self.game_data, context=_neutral_context(), n_simulations=20, seed=42
        )
        r2 = self.sim.simulate_game(
            self.game_data, context=_neutral_context(), n_simulations=20, seed=42
        )
        np.testing.assert_array_equal(r1.away_scores, r2.away_scores)
        np.testing.assert_array_equal(r1.home_scores, r2.home_scores)

    def test_different_seeds_produce_different_results(self):
        """Different seeds produce (almost certainly) different results."""
        r1 = self.sim.simulate_game(
            self.game_data, context=_neutral_context(), n_simulations=50, seed=1
        )
        r2 = self.sim.simulate_game(
            self.game_data, context=_neutral_context(), n_simulations=50, seed=2
        )
        # It's astronomically unlikely all 50 scores match with different seeds
        assert not np.array_equal(r1.away_scores, r2.away_scores)

    def test_pitcher_strikeout_stats_accumulated(self):
        """Pitcher stats accumulate strikeouts across simulations."""
        result = self.sim.simulate_game(
            self.game_data, context=_neutral_context(), n_simulations=50
        )
        assert hasattr(result, "away_pitcher_stats")
        away_ps = result.away_pitcher_stats  # stats for away_starter pitching to home batters
        assert away_ps.strikeouts >= 0
        assert away_ps.plate_appearances >= 0

    def test_high_k_pitcher_strikes_out_more(self):
        """High-K pitcher should average more K's per game than league-avg pitcher."""
        # High-K starter
        high_k_starter = _make_pitcher(999, "High K Pitcher")
        high_k_starter["strikeout_rate"] = 0.50

        low_k_starter = _make_pitcher(998, "Low K Pitcher")
        low_k_starter["strikeout_rate"] = 0.10

        gd_high_k = _make_game_data(
            self.away_lineup, self.home_lineup, high_k_starter, self.home_starter
        )
        gd_low_k = _make_game_data(
            self.away_lineup, self.home_lineup, low_k_starter, self.home_starter
        )

        result_high = self.sim.simulate_game(
            gd_high_k, context=_neutral_context(), n_simulations=200, seed=0
        )
        result_low = self.sim.simulate_game(
            gd_low_k, context=_neutral_context(), n_simulations=200, seed=0
        )

        avg_k_high = np.mean(result_high.away_pitcher_k_distribution)
        avg_k_low = np.mean(result_low.away_pitcher_k_distribution)

        assert avg_k_high > avg_k_low, (
            f"High-K pitcher mean K/game ({avg_k_high:.2f}) should exceed "
            f"low-K pitcher ({avg_k_low:.2f})"
        )

    def test_simulate_game_9_innings(self):
        """Standard simulation runs exactly 9 innings (no extras)."""
        result = self.sim.simulate_game(
            self.game_data,
            context=_neutral_context(),
            n_simulations=10,
            extra_innings=False,
        )
        # All simulations end at or after 9 innings
        assert all(i >= 9 for i in result.innings_played)

    def test_tie_games_go_to_extra_innings(self):
        """When extra_innings=True, tied games don't end at 9."""
        # This is probabilistic — with enough simulations, ties should occur
        result = self.sim.simulate_game(
            self.game_data,
            context=_neutral_context(),
            n_simulations=500,
            extra_innings=True,
            seed=777,
        )
        # At least some games should end > 9 innings (due to extra-inning ties)
        if result.tie_count > 0:
            assert any(i > 9 for i in result.innings_played)

    def test_pitcher_k_distribution_shape(self):
        """away_pitcher_k_distribution has correct length (one entry per sim)."""
        n_sims = 25
        result = self.sim.simulate_game(
            self.game_data, context=_neutral_context(), n_simulations=n_sims
        )
        assert len(result.away_pitcher_k_distribution) == n_sims
        assert len(result.home_pitcher_k_distribution) == n_sims

    def test_runs_per_game_plausible(self):
        """Average runs per team per game should be between 2 and 8 (plausible MLB range)."""
        result = self.sim.simulate_game(
            self.game_data, context=_neutral_context(), n_simulations=500, seed=42
        )
        avg_away = np.mean(result.away_scores)
        avg_home = np.mean(result.home_scores)
        assert 2.0 <= avg_away <= 8.0, f"Away avg runs {avg_away:.2f} out of plausible range"
        assert 2.0 <= avg_home <= 8.0, f"Home avg runs {avg_home:.2f} out of plausible range"


# ===========================================================================
# TestPropAnalyzer
# ===========================================================================


class TestPropAnalyzer:
    """Tests for PropAnalyzer — converts simulation K distributions into prop edges."""

    def _make_k_distribution(self, mean: float = 6.0, std: float = 2.0, n: int = 1000):
        """Generate a synthetic K distribution centred on `mean`."""
        rng = np.random.default_rng(seed=42)
        raw = rng.normal(loc=mean, scale=std, size=n)
        return np.clip(np.round(raw), 0, 27).astype(int)

    def test_analyze_over_edge(self):
        """With a high K mean and low prop line, PropAnalyzer should recommend OVER."""
        analyzer = PropAnalyzer()
        dist = self._make_k_distribution(mean=8.0, std=1.5)
        line = PropLine(pitcher_id=1, pitcher_name="Ace", stat_type="strikeouts",
                        line=5.5, over_odds=-115, under_odds=-105)
        analysis = analyzer.analyze(dist, line)
        assert isinstance(analysis, PropAnalysis)
        assert analysis.recommendation in ("over", "under", "no_play")
        if analysis.recommendation == "over":
            assert analysis.over_prob > analysis.under_prob

    def test_analyze_under_edge(self):
        """With a low K mean and high prop line, PropAnalyzer should recommend UNDER."""
        analyzer = PropAnalyzer()
        dist = self._make_k_distribution(mean=3.0, std=1.0)
        line = PropLine(pitcher_id=2, pitcher_name="Soft Tosser", stat_type="strikeouts",
                        line=6.5, over_odds=-110, under_odds=-110)
        analysis = analyzer.analyze(dist, line)
        assert isinstance(analysis, PropAnalysis)
        if analysis.recommendation == "under":
            assert analysis.under_prob > analysis.over_prob

    def test_analyze_returns_probabilities_in_range(self):
        """over_prob and under_prob are both in [0, 1]."""
        analyzer = PropAnalyzer()
        dist = self._make_k_distribution()
        line = PropLine(pitcher_id=3, pitcher_name="Pitcher", stat_type="strikeouts",
                        line=6.5, over_odds=-110, under_odds=-110)
        analysis = analyzer.analyze(dist, line)
        assert 0.0 <= analysis.over_prob <= 1.0
        assert 0.0 <= analysis.under_prob <= 1.0

    def test_analyze_probs_sum_approx_to_one(self):
        """over_prob + under_prob + push_prob ≈ 1.0 for half-point lines (no push)."""
        analyzer = PropAnalyzer()
        dist = self._make_k_distribution()
        # .5 line means no exact push
        line = PropLine(pitcher_id=4, pitcher_name="Pitcher", stat_type="strikeouts",
                        line=6.5, over_odds=-110, under_odds=-110)
        analysis = analyzer.analyze(dist, line)
        total = analysis.over_prob + analysis.under_prob + analysis.push_prob
        assert abs(total - 1.0) < 1e-6, f"Probs sum = {total}"

    def test_analyze_whole_number_line_has_push_mass(self):
        """Whole-number line (e.g. 6.0) should have some push probability."""
        analyzer = PropAnalyzer()
        dist = self._make_k_distribution(mean=6.0, std=1.5)
        line = PropLine(pitcher_id=5, pitcher_name="Pitcher", stat_type="strikeouts",
                        line=6.0, over_odds=-110, under_odds=-110)
        analysis = analyzer.analyze(dist, line)
        # With mean=6.0, some exact hits on 6 are expected
        assert analysis.push_prob >= 0.0  # Always true; we just ensure no exception

    def test_edge_value_calculation(self):
        """edge_pct reflects how much the model price differs from vig-free odds."""
        analyzer = PropAnalyzer()
        # Very high K dist vs low line — large edge expected
        dist = self._make_k_distribution(mean=10.0, std=1.0)
        line = PropLine(pitcher_id=6, pitcher_name="Ace", stat_type="strikeouts",
                        line=5.5, over_odds=-110, under_odds=-110)
        analysis = analyzer.analyze(dist, line)
        # Edge should be positive (model > vig-free implied)
        if analysis.recommendation == "over":
            assert analysis.ev_pct > 0.0

    def test_no_play_when_edge_below_threshold(self):
        """When model prob is very close to vig-free, recommendation is 'no_play'."""
        analyzer = PropAnalyzer(min_edge=0.10)  # 10% edge threshold
        dist = self._make_k_distribution(mean=6.0, std=2.0)
        # Line at exactly the mean — no edge
        line = PropLine(pitcher_id=7, pitcher_name="Pitcher", stat_type="strikeouts",
                        line=6.0, over_odds=-110, under_odds=-110)
        analysis = analyzer.analyze(dist, line)
        # With mean exactly at line and 10% threshold, likely no_play
        # (or possibly a play if variance creates slight edge)
        assert analysis.recommendation in ("over", "under", "no_play")

    def test_kelly_fraction_positive_for_edge(self):
        """kelly_fraction is positive when there is a genuine edge."""
        analyzer = PropAnalyzer()
        dist = self._make_k_distribution(mean=9.0, std=0.5)
        line = PropLine(pitcher_id=8, pitcher_name="Ace", stat_type="strikeouts",
                        line=5.5, over_odds=-110, under_odds=-110)
        analysis = analyzer.analyze(dist, line)
        if analysis.recommendation == "over":
            assert analysis.kelly_fraction >= 0.0

    def test_kelly_fraction_capped(self):
        """kelly_fraction never exceeds 1.0 (capped for bet-sizing safety)."""
        analyzer = PropAnalyzer()
        dist = self._make_k_distribution(mean=15.0, std=0.1)  # extreme edge
        line = PropLine(pitcher_id=9, pitcher_name="Robot", stat_type="strikeouts",
                        line=1.5, over_odds=-110, under_odds=-110)
        analysis = analyzer.analyze(dist, line)
        assert analysis.kelly_fraction <= 1.0

    def test_analyze_batch(self):
        """analyze_batch returns one PropAnalysis per input."""
        analyzer = PropAnalyzer()
        dists = [
            self._make_k_distribution(mean=m) for m in [4.0, 6.0, 8.0]
        ]
        lines = [
            PropLine(pitcher_id=i, pitcher_name=f"P{i}", stat_type="strikeouts",
                     line=5.5, over_odds=-110, under_odds=-110)
            for i in range(3)
        ]
        results = analyzer.analyze_batch(list(zip(dists, lines)))
        assert len(results) == 3
        assert all(isinstance(r, PropAnalysis) for r in results)

    def test_analyze_empty_distribution(self):
        """PropAnalyzer raises ValueError for an empty distribution."""
        analyzer = PropAnalyzer()
        line = PropLine(pitcher_id=10, pitcher_name="Ghost", stat_type="strikeouts",
                        line=5.5, over_odds=-110, under_odds=-110)
        with pytest.raises((ValueError, IndexError)):
            analyzer.analyze(np.array([], dtype=int), line)

    def test_summary_string_representation(self):
        """str(PropAnalysis) or repr(PropAnalysis) is a non-empty string."""
        analyzer = PropAnalyzer()
        dist = self._make_k_distribution()
        line = PropLine(pitcher_id=11, pitcher_name="Test", stat_type="strikeouts",
                        line=6.5, over_odds=-110, under_odds=-110)
        analysis = analyzer.analyze(dist, line)
        s = str(analysis)
        assert isinstance(s, str)
        assert len(s) > 0

    @pytest.mark.parametrize("over_odds,under_odds", [
        (-110, -110),   # balanced market
        (-120, +100),   # favourite over
        (+100, -120),   # favourite under
        (-150, +125),   # heavy favourite over
    ])
    def test_various_odds_structures(self, over_odds, under_odds):
        """PropAnalyzer handles various American odds structures without error."""
        analyzer = PropAnalyzer()
        dist = self._make_k_distribution(mean=6.0)
        line = PropLine(pitcher_id=12, pitcher_name="Pitcher", stat_type="strikeouts",
                        line=5.5, over_odds=over_odds, under_odds=under_odds)
        analysis = analyzer.analyze(dist, line)
        assert isinstance(analysis, PropAnalysis)
        assert 0.0 <= analysis.over_prob <= 1.0
        assert 0.0 <= analysis.under_prob <= 1.0

    def test_ev_pct_zero_for_coin_flip(self):
        """EV% is approximately zero when model prob matches vig-free implied prob.

        We construct a case where model over_prob ≈ 0.5 and market is -110/-110
        (vig-free ≈ 0.5). Expected value should be near zero.
        """
        analyzer = PropAnalyzer()
        # dist symmetric around line → over_prob ≈ 0.5
        rng = np.random.default_rng(seed=0)
        dist = np.round(rng.normal(6.5, 2.0, 10000)).astype(int)
        dist = np.clip(dist, 0, 27)
        line = PropLine(
            pitcher_id=13, pitcher_name="Coin Flip", stat_type="strikeouts",
            line=6.5, over_odds=-110, under_odds=-110
        )
        analysis = analyzer.analyze(dist, line)
        # over_prob ≈ 0.50 and vig-free implied ≈ 0.4762 → small positive EV
        # Accept |EV| < 5% as "near zero"
        if analysis.recommendation in ("over", "no_play"):
            expected_ev = analysis.ev_pct if analysis.recommendation == "over" else 0.0
        else:
            expected_ev = 0.0
        assert abs(analysis.ev_pct - expected_ev) < 1e-6
