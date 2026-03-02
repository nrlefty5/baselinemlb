#!/usr/bin/env python3
"""
fetch_statcast.py
Fetches Statcast pitch-level data via pybaseball for today's games.
Key metrics: called_strike_prob, framing runs, umpire tendencies.
Saves to data/statcast/statcast_YYYY-MM-DD.parquet (+ .json summary)
"""

import json
import os
import warnings
from datetime import date, timedelta

import pandas as pd

warnings.filterwarnings("ignore")

try:
    from pybaseball import statcast
    PYBASEBALL_AVAILABLE = True
except ImportError:
    PYBASEBALL_AVAILABLE = False
    print("pybaseball not installed. Install via: pip install pybaseball")


# Columns most relevant for framing + umpire analysis
FRAMING_COLS = [
    "game_date", "game_pk", "pitcher", "player_name", "batter",
    "catcher_id", "umpire",
    "pitch_type", "description", "zone", "type",
    "plate_x", "plate_z", "sz_top", "sz_bot",
    "called_strike", "balls", "strikes", "outs_when_up",
    "inning", "inning_topbot", "stand", "p_throws",
    "estimated_strike_prob",
]


def fetch_statcast_data(game_date: str) -> pd.DataFrame:
    """Fetch all Statcast pitches for a given date."""
    if not PYBASEBALL_AVAILABLE:
        return pd.DataFrame()
    print(f"Pulling Statcast data for {game_date}...")
    df = statcast(start_dt=game_date, end_dt=game_date)
    if df is None or df.empty:
        print("No data returned.")
        return pd.DataFrame()
    print(f"  Rows returned: {len(df)}")
    return df


def add_framing_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Add derived columns useful for framing and umpire analysis."""
    if df.empty:
        return df
    # Called strike = pitch called a strike (type == 'S', description == 'called_strike')
    df["called_strike"] = (
        (df["type"] == "S") & (df["description"] == "called_strike")
    ).astype(int)
    # Ball in strike zone: plate_x and plate_z within standard zone bounds
    # Standard zone: x in [-0.83, 0.83], z between sz_bot and sz_top
    df["in_zone"] = (
        (df["plate_x"].abs() <= 0.83) &
        (df["plate_z"] >= df["sz_bot"]) &
        (df["plate_z"] <= df["sz_top"])
    ).astype(int)
    # Shadow zone: borderline pitches within ~2in of zone edge
    df["shadow_zone"] = (
        (df["plate_x"].abs().between(0.63, 1.03)) |
        (df["plate_z"].between(df["sz_bot"] - 0.17, df["sz_bot"] + 0.17)) |
        (df["plate_z"].between(df["sz_top"] - 0.17, df["sz_top"] + 0.17))
    ).astype(int)
    # Framing opportunity: borderline pitch that could go either way
    df["framing_opportunity"] = df["shadow_zone"]
    # Correct call: umpire called it correctly per zone
    df["correct_call"] = (
        ((df["in_zone"] == 1) & (df["called_strike"] == 1)) |
        ((df["in_zone"] == 0) & (df["called_strike"] == 0))
    ).astype(int)
    return df


def summarize_catchers(df: pd.DataFrame) -> list:
    """Compute per-catcher framing stats."""
    if df.empty or "catcher_id" not in df.columns:
        return []
    shadow = df[df["shadow_zone"] == 1]
    if shadow.empty:
        return []
    summary = (
        shadow.groupby("catcher_id")
        .agg(
            framing_opps=("framing_opportunity", "sum"),
            extra_strikes=("called_strike", "sum"),
        )
        .reset_index()
    )
    summary["framing_rate"] = (
        summary["extra_strikes"] / summary["framing_opps"]
    ).round(3)
    return summary.to_dict(orient="records")


def summarize_umpires(df: pd.DataFrame) -> list:
    """Compute per-umpire accuracy stats on called pitches."""
    if df.empty or "umpire" not in df.columns:
        return []
    called = df[df["description"].isin(["called_strike", "ball"])]
    if called.empty:
        return []
    summary = (
        called.groupby("umpire")
        .agg(
            total_called=("called_strike", "count"),
            correct=("correct_call", "sum"),
            called_strikes=("called_strike", "sum"),
        )
        .reset_index()
    )
    summary["accuracy"] = (
        summary["correct"] / summary["total_called"]
    ).round(3)
    summary["cs_rate"] = (
        summary["called_strikes"] / summary["total_called"]
    ).round(3)
    return summary.to_dict(orient="records")


def save_results(df: pd.DataFrame, catcher_summary: list,
                 umpire_summary: list, game_date: str) -> None:
    out_dir = os.path.join("data", "statcast")
    os.makedirs(out_dir, exist_ok=True)
    if not df.empty:
        parquet_path = os.path.join(out_dir, f"statcast_{game_date}.parquet")
        df.to_parquet(parquet_path, index=False)
        print(f"Saved raw Statcast to {parquet_path}")
    summary = {
        "date": game_date,
        "catcher_framing": catcher_summary,
        "umpire_accuracy": umpire_summary,
    }
    json_path = os.path.join(out_dir, f"statcast_summary_{game_date}.json")
    with open(json_path, "w") as f:
        json.dump(summary, f, indent=2)
    print(f"Saved summary JSON to {json_path}")


if __name__ == "__main__":
    # Use yesterday's date (today's games not complete yet at run time)
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    df = fetch_statcast_data(yesterday)
    df = add_framing_columns(df)
    catcher_summary = summarize_catchers(df)
    umpire_summary = summarize_umpires(df)
    print(f"Catcher framing records: {len(catcher_summary)}")
    print(f"Umpire accuracy records: {len(umpire_summary)}")
    save_results(df, catcher_summary, umpire_summary, yesterday)
    print("Done.")
