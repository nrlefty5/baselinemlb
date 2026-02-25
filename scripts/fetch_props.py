#!/usr/bin/env python3
"""
fetch_props.py
Scrapes or pulls MLB player prop lines (strikeouts, hits, total bases,
RBIs, runs, home runs) from The Odds API.
Saves to data/props/props_YYYY-MM-DD.json

Requires env var: ODDS_API_KEY
"""

import os
import json
import requests
from datetime import date

ODDS_API_BASE = "https://api.the-odds-api.com/v4"
SPORT = "baseball_mlb"

# Props we care about for mid-stakes MLB prop betting
PROP_MARKETS = [
    "batter_hits",
    "batter_total_bases",
    "batter_rbis",
    "batter_runs_scored",
    "batter_home_runs",
    "pitcher_strikeouts",
    "pitcher_hits_allowed",
    "pitcher_walks",
    "pitcher_earned_runs",
    "pitcher_outs",
]


def get_api_key() -> str:
    key = os.environ.get("ODDS_API_KEY", "")
    if not key:
        raise EnvironmentError(
            "ODDS_API_KEY not set. Add it as a GitHub Actions secret."
        )
    return key


def fetch_event_ids(api_key: str) -> list:
    """Fetch today's MLB event IDs from The Odds API."""
    url = f"{ODDS_API_BASE}/sports/{SPORT}/events"
    params = {"apiKey": api_key, "dateFormat": "iso"}
    resp = requests.get(url, params=params, timeout=30)
    resp.raise_for_status()
    events = resp.json()
    print(f"Found {len(events)} MLB events.")
    return events


def fetch_props_for_event(api_key: str, event_id: str, markets: list) -> dict:
    """Fetch player prop odds for a single event."""
    url = f"{ODDS_API_BASE}/sports/{SPORT}/events/{event_id}/odds"
    params = {
        "apiKey": api_key,
        "regions": "us",
        "markets": ",".join(markets),
        "oddsFormat": "american",
        "dateFormat": "iso",
    }
    resp = requests.get(url, params=params, timeout=30)
    if resp.status_code == 422:
        # No prop data available for this event yet
        return {}
    resp.raise_for_status()
    return resp.json()


def parse_props(event_data: dict) -> list:
    """Flatten prop odds into a list of records."""
    records = []
    if not event_data:
        return records
    game_id = event_data.get("id", "")
    home_team = event_data.get("home_team", "")
    away_team = event_data.get("away_team", "")
    commence_time = event_data.get("commence_time", "")

    for bookmaker in event_data.get("bookmakers", []):
        book_key = bookmaker.get("key", "")
        for market in bookmaker.get("markets", []):
            market_key = market.get("key", "")
            for outcome in market.get("outcomes", []):
                records.append({
                    "game_id": game_id,
                    "home_team": home_team,
                    "away_team": away_team,
                    "commence_time": commence_time,
                    "bookmaker": book_key,
                    "market": market_key,
                    "player": outcome.get("description", ""),
                    "name": outcome.get("name", ""),
                    "price": outcome.get("price", None),
                    "point": outcome.get("point", None),
                })
    return records


def save_props(props: list, game_date: str) -> None:
    out_dir = os.path.join("data", "props")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, f"props_{game_date}.json")
    with open(out_path, "w") as f:
        json.dump(props, f, indent=2)
    print(f"Saved {len(props)} prop records to {out_path}")


if __name__ == "__main__":
    today = date.today().isoformat()
    api_key = get_api_key()
    print(f"Fetching MLB prop lines for {today}...")

    events = fetch_event_ids(api_key)
    all_props = []

    for event in events:
        event_id = event["id"]
        home = event.get("home_team", "")
        away = event.get("away_team", "")
        print(f"  Fetching props for {away} @ {home} (id={event_id})")
        event_data = fetch_props_for_event(api_key, event_id, PROP_MARKETS)
        props = parse_props(event_data)
        all_props.extend(props)

    save_props(all_props, today)
    print(f"Done. Total prop records: {len(all_props)}")
