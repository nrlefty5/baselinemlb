"""
pipeline/build_training_dataset.py

Transform raw Statcast plate-appearance data into feature vectors for the
XGBoost matchup model. Produces train/test split CSVs and feature metadata.
"""

import argparse
import json
import logging
import os

import numpy as np
import pandas as pd
from sklearn.model_selection import train_test_split

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
DEFAULT_INPUT = "data/statcast_historical.csv"
TRAIN_OUTPUT = "data/train_matchups.csv"
TEST_OUTPUT = "data/test_matchups.csv"
METADATA_OUTPUT = "data/feature_metadata.json"

# ---------------------------------------------------------------------------
# Park factors for strikeout rate adjustment (relative to league average = 1.0)
# Source: multi-year Statcast park factors (approximate)
# ---------------------------------------------------------------------------
PARK_K_FACTORS: dict[str, float] = {
    "ARI": 1.02,   # Chase Field - warm, humidor since 2018
    "ATL": 1.01,   # Truist Park
    "BAL": 0.98,   # Camden Yards - hitter friendly
    "BOS": 0.99,   # Fenway Park
    "CHC": 0.97,   # Wrigley Field - wind variable
    "CWS": 1.00,   # Guaranteed Rate Field
    "CIN": 0.99,   # Great American Ball Park
    "CLE": 1.01,   # Progressive Field
    "COL": 0.93,   # Coors Field - thin air, fewer Ks
    "DET": 1.01,   # Comerica Park
    "HOU": 1.03,   # Minute Maid Park - closed roof
    "KC":  1.00,   # Kauffman Stadium
    "LAA": 1.00,   # Angel Stadium
    "LAD": 1.02,   # Dodger Stadium
    "MIA": 1.03,   # loanDepot Park - retractable roof
    "MIL": 1.01,   # American Family Field - roof
    "MIN": 1.02,   # Target Field
    "NYM": 1.00,   # Citi Field
    "NYY": 0.99,   # Yankee Stadium
    "OAK": 1.01,   # Oakland Coliseum (or successor)
    "PHI": 1.00,   # Citizens Bank Park
    "PIT": 0.99,   # PNC Park
    "SD":  1.01,   # Petco Park - pitcher friendly
    "SEA": 1.02,   # T-Mobile Park - retractable roof
    "SF":  1.02,   # Oracle Park - cold/windy
    "STL": 1.00,   # Busch Stadium
    "TB":  1.03,   # Tropicana Field - dome
    "TEX": 1.01,   # Globe Life Field - dome
    "TOR": 1.01,   # Rogers Centre - dome
    "WSH": 1.00,   # Nationals Park
}

# League average defaults for imputation
LEAGUE_DEFAULTS: dict[str, float] = {
    "k_pct": 0.222,
    "bb_pct": 0.085,
    "iso": 0.160,
    "woba": 0.320,
    "avg_launch_angle": 11.5,
    "avg_launch_speed": 88.5,
    "whiff_rate": 0.245,
    "chase_rate": 0.285,
    "zone_rate": 0.480,
    "k9": 8.9,
    "bb9": 3.1,
    "avg_release_speed": 92.5,
}

TARGET_COL = "outcome"
OUTCOME_CLASSES = ["K", "BB", "1B", "2B", "3B", "HR", "HBP", "OUT"]

# ---------------------------------------------------------------------------
# Supabase helpers (optional source)
# ---------------------------------------------------------------------------
def _supabase_headers() -> dict:
    """Return standard Supabase REST API headers."""
    key = os.environ.get("SUPABASE_SERVICE_KEY", "")
    return {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "Prefer": "resolution=merge-duplicates",
    }


# ---------------------------------------------------------------------------
# Feature engineering helpers
# ---------------------------------------------------------------------------
def _pitch_mix(group: pd.DataFrame) -> dict[str, float]:
    """
    Compute pitch-type usage percentages for a pitcher group.

    Args:
        group: DataFrame subset for a single pitcher.

    Returns:
        Dict with fastball_pct, slider_pct, curve_pct, change_pct keys.
    """
    if "pitch_type" not in group.columns or group.empty:
        return {"fastball_pct": np.nan, "slider_pct": np.nan,
                "curve_pct": np.nan, "change_pct": np.nan}

    total = len(group)
    pt = group["pitch_type"].str.upper().fillna("XX")

    fastball_types = {"FF", "FT", "SI", "FC"}
    slider_types = {"SL", "ST", "SW"}
    curve_types = {"CU", "KC", "CS"}
    change_types = {"CH", "FS", "FO", "SC"}

    return {
        "fastball_pct": round(pt.isin(fastball_types).sum() / total, 4),
        "slider_pct":   round(pt.isin(slider_types).sum() / total, 4),
        "curve_pct":    round(pt.isin(curve_types).sum() / total, 4),
        "change_pct":   round(pt.isin(change_types).sum() / total, 4),
    }


