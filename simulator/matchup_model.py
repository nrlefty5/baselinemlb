"""
BaselineMLB -- matchup_model.py
================================
Core ML model that predicts per-PA outcome probabilities for each
batter-pitcher matchup.

Three classes are exposed:

  TrainedMatchupModel  -- LightGBM multi-class classifier (8 outcomes).
                         Falls back to OddsRatioModel when no saved model
                         is available.

  OddsRatioModel       -- Generalised log5 / odds-ratio formula with full
                         contextual adjustments (park, platoon, umpire,
                         catcher framing, weather). No training data required.

  MatchupModel         -- Unified facade that tries the trained model first
                         and degrades gracefully to OddsRatioModel.  Also
                         exposes the glass-box explain_prediction() method
                         that is BaselineMLB's key differentiator.

All predict_pa_probs() methods return a dict[str, float] whose values sum
to exactly 1.0, keyed by the 8 strings in MODEL_OUTCOMES.
"""

from __future__ import annotations

import logging
import warnings
from pathlib import Path
from typing import Optional

import numpy as np

from simulator.config import (
    FEATURE_COLUMNS,
    LEAGUE_AVG_RATES,
    MODEL_OUTCOMES,
)

try:
    import lightgbm as lgb  # type: ignore
    _LGBM_AVAILABLE = True
except ImportError:
    lgb = None  # type: ignore
    _LGBM_AVAILABLE = False

log = logging.getLogger(__name__)

NUM_OUTCOMES: int = len(MODEL_OUTCOMES)
OUTCOME_TO_IDX: dict[str, int] = {o: i for i, o in enumerate(MODEL_OUTCOMES)}

_REGRESSION_PA: dict[str, int] = {
    "strikeout": 200,
    "walk":      200,
    "hbp":       500,
    "single":    150,
    "double":    300,
    "triple":    600,
    "home_run":  300,
    "out":       100,
}

_PROB_MIN: float = 0.001
_PROB_MAX: float = 0.999

_PLATOON_HIT_BOOST: float  = 0.05
_PLATOON_K_REDUCTION: float = 0.03

_WEATHER_TEMP_BASELINE: float      = 72.0
_WEATHER_TEMP_COEFFICIENT: float   = 0.003
_WEATHER_WIND_OUT_BOOST: float     = 0.08
_WEATHER_WIND_IN_REDUCTION: float  = 0.06

_FRAMING_K_PER_SD: float = 0.025

_PA_FULL: int    = 502
_PA_PARTIAL: int = 150
_PA_MINIMAL: int = 30

_LEAGUE_RATES_ARRAY: np.ndarray = np.array(
    [LEAGUE_AVG_RATES[o] for o in MODEL_OUTCOMES], dtype=np.float64
)

_K_IDX:  int = OUTCOME_TO_IDX["strikeout"]
_BB_IDX: int = OUTCOME_TO_IDX["walk"]
_1B_IDX: int = OUTCOME_TO_IDX["single"]
_2B_IDX: int = OUTCOME_TO_IDX["double"]
_3B_IDX: int = OUTCOME_TO_IDX["triple"]
_HR_IDX: int = OUTCOME_TO_IDX["home_run"]
_HIT_INDICES: tuple[int, ...] = (_1B_IDX, _2B_IDX, _3B_IDX, _HR_IDX)


def _softmax(x: np.ndarray) -> np.ndarray:
    x = x - x.max()
    e = np.exp(x)
    return e / e.sum()


def _clip_and_normalise(probs: np.ndarray) -> np.ndarray:
    probs = np.clip(probs, _PROB_MIN, _PROB_MAX).astype(np.float64)
    total = probs.sum()
    if total <= 0:
        return np.full(len(probs), 1.0 / len(probs))
    return probs / total


def _array_to_dict(arr: np.ndarray) -> dict[str, float]:
    return {outcome: float(arr[i]) for i, outcome in enumerate(MODEL_OUTCOMES)}


def _regress_toward_league(observed_rate: float, outcome: str, sample_pa: int) -> float:
    reg_pa    = _REGRESSION_PA.get(outcome, 200)
    lg_avg    = LEAGUE_AVG_RATES[outcome]
    obs_events = max(0.0, observed_rate) * max(0, sample_pa)
    return float((obs_events + lg_avg * reg_pa) / (sample_pa + reg_pa))


def _confidence_from_sample(pitcher_pa: int, batter_pa: int) -> float:
    def _score(n: int) -> float:
        if n >= _PA_FULL:
            return 1.0
        if n >= _PA_PARTIAL:
            return 0.6 + 0.4 * (n - _PA_PARTIAL) / (_PA_FULL - _PA_PARTIAL)
        if n >= _PA_MINIMAL:
            return 0.2 + 0.4 * (n - _PA_MINIMAL) / (_PA_PARTIAL - _PA_MINIMAL)
        return 0.1 * n / max(_PA_MINIMAL, 1)
    ps = _score(pitcher_pa)
    bs = _score(batter_pa)
    if ps + bs == 0.0:
        return 0.0
    return 2.0 * ps * bs / (ps + bs)


