#!/usr/bin/env python3
"""
fetch_weather.py — Baseline MLB
Fetch weather data for each MLB ballpark using Open-Meteo (free, no API key).
Stores temperature, wind speed, wind direction, and humidity for game-time
conditions. Used as context features in the Monte Carlo simulation.

Data source: api.open-meteo.com (free, no key required)

Usage:
    # Fetch weather for today's games
    python pipeline/fetch_weather.py

    # Specific date
    python pipeline/fetch_weather.py --date 2025-06-15

    # Fetch historical weather for backfill
    python pipeline/fetch_weather.py --date 2024-07-04 --historical

    # Don't upload to Supabase
    python pipeline/fetch_weather.py --no-upload

Output:
    Upserts rows to the `game_weather` table in Supabase.
"""

import argparse
import json
import logging
import sys
import time
from datetime import date, timedelta
from pathlib import Path
from typing import Optional

import requests

# ── Project imports ───────────────────────────────────────────────────────────
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from lib.supabase import sb_get, sb_upsert

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("fetch_weather")

# ── Constants ─────────────────────────────────────────────────────────────────
MLB_API_BASE = "https://statsapi.mlb.com/api/v1"
OPEN_METEO_FORECAST = "https://api.open-meteo.com/v1/forecast"
OPEN_METEO_ARCHIVE = "https://archive-api.open-meteo.com/v1/archive"

# MLB ballpark coordinates (lat, lon)
# Source: official stadium locations
BALLPARK_COORDS = {
    "Chase Field":              (33.4455, -112.0667),
    "Truist Park":              (33.8907, -84.4677),
    "Oriole Park at Camden Yards": (39.2838, -76.6218),
    "Fenway Park":              (42.3467, -71.0972),
    "Wrigley Field":            (41.9484, -87.6553),
    "Guaranteed Rate Field":    (41.8299, -87.6338),
    "Great American Ball Park": (39.0974, -84.5065),
    "Progressive Field":        (41.4962, -81.6852),
    "Coors Field":              (39.7561, -104.9942),
    "Comerica Park":            (42.3390, -83.0485),
    "Minute Maid Park":         (29.7573, -95.3555),
    "Kauffman Stadium":         (39.0517, -94.4803),
    "Angel Stadium":            (33.8003, -117.8827),
    "Dodger Stadium":           (34.0739, -118.2400),
    "loanDepot park":           (25.7781, -80.2196),
    "American Family Field":    (43.0280, -87.9712),
    "Target Field":             (44.9818, -93.2775),
    "Citi Field":               (40.7571, -73.8458),
    "Yankee Stadium":           (40.8296, -73.9262),
    "Oakland Coliseum":         (37.7516, -122.2005),
    "Citizens Bank Park":       (39.9061, -75.1665),
    "PNC Park":                 (40.4469, -80.0058),
    "Petco Park":               (32.7076, -117.1570),
    "Oracle Park":              (37.7786, -122.3893),
    "T-Mobile Park":            (47.5914, -122.3325),
    "Busch Stadium":            (38.6226, -90.1928),
    "Tropicana Field":          (27.7682, -82.6534),
    "Globe Life Field":         (32.7473, -97.0845),
    "Rogers Centre":            (43.6414, -79.3894),
    "Nationals Park":           (38.8730, -77.0074),
    # 2025 relocated / new venues
    "Sacramento":               (38.5816, -121.4944),  # Athletics temporary
}

# Retractable/indoor roofs — weather less impactful
DOME_STADIUMS = {
    "Tropicana Field",        # Fixed dome
    "Minute Maid Park",       # Retractable
    "Globe Life Field",       # Retractable
    "Chase Field",            # Retractable
    "Rogers Centre",          # Retractable
    "American Family Field",  # Retractable
    "loanDepot park",         # Retractable
    "T-Mobile Park",          # Retractable
}


def get_ballpark_coords(venue_name: str) -> Optional[tuple]:
    """Look up lat/lon for a venue name, with fuzzy matching."""
    if venue_name in BALLPARK_COORDS:
        return BALLPARK_COORDS[venue_name]

    # Fuzzy match: check if venue name contains a known name
    venue_lower = venue_name.lower()
    for known_name, coords in BALLPARK_COORDS.items():
        if known_name.lower() in venue_lower or venue_lower in known_name.lower():
            return coords

    log.warning(f"Unknown venue: {venue_name}")
    return None


