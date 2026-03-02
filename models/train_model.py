"""
models/train_model.py
=====================
End-to-end training orchestration script for the BaselineMLB XGBoost matchup model.

Reads pre-built CSV datasets, trains a MatchupModel, evaluates on a held-out test
set, saves SHAP importances, and writes a comprehensive training report.

Expected data layout
--------------------
    <data_dir>/train_matchups.csv   -- training rows
    <data_dir>/test_matchups.csv    -- test rows

Both CSVs must contain all columns listed in matchup_model.ALL_FEATURES plus an
``outcome`` column with string labels from matchup_model.OUTCOME_CLASSES.

Usage
-----
    python -m models.train_model
    python -m models.train_model --data-dir data/ --output-dir models/trained/
    python -m models.train_model --data-dir data/ --output-dir models/trained/ --val-split 0.15
"""

import argparse
import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
from sklearn.metrics import (
    accuracy_score,
    classification_report,
    confusion_matrix,
    log_loss,
)

# Local import -- works when run as `python -m models.train_model` or directly
try:
    from models.matchup_model import ALL_FEATURES, OUTCOME_CLASSES, MatchupModel
except ImportError:
    from matchup_model import ALL_FEATURES, OUTCOME_CLASSES, MatchupModel

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

LABEL_COL: str = "outcome"
DEFAULT_DATA_DIR: str = "data"
DEFAULT_OUTPUT_DIR: str = "models/trained"
DEFAULT_VAL_SPLIT: float = 0.15  # fraction of *training* data held out for early stopping
RANDOM_SEED: int = 42


# ---------------------------------------------------------------------------
# Data loading helpers
# ---------------------------------------------------------------------------

def load_dataset(csv_path: str) -> Tuple[pd.DataFrame, pd.Series]:
    """Load a matchup CSV and return features + labels.

    Args:
        csv_path: Path to a CSV file containing ALL_FEATURES columns and an
                  ``outcome`` column.

    Returns:
        Tuple of (X, y) where X is the feature DataFrame and y is the label Series.

    Raises:
        FileNotFoundError: If *csv_path* does not exist.
        ValueError: If required columns are absent.
    """
    path = Path(csv_path)
    if not path.exists():
        raise FileNotFoundError(f"Dataset not found: {path}")

    df = pd.read_csv(path)
    logger.info("Loaded %d rows from %s", len(df), path)

    required = ALL_FEATURES + [LABEL_COL]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(f"Missing columns in {path}: {missing}")

    X = df[ALL_FEATURES].copy()
    y = df[LABEL_COL].copy()
    return X, y


def train_val_split(
    X: pd.DataFrame,
    y: pd.Series,
    val_fraction: float,
    seed: int = RANDOM_SEED,
) -> Tuple[pd.DataFrame, pd.Series, pd.DataFrame, pd.Series]:
    """Split training data into a train and validation subset.

    Args:
        X: Feature DataFrame.
        y: Label Series.
        val_fraction: Proportion of rows to use as validation (0 < val_fraction < 1).
        seed: Random seed for reproducibility.

    Returns:
        Tuple of (X_train, y_train, X_val, y_val).
    """
    rng = np.random.default_rng(seed)
    n = len(X)
    val_n = max(1, int(n * val_fraction))
    indices = rng.permutation(n)
    val_idx = indices[:val_n]
    train_idx = indices[val_n:]

    return (
        X.iloc[train_idx].reset_index(drop=True),
        y.iloc[train_idx].reset_index(drop=True),
        X.iloc[val_idx].reset_index(drop=True),
        y.iloc[val_idx].reset_index(drop=True),
    )


# ---------------------------------------------------------------------------
# Evaluation helpers
# ---------------------------------------------------------------------------