class TrainedMatchupModel:
    def __init__(self, model_path: Optional[str | Path] = None) -> None:
        self.model_path    = Path(model_path) if model_path else None
        self.is_loaded: bool = False
        self._model: Optional["lgb.Booster"] = None
        self._feature_names: list[str] = list(FEATURE_COLUMNS)
        if not _LGBM_AVAILABLE:
            log.warning("lightgbm is not installed. TrainedMatchupModel will not function.")
            return
        if self.model_path is not None and self.model_path.is_file():
            self._load(self.model_path)
        elif self.model_path is not None:
            log.warning("Model file not found at '%s'. Falling back to OddsRatioModel.", self.model_path)

    def predict_pa_probs(self, features: np.ndarray) -> dict[str, float]:
        if not self.is_loaded or self._model is None:
            raise RuntimeError("TrainedMatchupModel has no loaded model.")
        features = np.asarray(features, dtype=np.float64)
        if features.ndim == 1:
            features = features.reshape(1, -1)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            raw: np.ndarray = self._model.predict(features)[0]
        probs = _softmax(raw)
        probs = _clip_and_normalise(probs)
        return _array_to_dict(probs)

    def get_feature_importance(self) -> dict[str, float]:
        if not self.is_loaded or self._model is None:
            return {}
        raw: np.ndarray = self._model.feature_importance(importance_type="gain")
        names: list[str] = self._model.feature_name()
        total = raw.sum()
        if total == 0:
            return {n: 0.0 for n in names}
        normalised = {n: float(v / total) for n, v in zip(names, raw)}
        return dict(sorted(normalised.items(), key=lambda kv: kv[1], reverse=True))

    def _load(self, path: Path) -> None:
        try:
            suffix = path.suffix.lower()
            if suffix in (".pkl", ".pickle"):
                import pickle
                with open(path, "rb") as fh:
                    self._model = pickle.load(fh)
            else:
                self._model = lgb.Booster(model_file=str(path))
            self.is_loaded = True
            log.info("Loaded TrainedMatchupModel from '%s'.", path)
            try:
                self._feature_names = self._model.feature_name()
            except Exception:
                pass
        except Exception as exc:
            log.error("Failed to load LightGBM model from '%s': %s. Falling back to OddsRatioModel.", path, exc)
            self._model = None
            self.is_loaded = False


