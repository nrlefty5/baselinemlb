#!/usr/bin/env python3
"""
build_training_dataset.py — Baseline MLB
Transform the Statcast PA-level parquet into the exact feature matrix
(X) and label vector (y) required for training the matchup probability
model (XGBoost / LightGBM).

The model predicts P(outcome | pitcher_features, batter_features, context)
where outcome ∈ {K, BB, HBP, 1B, 2B, 3B, HR, out}.

Usage:
    # Default: read from data/statcast_pa_features_2020_2025.parquet
    python pipeline/build_training_dataset.py

    # Custom input file
    python pipeline/build_training_dataset.py --input data/statcast_pa_features_2024_2024.parquet

    # Specify train/test split
    python pipeline/build_training_dataset.py --test-year 2025

    # Output binary outcome (K vs not-K) for strikeout model
    python pipeline/build_training_dataset.py --binary-target K

Output:
    data/training/X_train.parquet
    data/training/y_train.parquet
    data/training/X_test.parquet
    data/training/y_test.parquet
    data/training/feature_metadata.json
"""

import argparse
import json
import logging
import sys
from pathlib import Path

import pandas as pd

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("build_training_dataset")

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
TRAIN_DIR = DATA_DIR / "training"

# ── Outcome encoding ────────────────────────────────────────────────────────────────────────────
OUTCOME_LABELS = ["K", "BB", "HBP", "1B", "2B", "3B", "HR", "out"]
OUTCOME_TO_IDX = {label: idx for idx, label in enumerate(OUTCOME_LABELS)}

# ── Feature columns ────────────────────────────────────────────────────────────────────────────

# Pitcher features (all numeric)
PITCHER_FEATURES = [
    "p_avg_velo",
    "p_swstr_pct",
    "p_csw_pct",
    "p_zone_pct",
    "p_k_pct",
    "p_bb_pct",
    "p_gb_rate",
    "p_fb_rate",
    "p_ld_rate",
    "p_pct_fastball",
    "p_pct_slider",
    "p_pct_curve",
    "p_pct_change",
    "p_pct_cutter",
    "p_whiff_fastball",
    "p_whiff_slider",
    "p_whiff_curve",
    "p_whiff_change",
    "p_whiff_cutter",
]

# Batter features (all numeric)
BATTER_FEATURES = [
    "b_k_pct",
    "b_bb_pct",
    "b_xba",
    "b_xslg",
    "b_barrel_pct",
    "b_chase_rate",
    "b_whiff_pct",
    "b_avg_ev",
    "b_hard_hit_pct",
]

# Matchup features (engineered)
MATCHUP_FEATURES = [
    "platoon_same",       # 1 if same hand, 0 if opposite
    "platoon_opposite",   # 1 if opposite hand, 0 if same
    "p_throws_L",         # 1 if pitcher is LHP
    "b_stands_L",         # 1 if batter is LHB
]

# Context features
CONTEXT_FEATURES = [
    "park_factor_hr",
    "park_factor_hit",
    "temp_f",
    "wind_mph",
    "wind_out",           # binary: 1 = blowing out
    "umpire_k_delta",
    "umpire_bb_delta",
    "inning",
    "score_diff",
]

ALL_FEATURES = PITCHER_FEATURES + BATTER_FEATURES + MATCHUP_FEATURES + CONTEXT_FEATURES


def load_parquet(path: Path) -> pd.DataFrame:
    """Load a Statcast PA-level parquet file."""
    log.info(f"Loading {path} ...")
    df = pd.read_parquet(path)
    log.info(f"  Loaded {len(df):,} rows, {df.shape[1]} columns")
    return df


def filter_valid_rows(df: pd.DataFrame) -> pd.DataFrame:
    """Drop rows missing key identifiers or outcome."""
    before = len(df)
    df = df.dropna(subset=["pa_outcome", "pitcher_id", "batter_id"])
    log.info(f"  Dropped {before - len(df):,} rows missing outcome/IDs")
    return df


def encode_outcomes(df: pd.DataFrame) -> pd.DataFrame:
    """
    Map pa_outcome strings to integer class indices.
    Unmapped outcomes are coerced to 'out'.
    """
    df = df.copy()
    df["pa_outcome"] = df["pa_outcome"].apply(
        lambda x: x if x in OUTCOME_TO_IDX else "out"
    )
    df["label"] = df["pa_outcome"].map(OUTCOME_TO_IDX)
    return df


def engineer_platoon_features(df: pd.DataFrame) -> pd.DataFrame:
    """One-hot encode pitcher handedness and batter stance."""
    df = df.copy()
    df["p_throws_L"] = (df["p_throws"].str.upper() == "L").astype(int)
    df["b_stands_L"] = (df["b_stands"].str.upper() == "L").astype(int)
    df["platoon_same"] = (df["p_throws_L"] == df["b_stands_L"]).astype(int)
    df["platoon_opposite"] = 1 - df["platoon_same"]
    return df


def fill_missing_features(df: pd.DataFrame) -> pd.DataFrame:
    """Fill missing numeric feature values with column medians."""
    for col in ALL_FEATURES:
        if col in df.columns:
            missing = df[col].isna().sum()
            if missing > 0:
                median = df[col].median()
                df[col] = df[col].fillna(median)
                log.debug(f"  Filled {missing:,} NaNs in {col} with median={median:.4f}")
    return df


