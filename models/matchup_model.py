"""
models/matchup_model.py
=======================
XGBoost multiclass classifier that predicts plate-appearance outcome probabilities
for pitcher-batter matchups in the BaselineMLB Monte Carlo simulator.

Outcome classes (8):
    0 = K    1 = BB   2 = 1B   3 = 2B   4 = 3B
    5 = HR   6 = HBP  7 = OUT

Usage
-----
    from models.matchup_model import MatchupModel

    model = MatchupModel()
    model.fit(X_train, y_train, X_val, y_val)
    proba = model.predict_proba(X)          # shape (n, 8)
    model.save("models/trained/matchup_model.joblib")

    loaded = MatchupModel.load("models/trained/matchup_model.joblib")
    importances = loaded.explain(X[:5])     # SHAP values per class
"""

import argparse
import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import joblib
import numpy as np
import pandas as pd
import shap
import xgboost as xgb
from sklearn.metrics import accuracy_score, log_loss
from sklearn.preprocessing import LabelEncoder

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

OUTCOME_CLASSES: List[str] = ["K", "BB", "1B", "2B", "3B", "HR", "HBP", "OUT"]

PITCHER_FEATURES: List[str] = [
    "career_k9",
    "career_bb9",
    "avg_velocity",
    "fb_pct",
    "sl_pct",
    "cu_pct",
    "ch_pct",
    "whiff_rate",
    "chase_rate",
    "zone_rate",
    "pitcher_hand_enc",
]

BATTER_FEATURES: List[str] = [
    "k_pct",
    "bb_pct",
    "iso",
    "woba",
    "avg_launch_angle",
    "avg_launch_speed",
    "chase_rate_batter",
    "whiff_rate_batter",
    "batter_hand_enc",
]

MATCHUP_FEATURES: List[str] = [
    "platoon_advantage",
    "prior_pa_count",
]

CONTEXT_FEATURES: List[str] = [
    "home_away_enc",
    "park_factor",
]

ALL_FEATURES: List[str] = (
    PITCHER_FEATURES + BATTER_FEATURES + MATCHUP_FEATURES + CONTEXT_FEATURES
)

DEFAULT_HYPERPARAMS: Dict[str, Any] = {
    "max_depth": 6,
    "n_estimators": 500,
    "learning_rate": 0.05,
    "min_child_weight": 5,
    "subsample": 0.8,
    "colsample_bytree": 0.8,
    "objective": "multi:softprob",
    "num_class": len(OUTCOME_CLASSES),
    "eval_metric": "mlogloss",
    "use_label_encoder": False,
    "verbosity": 0,
    "n_jobs": -1,
    "random_state": 42,
}

MODEL_VERSION: str = "1.0.0"


# ---------------------------------------------------------------------------
# Helper utilities
# ---------------------------------------------------------------------------

def encode_hand(series: pd.Series) -> pd.Series:
    """Encode pitcher/batter handedness: R -> 0, L -> 1, S -> 2.

    Args:
        series: Pandas Series containing 'R', 'L', or 'S' string values.

    Returns:
        Integer-encoded Series.
    """
    mapping = {"R": 0, "L": 1, "S": 2}
    return series.map(mapping).fillna(0).astype(int)


def encode_home_away(series: pd.Series) -> pd.Series:
    """Encode home/away indicator: home -> 1, away -> 0.

    Args:
        series: Pandas Series containing 'home' or 'away' string values.

    Returns:
        Integer-encoded Series (1 = home, 0 = away).
    """
    return (series.str.lower() == "home").astype(int)


def validate_features(df: pd.DataFrame) -> None:
    """Assert that all required model features are present in *df*.

    Args:
        df: Feature DataFrame to validate.

    Raises:
        ValueError: If any required column is missing.
    """
    missing = [col for col in ALL_FEATURES if col not in df.columns]
    if missing:
        raise ValueError(f"Missing required feature columns: {missing}")


# ---------------------------------------------------------------------------
# MatchupModel
# ---------------------------------------------------------------------------