def fetch_weather_for_location(
    lat: float,
    lon: float,
    target_date: str,
    game_hour: int = 19,
    historical: bool = False,
) -> Optional[dict]:
    """
    Fetch hourly weather from Open-Meteo for a specific location and date.

    Args:
        lat, lon: Coordinates.
        target_date: YYYY-MM-DD.
        game_hour: Expected game start hour (local time, 24h). Default 7pm.
        historical: Use archive API for past dates.

    Returns:
        Dict with temp_f, wind_speed_mph, wind_direction, humidity, conditions.
    """
    base_url = OPEN_METEO_ARCHIVE if historical else OPEN_METEO_FORECAST
    params = {
        "latitude": lat,
        "longitude": lon,
        "hourly": "temperature_2m,relative_humidity_2m,wind_speed_10m,wind_direction_10m,precipitation,weathercode",
        "temperature_unit": "fahrenheit",
        "wind_speed_unit": "mph",
        "timezone": "America/New_York",
    }

    if historical:
        params["start_date"] = target_date
        params["end_date"] = target_date
    else:
        params["start_date"] = target_date
        params["end_date"] = target_date

    try:
        r = requests.get(base_url, params=params, timeout=15)
        r.raise_for_status()
        data = r.json()

        hourly = data.get("hourly", {})
        times = hourly.get("time", [])
        temps = hourly.get("temperature_2m", [])
        humidity = hourly.get("relative_humidity_2m", [])
        wind_speed = hourly.get("wind_speed_10m", [])
        wind_dir = hourly.get("wind_direction_10m", [])
        precip = hourly.get("precipitation", [])
        weather_codes = hourly.get("weathercode", [])

        if not times:
            return None

        # Find the hour closest to game time
        target_idx = min(game_hour, len(times) - 1)
        for i, t in enumerate(times):
            if f"T{game_hour:02d}:" in t:
                target_idx = i
                break

        weather_code = weather_codes[target_idx] if target_idx < len(weather_codes) else None
        conditions = _decode_weather_code(weather_code)

        return {
            "temp_f": round(temps[target_idx], 1) if target_idx < len(temps) else None,
            "humidity_pct": round(humidity[target_idx], 1) if target_idx < len(humidity) else None,
            "wind_speed_mph": round(wind_speed[target_idx], 1) if target_idx < len(wind_speed) else None,
            "wind_direction_deg": round(wind_dir[target_idx], 0) if target_idx < len(wind_dir) else None,
            "precipitation_mm": round(precip[target_idx], 2) if target_idx < len(precip) else None,
            "conditions": conditions,
        }

    except Exception as e:
        log.warning(f"Weather fetch failed for ({lat}, {lon}): {e}")
        return None


def _decode_weather_code(code) -> str:
    """Decode WMO weather code to human-readable string."""
    if code is None:
        return "unknown"
    WMO_CODES = {
        0: "clear", 1: "mainly_clear", 2: "partly_cloudy", 3: "overcast",
        45: "fog", 48: "fog", 51: "light_drizzle", 53: "drizzle",
        55: "heavy_drizzle", 61: "light_rain", 63: "rain", 65: "heavy_rain",
        71: "light_snow", 73: "snow", 75: "heavy_snow", 80: "light_showers",
        81: "showers", 82: "heavy_showers", 95: "thunderstorm",
        96: "thunderstorm_hail", 99: "thunderstorm_hail",
    }
    return WMO_CODES.get(int(code), "unknown")


def _wind_direction_label(degrees: float) -> str:
    """Convert wind direction in degrees to compass label."""
    if degrees is None:
        return "unknown"
    dirs = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
            "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"]
    idx = int((degrees + 11.25) / 22.5) % 16
    return dirs[idx]


def fetch_todays_games(target_date: str) -> list[dict]:
    """Get games from Supabase or MLB API for the target date."""
    # Try Supabase first (games table populated by fetch_games.py)
    try:
        games = sb_get("games", {
            "game_date": f"eq.{target_date}",
            "select": "game_pk,game_date,venue,home_team,away_team,game_time",
        })
        if games:
            return games
    except Exception as e:
        log.debug(f"Supabase games fetch failed: {e}")

    # Fall back to MLB API
    log.info("Falling back to MLB Stats API for schedule ...")
    url = f"{MLB_API_BASE}/schedule"
    params = {"sportId": 1, "date": target_date, "hydrate": "venue"}
    try:
        r = requests.get(url, params=params, timeout=15)
        r.raise_for_status()
        data = r.json()
        games = []
        for day in data.get("dates", []):
            for game in day.get("games", []):
                games.append({
                    "game_pk": game.get("gamePk"),
                    "game_date": target_date,
                    "venue": game.get("venue", {}).get("name"),
                    "home_team": game.get("teams", {}).get("home", {}).get("team", {}).get("name"),
                    "away_team": game.get("teams", {}).get("away", {}).get("team", {}).get("name"),
                    "game_time": game.get("gameDate", "")[11:16],
                })
        return games
    except Exception as e:
        log.error(f"Failed to fetch schedule: {e}")
        return []