def _whiff_rate(group: pd.DataFrame) -> float:
    """
    Compute swinging-strike (whiff) rate.

    Args:
        group: DataFrame subset containing a 'description' column.

    Returns:
        Fraction of pitches that resulted in a swinging strike.
    """
    if "description" not in group.columns or group.empty:
        return np.nan
    whiffs = group["description"].str.contains("swinging_strike", na=False).sum()
    return round(whiffs / len(group), 4)


def _chase_rate(group: pd.DataFrame) -> float:
    """
    Compute chase rate (swings on balls outside strike zone).

    Approximated as swings where plate_x or plate_z is outside [-1, 1].

    Args:
        group: DataFrame with plate_x, plate_z, description columns.

    Returns:
        Chase rate float.
    """
    if not {"plate_x", "plate_z", "description"}.issubset(group.columns) or group.empty:
        return np.nan
    outside = (group["plate_x"].abs() > 1.0) | (group["plate_z"].abs() > 1.0)
    swings = group["description"].str.contains("swing|foul|hit_into_play", na=False, regex=True)
    denom = outside.sum()
    if denom == 0:
        return np.nan
    return round((outside & swings).sum() / denom, 4)


def _zone_rate(group: pd.DataFrame) -> float:
    """
    Compute zone rate (fraction of pitches within the strike zone).

    Args:
        group: DataFrame with plate_x, plate_z columns.

    Returns:
        Zone rate float.
    """
    if not {"plate_x", "plate_z"}.issubset(group.columns) or group.empty:
        return np.nan
    in_zone = (group["plate_x"].abs() <= 0.83) & (group["plate_z"].between(1.5, 3.5))
    return round(in_zone.sum() / len(group), 4)


def build_pitcher_features(pa_df: pd.DataFrame) -> pd.DataFrame:
    """
    Compute per-pitcher career aggregate features from plate-appearance data.

    Args:
        pa_df: Full plate-appearance DataFrame.

    Returns:
        DataFrame indexed by pitcher_id with pitcher feature columns.
    """
    logger.info("Building pitcher features...")
    records = []

    for pitcher_id, grp in pa_df.groupby("pitcher"):
        total_pa = len(grp)
        if total_pa == 0:
            continue

        k_pa   = (grp["outcome"] == "K").sum()
        bb_pa  = (grp["outcome"] == "BB").sum()

        # Approximate K/9 and BB/9 using 4.3 PA per inning heuristic
        innings = total_pa / 4.3
        k9  = round((k_pa  / innings) if innings > 0 else LEAGUE_DEFAULTS["k9"],  2)
        bb9 = round((bb_pa / innings) if innings > 0 else LEAGUE_DEFAULTS["bb9"], 2)

        # Splits: K% vs LHB vs RHB
        lhb_k = _safe_pct(grp[grp["stand"] == "L"], "outcome", "K")
        rhb_k = _safe_pct(grp[grp["stand"] == "R"], "outcome", "K")

        mix   = _pitch_mix(grp)
        avail = grp["release_speed"].dropna()
        avg_velo = round(avail.mean(), 1) if not avail.empty else LEAGUE_DEFAULTS["avg_release_speed"]

        rec = {
            "pitcher_id": pitcher_id,
            "p_throws": grp["p_throws"].mode()[0] if not grp["p_throws"].isna().all() else "R",
            "pitcher_total_pa": total_pa,
            "pitcher_k9": k9,
            "pitcher_bb9": bb9,
            "pitcher_avg_release_speed": avg_velo,
            "pitcher_whiff_rate": _whiff_rate(grp),
            "pitcher_chase_rate": _chase_rate(grp),
            "pitcher_zone_rate": _zone_rate(grp),
            "pitcher_k_vs_lhb": lhb_k,
            "pitcher_k_vs_rhb": rhb_k,
            **{f"pitcher_{k}": v for k, v in mix.items()},
        }
        records.append(rec)

    df = pd.DataFrame(records).set_index("pitcher_id")
    logger.info("Pitcher features built for %d pitchers", len(df))
    return df


