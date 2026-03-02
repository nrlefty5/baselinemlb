import os
from datetime import date, timedelta

import pandas as pd
import pybaseball as pb
from dotenv import load_dotenv

from supabase import Client, create_client

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_KEY")

if not all([SUPABASE_URL, SUPABASE_KEY]):
    raise EnvironmentError("Missing SUPABASE_URL or SUPABASE_SERVICE_KEY in .env")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# Cache pybaseball requests to disk so we don't hammer the server
pb.cache.enable()

# ── Umpire Framing Composite ──────────────────────────────────────────
def fetch_catcher_framing(season: int) -> pd.DataFrame:
    """
    Pull catcher framing stats from Baseball Savant via pybaseball.
    Returns a DataFrame with columns: player_id, player_name, framing_runs
    Returns empty DataFrame if data is not available (pre-season).
    """
    try:
        df = pb.statcast_catcher_framing(season)
        if df is None or df.empty:
            print(f"  No catcher framing data available for {season} season (pre-season or no games yet).")
            return pd.DataFrame()
        # Rename for clarity
        df = df.rename(columns={
            "last_name, first_name": "player_name",
            "fielding_runs_above_average": "framing_runs",
        })
        df["season"] = season
        # Only return rows with expected columns
        available_cols = [c for c in ["player_id", "player_name", "framing_runs", "season"] if c in df.columns]
        return df[available_cols]
    except Exception as e:
        print(f"  Warning: Could not fetch catcher framing for {season}: {e}")
        print("  This is expected before the season starts. Skipping.")
        return pd.DataFrame()


def fetch_umpire_data(start_date: str, end_date: str) -> pd.DataFrame:
    """
    Pull Statcast pitch-level data and compute per-umpire strike-call accuracy.
    start_date / end_date: 'YYYY-MM-DD'
    Returns empty DataFrame if no games in the date range (pre-season).
    """
    try:
        print(f"  Pulling Statcast data {start_date} -> {end_date} ...")
        df = pb.statcast(start_dt=start_date, end_dt=end_date)
        if df is None or df.empty:
            print(f"  No Statcast data available for {start_date} to {end_date} (no games played yet).")
            return pd.DataFrame()

        # Keep only pitches with umpire and zone data
        df = df.dropna(subset=["umpire", "zone", "type"])
        if df.empty:
            print("  No valid pitch data found. Skipping umpire analysis.")
            return pd.DataFrame()

        # 'type' = 'S' (strike), 'B' (ball), 'X' (in play)
        # Edge zone calls: zones 11-14 are borderline
        edge_zones = {11, 12, 13, 14}
        df["is_edge"] = df["zone"].isin(edge_zones)
        df["called_strike"] = (df["type"] == "S") & (df["description"] == "called_strike")
        df["called_ball"] = (df["type"] == "B") & (df["description"] == "ball")

        ump_stats = (
            df.groupby("umpire")
            .agg(
                total_pitches=("type", "count"),
                edge_called_strikes=("called_strike", lambda x: x[df.loc[x.index, "is_edge"]].sum()),
                edge_pitches=("is_edge", "sum"),
            )
            .reset_index()
        )
        ump_stats["edge_strike_pct"] = (
            ump_stats["edge_called_strikes"] / ump_stats["edge_pitches"]
        ).round(4)
        ump_stats["as_of"] = end_date
        return ump_stats
    except Exception as e:
        print(f"  Warning: Could not fetch Statcast umpire data: {e}")
        print("  This is expected before the season starts. Skipping.")
        return pd.DataFrame()


def upsert_framing(df: pd.DataFrame) -> None:
    if df.empty:
        print("  No framing data to upsert.")
        return
    rows = df.to_dict(orient="records")
    for i in range(0, len(rows), 500):
        supabase.table("catcher_framing").upsert(rows[i:i+500]).execute()
    print(f"  Upserted {len(rows)} catcher framing rows.")


def upsert_umpires(df: pd.DataFrame) -> None:
    if df.empty:
        print("  No umpire data to upsert.")
        return
    rows = df.to_dict(orient="records")
    for i in range(0, len(rows), 500):
        supabase.table("umpire_tendencies").upsert(rows[i:i+500]).execute()
    print(f"  Upserted {len(rows)} umpire rows.")


def main():
    season = date.today().year
    # Use last 30 days for umpire data
    end = str(date.today())
    start = str(date.today() - timedelta(days=30))

    print("Fetching catcher framing ...")
    framing_df = fetch_catcher_framing(season)
    upsert_framing(framing_df)

    print("Fetching umpire tendencies ...")
    ump_df = fetch_umpire_data(start, end)
    upsert_umpires(ump_df)

    print("Done. (Pre-season: data will populate once games begin.)")


if __name__ == "__main__":
    main()
