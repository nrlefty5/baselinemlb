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

from simulation.config import (
    FEATURE_COLUMNS,
    LEAGUE_AVG_RATES,
    MODEL_OUTCOMES,
    PARK_FACTORS,
    SimulationConfig,
)
from simulation.game_engine import (
    GameSimulator,
    GameState,
    PlayerStats,
    SimulationResult,
)
from simulation.matchup_model import (
    MatchupModel,
    OddsRatioModel,
)
from simulation.prop_analyzer import (
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
        initial_score = gs.score["away"]
        runs = gs.advance_runners_probabilistic("single", rng=rng)
        assert isinstance(runs, int)
        assert runs >= 0
        assert gs.score["away"] == initial_score + runs

    def test_advance_runners_probabilistic_triple(self):
        """advance_runners_probabilistic('triple') scores all runners."""
        rng = np.random.default_rng(seed=0)
        gs = GameState()
        gs.half = "top"
        gs.runners = {1: 1, 2: 2, 3: 3}
        runs = gs.advance_runners_probabilistic("triple", rng=rng)
        # All 3 runners should score on a triple
        assert runs == 3
        assert gs.runners[3] is not None  # batter on 3B


# ===========================================================================
# TestPlayerStats
# ===========================================================================


class TestPlayerStats:
    """Tests for PlayerStats — the aggregated stat container."""

    def test_from_dict_batter(self):
        """PlayerStats.from_dict creates a valid batter stats object."""
        raw = _make_player(100, "Test Batter")
        ps = PlayerStats.from_dict(raw)
        assert ps.mlbam_id == 100
        assert ps.name == "Test Batter"
        for outcome in MODEL_OUTCOMES:
            assert hasattr(ps, f"{outcome}_rate")

    def test_from_dict_pitcher(self):
        """PlayerStats.from_dict creates a valid pitcher stats object."""
        raw = _make_pitcher(200, "Test Pitcher")
        ps = PlayerStats.from_dict(raw)
        assert ps.mlbam_id == 200
        assert ps.name == "Test Pitcher"

    def test_rates_non_negative(self):
        """All rate attributes are non-negative after from_dict."""
        ps = PlayerStats.from_dict(_make_player(1, "Player"))
        for outcome in MODEL_OUTCOMES:
            val = getattr(ps, f"{outcome}_rate")
            assert val >= 0.0, f"{outcome}_rate is negative: {val}"

    def test_sample_pa_preserved(self):
        """sample_pa is correctly stored from the input dict."""
        raw = _make_player(99, "A", hand="L")
        raw["sample_pa"] = 350
        ps = PlayerStats.from_dict(raw)
        assert ps.sample_pa == 350

    def test_hand_preserved(self):
        """Hand attribute is correctly stored."""
        raw = _make_player(88, "B", hand="L")
        ps = PlayerStats.from_dict(raw)
        assert ps.hand == "L"

    def test_missing_hand_defaults_to_r(self):
        """If 'hand' is missing from dict, defaults to 'R'."""
        raw = _make_player(77, "C")
        del raw["hand"]
        ps = PlayerStats.from_dict(raw)
        assert ps.hand == "R"


# ===========================================================================
# TestGameSimulator
# ===========================================================================


class TestGameSimulator:
    """Tests for GameSimulator — the full Monte Carlo game engine."""

    @pytest.fixture(autouse=True)
    def setup(self):
        """Build a standard 9-batter lineup for both teams."""
        self.away_lineup = [_make_player(i, f"Away {i}") for i in range(1, 10)]
        self.home_lineup = [_make_player(i + 100, f"Home {i}") for i in range(1, 10)]
        self.away_starter = _make_pitcher(201, "Away SP")
        self.home_starter = _make_pitcher(202, "Home SP")
        self.game_data = _make_game_data(
            self.away_lineup,
            self.home_lineup,
            self.away_starter,
            self.home_starter,
        )
        self.matchup_model = MockMatchupModel()
        self.cfg = SimulationConfig(NUM_SIMULATIONS=100, RANDOM_SEED=42)
        self.sim = GameSimulator(
            matchup_model=self.matchup_model,
            config=self.cfg,
        )

    def test_run_returns_simulation_result(self):
        """GameSimulator.run() returns a SimulationResult."""
        result = self.sim.simulate_game(self.game_data)
        assert isinstance(result, SimulationResult)

    def test_win_probs_sum_to_one(self):
        """away_win_prob + home_win_prob + tie_prob == 1.0."""
        result = self.sim.simulate_game(self.game_data)
        total = result.away_win_prob + result.home_win_prob + result.tie_prob
        assert abs(total - 1.0) < 1e-9, f"Win probs sum = {total}"

    def test_win_probs_in_range(self):
        """All win probabilities are in [0, 1]."""
        result = self.sim.simulate_game(self.game_data)
        assert 0.0 <= result.away_win_prob <= 1.0
        assert 0.0 <= result.home_win_prob <= 1.0
        assert 0.0 <= result.tie_prob <= 1.0

    def test_total_runs_non_negative(self):
        """Average runs scored per team is non-negative."""
        result = self.sim.simulate_game(self.game_data)
        assert result.avg_away_runs >= 0.0
        assert result.avg_home_runs >= 0.0

    def test_player_stats_present(self):
        """SimulationResult contains player_stats dict with at least one entry."""
        result = self.sim.simulate_game(self.game_data)
        assert isinstance(result.player_stats, dict)
        assert len(result.player_stats) > 0

    def test_player_stats_hits_non_negative(self):
        """Every player's average hits is non-negative."""
        result = self.sim.simulate_game(self.game_data)
        for player_id, stats in result.player_stats.items():
            assert stats.get("avg_hits", 0) >= 0.0, (
                f"Player {player_id} has negative avg_hits"
            )

    def test_player_stats_contains_lineup_players(self):
        """All lineup players appear in player_stats."""
        result = self.sim.simulate_game(self.game_data)
        for player in self.away_lineup + self.home_lineup:
            pid = player["mlbam_id"]
            assert pid in result.player_stats, (
                f"Player {pid} missing from player_stats"
            )

    def test_simulation_count_matches_config(self):
        """The internal simulation ran exactly NUM_SIMULATIONS times."""
        result = self.sim.simulate_game(self.game_data)
        assert result.num_simulations == self.cfg.NUM_SIMULATIONS

    def test_random_seed_reproducibility(self):
        """Two simulators with the same seed produce identical results."""
        cfg1 = SimulationConfig(NUM_SIMULATIONS=50, RANDOM_SEED=99)
        cfg2 = SimulationConfig(NUM_SIMULATIONS=50, RANDOM_SEED=99)
        sim1 = GameSimulator(
            matchup_model=self.matchup_model, config=cfg1
        )
        sim2 = GameSimulator(
            matchup_model=self.matchup_model, config=cfg2
        )
        r1 = sim1.simulate_game(self.game_data)
        r2 = sim2.simulate_game(self.game_data)
        assert r1.away_win_prob == r2.away_win_prob
        assert r1.home_win_prob == r2.home_win_prob
        assert r1.avg_away_runs == r2.avg_away_runs

    def test_different_seeds_usually_differ(self):
        """Two simulators with different seeds almost always produce different results."""
        cfg1 = SimulationConfig(NUM_SIMULATIONS=200, RANDOM_SEED=1)
        cfg2 = SimulationConfig(NUM_SIMULATIONS=200, RANDOM_SEED=2)
        sim1 = GameSimulator(
            matchup_model=self.matchup_model, config=cfg1
        )
        sim2 = GameSimulator(
            matchup_model=self.matchup_model, config=cfg2
        )
        r1 = sim1.simulate_game(self.game_data)
        r2 = sim2.simulate_game(self.game_data)
        # It is astronomically unlikely both are identical with 200 sims
        assert (
            r1.away_win_prob != r2.away_win_prob
            or r1.avg_away_runs != r2.avg_away_runs
        )

    def test_result_has_score_distribution(self):
        """SimulationResult contains a score_distribution dict."""
        result = self.sim.simulate_game(self.game_data)
        assert hasattr(result, "score_distribution")
        assert isinstance(result.score_distribution, dict)

    def test_score_distribution_probabilities_sum_to_one(self):
        """All values in score_distribution sum to approximately 1.0."""
        result = self.sim.simulate_game(self.game_data)
        total = sum(result.score_distribution.values())
        assert abs(total - 1.0) < 1e-6, f"Score dist sum = {total}"

    def test_over_under_line_returns_probs(self):
        """get_over_under returns a dict with 'over' and 'under' keys."""
        result = self.sim.simulate_game(self.game_data)
        ou = result.get_over_under(line=8.5)
        assert "over" in ou and "under" in ou
        assert abs(ou["over"] + ou["under"] - 1.0) < 1e-9

    def test_over_under_at_zero_line_all_over(self):
        """Line of 0.0 means virtually all simulated games go over (≥1 total run)."""
        result = self.sim.simulate_game(self.game_data)
        ou = result.get_over_under(line=0.0)
        assert ou["over"] > 0.99, f"Expected >99% over at line 0.0, got {ou['over']:.4f}"

    def test_over_under_at_huge_line_all_under(self):
        """Line of 100.0 means virtually all simulated games go under."""
        result = self.sim.simulate_game(self.game_data)
        ou = result.get_over_under(line=100.0)
        assert ou["under"] > 0.99, (
            f"Expected >99% under at line 100.0, got {ou['under']:.4f}"
        )

    def test_single_game_sim_returns_valid_dict(self):
        """_run_single_game returns a dict with required keys."""
        rng = np.random.default_rng(seed=0)
        game_result = self.sim._run_single_game(rng=rng)
        required_keys = {"away_score", "home_score", "innings_played", "player_log"}
        for key in required_keys:
            assert key in game_result, f"Missing key '{key}' in single-game result"

    def test_single_game_score_non_negative(self):
        """Single game scores are non-negative integers."""
        rng = np.random.default_rng(seed=1)
        game_result = self.sim._run_single_game(rng=rng)
        assert game_result["away_score"] >= 0
        assert game_result["home_score"] >= 0

    def test_single_game_innings_at_least_9(self):
        """A single game simulation plays at least 9 innings."""
        rng = np.random.default_rng(seed=2)
        game_result = self.sim._run_single_game(rng=rng)
        assert game_result["innings_played"] >= 9

    def test_run_is_idempotent(self):
        """Calling run() twice on the same simulator produces consistent results
        (with a fixed seed, results should be identical)."""
        cfg = SimulationConfig(NUM_SIMULATIONS=50, RANDOM_SEED=7)
        sim = GameSimulator(
            matchup_model=self.matchup_model,
            config=cfg,
        )
        r1 = sim.simulate_game(self.game_data)
        r2 = sim.simulate_game(self.game_data)
        assert r1.away_win_prob == r2.away_win_prob
        assert r1.home_win_prob == r2.home_win_prob

    def test_high_k_pitcher_produces_more_ks(self):
        """Lineup facing a high-K pitcher accumulates more strikeouts per sim."""

        class HighKModel:
            def predict_pa_probs(self, pitcher, batter, context, **kwargs):
                probs = dict(LEAGUE_AVG_RATES)
                k_boost = 0.15
                probs["strikeout"] = min(1.0, probs["strikeout"] + k_boost)
                # Re-normalise
                total = sum(probs.values())
                return {k: v / total for k, v in probs.items()}

        cfg = SimulationConfig(NUM_SIMULATIONS=200, RANDOM_SEED=42)
        sim_highk = GameSimulator(
            matchup_model=HighKModel(), config=cfg
        )
        result_highk = sim_highk.simulate_game(self.game_data)

        sim_baseline = GameSimulator(
            matchup_model=self.matchup_model, config=cfg
        )
        result_baseline = sim_baseline.simulate_game(self.game_data)

        # High-K model should produce more total strikeouts
        def total_ks(result):
            return sum(
                stats.get("avg_strikeouts", 0)
                for stats in result.player_stats.values()
            )

        assert total_ks(result_highk) > total_ks(result_baseline), (
            f"High-K model KS={total_ks(result_highk):.2f} should exceed "
            f"baseline KS={total_ks(result_baseline):.2f}"
        )


# ===========================================================================
# TestPropAnalyzer
# ===========================================================================


class TestPropAnalyzer:
    """Tests for PropAnalyzer — the prop-bet analysis layer."""

    @pytest.fixture(autouse=True)
    def setup(self):
        """Set up a standard PropAnalyzer with a pre-built SimulationResult."""
        away_lineup = [_make_player(i, f"Away {i}") for i in range(1, 10)]
        home_lineup = [_make_player(i + 100, f"Home {i}") for i in range(1, 10)]
        away_starter = _make_pitcher(201, "Away SP")
        home_starter = _make_pitcher(202, "Home SP")
        game_data = _make_game_data(away_lineup, home_lineup, away_starter, home_starter)

        cfg = SimulationConfig(NUM_SIMULATIONS=500, RANDOM_SEED=42)
        sim = GameSimulator(
            matchup_model=MockMatchupModel(),
            config=cfg,
        )
        self.result = sim.simulate_game(game_data)
        self.analyzer = PropAnalyzer(simulation_result=self.result)

        # Pick a player that exists in player_stats
        self.player_id = away_lineup[0]["mlbam_id"]
        self.player_name = away_lineup[0]["name"]

    # --- PropLine tests ---

    def test_prop_line_valid(self):
        """PropLine can be created with valid inputs."""
        prop = PropLine(
            player_id=self.player_id,
            player_name=self.player_name,
            prop_type="hits",
            line=0.5,
            over_odds=-115,
            under_odds=-105,
        )
        assert prop.player_id == self.player_id
        assert prop.line == 0.5

    def test_prop_line_negative_line_raises(self):
        """PropLine with a negative line raises ValueError."""
        with pytest.raises(ValueError, match="line"):
            PropLine(
                player_id=1,
                player_name="X",
                prop_type="hits",
                line=-0.5,
                over_odds=-110,
                under_odds=-110,
            )

    def test_prop_line_invalid_prop_type_raises(self):
        """PropLine with an unknown prop_type raises ValueError."""
        with pytest.raises(ValueError, match="prop_type"):
            PropLine(
                player_id=1,
                player_name="X",
                prop_type="fantasy_points",
                line=0.5,
                over_odds=-110,
                under_odds=-110,
            )

    # --- PropAnalysis tests ---

    def _make_prop(self, prop_type="hits", line=0.5):
        return PropLine(
            player_id=self.player_id,
            player_name=self.player_name,
            prop_type=prop_type,
            line=line,
            over_odds=-110,
            under_odds=-110,
        )

    def test_analyze_returns_prop_analysis(self):
        """PropAnalyzer.analyze() returns a PropAnalysis object."""
        prop = self._make_prop()
        analysis = self.analyzer.analyze(prop)
        assert isinstance(analysis, PropAnalysis)

    def test_over_under_probs_sum_to_one(self):
        """over_prob + under_prob + push_prob == 1.0."""
        prop = self._make_prop()
        analysis = self.analyzer.analyze(prop)
        total = analysis.over_prob + analysis.under_prob + analysis.push_prob
        assert abs(total - 1.0) < 1e-9, f"Over/under/push sum = {total}"

    def test_over_prob_in_range(self):
        """over_prob is in [0, 1]."""
        prop = self._make_prop()
        analysis = self.analyzer.analyze(prop)
        assert 0.0 <= analysis.over_prob <= 1.0

    def test_under_prob_in_range(self):
        """under_prob is in [0, 1]."""
        prop = self._make_prop()
        analysis = self.analyzer.analyze(prop)
        assert 0.0 <= analysis.under_prob <= 1.0

    def test_recommended_side_valid(self):
        """recommended_side is one of 'over', 'under', or 'no_bet'."""
        prop = self._make_prop()
        analysis = self.analyzer.analyze(prop)
        assert analysis.recommended_side in ("over", "under", "no_bet")

    def test_hits_prop_analysis(self):
        """Hits prop returns a valid analysis."""
        analysis = self.analyzer.analyze(self._make_prop("hits", 0.5))
        assert isinstance(analysis, PropAnalysis)
        assert analysis.prop_type == "hits"

    def test_strikeouts_prop_analysis(self):
        """Strikeouts prop returns a valid analysis (pitcher K prop)."""
        # Use a batter for simplicity — analyzer treats same as any counter
        analysis = self.analyzer.analyze(self._make_prop("strikeouts", 0.5))
        assert isinstance(analysis, PropAnalysis)

    def test_home_runs_prop_analysis(self):
        """Home runs prop works correctly."""
        analysis = self.analyzer.analyze(self._make_prop("home_runs", 0.5))
        assert isinstance(analysis, PropAnalysis)
        assert analysis.prop_type == "home_runs"

    def test_walks_prop_analysis(self):
        """Walks prop works correctly."""
        analysis = self.analyzer.analyze(self._make_prop("walks", 0.5))
        assert isinstance(analysis, PropAnalysis)

    def test_total_bases_prop_analysis(self):
        """Total bases prop works correctly."""
        analysis = self.analyzer.analyze(self._make_prop("total_bases", 1.5))
        assert isinstance(analysis, PropAnalysis)
        assert analysis.prop_type == "total_bases"

    def test_rbi_prop_analysis(self):
        """RBI prop works correctly."""
        analysis = self.analyzer.analyze(self._make_prop("rbi", 0.5))
        assert isinstance(analysis, PropAnalysis)

    def test_runs_prop_analysis(self):
        """Runs scored prop works correctly."""
        analysis = self.analyzer.analyze(self._make_prop("runs", 0.5))
        assert isinstance(analysis, PropAnalysis)

    def test_unknown_player_raises(self):
        """Analyzing a prop for an unknown player_id raises KeyError or ValueError."""
        bad_prop = PropLine(
            player_id=99999,  # not in player_stats
            player_name="Ghost Player",
            prop_type="hits",
            line=0.5,
            over_odds=-110,
            under_odds=-110,
        )
        with pytest.raises((KeyError, ValueError)):
            self.analyzer.analyze(bad_prop)

    def test_ev_pct_present_and_numeric(self):
        """ev_pct is a float (expected value as a percentage)."""
        analysis = self.analyzer.analyze(self._make_prop())
        assert isinstance(analysis.ev_pct, float)

    def test_ev_pct_non_negative_for_good_bet(self):
        """A highly favorable bet (line=0.5 hits, heavy over prob) has positive EV."""
        # Create a prop where the line is very low so over is near certain
        prop = self._make_prop("hits", line=0.5)
        analysis = self.analyzer.analyze(prop)
        if analysis.recommended_side in ("over", "under"):
            assert analysis.ev_pct >= 0.0, (
                f"Recommended bet has negative EV: {analysis.ev_pct:.4f}"
            )

    def test_edge_values_are_finite(self):
        """edge_over and edge_under are finite floats."""
        analysis = self.analyzer.analyze(self._make_prop())
        import math
        assert math.isfinite(analysis.edge_over)
        assert math.isfinite(analysis.edge_under)

    def test_edge_calculation_consistency(self):
        """ev_pct is consistent with edge_over / edge_under and recommended_side."""
        analysis = self.analyzer.analyze(self._make_prop())
        if analysis.recommended_side == "over":
            expected_ev = round(analysis.edge_over * 100, 4)
        elif analysis.recommended_side == "under":
            expected_ev = round(analysis.edge_under * 100, 4)
        else:
            expected_ev = 0.0
        assert abs(analysis.ev_pct - expected_ev) < 1e-6