class OddsRatioModel:
    """
    Generalised log5 / odds-ratio matchup model with contextual adjustments.
    Reference: SABR -- Matchup Probabilities in Major League Baseball
    https://sabr.org/journal/article/matchup-probabilities-in-major-league-baseball/
    """

    def __init__(self) -> None:
        self._league_rates = dict(LEAGUE_AVG_RATES)

    def predict_pa_probs(self, pitcher_stats: dict, batter_stats: dict, context: dict) -> dict[str, float]:
        pitcher_pa = int(pitcher_stats.get("sample_pa", _PA_PARTIAL))
        batter_pa  = int(batter_stats.get("sample_pa", _PA_PARTIAL))

        pitcher_rates = np.zeros(NUM_OUTCOMES, dtype=np.float64)
        batter_rates  = np.zeros(NUM_OUTCOMES, dtype=np.float64)

        for i, outcome in enumerate(MODEL_OUTCOMES):
            key    = f"{outcome}_rate"
            lg_avg = self._league_rates[outcome]
            p_raw = float(np.clip(pitcher_stats.get(key, lg_avg), 0.0, 1.0))
            b_raw = float(np.clip(batter_stats.get(key,  lg_avg), 0.0, 1.0))
            pitcher_rates[i] = _regress_toward_league(p_raw, outcome, pitcher_pa)
            batter_rates[i]  = _regress_toward_league(b_raw, outcome, batter_pa)

        safe_league  = np.where(_LEAGUE_RATES_ARRAY > 0.0, _LEAGUE_RATES_ARRAY, 1e-9)
        batter_rel   = batter_rates / safe_league
        b_rel_sum    = batter_rel.sum()
        if b_rel_sum <= 0.0:
            batter_rel = np.ones(NUM_OUTCOMES, dtype=np.float64)
            b_rel_sum  = float(NUM_OUTCOMES)

        x_prime    = batter_rel / b_rel_sum
        numerators = x_prime * pitcher_rates
        denom      = numerators.sum()
        probs      = (numerators / denom) if denom > 0.0 else _LEAGUE_RATES_ARRAY.copy()

        probs = self._apply_park_factors(probs, context)
        probs = self._apply_platoon(probs, batter_stats, context)
        probs = self._apply_umpire(probs, context)
        probs = self._apply_catcher_framing(probs, context)
        probs = self._apply_weather(probs, context)
        probs = _clip_and_normalise(probs)
        return _array_to_dict(probs)

    def _apply_park_factors(self, probs: np.ndarray, context: dict) -> np.ndarray:
        pf_hr = float(np.clip(context.get("park_hr_factor", 1.0), 0.5, 2.0))
        pf_2b = float(np.clip(context.get("park_2b_factor", 1.0), 0.5, 2.0))
        pf_3b = float(np.clip(context.get("park_3b_factor", 1.0), 0.5, 2.0))
        pf_1b = float(np.clip(context.get("park_1b_factor", 1.0), 0.5, 2.0))
        probs = probs.copy()
        probs[_HR_IDX] *= pf_hr
        probs[_2B_IDX] *= pf_2b
        probs[_3B_IDX] *= pf_3b
        probs[_1B_IDX] *= pf_1b
        total = probs.sum()
        if total > 0.0:
            probs /= total
        return probs

    def _apply_platoon(self, probs: np.ndarray, batter_stats: dict, context: dict) -> np.ndarray:
        if "platoon_advantage" in context:
            has_advantage = bool(context["platoon_advantage"])
        else:
            batter_hand  = str(batter_stats.get("hand", "R")).upper()
            pitcher_hand = str(context.get("pitcher_hand", "R")).upper()
            has_advantage = (batter_hand == "S") or (batter_hand != pitcher_hand)
        if not has_advantage:
            return probs
        probs = probs.copy()
        for idx in _HIT_INDICES:
            probs[idx] *= (1.0 + _PLATOON_HIT_BOOST)
        probs[_K_IDX] *= (1.0 - _PLATOON_K_REDUCTION)
        total = probs.sum()
        if total > 0.0:
            probs /= total
        return probs

    def _apply_umpire(self, probs: np.ndarray, context: dict) -> np.ndarray:
        ump_k  = float(np.clip(context.get("umpire_k_factor",  1.0), 0.5, 2.0))
        ump_bb = float(np.clip(context.get("umpire_bb_factor", 1.0), 0.5, 2.0))
        if abs(ump_k - 1.0) < 1e-6 and abs(ump_bb - 1.0) < 1e-6:
            return probs
        probs = probs.copy()
        probs[_K_IDX]  *= ump_k
        probs[_BB_IDX] *= ump_bb
        total = probs.sum()
        if total > 0.0:
            probs /= total
        return probs

    def _apply_catcher_framing(self, probs: np.ndarray, context: dict) -> np.ndarray:
        framing_z = float(np.clip(context.get("catcher_framing_score", 0.0), -3.0, 3.0))
        if abs(framing_z) < 1e-6:
            return probs
        multiplier = float(np.clip(1.0 + framing_z * _FRAMING_K_PER_SD, 0.5, 1.5))
        probs = probs.copy()
        probs[_K_IDX] *= multiplier
        total = probs.sum()
        if total > 0.0:
            probs /= total
        return probs

    def _apply_weather(self, probs: np.ndarray, context: dict) -> np.ndarray:
        temp       = float(np.clip(context.get("temperature",  _WEATHER_TEMP_BASELINE), 20.0, 120.0))
        wind_speed = float(np.clip(context.get("wind_speed",   0.0), 0.0, 40.0))
        wind_to_cf = float(np.clip(context.get("wind_to_cf",   0.0), -1.0, 1.0))
        temp_adj = _WEATHER_TEMP_COEFFICIENT * (temp - _WEATHER_TEMP_BASELINE)
        wind_fraction = min(wind_speed / 15.0, 1.0)
        wind_adj = (
            wind_to_cf * wind_fraction * _WEATHER_WIND_OUT_BOOST
            if wind_to_cf >= 0
            else wind_to_cf * wind_fraction * _WEATHER_WIND_IN_REDUCTION
        )
        total_adj = temp_adj + wind_adj
        if abs(total_adj) < 1e-6:
            return probs
        probs = probs.copy()
        probs[_HR_IDX] = max(_PROB_MIN, probs[_HR_IDX] * (1.0 + total_adj))
        total = probs.sum()
        if total > 0.0:
            probs /= total
        return probs


