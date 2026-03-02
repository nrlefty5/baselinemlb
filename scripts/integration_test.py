"""
integration_test.py
-------------------
End-to-end integration test for the BaselineMLB Monte Carlo simulator pipeline.

Performs a full dry-run of every stage without touching external APIs or
credentials:
  1. Synthetic Statcast data generation (50 plate appearances)
  2. Training dataset construction
  3. XGBoost matchup model training
  4. Monte Carlo simulation for one fake game
  5. Prop calculator execution on simulation results
  6. Output-format verification (keys, dtypes)
  7. Supabase row-format validation (schema contract check, no upload)

Exit codes:
  0  - all steps passed
  1  - one or more steps failed

Usage:
  python scripts/integration_test.py
"""

from __future__ import annotations

import logging
import os
import random
import sys
import time
import traceback
from typing import Any

import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# Ensure project root is on the path so sibling packages resolve correctly.
# When running from the repo root:  python scripts/integration_test.py
# When running from scripts/:       python integration_test.py
# ---------------------------------------------------------------------------
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
N_PLATE_APPEARANCES = 50
N_SIMULATIONS = 500          # small number for speed during testing
LINEUP_SIZE = 9
RANDOM_SEED = 42
random.seed(RANDOM_SEED)
np.random.seed(RANDOM_SEED)

# Expected output keys for downstream contract validation
SIM_RESULT_REQUIRED_KEYS = {
    "player_id", "player_name", "stat_type",
    "sim_mean", "sim_median", "sim_std",
    "sim_p10", "sim_p25", "sim_p75", "sim_p90",
    "n_simulations",
}

SUPABASE_ROW_REQUIRED_KEYS = {
    "game_date", "game_pk", "player_id", "player_name",
    "stat_type", "sim_mean", "sim_median", "sim_std",
    "sim_p10", "sim_p25", "sim_p75", "sim_p90",
    "n_simulations", "model_version",
}

PROP_EDGE_REQUIRED_KEYS = {
    "player_id", "player_name", "stat_type",
    "prop_line", "over_prob", "under_prob",
    "edge_pct", "direction",
}


# ===========================================================================
# Synthetic data helpers
# ===========================================================================

def _make_player_ids(n: int = LINEUP_SIZE, prefix: str = "home") -> list[int]:
    """Return a list of fake MLB-style player IDs."""
    base = 600000 if prefix == "home" else 700000
    return [base + i for i in range(1, n + 1)]


def generate_synthetic_statcast(n: int = N_PLATE_APPEARANCES) -> pd.DataFrame:
    """
    Generate a synthetic Statcast-style DataFrame with ``n`` plate appearances.

    Columns mirror the real Statcast CSV export so that downstream feature
    engineering code does not need to be modified.

    Parameters
    ----------
    n:
        Number of plate appearance rows to generate.

    Returns
    -------
    pd.DataFrame
        Synthetic plate-appearance data with realistic column names and value
        ranges.
    """
    player_ids = _make_player_ids(10, "home") + _make_player_ids(10, "away")
    pitcher_ids = [800001, 800002, 800003]

    events = ["single", "double", "triple", "home_run", "strikeout",
              "walk", "field_out", "force_out", "grounded_into_double_play"]
    event_weights = [0.15, 0.05, 0.01, 0.03, 0.22, 0.08, 0.28, 0.10, 0.08]

    descriptions = ["called_strike", "swinging_strike", "ball", "foul",
                    "hit_into_play", "blocked_ball"]

    rng = np.random.default_rng(RANDOM_SEED)

    data = {
        "game_date": pd.date_range("2025-04-01", periods=n, freq="D").strftime("%Y-%m-%d").tolist(),
        "game_pk": rng.integers(700000, 800000, size=n).tolist(),
        "batter": rng.choice(player_ids, size=n).tolist(),
        "pitcher": rng.choice(pitcher_ids, size=n).tolist(),
        "events": random.choices(events, weights=event_weights, k=n),
        "description": random.choices(descriptions, k=n),
        "stand": rng.choice(["L", "R"], size=n).tolist(),
        "p_throws": rng.choice(["L", "R"], p=[0.28, 0.72], size=n).tolist(),
        "home_team": ["NYY"] * n,
        "away_team": ["BOS"] * n,
        "inning": rng.integers(1, 10, size=n).tolist(),
        "inning_topbot": rng.choice(["Top", "Bot"], size=n).tolist(),
        "balls": rng.integers(0, 4, size=n).tolist(),
        "strikes": rng.integers(0, 3, size=n).tolist(),
        "outs_when_up": rng.integers(0, 3, size=n).tolist(),
        "launch_speed": np.where(
            rng.random(n) > 0.35,
            rng.normal(90, 12, n),
            np.nan,
        ).tolist(),
        "launch_angle": np.where(
            rng.random(n) > 0.35,
            rng.normal(12, 25, n),
            np.nan,
        ).tolist(),
        "estimated_ba_using_speedangle": np.clip(rng.beta(2, 5, n), 0, 1).tolist(),
        "estimated_woba_using_speedangle": np.clip(rng.beta(2, 5, n), 0, 1).tolist(),
        "woba_value": np.clip(rng.exponential(0.3, n), 0, 2).tolist(),
        "babip_value": np.clip(rng.beta(3, 7, n), 0, 1).tolist(),
        "iso_value": np.clip(rng.exponential(0.08, n), 0, 0.6).tolist(),
        "release_speed": rng.normal(92, 5, n).tolist(),
        "release_spin_rate": rng.normal(2250, 300, n).tolist(),
        "pfx_x": rng.normal(0, 6, n).tolist(),
        "pfx_z": rng.normal(8, 4, n).tolist(),
    }

    df = pd.DataFrame(data)
    logger.info("Generated synthetic Statcast data: %d rows, %d columns", len(df), len(df.columns))
    return df