def build_batter_features(pa_df: pd.DataFrame) -> pd.DataFrame:
    """
    Compute per-batter career aggregate features from plate-appearance data.

    Args:
        pa_df: Full plate-appearance DataFrame.

    Returns:
        DataFrame indexed by batter_id with batter feature columns.
    """
    logger.info("Building batter features...")
    records = []

    for batter_id, grp in pa_df.groupby("batter"):
        total_pa = len(grp)
        if total_pa == 0:
            continue

        k_pct  = _safe_pct(grp, "outcome", "K")
        bb_pct = _safe_pct(grp, "outcome", "BB")

        la = grp["launch_angle"].dropna()
        ls = grp["launch_speed"].dropna()
        woba = grp["estimated_woba_using_speedangle"].dropna()

        # ISO proxy: (2B*2 + 3B*3 + HR*4) / PA  (simplified)
        iso = round(
            (2 * (grp["outcome"] == "2B").sum()
             + 3 * (grp["outcome"] == "3B").sum()
             + 4 * (grp["outcome"] == "HR").sum()) / total_pa,
            4,
        )

        # L/R splits
        vs_lhp_k = _safe_pct(grp[grp["p_throws"] == "L"], "outcome", "K")
        vs_rhp_k = _safe_pct(grp[grp["p_throws"] == "R"], "outcome", "K")

        rec = {
            "batter_id": batter_id,
            "stand": grp["stand"].mode()[0] if not grp["stand"].isna().all() else "R",
            "batter_total_pa": total_pa,
            "batter_k_pct": k_pct,
            "batter_bb_pct": bb_pct,
            "batter_iso": iso,
            "batter_woba": round(woba.mean(), 4) if not woba.empty else LEAGUE_DEFAULTS["woba"],
            "batter_avg_launch_angle": round(la.mean(), 2) if not la.empty else LEAGUE_DEFAULTS["avg_launch_angle"],
            "batter_avg_launch_speed": round(ls.mean(), 2) if not ls.empty else LEAGUE_DEFAULTS["avg_launch_speed"],
            "batter_chase_rate": _chase_rate(grp),
            "batter_whiff_rate": _whiff_rate(grp),
            "batter_k_vs_lhp": vs_lhp_k,
            "batter_k_vs_rhp": vs_rhp_k,
        }
        records.append(rec)

    df = pd.DataFrame(records).set_index("batter_id")
    logger.info("Batter features built for %d batters", len(df))
    return df


def build_matchup_pa_counts(pa_df: pd.DataFrame) -> pd.Series:
    """
    Count prior plate appearances between each pitcher-batter pair.

    Args:
        pa_df: Full plate-appearance DataFrame.

    Returns:
        Series indexed by (pitcher, batter) tuples with PA count.
    """
    return pa_df.groupby(["pitcher", "batter"]).size().rename("prior_pa_count")


def _safe_pct(df: pd.DataFrame, col: str, value: str) -> float:
    """
    Safely compute the fraction of rows in col equal to value.

    Args:
        df:    DataFrame to compute over.
        col:   Column name.
        value: Target value to count.

    Returns:
        Fraction as float, or NaN if df is empty.
    """
    if df.empty:
        return np.nan
    return round((df[col] == value).sum() / len(df), 4)


def _team_from_game(row: pd.Series) -> str:
    """
    Derive home team abbreviation from a PA row.

    Args:
        row: Pandas Series with home_team / away_team fields.

    Returns:
        Home team abbreviation string, or empty string if unavailable.
    """
    return str(row.get("home_team", "")).upper()