class MatchupModel:
    """XGBoost multiclass classifier for plate-appearance outcome probabilities.

    The model predicts a probability distribution over 8 outcome classes
    (K, BB, 1B, 2B, 3B, HR, HBP, OUT) for every pitcher-batter matchup.

    Attributes:
        clf: Underlying XGBoost classifier (set after fit()).
        label_encoder: Maps string outcome labels to integer class indices.
        feature_names: Ordered list of feature columns used during training.
        metadata: Dict containing training date, metrics, and version info.
        hyperparams: Hyperparameter dict passed to XGBoost.
    """

    def __init__(self, hyperparams: Optional[Dict[str, Any]] = None) -> None:
        """Initialise the MatchupModel.

        Args:
            hyperparams: Optional dict of XGBoost hyperparameters.  Any keys
                provided will override the DEFAULT_HYPERPARAMS defaults.
        """
        self.hyperparams: Dict[str, Any] = {**DEFAULT_HYPERPARAMS, **(hyperparams or {})}
        self.clf: Optional[xgb.XGBClassifier] = None
        self.label_encoder: LabelEncoder = LabelEncoder()
        self.label_encoder.fit(OUTCOME_CLASSES)
        self.feature_names: List[str] = ALL_FEATURES
        self.metadata: Dict[str, Any] = {
            "version": MODEL_VERSION,
            "outcome_classes": OUTCOME_CLASSES,
            "features": ALL_FEATURES,
            "trained_at": None,
            "metrics": {},
        }

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def fit(
        self,
        X_train: pd.DataFrame,
        y_train: pd.Series,
        X_val: pd.DataFrame,
        y_val: pd.Series,
        early_stopping_rounds: int = 30,
    ) -> "MatchupModel":
        """Train the XGBoost classifier.

        Args:
            X_train: Training feature DataFrame with ALL_FEATURES columns.
            y_train: Training outcome labels (string values from OUTCOME_CLASSES).
            X_val: Validation feature DataFrame used for early stopping.
            y_val: Validation outcome labels.
            early_stopping_rounds: Stop training if validation mlogloss does not
                improve for this many consecutive rounds.

        Returns:
            self (for method chaining).
        """
        validate_features(X_train)
        validate_features(X_val)

        y_train_enc = self.label_encoder.transform(y_train)
        y_val_enc = self.label_encoder.transform(y_val)

        params = {k: v for k, v in self.hyperparams.items() if k != "n_estimators"}
        self.clf = xgb.XGBClassifier(
            n_estimators=self.hyperparams["n_estimators"],
            early_stopping_rounds=early_stopping_rounds,
            **params,
        )

        logger.info(
            "Fitting XGBoost: %d training rows, %d validation rows, %d features",
            len(X_train),
            len(X_val),
            len(self.feature_names),
        )

        self.clf.fit(
            X_train[self.feature_names],
            y_train_enc,
            eval_set=[(X_val[self.feature_names], y_val_enc)],
            verbose=False,
        )

        best_iter = self.clf.best_iteration
        logger.info("Training complete. Best iteration: %d", best_iter)

        # Compute training metrics
        train_proba = self.clf.predict_proba(X_train[self.feature_names])
        val_proba = self.clf.predict_proba(X_val[self.feature_names])

        train_preds = np.argmax(train_proba, axis=1)
        val_preds = np.argmax(val_proba, axis=1)

        self.metadata["trained_at"] = datetime.utcnow().isoformat()
        self.metadata["best_iteration"] = best_iter
        self.metadata["n_train"] = int(len(X_train))
        self.metadata["n_val"] = int(len(X_val))
        self.metadata["metrics"] = {
            "train_accuracy": float(accuracy_score(y_train_enc, train_preds)),
            "val_accuracy": float(accuracy_score(y_val_enc, val_preds)),
            "train_log_loss": float(log_loss(y_train_enc, train_proba)),
            "val_log_loss": float(log_loss(y_val_enc, val_proba)),
        }
        logger.info(
            "Val accuracy=%.4f  Val log-loss=%.4f",
            self.metadata["metrics"]["val_accuracy"],
            self.metadata["metrics"]["val_log_loss"],
        )
        return self

    def predict_proba(self, X: pd.DataFrame) -> np.ndarray:
        """Return per-class probability matrix for each row in *X*.

        Args:
            X: Feature DataFrame with ALL_FEATURES columns.

        Returns:
            NumPy array of shape (n_samples, 8) where each row sums to 1.0.
            Column order matches OUTCOME_CLASSES.

        Raises:
            RuntimeError: If the model has not been trained or loaded yet.
        """
        if self.clf is None:
            raise RuntimeError("Model has not been fitted. Call fit() or load() first.")
        validate_features(X)
        proba = self.clf.predict_proba(X[self.feature_names])
        # Guarantee rows sum to exactly 1.0 (handle floating-point drift)
        row_sums = proba.sum(axis=1, keepdims=True)
        return proba / row_sums

    def predict(self, X: pd.DataFrame) -> np.ndarray:
        """Return the most-likely outcome class index for each row.

        Args:
            X: Feature DataFrame with ALL_FEATURES columns.

        Returns:
            Array of integer class indices aligned with OUTCOME_CLASSES.
        """
        return np.argmax(self.predict_proba(X), axis=1)

    def predict_named(self, X: pd.DataFrame) -> List[str]:
        """Return the most-likely outcome class *name* for each row.

        Args:
            X: Feature DataFrame with ALL_FEATURES columns.

        Returns:
            List of outcome class strings, e.g. ['K', 'HR', 'OUT', ...].
        """
        indices = self.predict(X)
        return [OUTCOME_CLASSES[i] for i in indices]

    def explain(self, X: pd.DataFrame) -> Dict[str, Any]:
        """Compute SHAP feature importances using TreeExplainer.

        Args:
            X: Feature DataFrame to explain (can be a sample, e.g. 100 rows).

        Returns:
            Dict with keys:
                - "feature_names": ordered list of features
                - "mean_abs_shap": mean |SHAP| per feature across all classes (float list)
                - "per_class": dict mapping each outcome class name to its mean |SHAP| list
                - "shap_values": raw SHAP array, shape (n_classes, n_samples, n_features)
        """
        if self.clf is None:
            raise RuntimeError("Model has not been fitted. Call fit() or load() first.")

        explainer = shap.TreeExplainer(self.clf)
        shap_values = explainer.shap_values(X[self.feature_names])
        # shap_values: list of (n_samples, n_features) arrays, one per class
        n_classes = len(OUTCOME_CLASSES)
        if not isinstance(shap_values, list):
            shap_values = [shap_values]

        mean_abs = np.zeros(len(self.feature_names))
        per_class: Dict[str, List[float]] = {}
        for cls_idx, cls_name in enumerate(OUTCOME_CLASSES):
            if cls_idx < len(shap_values):
                arr = np.abs(shap_values[cls_idx])
                cls_mean = arr.mean(axis=0).tolist()
            else:
                cls_mean = [0.0] * len(self.feature_names)
            per_class[cls_name] = cls_mean
            mean_abs += np.array(cls_mean)

        mean_abs = (mean_abs / n_classes).tolist()

        return {
            "feature_names": self.feature_names,
            "mean_abs_shap": mean_abs,
            "per_class": per_class,
            "shap_values": shap_values,
        }

    def save(self, model_path: str) -> None:
        """Serialise model and metadata to disk.

        Writes two files:
            - <model_path>                      -> joblib binary (XGBClassifier + wrapper state)
            - <model_path>.meta.json            -> human-readable metadata sidecar

        Args:
            model_path: Destination path for the joblib file, e.g.
                        ``"models/trained/matchup_model.joblib"``.
        """
        if self.clf is None:
            raise RuntimeError("Nothing to save -- model has not been trained yet.")

        path = Path(model_path)
        path.parent.mkdir(parents=True, exist_ok=True)

        payload = {
            "clf": self.clf,
            "label_encoder": self.label_encoder,
            "feature_names": self.feature_names,
            "hyperparams": self.hyperparams,
            "metadata": self.metadata,
        }
        joblib.dump(payload, path)
        logger.info("Model saved to %s", path)

        meta_path = path.with_suffix(".joblib.meta.json")
        with open(meta_path, "w") as fh:
            json.dump(self.metadata, fh, indent=2)
        logger.info("Metadata sidecar saved to %s", meta_path)

    @classmethod
    def load(cls, model_path: str) -> "MatchupModel":
        """Deserialise a previously saved MatchupModel from disk.

        Args:
            model_path: Path to the joblib file written by :meth:`save`.

        Returns:
            A fully initialised MatchupModel ready for inference.

        Raises:
            FileNotFoundError: If *model_path* does not exist.
        """
        path = Path(model_path)
        if not path.exists():
            raise FileNotFoundError(f"Model file not found: {path}")

        payload = joblib.load(path)
        instance = cls(hyperparams=payload.get("hyperparams"))
        instance.clf = payload["clf"]
        instance.label_encoder = payload["label_encoder"]
        instance.feature_names = payload["feature_names"]
        instance.metadata = payload.get("metadata", instance.metadata)
        logger.info("Model loaded from %s (trained at %s)", path, instance.metadata.get("trained_at"))
        return instance