class MatchupModel:
    def __init__(self, model_path: Optional[str | Path] = None, use_ml: bool = True) -> None:
        self.use_ml       = use_ml
        self._odds_model  = OddsRatioModel()
        self._trained_model: Optional[TrainedMatchupModel] = None
        self._active_model: str = "odds_ratio"
        if use_ml and _LGBM_AVAILABLE:
            trained = TrainedMatchupModel(model_path=model_path)
            if trained.is_loaded:
                self._trained_model = trained
                self._active_model  = "trained_lgbm"
        elif use_ml and not _LGBM_AVAILABLE:
            log.warning("use_ml=True but LightGBM is not installed. Falling back to OddsRatioModel.")

    @property
    def active_model(self) -> str:
        return self._active_model

    def predict_pa_probs(self, pitcher_stats: dict, batter_stats: dict, context: dict, features: Optional[np.ndarray] = None) -> dict[str, float]:
        if (self._active_model == "trained_lgbm" and self._trained_model is not None and features is not None):
            try:
                return self._trained_model.predict_pa_probs(features)
            except Exception as exc:
                log.warning("TrainedMatchupModel raised %s; falling back to OddsRatioModel.", exc)
        return self._odds_model.predict_pa_probs(pitcher_stats, batter_stats, context)

    def explain_prediction(self, pitcher_stats: dict, batter_stats: dict, context: dict) -> dict:
        odds = self._odds_model
        pitcher_pa = int(pitcher_stats.get("sample_pa", _PA_PARTIAL))
        batter_pa  = int(batter_stats.get("sample_pa", _PA_PARTIAL))
        confidence = _confidence_from_sample(pitcher_pa, batter_pa)
        base_arr = self._compute_base_probs(pitcher_stats, batter_stats)
        after_park    = odds._apply_park_factors(base_arr.copy(), context)
        after_platoon = odds._apply_platoon(after_park.copy(), batter_stats, context)
        after_umpire  = odds._apply_umpire(after_platoon.copy(), context)
        after_framing = odds._apply_catcher_framing(after_umpire.copy(), context)
        after_weather = odds._apply_weather(after_framing.copy(), context)
        base_norm    = _clip_and_normalise(base_arr.copy())
        park_norm    = _clip_and_normalise(after_park.copy())
        platoon_norm = _clip_and_normalise(after_platoon.copy())
        umpire_norm  = _clip_and_normalise(after_umpire.copy())
        framing_norm = _clip_and_normalise(after_framing.copy())
        final_norm   = _clip_and_normalise(after_weather.copy())
        outcomes_explanation: dict = {}
        batter_hand  = str(batter_stats.get("hand", "R")).upper()
        pitcher_hand = str(context.get("pitcher_hand", "R")).upper()
        has_plat = bool(context.get("platoon_advantage", (batter_hand == "S") or (batter_hand != pitcher_hand)))
        def _direction(delta: float) -> str:
            if delta > 0.0005: return "up"
            if delta < -0.0005: return "down"
            return "neutral"
        for i, outcome in enumerate(MODEL_OUTCOMES):
            base_p  = float(base_norm[i])
            final_p = float(final_norm[i])
            outcomes_explanation[outcome] = {
                "base_prob": round(base_p, 5),
                "final_prob": round(final_p, 5),
                "delta": round(final_p - base_p, 5),
            }
        return {
            "outcomes":     outcomes_explanation,
            "confidence":   round(confidence, 3),
            "active_model": self._active_model,
        }

    def _compute_base_probs(self, pitcher_stats: dict, batter_stats: dict) -> np.ndarray:
        pitcher_pa = int(pitcher_stats.get("sample_pa", _PA_PARTIAL))
        batter_pa  = int(batter_stats.get("sample_pa",  _PA_PARTIAL))
        pitcher_rates = np.zeros(NUM_OUTCOMES, dtype=np.float64)
        batter_rates  = np.zeros(NUM_OUTCOMES, dtype=np.float64)
        for i, outcome in enumerate(MODEL_OUTCOMES):
            key    = f"{outcome}_rate"
            lg_avg = LEAGUE_AVG_RATES[outcome]
            p_raw  = float(np.clip(pitcher_stats.get(key, lg_avg), 0.0, 1.0))
            b_raw  = float(np.clip(batter_stats.get(key,  lg_avg), 0.0, 1.0))
            pitcher_rates[i] = _regress_toward_league(p_raw, outcome, pitcher_pa)
            batter_rates[i]  = _regress_toward_league(b_raw, outcome, batter_pa)
        safe_league = np.where(_LEAGUE_RATES_ARRAY > 0.0, _LEAGUE_RATES_ARRAY, 1e-9)
        batter_rel  = batter_rates / safe_league
        b_sum       = batter_rel.sum()
        if b_sum <= 0.0:
            batter_rel = np.ones(NUM_OUTCOMES, dtype=np.float64)
            b_sum = float(NUM_OUTCOMES)
        x_prime    = batter_rel / b_sum
        numerators = x_prime * pitcher_rates
        denom      = numerators.sum()
        return (numerators / denom) if denom > 0.0 else _LEAGUE_RATES_ARRAY.copy()
