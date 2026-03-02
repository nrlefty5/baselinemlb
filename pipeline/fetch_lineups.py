#!/usr/bin/env python3
"""
fetch_lineups.py — Baseline MLB
Fetch confirmed starting lineups from the MLB Stats API for today's games
(or a specified date). Required so the Monte Carlo simulator only models
batters who are actually in the lineup.

Data source: statsapi.mlb.com/api/v1

Usage:
    # Fetch today's lineups
    python pipeline/fetch_lineups.py

    # Specific date
    python pipeline/fetch_lineups.py --date 2025-06-15

    # Don't upload to Supabase (local only)
    python pipeline/fetch_lineups.py --no-upload

Output:
    Upserts rows to the `lineups` table in Supabase.
    Also prints JSON summary to stdout.
"""

import argparse
import json
import logging
import sys
from datetime import date
from pathlib import Path

import requests

# ── Project imports ────────────────────────────────────────────────────────────────────────────
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from lib.supabase import sb_upsert

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("fetch_lineups")

# ── Constants ────────────────────────────────────────────────────────────────────────────
MLB_API_BASE = "https://statsapi.mlb.com/api/v1"


def fetch_schedule(target_date: str) -> list[dict]:
    """Get today's game schedule from MLB Stats API."""
    url = f"{MLB_API_BASE}/schedule"
    params = {
        "sportId": 1,
        "date": target_date,
        "hydrate": "probablePitcher,lineups,venue",
    }
    try:
        r = requests.get(url, params=params, timeout=15)
        r.raise_for_status()
        data = r.json()
        games = []
        for day in data.get("dates", []):
            for game in day.get("games", []):
                games.append(game)
        return games
    except Exception as e:
        log.error(f"Failed to fetch schedule: {e}")
        return []


def fetch_game_lineup(game_pk: int) -> dict:
    """
    Fetch the confirmed lineup for a specific game via the boxscore endpoint.
    Returns lineup data for both home and away teams.
    """
    url = f"{MLB_API_BASE}/game/{game_pk}/boxscore"
    try:
        r = requests.get(url, timeout=15)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        log.warning(f"Failed to fetch boxscore for game {game_pk}: {e}")
        return {}


def extract_lineup_from_boxscore(boxscore: dict, side: str) -> list[dict]:
    """
    Extract the batting order from a boxscore response.

    Args:
        boxscore: The boxscore JSON response.
        side: "home" or "away".

    Returns:
        List of dicts with batting order, player info.
    """
    team_data = boxscore.get("teams", {}).get(side, {})
    players_data = team_data.get("players", {})
    team_info = team_data.get("team", {})
    team_name = team_info.get("name", "Unknown")

    lineup = []
    for player_key, player_data in players_data.items():
        batting_order = player_data.get("battingOrder")
        if not batting_order:
            continue

        person = player_data.get("person", {})
        position = player_data.get("position", {})

        # battingOrder is a string like "100", "200", ..., "900"
        # The hundreds digit = lineup slot (1-9)
        try:
            order_num = int(str(batting_order)[0])
        except (ValueError, IndexError):
            continue

        # Skip non-starters (substitutes have orders like "101", "201")
        if len(str(batting_order)) > 1 and str(batting_order)[-2:] != "00":
            continue

        lineup.append({
            "mlbam_id": person.get("id"),
            "full_name": person.get("fullName", "Unknown"),
            "batting_order": order_num,
            "position": position.get("abbreviation", ""),
            "team": team_name,
            "side": side,
            "bats": None,  # Will be filled from roster data if available
        })

    # Sort by batting order
    lineup.sort(key=lambda x: x["batting_order"])
    return lineup


def fetch_lineup_from_feed(game_pk: int) -> dict:
    """
    Alternative: fetch lineup from the game feed (live data).
    Sometimes more reliable for pre-game lineups.
    """
    url = f"{MLB_API_BASE}.1/game/{game_pk}/feed/live"
    try:
        r = requests.get(url, timeout=15)
        r.raise_for_status()
        data = r.json()

        result = {"home": [], "away": []}
        for side in ["home", "away"]:
            team_data = data.get("liveData", {}).get("boxscore", {}).get("teams", {}).get(side, {})
            batting_order_list = team_data.get("battingOrder", [])
            players = team_data.get("players", {})
            team_info = data.get("gameData", {}).get("teams", {}).get(side, {})
            team_name = team_info.get("name", "Unknown")

            for idx, player_id in enumerate(batting_order_list, 1):
                pkey = f"ID{player_id}"
                pdata = players.get(pkey, {})
                person = pdata.get("person", {})
                position = pdata.get("position", {})

                result[side].append({
                    "mlbam_id": player_id,
                    "full_name": person.get("fullName", f"Player {player_id}"),
                    "batting_order": idx,
                    "position": position.get("abbreviation", ""),
                    "team": team_name,
                    "side": side,
                    "bats": person.get("batSide", {}).get("code"),
                })

        return result
    except Exception as e:
        log.debug(f"Feed lineup fetch failed for {game_pk}: {e}")
        return {"home": [], "away": []}