# ---------------------------------------------------------------------------
# __main__ -- quick smoke-test / demo
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="MatchupModel smoke-test with synthetic data")
    parser.add_argument("--rows", type=int, default=2000, help="Synthetic row count (default: 2000)")
    parser.add_argument(
        "--save-path",
        default="models/trained/matchup_model.joblib",
        help="Where to save the demo model",
    )
    args = parser.parse_args()

    rng = np.random.default_rng(0)
    n = args.rows

    # Build a minimal synthetic DataFrame that satisfies the feature schema
    data: Dict[str, Any] = {
        "career_k9": rng.uniform(5, 12, n),
        "career_bb9": rng.uniform(1, 5, n),
        "avg_velocity": rng.uniform(88, 98, n),
        "fb_pct": rng.uniform(0.3, 0.6, n),
        "sl_pct": rng.uniform(0.1, 0.35, n),
        "cu_pct": rng.uniform(0.05, 0.25, n),
        "ch_pct": rng.uniform(0.05, 0.25, n),
        "whiff_rate": rng.uniform(0.18, 0.42, n),
        "chase_rate": rng.uniform(0.25, 0.42, n),
        "zone_rate": rng.uniform(0.40, 0.58, n),
        "pitcher_hand_enc": rng.integers(0, 2, n),
        "k_pct": rng.uniform(0.12, 0.35, n),
        "bb_pct": rng.uniform(0.04, 0.15, n),
        "iso": rng.uniform(0.08, 0.28, n),
        "woba": rng.uniform(0.28, 0.42, n),
        "avg_launch_angle": rng.uniform(5, 20, n),
        "avg_launch_speed": rng.uniform(85, 95, n),
        "chase_rate_batter": rng.uniform(0.22, 0.40, n),
        "whiff_rate_batter": rng.uniform(0.18, 0.38, n),
        "batter_hand_enc": rng.integers(0, 3, n),
        "platoon_advantage": rng.integers(0, 2, n),
        "prior_pa_count": rng.integers(0, 200, n),
        "home_away_enc": rng.integers(0, 2, n),
        "park_factor": rng.uniform(0.88, 1.12, n),
    }
    df = pd.DataFrame(data)
    labels = rng.choice(OUTCOME_CLASSES, size=n, p=[0.22, 0.09, 0.14, 0.05, 0.01, 0.04, 0.01, 0.44])

    split = int(n * 0.8)
    X_tr, X_va = df.iloc[:split], df.iloc[split:]
    y_tr, y_va = pd.Series(labels[:split]), pd.Series(labels[split:])

    model = MatchupModel()
    model.fit(X_tr, y_tr, X_va, y_va)

    proba = model.predict_proba(X_va.head(5))
    print("\nSample predicted probabilities (first 5 rows):")
    print(pd.DataFrame(proba, columns=OUTCOME_CLASSES).to_string(index=False))

    model.save(args.save_path)

    # Reload and re-run
    m2 = MatchupModel.load(args.save_path)
    proba2 = m2.predict_proba(X_va.head(5))
    assert np.allclose(proba, proba2), "Round-trip save/load mismatch!"
    print("\nSave/load round-trip: PASSED")

    shap_info = m2.explain(X_va.head(50))
    print("\nTop-5 features by mean |SHAP|:")
    feat_imp = sorted(
        zip(shap_info["feature_names"], shap_info["mean_abs_shap"]),
        key=lambda x: x[1],
        reverse=True,
    )
    for fname, imp in feat_imp[:5]:
        print(f"  {fname:<30s}  {imp:.5f}")