def evaluate_model(
    model: MatchupModel,
    X: pd.DataFrame,
    y: pd.Series,
    split_name: str = "test",
) -> Dict[str, Any]:
    """Run full evaluation on a held-out split and return a metrics dict.

    Computes accuracy, per-class precision/recall/F1, confusion matrix, and
    log-loss over the provided split.

    Args:
        model: A fitted MatchupModel instance.
        X: Feature DataFrame.
        y: Ground-truth label Series (string outcomes).
        split_name: Label used in log messages (e.g. ``"test"``).

    Returns:
        Dict containing all computed metrics serialisable to JSON.
    """
    proba = model.predict_proba(X)
    preds_idx = np.argmax(proba, axis=1)
    preds_str = [OUTCOME_CLASSES[i] for i in preds_idx]

    le = model.label_encoder
    y_enc = le.transform(y)

    acc = float(accuracy_score(y_enc, preds_idx))
    ll = float(log_loss(y_enc, proba, labels=list(range(len(OUTCOME_CLASSES)))))

    report = classification_report(
        y,
        preds_str,
        labels=OUTCOME_CLASSES,
        output_dict=True,
        zero_division=0,
    )

    cm = confusion_matrix(y, preds_str, labels=OUTCOME_CLASSES).tolist()

    logger.info("[%s] accuracy=%.4f  log_loss=%.4f", split_name, acc, ll)
    return {
        "split": split_name,
        "n_samples": int(len(X)),
        "accuracy": acc,
        "log_loss": ll,
        "classification_report": report,
        "confusion_matrix": {
            "labels": OUTCOME_CLASSES,
            "matrix": cm,
        },
    }


def compute_shap_importances(
    model: MatchupModel,
    X_sample: pd.DataFrame,
    output_path: str,
) -> Dict[str, Any]:
    """Compute and persist SHAP feature importances.

    Args:
        model: A fitted MatchupModel instance.
        X_sample: Subset of features to explain (e.g. first 500 rows of test set).
        output_path: JSON file path where importances will be written.

    Returns:
        Dict with ``feature_names``, ``mean_abs_shap``, and ``per_class`` keys.
    """
    logger.info("Computing SHAP importances on %d rows ...", len(X_sample))
    shap_info = model.explain(X_sample)

    # Drop raw shap_values array -- not JSON-serialisable
    payload = {
        "feature_names": shap_info["feature_names"],
        "mean_abs_shap": shap_info["mean_abs_shap"],
        "per_class": shap_info["per_class"],
    }

    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as fh:
        json.dump(payload, fh, indent=2)
    logger.info("SHAP importances saved to %s", path)
    return payload


# ---------------------------------------------------------------------------
# Report formatting
# ---------------------------------------------------------------------------

def format_summary_table(
    train_metrics: Dict[str, Any],
    test_metrics: Dict[str, Any],
    shap_payload: Dict[str, Any],
) -> str:
    """Build a human-readable summary table for stdout.

    Args:
        train_metrics: Evaluation dict from evaluate_model() on training data.
        test_metrics: Evaluation dict from evaluate_model() on test data.
        shap_payload: SHAP dict from compute_shap_importances().

    Returns:
        Multi-line formatted string suitable for printing.
    """
    sep = "=" * 60

    lines: List[str] = [
        sep,
        "  BaselineMLB XGBoost Matchup Model -- Training Summary",
        sep,
        f"  {'Metric':<25s}  {'Train':>10s}  {'Test':>10s}",
        f"  {'-'*25}  {'-'*10}  {'-'*10}",
        f"  {'Accuracy':<25s}  {train_metrics['accuracy']:>10.4f}  {test_metrics['accuracy']:>10.4f}",
        f"  {'Log Loss':<25s}  {train_metrics['log_loss']:>10.4f}  {test_metrics['log_loss']:>10.4f}",
        sep,
        "  Per-Class Test F1",
        f"  {'-'*25}",
    ]

    cls_report = test_metrics["classification_report"]
    for cls_name in OUTCOME_CLASSES:
        if cls_name in cls_report:
            f1 = cls_report[cls_name]["f1-score"]
            support = cls_report[cls_name]["support"]
            lines.append(f"  {cls_name:<10s}  F1={f1:.3f}  support={int(support)}")

    lines += [
        sep,
        "  Top-10 Features by Mean |SHAP|",
        f"  {'-'*45}",
    ]
    pairs = sorted(
        zip(shap_payload["feature_names"], shap_payload["mean_abs_shap"]),
        key=lambda x: x[1],
        reverse=True,
    )
    for rank, (fname, imp) in enumerate(pairs[:10], start=1):
        lines.append(f"  {rank:>2d}. {fname:<32s}  {imp:.5f}")

    lines.append(sep)
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main training orchestrator
# ---------------------------------------------------------------------------