# ---------------------------------------------------------------------------
# Main feature assembly
# ---------------------------------------------------------------------------
def assemble_features(
    pa_df: pd.DataFrame,
    pitcher_feats: pd.DataFrame,
    batter_feats: pd.DataFrame,
    prior_pa: pd.Series,
) -> pd.DataFrame:
    """
    Join all feature sets into a single training-ready DataFrame.

    Args:
        pa_df:         Plate-appearance level DataFrame.
        pitcher_feats: Per-pitcher career stats (indexed by pitcher_id).
        batter_feats:  Per-batter career stats (indexed by batter_id).
        prior_pa:      Series of prior PA counts indexed by (pitcher, batter).

    Returns:
        Wide DataFrame with all feature columns and target outcome.
    """
    logger.info("Assembling full feature matrix...")
    df = pa_df.copy()

    # -- Pitcher features --
    df = df.join(pitcher_feats, on="pitcher", how="left", rsuffix="_p")

    # -- Batter features --
    df = df.join(batter_feats, on="batter", how="left", rsuffix="_b")

    # -- Prior PA count --
    df["prior_pa_count"] = df.set_index(["pitcher", "batter"]).index.map(prior_pa).values

    # -- Platoon advantage (same hand = disadvantage for pitcher) --
    df["platoon_advantage"] = (
        ((df["p_throws"] == "R") & (df["stand"] == "L"))
        | ((df["p_throws"] == "L") & (df["stand"] == "R"))
    ).astype(int)

    # -- Park factor --
    df["park_factor_k"] = df.apply(
        lambda r: PARK_K_FACTORS.get(_team_from_game(r), 1.0), axis=1
    )

    # -- Context features already in pa_df: inning, outs_when_up, runners_on_base, score_diff --
    df["inning"] = df.get("inning", pd.Series(dtype=float))
    df["outs_when_up"] = df.get("outs_when_up", pd.Series(dtype=float))

    # -- Game month --
    if "game_date" in df.columns:
        df["game_month"] = pd.to_datetime(df["game_date"], errors="coerce").dt.month
    else:
        df["game_month"] = np.nan

    # -- Target encode home/away --
    df["is_home_batter"] = (
        df.apply(
            lambda r: 1 if str(r.get("home_team", "")).upper() in
                          [str(r.get("batter_team", "")).upper()] else 0,
            axis=1,
        )
    )

    # -- Impute missing values with league averages --
    defaults = {
        "pitcher_k9":                  LEAGUE_DEFAULTS["k9"],
        "pitcher_bb9":                 LEAGUE_DEFAULTS["bb9"],
        "pitcher_avg_release_speed":   LEAGUE_DEFAULTS["avg_release_speed"],
        "pitcher_whiff_rate":          LEAGUE_DEFAULTS["whiff_rate"],
        "pitcher_chase_rate":          LEAGUE_DEFAULTS["chase_rate"],
        "pitcher_zone_rate":           LEAGUE_DEFAULTS["zone_rate"],
        "pitcher_k_vs_lhb":            LEAGUE_DEFAULTS["k_pct"],
        "pitcher_k_vs_rhb":            LEAGUE_DEFAULTS["k_pct"],
        "pitcher_fastball_pct":        0.55,
        "pitcher_slider_pct":          0.18,
        "pitcher_curve_pct":           0.12,
        "pitcher_change_pct":          0.11,
        "batter_k_pct":                LEAGUE_DEFAULTS["k_pct"],
        "batter_bb_pct":               LEAGUE_DEFAULTS["bb_pct"],
        "batter_iso":                  LEAGUE_DEFAULTS["iso"],
        "batter_woba":                 LEAGUE_DEFAULTS["woba"],
        "batter_avg_launch_angle":     LEAGUE_DEFAULTS["avg_launch_angle"],
        "batter_avg_launch_speed":     LEAGUE_DEFAULTS["avg_launch_speed"],
        "batter_chase_rate":           LEAGUE_DEFAULTS["chase_rate"],
        "batter_whiff_rate":           LEAGUE_DEFAULTS["whiff_rate"],
        "prior_pa_count":              0,
        "score_diff":                  0,
        "park_factor_k":               1.0,
    }
    for col, default in defaults.items():
        if col in df.columns:
            df[col] = df[col].fillna(default)

    return df