def build_training_dataset(statcast_df: pd.DataFrame) -> tuple[pd.DataFrame, pd.Series]:
    """
    Build a minimal training feature matrix and target series from raw
    Statcast plate-appearance data.

    Parameters
    ----------
    statcast_df:
        Raw synthetic Statcast DataFrame produced by
        :func:`generate_synthetic_statcast`.

    Returns
    -------
    (X, y)
        Feature matrix and binary target (1 = reached base, 0 = out).
    """
    df = statcast_df.copy()

    # Binary target: did the batter reach base?
    on_base_events = {"single", "double", "triple", "home_run", "walk"}
    df["target"] = df["events"].isin(on_base_events).astype(int)

    # Encode categorical features
    df["stand_enc"] = (df["stand"] == "R").astype(int)
    df["p_throws_enc"] = (df["p_throws"] == "R").astype(int)
    df["inning_topbot_enc"] = (df["inning_topbot"] == "Top").astype(int)

    feature_cols = [
        "stand_enc", "p_throws_enc", "inning_topbot_enc",
        "balls", "strikes", "outs_when_up", "inning",
        "release_speed", "release_spin_rate",
        "estimated_ba_using_speedangle",
        "estimated_woba_using_speedangle",
    ]

    X = df[feature_cols].fillna(df[feature_cols].median())
    y = df["target"]

    logger.info("Training dataset: %d samples, %d features", len(X), len(X.columns))
    return X, y


# ===========================================================================
# Lightweight stubs for modules that may not exist yet
# (allows the integration test to verify *logic* even before all modules land)
# ===========================================================================

class _StubMatchupModel:
    """Minimal stand-in if models.matchup_model is not yet importable."""

    def __init__(self) -> None:
        self.model_version = "stub-0.1"
        self._trained = False

    def train(self, X: pd.DataFrame, y: pd.Series, **kwargs: Any) -> None:
        import xgboost as xgb
        self._clf = xgb.XGBClassifier(
            n_estimators=10,
            max_depth=3,
            use_label_encoder=False,
            eval_metric="logloss",
            random_state=RANDOM_SEED,
        )
        self._clf.fit(X, y)
        self._trained = True
        logger.info("StubMatchupModel trained on %d samples", len(X))

    def predict_proba(self, X: pd.DataFrame) -> np.ndarray:
        if not self._trained:
            raise RuntimeError("Model not trained")
        return self._clf.predict_proba(X)