def enrich_batter_handedness(lineup: list[dict]) -> list[dict]:
    """Add batter handedness from MLB Stats API if not already present."""
    for batter in lineup:
        if batter.get("bats"):
            continue
        mlbam_id = batter.get("mlbam_id")
        if not mlbam_id:
            continue
        try:
            url = f"{MLB_API_BASE}/people/{mlbam_id}"
            r = requests.get(url, timeout=10)
            r.raise_for_status()
            person = r.json().get("people", [{}])[0]
            batter["bats"] = person.get("batSide", {}).get("code", "R")
        except Exception:
            batter["bats"] = "R"  # Default fallback
    return lineup


def process_games(target_date: str, upload: bool = True) -> list[dict]:
    """
    Main logic: fetch schedule, extract lineups, optionally upload to Supabase.
    """
    log.info(f"Fetching lineups for {target_date} ...")
    games = fetch_schedule(target_date)
    log.info(f"Found {len(games)} games")

    all_lineup_rows = []
    games_with_lineups = 0

    for game in games:
        game_pk = game.get("gamePk")
        status = game.get("status", {}).get("detailedState", "")

        teams = game.get("teams", {})
        home_team = teams.get("home", {}).get("team", {}).get("name", "Unknown")
        away_team = teams.get("away", {}).get("team", {}).get("name", "Unknown")
        venue = game.get("venue", {}).get("name", "Unknown")

        log.info(f"  Game {game_pk}: {away_team} @ {home_team} ({status})")

        # Try feed endpoint first (better for pre-game lineups)
        feed_data = fetch_lineup_from_feed(game_pk)
        home_lineup = feed_data.get("home", [])
        away_lineup = feed_data.get("away", [])

        # Fall back to boxscore if feed is empty
        if not home_lineup and not away_lineup:
            boxscore = fetch_game_lineup(game_pk)
            if boxscore:
                home_lineup = extract_lineup_from_boxscore(boxscore, "home")
                away_lineup = extract_lineup_from_boxscore(boxscore, "away")

        if not home_lineup and not away_lineup:
            log.info("    No lineup available yet (lineups typically posted ~2hrs before game)")
            continue

        games_with_lineups += 1

        # Enrich with handedness
        home_lineup = enrich_batter_handedness(home_lineup)
        away_lineup = enrich_batter_handedness(away_lineup)

        # Build rows for Supabase
        for batter in home_lineup + away_lineup:
            all_lineup_rows.append({
                "game_pk": game_pk,
                "game_date": target_date,
                "mlbam_id": batter["mlbam_id"],
                "full_name": batter["full_name"],
                "team": batter["team"],
                "side": batter["side"],
                "batting_order": batter["batting_order"],
                "position": batter["position"],
                "bats": batter.get("bats"),
                "venue": venue,
            })

        h_count = len(home_lineup)
        a_count = len(away_lineup)
        log.info(f"    Home: {h_count} batters, Away: {a_count} batters")

    log.info(f"\n{games_with_lineups}/{len(games)} games have confirmed lineups")
    log.info(f"Total lineup entries: {len(all_lineup_rows)}")

    # Upload to Supabase
    if upload and all_lineup_rows:
        sb_upsert("lineups", all_lineup_rows)
        log.info(f"Uploaded {len(all_lineup_rows)} lineup entries to Supabase.")

    return all_lineup_rows


# ── CLI ─────────────────────────────────────────────────────────────────────────────────────

def parse_args():
    parser = argparse.ArgumentParser(
        description="Fetch confirmed starting lineups from MLB Stats API."
    )
    parser.add_argument(
        "--date", type=str, default=None,
        help="Game date (YYYY-MM-DD). Default: today."
    )
    parser.add_argument(
        "--no-upload", action="store_true",
        help="Skip Supabase upload (print to stdout only)."
    )
    parser.add_argument(
        "--json", action="store_true",
        help="Output lineup data as JSON."
    )
    return parser.parse_args()


def main():
    args = parse_args()
    target_date = args.date or date.today().isoformat()
    upload = not args.no_upload

    rows = process_games(target_date, upload=upload)

    if args.json:
        print(json.dumps(rows, indent=2, default=str))

    log.info("=== Done ===")


if __name__ == "__main__":
    main()