def split_train_test(
    df: pd.DataFrame,
    test_year: int | None = None,
    include_weights: bool = False,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """
    Split dataset into train/test.

    If test_year is specified, that season is held out as the test set.
    Otherwise, the most recent season is used.
    """
    if "game_year" not in df.columns:
        raise ValueError("DataFrame must contain a 'game_year' column for split.")

    years = sorted(df["game_year"].unique())
    test_yr = test_year or max(years)

    log.info(f"  Train years: {[y for y in years if y != test_yr]}")
    log.info(f"  Test year:   {test_yr}")

    train_df = df[df["game_year"] != test_yr].copy()
    test_df = df[df["game_year"] == test_yr].copy()

    feature_cols = [c for c in ALL_FEATURES if c in df.columns]

    X_train = train_df[feature_cols].reset_index(drop=True)
    y_train = train_df[["label"]].reset_index(drop=True)
    X_test = test_df[feature_cols].reset_index(drop=True)
    y_test = test_df[["label"]].reset_index(drop=True)

    if include_weights and "sample_weight" in train_df.columns:
        y_train["sample_weight"] = train_df["sample_weight"].values

    return X_train, y_train, X_test, y_test


def save_feature_metadata(feature_cols: list[str], outcome_labels: list[str]) -> None:
    """Save feature metadata JSON for use during inference."""
    TRAIN_DIR.mkdir(parents=True, exist_ok=True)
    meta = {
        "feature_columns": feature_cols,
        "outcome_labels": outcome_labels,
        "outcome_to_idx": OUTCOME_TO_IDX,
        "n_features": len(feature_cols),
        "n_classes": len(outcome_labels),
    }
    out_path = TRAIN_DIR / "feature_metadata.json"
    with open(out_path, "w") as f:
        json.dump(meta, f, indent=2)
    log.info(f"  Saved feature metadata to {out_path}")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Build training dataset for matchup model.")
    parser.add_argument(
        "--input", type=str, default=None,
        help="Path to input Statcast parquet file. Defaults to data/statcast_pa_features_2020_2025.parquet."
    )
    parser.add_argument(
        "--test-year", type=int, default=None,
        help="Season to hold out as test set (default: most recent)."
    )
    parser.add_argument(
        "--binary-target", type=str, default=None,
        help="If specified, output binary labels: 1 = this outcome, 0 = everything else."
    )
    parser.add_argument(
        "--include-weights", action="store_true",
        help="Include sample_weight column in y_train if available."
    )
    parser.add_argument(
        "--output-dir", type=str, default=None,
        help="Output directory for parquet files. Defaults to data/training/."
    )
    args = parser.parse_args(argv)

    # Resolve input path
    input_path = Path(args.input) if args.input else DATA_DIR / "statcast_pa_features_2020_2025.parquet"
    if not input_path.exists():
        log.error(f"Input file not found: {input_path}")
        sys.exit(1)

    # Override output dir if specified
    out_dir = Path(args.output_dir) if args.output_dir else TRAIN_DIR
    out_dir.mkdir(parents=True, exist_ok=True)

    # Load
    df = load_parquet(input_path)

    # Clean
    df = filter_valid_rows(df)
    df = encode_outcomes(df)
    df = engineer_platoon_features(df)
    df = fill_missing_features(df)

    log.info(f"Dataset after cleaning: {len(df):,} rows")
    log.info(f"Outcome distribution:\n{df['pa_outcome'].value_counts()}")

    # Binary target override
    if args.binary_target:
        valid_targets = set(OUTCOME_LABELS)
        if args.binary_target not in valid_targets:
            log.error(f"Invalid binary target '{args.binary_target}'. Must be one of {sorted(valid_targets)}.")
            sys.exit(1)
        target_idx = OUTCOME_TO_IDX[args.binary_target]
        df["label"] = (df["label"] == target_idx).astype(int)
        log.info(f"Binary target: {args.binary_target} (1) vs rest (0). Positive rate: {df['label'].mean():.3f}")

    # Split
    X_train, y_train, X_test, y_test = split_train_test(
        df, test_year=args.test_year, include_weights=args.include_weights
    )
    log.info(f"Train size: {len(X_train):,}  Test size: {len(X_test):,}")

    # Save
    X_train.to_parquet(out_dir / "X_train.parquet", index=False)
    y_train.to_parquet(out_dir / "y_train.parquet", index=False)
    X_test.to_parquet(out_dir / "X_test.parquet", index=False)
    y_test.to_parquet(out_dir / "y_test.parquet", index=False)
    log.info(f"Saved X_train, y_train, X_test, y_test to {out_dir}/")

    feature_cols = [c for c in ALL_FEATURES if c in df.columns]
    save_feature_metadata(feature_cols, OUTCOME_LABELS)

    log.info("=== Dataset build complete ===")
    log.info(f"  Features: {len(feature_cols)}")
    log.info(f"  Train rows: {len(X_train):,}")
    log.info(f"  Test rows:  {len(X_test):,}")


if __name__ == "__main__":
    main()