class _StubSimulator:
    """Minimal stand-in if simulator.monte_carlo_engine is not yet importable."""

    def __init__(self, n_sims: int = N_SIMULATIONS) -> None:
        self.n_sims = n_sims

    def simulate_game(
        self,
        home_lineup: list[dict],
        away_lineup: list[dict],
        matchup_model: Any,
    ) -> list[dict]:
        rng = np.random.default_rng(RANDOM_SEED)
        results = []
        for lineup in (home_lineup, away_lineup):
            for player in lineup:
                for stat in ("hits", "total_bases", "strikeouts", "walks"):
                    samples = rng.poisson(0.8 if stat != "strikeouts" else 1.1, self.n_sims)
                    results.append({
                        "player_id": player["player_id"],
                        "player_name": player["player_name"],
                        "stat_type": stat,
                        "sim_mean": float(np.mean(samples)),
                        "sim_median": float(np.median(samples)),
                        "sim_std": float(np.std(samples)),
                        "sim_p10": float(np.percentile(samples, 10)),
                        "sim_p25": float(np.percentile(samples, 25)),
                        "sim_p75": float(np.percentile(samples, 75)),
                        "sim_p90": float(np.percentile(samples, 90)),
                        "n_simulations": self.n_sims,
                        "_samples": samples,   # internal; stripped before upload
                    })
        return results


class _StubPropCalculator:
    """Minimal stand-in if simulator.prop_calculator is not yet importable."""

    def calculate_edges(
        self,
        sim_results: list[dict],
        prop_lines: dict[tuple[int, str], float],
    ) -> list[dict]:
        edges = []
        for row in sim_results:
            key = (row["player_id"], row["stat_type"])
            line = prop_lines.get(key)
            if line is None:
                continue
            samples = row.get("_samples")
            if samples is None:
                over_prob = 0.50
            else:
                over_prob = float(np.mean(samples > line))
            under_prob = 1.0 - over_prob
            book_over = 0.5238   # -110 juice
            edge_pct = over_prob - book_over
            direction = "over" if edge_pct > 0 else "under"
            kelly = max(0.0, edge_pct / (1 - book_over))
            edges.append({
                "player_id": row["player_id"],
                "player_name": row["player_name"],
                "stat_type": row["stat_type"],
                "prop_line": line,
                "over_prob": round(over_prob, 4),
                "under_prob": round(under_prob, 4),
                "book_implied_over": book_over,
                "book_implied_under": 1 - book_over,
                "edge_pct": round(edge_pct, 4),
                "direction": direction,
                "kelly_fraction": round(kelly, 4),
                "confidence": round(min(abs(edge_pct) * 4, 1.0), 3),
            })
        return edges


def _try_real_import() -> tuple[Any, Any, Any]:
    """Attempt to import real modules; fall back to stubs gracefully."""
    matchup_cls = prop_cls = sim_cls = None

    try:
        from models.matchup_model import MatchupModel  # type: ignore
        matchup_cls = MatchupModel
        logger.info("Imported real MatchupModel")
    except ImportError:
        logger.warning("models.matchup_model not found – using stub")
        matchup_cls = _StubMatchupModel

    try:
        from simulator.monte_carlo_engine import GameSimulator, SimulationConfig  # type: ignore
        sim_cls = GameSimulator
        logger.info("Imported real GameSimulator")
    except ImportError:
        logger.warning("simulator.monte_carlo_engine not found – using stub")
        sim_cls = _StubSimulator

    try:
        from simulator.prop_calculator import PropCalculator  # type: ignore
        prop_cls = PropCalculator
        logger.info("Imported real PropCalculator")
    except ImportError:
        logger.warning("simulator.prop_calculator not found – using stub")
        prop_cls = _StubPropCalculator

    return matchup_cls, sim_cls, prop_cls


def _build_fake_lineup(player_ids: list[int], prefix: str = "home") -> list[dict]:
    """Return a 9-player lineup list suitable for the simulator."""
    return [
        {
            "player_id": pid,
            "player_name": f"{prefix.capitalize()}Player{i + 1}",
            "batting_order": i + 1,
            "stand": random.choice(["L", "R"]),
        }
        for i, pid in enumerate(player_ids[:LINEUP_SIZE])
    ]


def _build_fake_prop_lines(
    home_ids: list[int],
    away_ids: list[int],
) -> dict[tuple[int, str], float]:
    """Build a dict of (player_id, stat_type) -> prop_line for testing."""
    prop_lines: dict[tuple[int, str], float] = {}
    for pid in home_ids + away_ids:
        prop_lines[(pid, "hits")] = 0.5
        prop_lines[(pid, "total_bases")] = 1.5
        prop_lines[(pid, "strikeouts")] = 0.5
    return prop_lines


