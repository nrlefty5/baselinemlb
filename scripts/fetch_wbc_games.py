#!/usr/bin/env python3
"""
fetch_wbc_games.py
Fetches World Baseball Classic game schedule using sportId=51
and upserts games into the same Supabase `games` table as MLB games.
Designed to run daily during WBC (March 5 - March 22, 2026).
Uses Option A: separate script, same games table, no changes to existing pipeline scripts.
"""
import os
import json
import logging
import requests
from datetime import date

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("fetch_wbc_games")

BASE_URL = "https://statsapi.mlb.com/api/v1"
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_KEY")

WBC_SPORT_ID = 51  # World Baseball Classic


def fetch_wbc_schedule(game_date: str = None) -> dict:
    """Fetch WBC schedule for a given date (default: today)."""
    if game_date is None:
        game_date = date.today().isoformat()
    url = f"{BASE_URL}/schedule"
    params = {
        "sportId": WBC_SPORT_ID,
        "date": game_date,
        "hydrate": "team,linescore,probablePitcher,officials,weather",
    }
    resp = requests.get(url, params=params, timeout=30)
    resp.raise_for_status()
    return resp.json()


def parse_wbc_games(schedule: dict) -> list:
    """Parse WBC schedule response into a flat list of game dicts."""
    games = []
    for date_block in schedule.get("dates", []):
        for game in date_block.get("games", []):
            games.append({
                "game_pk": game["gamePk"],
                "game_date": game["gameDate"],
                "game_time": game["gameDate"][11:16] if "T" in game.get("gameDate", "") else None,
                "status": game["status"]["detailedState"],
                "home_team": game["teams"]["home"]["team"]["name"],
                "home_team_id": game["teams"]["home"]["team"]["id"],
                "away_team": game["teams"]["away"]["team"]["name"],
                "away_team_id": game["teams"]["away"]["team"]["id"],
                "venue": game.get("venue", {}).get("name", ""),
                "home_probable_pitcher": (
                    game["teams"]["home"]
                    .get("probablePitcher", {})
                    .get("fullName", "TBD")
                ),
                "away_probable_pitcher": (
                    game["teams"]["away"]
                    .get("probablePitcher", {})
                    .get("fullName", "TBD")
                ),
                "home_pitcher_id": (
                    game["teams"]["home"]
                    .get("probablePitcher", {})
                    .get("id", None)
                ),
                "away_pitcher_id": (
                    game["teams"]["away"]
                    .get("probablePitcher", {})
                    .get("id", None)
                ),
                "sport_id": WBC_SPORT_ID,
                "series_description": game.get("seriesDescription", "World Baseball Classic"),
            })
    return games


def upsert_games_to_supabase(games: list):
    """Upsert WBC games to the Supabase games table."""
    if not games:
        log.info("No WBC games to upsert.")
        return
    url = f"{SUPABASE_URL}/rest/v1/games"
    headers = {
        "apikey": SUPABASE_SERVICE_KEY,
        "Authorization": f"Bearer {SUPABASE_SERVICE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "resolution=merge-duplicates",
    }
    resp = requests.post(url, headers=headers, json=games)
    resp.raise_for_status()
    log.info(f"Upserted {len(games)} WBC games to Supabase.")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Fetch WBC games (sportId=51) and upsert to Supabase")
    parser.add_argument("--date", type=str, default=None, help="Date to fetch (YYYY-MM-DD). Defaults to today.")
    parser.add_argument("--dry-run", action="store_true", help="Print games without writing to Supabase.")
    args = parser.parse_args()

    game_date = args.date or date.today().isoformat()
    log.info(f"Fetching WBC games for {game_date} (sportId={WBC_SPORT_ID})")

    schedule = fetch_wbc_schedule(game_date)
    games = parse_wbc_games(schedule)

    log.info(f"Found {len(games)} WBC games on {game_date}")
    for g in games:
        log.info(f"  {g['away_team']} @ {g['home_team']} at {g['venue']} | {g['away_probable_pitcher']} vs {g['home_probable_pitcher']}")

    if args.dry_run:
        log.info("[DRY RUN] Skipping Supabase upsert.")
        print(json.dumps(games, indent=2))
    else:
        if not SUPABASE_URL or not SUPABASE_SERVICE_KEY:
            raise EnvironmentError("SUPABASE_URL and SUPABASE_SERVICE_KEY must be set.")
        upsert_games_to_supabase(games)
