#!/usr/bin/env python3
"""
fetch_games.py
Fetches today's MLB game schedule from the MLB Stats API
and saves it to data/games/games_YYYY-MM-DD.json
"""

import os
import json
import requests
from datetime import date

BASE_URL = "https://statsapi.mlb.com/api/v1"


def fetch_schedule(game_date: str = None) -> dict:
    """Fetch MLB schedule for a given date (default: today)."""
    if game_date is None:
        game_date = date.today().isoformat()

    url = f"{BASE_URL}/schedule"
    params = {
        "sportId": 1,
        "date": game_date,
        "hydrate": "team,linescore,probablePitcher,officials,weather",
    }
    resp = requests.get(url, params=params, timeout=30)
    resp.raise_for_status()
    return resp.json()


def parse_games(schedule: dict) -> list:
    """Parse raw schedule response into a flat list of game dicts."""
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
            })
    return games


def save_games(games: list, game_date: str) -> None:
    """Save games list to data/games/games_YYYY-MM-DD.json."""
    out_dir = os.path.join("data", "games")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, f"games_{game_date}.json")
    with open(out_path, "w") as f:
        json.dump(games, f, indent=2)
    print(f"Saved {len(games)} games to {out_path}")


if __name__ == "__main__":
    today = date.today().isoformat()
    print(f"Fetching MLB schedule for {today}...")
    schedule = fetch_schedule(today)
    games = parse_games(schedule)
    save_games(games, today)
    print("Done.")