def _format_supabase_rows(
    sim_results: list[dict],
    game_date: str,
    game_pk: int,
    model_version: str,
) -> list[dict]:
    """Strip internal keys and add DB-required fields."""
    rows = []
    for r in sim_results:
        row = {k: v for k, v in r.items() if not k.startswith("_")}
        row["game_date"] = game_date
        row["game_pk"] = game_pk
        row["model_version"] = model_version
        rows.append(row)
    return rows


# ===========================================================================
# Test steps
# ===========================================================================

class TestResult:
    def __init__(self, name: str) -> None:
        self.name = name
        self.passed: bool = False
        self.elapsed: float = 0.0
        self.error: str = ""


def run_step(name: str, fn) -> TestResult:
    result = TestResult(name)
    t0 = time.perf_counter()
    try:
        fn()
        result.passed = True
        logger.info("PASS  %s", name)
    except Exception as exc:
        result.error = traceback.format_exc()
        logger.error("FAIL  %s  –  %s", name, exc)
    result.elapsed = time.perf_counter() - t0
    return result


def main() -> int:
    """Run all integration test steps and return exit code."""
    logger.info("=" * 60)
    logger.info("BaselineMLB Monte Carlo Simulator – Integration Test")
    logger.info("=" * 60)

    MatchupModel, SimulatorCls, PropCalculatorCls = _try_real_import()

    # Shared state mutated across step closures
    state: dict[str, Any] = {}

    # ------------------------------------------------------------------
    # Step 1 – Generate synthetic Statcast data
    # ------------------------------------------------------------------
    def step1_generate_data() -> None:
        df = generate_synthetic_statcast(N_PLATE_APPEARANCES)
        assert isinstance(df, pd.DataFrame), "Expected a DataFrame"
        assert len(df) == N_PLATE_APPEARANCES, f"Expected {N_PLATE_APPEARANCES} rows, got {len(df)}"
        required_cols = {"game_date", "batter", "pitcher", "events", "release_speed"}
        missing = required_cols - set(df.columns)
        assert not missing, f"Missing columns: {missing}"
        state["statcast_df"] = df

    # ------------------------------------------------------------------
    # Step 2 – Build training dataset
    # ------------------------------------------------------------------
    def step2_build_dataset() -> None:
        assert "statcast_df" in state, "statcast_df not available from step 1"
        X, y = build_training_dataset(state["statcast_df"])
        assert isinstance(X, pd.DataFrame), "X must be a DataFrame"
        assert isinstance(y, pd.Series), "y must be a Series"
        assert len(X) == len(y), "X and y must have equal length"
        assert X.isnull().sum().sum() == 0, "Feature matrix contains NaNs"
        assert set(y.unique()).issubset({0, 1}), "Target must be binary"
        state["X"] = X
        state["y"] = y

    # ------------------------------------------------------------------
    # Step 3 – Train XGBoost matchup model
    # ------------------------------------------------------------------
    def step3_train_model() -> None:
        model = MatchupModel()
        model.train(state["X"], state["y"])
        state["model"] = model
        # Quick sanity: predict on the same training data
        probas = model.predict_proba(state["X"])
        assert probas.shape == (len(state["X"]), 2), (
            f"Expected shape ({len(state['X'])}, 2), got {probas.shape}"
        )
        assert np.allclose(probas.sum(axis=1), 1.0, atol=1e-5), "Probabilities must sum to 1"

    # ------------------------------------------------------------------
    # Step 4 – Run Monte Carlo simulation
    # ------------------------------------------------------------------
    def step4_run_simulation() -> None:
        home_ids = _make_player_ids(LINEUP_SIZE, "home")
        away_ids = _make_player_ids(LINEUP_SIZE, "away")
        home_lineup = _build_fake_lineup(home_ids, "home")
        away_lineup = _build_fake_lineup(away_ids, "away")

        simulator = SimulatorCls(n_sims=N_SIMULATIONS)
        results = simulator.simulate_game(
            home_lineup=home_lineup,
            away_lineup=away_lineup,
            matchup_model=state["model"],
        )
        assert isinstance(results, list), "simulate_game must return a list"
        assert len(results) > 0, "Simulation returned no results"

        state["sim_results"] = results
        state["home_ids"] = home_ids
        state["away_ids"] = away_ids

    # ------------------------------------------------------------------
    # Step 5 – Run prop calculator
    # ------------------------------------------------------------------
    def step5_prop_calculator() -> None:
        prop_lines = _build_fake_prop_lines(
            state["home_ids"], state["away_ids"]
        )
        calc = PropCalculatorCls()
        edges = calc.calculate_edges(state["sim_results"], prop_lines)
        assert isinstance(edges, list), "calculate_edges must return a list"
        state["edges"] = edges

    # ------------------------------------------------------------------
    # Step 6 – Verify simulation output format
    # ------------------------------------------------------------------
    def step6_verify_sim_format() -> None:
        for row in state["sim_results"]:
            missing = SIM_RESULT_REQUIRED_KEYS - set(row.keys())
            assert not missing, f"sim_result row missing keys: {missing}"
            assert isinstance(row["sim_mean"], (int, float)), "sim_mean must be numeric"
            assert row["n_simulations"] > 0, "n_simulations must be positive"
            assert row["sim_p10"] <= row["sim_p25"] <= row["sim_p75"] <= row["sim_p90"], (
                "Percentile ordering violated"
            )

        for edge in state.get("edges", []):
            missing = PROP_EDGE_REQUIRED_KEYS - set(edge.keys())
            assert not missing, f"edge row missing keys: {missing}"
            assert 0.0 <= edge["over_prob"] <= 1.0, "over_prob out of [0,1]"
            assert abs(edge["over_prob"] + edge["under_prob"] - 1.0) < 1e-6, (
                "over_prob + under_prob must equal 1.0"
            )
            assert edge["direction"] in ("over", "under"), (
                f"Invalid direction: {edge['direction']}"
            )

    # ------------------------------------------------------------------
    # Step 7 – Verify Supabase upload format
    # ------------------------------------------------------------------
    def step7_verify_supabase_format() -> None:
        rows = _format_supabase_rows(
            state["sim_results"],
            game_date="2026-03-02",
            game_pk=748516,
            model_version="test-0.1",
        )
        assert len(rows) > 0, "No rows to validate"
        for row in rows:
            missing = SUPABASE_ROW_REQUIRED_KEYS - set(row.keys())
            assert not missing, f"Supabase row missing keys: {missing}"
            # No internal _keys should leak into the upload payload
            internal = [k for k in row if k.startswith("_")]
            assert not internal, f"Internal keys found in upload payload: {internal}"
            # game_pk must be an int
            assert isinstance(row["game_pk"], int), "game_pk must be int"
            # Numeric precision sanity
            assert isinstance(row["sim_mean"], float), "sim_mean must be float"

    # ------------------------------------------------------------------
    # Execute all steps
    # ------------------------------------------------------------------
    steps = [
        ("Step 1 – Generate synthetic Statcast data", step1_generate_data),
        ("Step 2 – Build training dataset",           step2_build_dataset),
        ("Step 3 – Train XGBoost matchup model",      step3_train_model),
        ("Step 4 – Run Monte Carlo simulation",       step4_run_simulation),
        ("Step 5 – Run prop calculator",              step5_prop_calculator),
        ("Step 6 – Verify simulation output format",  step6_verify_sim_format),
        ("Step 7 – Verify Supabase upload format",    step7_verify_supabase_format),
    ]

    results: list[TestResult] = []
    for name, fn in steps:
        results.append(run_step(name, fn))

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------
    logger.info("")
    logger.info("=" * 60)
    logger.info("INTEGRATION TEST SUMMARY")
    logger.info("=" * 60)
    any_fail = False
    for r in results:
        status = "PASS" if r.passed else "FAIL"
        logger.info("  [%s]  %s  (%.3fs)", status, r.name, r.elapsed)
        if not r.passed:
            any_fail = True
            logger.error("         Error: %s", r.error.strip().splitlines()[-1])

    logger.info("=" * 60)
    if any_fail:
        logger.error("Result: FAILED (%d/%d steps passed)", sum(r.passed for r in results), len(results))
        return 1
    logger.info("Result: ALL %d STEPS PASSED", len(results))
    return 0


if __name__ == "__main__":
    sys.exit(main())