def run_training(
    data_dir: str,
    output_dir: str,
    val_split: float,
    shap_sample_size: int,
) -> None:
    """Orchestrate end-to-end model training, evaluation, and artefact writing.

    Args:
        data_dir: Directory containing ``train_matchups.csv`` and
                  ``test_matchups.csv``.
        output_dir: Directory where the trained model and reports will be written.
        val_split: Fraction of training rows to reserve for early-stopping validation.
        shap_sample_size: Number of test rows used for SHAP explanation (caps at
                          actual test size).
    """
    start_ts = time.time()
    logger.info("Starting training run -- data_dir=%s  output_dir=%s", data_dir, output_dir)

    # ---- Load data -------------------------------------------------------
    train_csv = os.path.join(data_dir, "train_matchups.csv")
    test_csv = os.path.join(data_dir, "test_matchups.csv")
    X_all_train, y_all_train = load_dataset(train_csv)
    X_test, y_test = load_dataset(test_csv)

    # ---- Train / val split -----------------------------------------------
    X_train, y_train, X_val, y_val = train_val_split(X_all_train, y_all_train, val_split)
    logger.info(
        "Split: train=%d  val=%d  test=%d",
        len(X_train), len(X_val), len(X_test),
    )

    # ---- Instantiate and train -------------------------------------------
    model = MatchupModel()
    model.fit(X_train, y_train, X_val, y_val)

    # ---- Evaluate --------------------------------------------------------
    # Use full train (train+val) for train metrics reporting
    train_metrics = evaluate_model(model, X_all_train, y_all_train, split_name="train")
    test_metrics = evaluate_model(model, X_test, y_test, split_name="test")

    # ---- SHAP ------------------------------------------------------------
    sample_n = min(shap_sample_size, len(X_test))
    shap_path = os.path.join(output_dir, "shap_importances.json")
    shap_payload = compute_shap_importances(model, X_test.head(sample_n), shap_path)

    # ---- Save model ------------------------------------------------------
    model_path = os.path.join(output_dir, "matchup_model.joblib")
    model.save(model_path)

    # ---- Write training report -------------------------------------------
    elapsed = time.time() - start_ts
    report = {
        "model_version": model.metadata.get("version"),
        "trained_at": model.metadata.get("trained_at"),
        "elapsed_seconds": round(elapsed, 2),
        "data": {
            "train_csv": train_csv,
            "test_csv": test_csv,
            "n_train": int(len(X_all_train)),
            "n_test": int(len(X_test)),
            "val_split": val_split,
        },
        "hyperparameters": model.hyperparams,
        "best_iteration": model.metadata.get("best_iteration"),
        "train_metrics": train_metrics,
        "test_metrics": test_metrics,
        "shap_importances_path": shap_path,
    }

    report_path = os.path.join(output_dir, "training_report.json")
    Path(report_path).parent.mkdir(parents=True, exist_ok=True)
    with open(report_path, "w") as fh:
        json.dump(report, fh, indent=2)
    logger.info("Training report saved to %s", report_path)

    # ---- Print summary ---------------------------------------------------
    summary = format_summary_table(train_metrics, test_metrics, shap_payload)
    print(summary)
    print(f"\n  Total training time: {elapsed:.1f}s")
    print(f"  Model saved to:      {model_path}")
    print(f"  Report saved to:     {report_path}")


# ---------------------------------------------------------------------------
# __main__
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Train the BaselineMLB XGBoost matchup model.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--data-dir",
        default=DEFAULT_DATA_DIR,
        help="Directory containing train_matchups.csv and test_matchups.csv",
    )
    parser.add_argument(
        "--output-dir",
        default=DEFAULT_OUTPUT_DIR,
        help="Directory where model artefacts (joblib, JSON) will be written",
    )
    parser.add_argument(
        "--val-split",
        type=float,
        default=DEFAULT_VAL_SPLIT,
        help="Fraction of training rows held out for early-stopping validation",
    )
    parser.add_argument(
        "--shap-sample-size",
        type=int,
        default=500,
        help="Number of test rows used for SHAP explanation",
    )
    args = parser.parse_args()

    try:
        run_training(
            data_dir=args.data_dir,
            output_dir=args.output_dir,
            val_split=args.val_split,
            shap_sample_size=args.shap_sample_size,
        )
    except FileNotFoundError as exc:
        logger.error("Data file not found: %s", exc)
        sys.exit(1)
    except ValueError as exc:
        logger.error("Data validation error: %s", exc)
        sys.exit(1)
