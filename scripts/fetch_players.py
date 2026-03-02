#!/usr/bin/env python3
"""
fetch_players.py
Fetches MLB player stats (hitting + pitching) for today's
probable pitchers and active roster batters.
Saves to data/players/players_YYYY-MM-DD.json
"""
import json
import os
from datetime import date

import requests

BASE_URL = "https://statsapi.mlb.com/api/v1"


def fetch_player_stats(player_id: int, group: str = "hitting", season: int = None) -> dict:
    """Fetch season stats for a single player."""
    if season is None:
        season = date.today().year
    url = f"{BASE_URL}/people/{player_id}/stats"
    params = {
        "stats": "season",
        "group": group,
        "season": season,
    }
    resp = requests.get(url, params=params, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    stats_list = data.get("stats", [])
    if not stats_list:
        return {}
    splits = stats_list[0].get("splits", [])
    if splits:
        return splits[0].get("stat", {})
    return {}


def fetch_player_info(player_id: int) -> dict:
    """Fetch basic bio info for a player."""
    url = f"{BASE_URL}/people/{player_id}"
    resp = requests.get(url, params={"hydrate": "currentTeam"}, timeout=30)
    resp.raise_for_status()
    people = resp.json().get("people", [])
    if people:
        p = people[0]
        return {
            "id": p["id"],
            "fullName": p.get("fullName", ""),
            "primaryPosition": p.get("primaryPosition", {}).get("abbreviation", ""),
            "currentTeam": p.get("currentTeam", {}).get("name", ""),
            "batSide": p.get("batSide", {}).get("code", ""),
            "pitchHand": p.get("pitchHand", {}).get("code", ""),
        }
    return {}


def load_today_pitcher_ids() -> list:
    """Load pitcher IDs from today's games file."""
    today = date.today().isoformat()
    games_path = os.path.join("data", "games", f"games_{today}.json")
    if not os.path.exists(games_path):
        print(f"Games file not found: {games_path}. Run fetch_games.py first.")
        return []
    with open(games_path) as f:
        games = json.load(f)
    ids = set()
    for g in games:
        if g.get("home_pitcher_id"):
            ids.add(g["home_pitcher_id"])
        if g.get("away_pitcher_id"):
            ids.add(g["away_pitcher_id"])
    return list(ids)


def fetch_team_roster(team_id: int) -> list:
    """Return active roster player IDs for a team."""
    url = f"{BASE_URL}/teams/{team_id}/roster"
    params = {"rosterType": "active"}
    resp = requests.get(url, params=params, timeout=30)
    resp.raise_for_status()
    roster = resp.json().get("roster", [])
    return [p["person"]["id"] for p in roster]


def save_players(players: list, game_date: str) -> None:
    out_dir = os.path.join("data", "players")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, f"players_{game_date}.json")
    with open(out_path, "w") as f:
        json.dump(players, f, indent=2)
    print(f"Saved {len(players)} player records to {out_path}")


if __name__ == "__main__":
    today = date.today().isoformat()
    pitcher_ids = load_today_pitcher_ids()
    print(f"Found {len(pitcher_ids)} probable pitchers for {today}")
    players = []
    for pid in pitcher_ids:
        try:
            info = fetch_player_info(pid)
            stats = fetch_player_stats(pid, group="pitching")
            players.append({"info": info, "pitching_stats": stats})
            print(f"  Fetched pitcher: {info.get('fullName', pid)}")
        except Exception as e:
            print(f"  Warning: Could not fetch stats for player {pid}: {e}")
            continue
    save_players(players, today)
    print("Done.")