def estimate_game_hour(game_time: str) -> int:
    """Estimate local game hour from UTC time string (HH:MM)."""
    if not game_time:
        return 19  # Default 7pm local
    try:
        hour = int(game_time.split(":")[0])
        # Convert UTC to approximate ET (subtract 4-5 hours)
        local_hour = (hour - 4) % 24
        return local_hour
    except (ValueError, IndexError):
        return 19


def process_weather(target_date: str, historical: bool = False, upload: bool = True) -> list[dict]:
    """
    Main logic: fetch weather for all games on the target date.
    """
    games = fetch_todays_games(target_date)
    log.info(f"Found {len(games)} games for {target_date}")

    weather_rows = []
    for game in games:
        venue = game.get("venue", "Unknown")
        game_pk = game.get("game_pk")
        game_time = game.get("game_time")
        game_hour = estimate_game_hour(game_time)

        coords = get_ballpark_coords(venue)
        if not coords:
            log.warning(f"  Skipping {venue} (unknown coordinates)")
            continue

        is_dome = venue in DOME_STADIUMS
        lat, lon = coords

        log.info(f"  {venue}: ({lat}, {lon}) {'[dome]' if is_dome else ''}")

        weather = fetch_weather_for_location(
            lat, lon, target_date,
            game_hour=game_hour,
            historical=historical,
        )

        if weather:
            row = {
                "game_pk": game_pk,
                "game_date": target_date,
                "venue": venue,
                "home_team": game.get("home_team"),
                "is_dome": is_dome,
                "temp_f": weather["temp_f"],
                "humidity_pct": weather["humidity_pct"],
                "wind_speed_mph": weather["wind_speed_mph"],
                "wind_direction_deg": weather["wind_direction_deg"],
                "wind_direction_label": _wind_direction_label(weather["wind_direction_deg"]),
                "precipitation_mm": weather["precipitation_mm"],
                "conditions": weather["conditions"],
                "game_hour_local": game_hour,
            }
            weather_rows.append(row)

            log.info(
                f"    {weather['temp_f']}°F, "
                f"wind {weather['wind_speed_mph']}mph "
                f"{_wind_direction_label(weather['wind_direction_deg'])}, "
                f"humidity {weather['humidity_pct']}%, "
                f"{weather['conditions']}"
            )
        else:
            log.warning("    No weather data available")

        # Rate limit: Open-Meteo allows 10,000 requests/day but be polite
        time.sleep(0.5)

    log.info(f"\nWeather data for {len(weather_rows)}/{len(games)} games")

    if upload and weather_rows:
        sb_upsert("game_weather", weather_rows)
        log.info(f"Uploaded {len(weather_rows)} weather rows to Supabase.")

    return weather_rows


# ── CLI ───────────────────────────────────────────────────────────────────────

def parse_args():
    parser = argparse.ArgumentParser(
        description="Fetch weather data for MLB ballparks using Open-Meteo."
    )
    parser.add_argument(
        "--date", type=str, default=None,
        help="Game date (YYYY-MM-DD). Default: today."
    )
    parser.add_argument(
        "--historical", action="store_true",
        help="Use archive API for past dates."
    )
    parser.add_argument(
        "--no-upload", action="store_true",
        help="Skip Supabase upload."
    )
    parser.add_argument(
        "--json", action="store_true",
        help="Output weather data as JSON."
    )
    parser.add_argument(
        "--backfill-days", type=int, default=None,
        help="Backfill weather for N days before --date."
    )
    return parser.parse_args()


def main():
    args = parse_args()
    target_date = args.date or date.today().isoformat()
    upload = not args.no_upload

    # Auto-detect if we need historical API
    historical = args.historical
    if not historical:
        try:
            if date.fromisoformat(target_date) < date.today():
                historical = True
        except ValueError:
            pass

    if args.backfill_days:
        log.info(f"Backfilling {args.backfill_days} days of weather data ...")
        end_date = date.fromisoformat(target_date)
        for i in range(args.backfill_days):
            d = end_date - timedelta(days=i)
            log.info(f"\n=== {d} ===")
            rows = process_weather(str(d), historical=True, upload=upload)
            if args.json and rows:
                print(json.dumps(rows, indent=2, default=str))
            time.sleep(1)
    else:
        rows = process_weather(target_date, historical=historical, upload=upload)
        if args.json:
            print(json.dumps(rows, indent=2, default=str))

    log.info("=== Done ===")


if __name__ == "__main__":
    main()
