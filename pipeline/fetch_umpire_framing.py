#!/usr/bin/env python3
"""
fetch_umpire_framing.py
Week 2 Priority 1: Umpire accuracy composites + catcher framing scores.
Populates the `umpire_framing` table in Supabase with:
  - Per-game umpire zone call rate (extra_strikes, strike_rate)
  - Per-game catcher framing runs (framing_runs, composite_score)
Runs nightly in the overnight-statcast-grading pipeline job.
"""
import os
import sys
from datetime import date, timedelta

import pandas as pd
from supabase import create_client, Client

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_KEY")

if not all([SUPABASE_URL, SUPABASE_KEY]):
    raise EnvironmentError("Missing SUPABASE_URL or SUPABASE_SERVICE_KEY")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

try:
    import pybaseball as pb
    pb.cache.enable()
    PYBASEBALL_AVAILABLE = True
except ImportError:
    PYBASEBALL_AVAILABLE = False
    print("pybaseball not installed.")


def fetch_statcast_for_date(game_date: str) -> pd.DataFrame:
    """Pull Statcast pitch-level data for a single date."""
    if not PYBASEBALL_AVAILABLE:
        return pd.DataFrame()
    try:
        print(f"  Pulling Statcast data for {game_date} ...")
        df = pb.statcast(start_dt=game_date, end_dt=game_date)
        if df is None or df.empty:
            print(f"  No Statcast data for {game_date} (pre-season or off day).")
            return pd.DataFrame()
        print(f"  {len(df)} pitches returned.")
        return df
    except Exception as e:
        print(f"  Warning: Could not fetch Statcast for {game_date}: {e}")
        return pd.DataFrame()


def compute_umpire_framing_rows(df: pd.DataFrame, game_date: str) -> list:
    """
    Compute per-game umpire + catcher composite rows for the umpire_framing table.
    Each row = one (game_pk, umpire, catcher) combination.
    """
    if df.empty:
        return []

    needed = ["game_pk", "umpire", "catcher_id", "type", "description",
              "plate_x", "plate_z", "sz_bot", "sz_top"]
    missing = [c for c in needed if c not in df.columns]
    if missing:
        print(f"  Skipping: missing columns {missing}")
        return []

    # Drop rows without umpire or catcher
    df = df.dropna(subset=["umpire", "catcher_id", "type"])
    if df.empty:
        return []

    # --- Zone geometry flags ---
    df["called_strike"] = (
        (df["type"] == "S") & (df["description"] == "called_strike")
    ).astype(int)

    df["in_zone"] = (
        (df["plate_x"].abs() <= 0.83)
        & (df["plate_z"] >= df["sz_bot"])
        & (df["plate_z"] <= df["sz_top"])
    ).astype(int)

    # Shadow zone: borderline pitches within ~2 inches of edge
    df["shadow_zone"] = (
        (df["plate_x"].abs().between(0.63, 1.03))
        | (df["plate_z"].between(df["sz_bot"] - 0.17, df["sz_bot"] + 0.17))
        | (df["plate_z"].between(df["sz_top"] - 0.17, df["sz_top"] + 0.17))
    ).astype(int)

    # Extra strikes = called strikes in shadow zone (framing opportunities)
    df["extra_strike"] = (
        (df["shadow_zone"] == 1) & (df["called_strike"] == 1)
    ).astype(int)

    rows = []
    game_date_val = game_date

    grouped = df.groupby(["game_pk", "umpire", "catcher_id"])
    for (game_pk, umpire_name, catcher_id), grp in grouped:
        total_pitches = len(grp)
        called_strikes = int(grp["called_strike"].sum())
        extra_strikes = int(grp["extra_strike"].sum())
        shadow_total = int(grp["shadow_zone"].sum())

        strike_rate = round(called_strikes / total_pitches, 4) if total_pitches > 0 else 0.0
        framing_runs = round(extra_strikes * 0.125, 4)  # ~0.125 runs per extra strike
        composite_score = round(
            (strike_rate * 0.5) + (framing_runs / max(shadow_total, 1) * 0.5), 4
        )

        # Try to get catcher name from data
        catcher_rows = grp[grp["catcher_id"] == catcher_id]
        catcher_name = str(catcher_id)  # fallback

        rows.append({
            "game_pk": int(game_pk),
            "game_date": game_date_val,
            "umpire_id": None,  # Statcast doesn't give umpire numeric ID
            "umpire_name": str(umpire_name),
            "catcher_id": int(catcher_id),
            "catcher_name": catcher_name,
            "total_pitches": total_pitches,
            "called_strikes": called_strikes,
            "extra_strikes": extra_strikes,
            "framing_runs": framing_runs,
            "strike_rate": strike_rate,
            "composite_score": composite_score,
        })

    return rows


def upsert_umpire_framing(rows: list) -> None:
    if not rows:
        print("  No umpire_framing rows to upsert.")
        return
    # Upsert in batches of 500
    for i in range(0, len(rows), 500):
        batch = rows[i:i + 500]
        supabase.table("umpire_framing").upsert(batch).execute()
    print(f"  Upserted {len(rows)} umpire_framing rows.")


def main():
    # Process yesterday's games (today's not complete at 2 AM run time)
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    print(f"fetch_umpire_framing.py — processing {yesterday}")

    df = fetch_statcast_for_date(yesterday)
    rows = compute_umpire_framing_rows(df, yesterday)
    print(f"  Computed {len(rows)} umpire_framing rows for {yesterday}.")
    upsert_umpire_framing(rows)
    print("Done.")


if __name__ == "__main__":
    main()
