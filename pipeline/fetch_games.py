import os
from datetime import date, timedelta

import requests

from supabase import Client, create_client

# from dotenv import load_dotenv  # DISABLED - GitHub Actions provides env vars

# load_dotenv()

# ── Clients ───────────────────────────────────────────────────────────────────
SUPABASE_URL = os.getenv("SUPABASE_URL", "").strip()
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_KEY", "").strip()

# Fail fast with a clear error instead of cryptic HTTP 400
if not SUPABASE_URL.startswith("https://") or not SUPABASE_URL.endswith(".supabase.co"):
    raise RuntimeError(f"Invalid SUPABASE_URL (length={len(SUPABASE_URL)}, repr={repr(SUPABASE_URL[:30])})")

if not all([SUPABASE_URL, SUPABASE_KEY]):
    raise EnvironmentError("Missing SUPABASE_URL or SUPABASE_SERVICE_KEY in .env")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# ── Config ──────────────────────────────────────────────────────────────────
BASE_URL = "https://statsapi.mlb.com/api/v1"
SPORT_ID = 1  # MLB


def fetch_schedule(target_date: date, days_ahead: int = 6) -> list[dict]:
    """
    Pull the schedule from the MLB Stats API for a date window.
    Default: today through the next 6 days (a full week).
    Returns a flat list of game dicts.
    """
    start = target_date.strftime("%Y-%m-%d")
    end = (target_date + timedelta(days=days_ahead)).strftime("%Y-%m-%d")

    url = f"{BASE_URL}/schedule"
    params = {
        "sportId": SPORT_ID,
        "startDate": start,
        "endDate": end,
        "hydrate": "venue,probablePitcher,linescore,flags,decisions,game(content(summary))",
    }

    r = requests.get(url, params=params, timeout=15)
    r.raise_for_status()
    data = r.json()

    games = []
    for day in data.get("dates", []):
        for game in day.get("games", []):
            games.append(game)

    return games


def parse_game(game: dict) -> dict | None:
    """
    Map an MLB Stats API game object to our games table schema.
    Returns None if the game is missing essential fields.
    Includes probable pitcher IDs and names.
    """
    game_pk = game.get("gamePk")
    if not game_pk:
        return None

    game_date_str = game.get("officialDate") or game.get("gameDate", "")[:10]

    teams = game.get("teams", {})
    home = teams.get("home", {})
    away = teams.get("away", {})

    home_team = home.get("team", {}).get("name", "Unknown")
    away_team = away.get("team", {}).get("name", "Unknown")

    venue = game.get("venue", {}).get("name")
    status = game.get("status", {}).get("detailedState")

    # Scores (only present after game starts)
    linescore = game.get("linescore", {})
    home_score = linescore.get("teams", {}).get("home", {}).get("runs")
    away_score = linescore.get("teams", {}).get("away", {}).get("runs")

    # Probable pitchers (present once announced)
    home_pp = home.get("probablePitcher", {})
    away_pp = away.get("probablePitcher", {})

    home_probable_pitcher_id = home_pp.get("id")
    home_probable_pitcher_name = home_pp.get("fullName")

    away_probable_pitcher_id = away_pp.get("id")
    away_probable_pitcher_name = away_pp.get("fullName")

    # Game time (UTC ISO string truncated to HH:MM)
    game_time_raw = game.get("gameDate", "")
    game_time = game_time_raw[11:16] if len(game_time_raw) >= 16 else None

    return {
        "game_pk": game_pk,
        "game_date": game_date_str,
        "home_team": home_team,
        "away_team": away_team,
        "venue": venue,
        "status": status,
        "home_score": home_score,
        "away_score": away_score,
        "home_probable_pitcher_id": home_probable_pitcher_id,
        "home_probable_pitcher": home_probable_pitcher_name,
        "away_probable_pitcher_id": away_probable_pitcher_id,
        "away_probable_pitcher": away_probable_pitcher_name,
        "game_time": game_time,
    }


def upsert_games(rows: list[dict]) -> None:
    """Upsert game rows into Supabase; conflict key is game_pk."""
    if not rows:
        print(" No game rows to upsert.")
        return

    for i in range(0, len(rows), 200):
        batch = rows[i : i + 200]
        supabase.table("games").upsert(batch, on_conflict="game_pk").execute()

    print(f" Upserted {len(rows)} game rows.")


def main(days_ahead: int = 6):
    today = date.today()
    print(f"Fetching MLB schedule: {today} through {today + timedelta(days=days_ahead)} ...")

    raw_games = fetch_schedule(today, days_ahead=days_ahead)
    print(f" API returned {len(raw_games)} raw games.")

    rows = [r for g in raw_games if (r := parse_game(g)) is not None]
    print(f" Parsed {len(rows)} valid game rows.")

    # Count how many have probable pitchers
    with_pitchers = sum(1 for r in rows if r.get("home_probable_pitcher_id") or r.get("away_probable_pitcher_id"))
    print(f" {with_pitchers} games have at least one probable pitcher announced.")

    upsert_games(rows)
    print("Done.")


if __name__ == "__main__":
    main()