# ---------------------------------------------------------------------------
# Feature column definitions
# ---------------------------------------------------------------------------
FEATURE_COLS = [
    # Pitcher
    "pitcher_k9", "pitcher_bb9", "pitcher_avg_release_speed",
    "pitcher_whiff_rate", "pitcher_chase_rate", "pitcher_zone_rate",
    "pitcher_k_vs_lhb", "pitcher_k_vs_rhb",
    "pitcher_fastball_pct", "pitcher_slider_pct", "pitcher_curve_pct", "pitcher_change_pct",
    # Batter
    "batter_k_pct", "batter_bb_pct", "batter_iso", "batter_woba",
    "batter_avg_launch_angle", "batter_avg_launch_speed",
    "batter_chase_rate", "batter_whiff_rate",
    "batter_k_vs_lhp", "batter_k_vs_rhp",
    # Matchup
    "platoon_advantage", "prior_pa_count",
    # Context
    "inning", "outs_when_up", "runners_on_base", "score_diff",
    "park_factor_k", "game_month", "is_home_batter",
]


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def build_dataset(input_path: str, test_size: float = 0.2, random_state: int = 42) -> None:
    """
    End-to-end function: load PA data, engineer features, split, and save.

    Args:
        input_path:   Path to statcast_historical.csv.
        test_size:    Fraction of data held out for test set.
        random_state: Random seed for reproducibility.
    """
    logger.info("Reading plate-appearance data from %s", input_path)
    pa_df = pd.read_csv(input_path, low_memory=False)
    logger.info("Loaded %d rows", len(pa_df))

    # Drop rows with no outcome
    pa_df = pa_df[pa_df["outcome"].isin(OUTCOME_CLASSES)].reset_index(drop=True)
    logger.info("%d rows with valid outcomes", len(pa_df))

    pitcher_feats = build_pitcher_features(pa_df)
    batter_feats  = build_batter_features(pa_df)
    prior_pa      = build_matchup_pa_counts(pa_df)

    full_df = assemble_features(pa_df, pitcher_feats, batter_feats, prior_pa)

    # Select features + target
    available_feats = [c for c in FEATURE_COLS if c in full_df.columns]
    missing_feats   = [c for c in FEATURE_COLS if c not in full_df.columns]
    if missing_feats:
        logger.warning("Missing feature columns (will be excluded): %s", missing_feats)

    model_df = full_df[available_feats + [TARGET_COL]].dropna(subset=[TARGET_COL])

    # Encode target as integer label
    outcome_to_int = {oc: i for i, oc in enumerate(OUTCOME_CLASSES)}
    model_df = model_df.copy()
    model_df["outcome_label"] = model_df[TARGET_COL].map(outcome_to_int)

    # Train / test split
    train_df, test_df = train_test_split(
        model_df, test_size=test_size, random_state=random_state, stratify=model_df["outcome_label"]
    )
    logger.info("Train: %d rows | Test: %d rows", len(train_df), len(test_df))

    os.makedirs("data", exist_ok=True)
    train_df.to_csv(TRAIN_OUTPUT, index=False)
    test_df.to_csv(TEST_OUTPUT, index=False)
    logger.info("Saved train -> %s, test -> %s", TRAIN_OUTPUT, TEST_OUTPUT)

    # Feature metadata
    metadata = {
        "feature_columns": available_feats,
        "missing_features": missing_feats,
        "target_column": TARGET_COL,
        "target_label_column": "outcome_label",
        "outcome_classes": OUTCOME_CLASSES,
        "outcome_to_int": outcome_to_int,
        "int_to_outcome": {str(v): k for k, v in outcome_to_int.items()},
        "league_defaults": LEAGUE_DEFAULTS,
        "park_k_factors": PARK_K_FACTORS,
        "train_rows": len(train_df),
        "test_rows": len(test_df),
        "test_size": test_size,
        "random_state": random_state,
    }
    with open(METADATA_OUTPUT, "w") as fh:
        json.dump(metadata, fh, indent=2)
    logger.info("Saved feature metadata -> %s", METADATA_OUTPUT)


def main() -> None:
    """CLI entry point for building the matchup training dataset."""
    parser = argparse.ArgumentParser(
        description="Build XGBoost training dataset from raw Statcast plate-appearance data."
    )
    parser.add_argument(
        "--input", default=DEFAULT_INPUT,
        help=f"Path to statcast_historical.csv (default: {DEFAULT_INPUT})",
    )
    parser.add_argument(
        "--test-size", type=float, default=0.2,
        help="Fraction of data to hold out for testing (default: 0.2)",
    )
    parser.add_argument(
        "--random-state", type=int, default=42,
        help="Random seed for train/test split (default: 42)",
    )
    args = parser.parse_args()

    build_dataset(args.input, test_size=args.test_size, random_state=args.random_state)


if __name__ == "__main__":
    main()
