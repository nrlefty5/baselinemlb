#!/usr/bin/env python3
"""
run_daily.py — BaselineMLB
============================
Daily orchestrator that fetches today's lineups, weather, and umpire data,
runs Monte Carlo simulations for all games, and outputs a JSON file of all
prop edges.

Usage:
    python -m simulator.run_daily [--date 2026-04-01] [--sims 3000]
                                  [--bankroll 5000] [--output edges.json]

Environment Variables:
    SUPABASE_URL            Supabase project URL
    SUPABASE_SERVICE_KEY    Supabase service-role key (for reads + writes)
    ODDS_API_KEY            (Optional) The Odds API key for live prop lines
    OPENWEATHER_API_KEY     (Optional) OpenWeatherMap API key for weather data
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from datetime import date, datetime
from typing import Optional

import numpy as np
import requests

# Handle both direct and package imports
try:
    from simulator.monte_carlo_engine import (
        BatterProfile,
        BullpenProfile,
        GameMatchup,
        GameSimResults,
        PitcherProfile,
        build_batter_probs,
        build_bullpen_profile,
        build_pitcher_profile_from_stats,
        simulate_game_with_pitcher_ks,
        MLB_AVG_PROBS,
    )
    from simulator.prop_calculator import PropCalculator, PropEdge, PropLine
except ImportError:
    from monte_carlo_engine import (
        BatterProfile,
        BullpenProfile,
        GameMatchup,
        GameSimResults,
        PitcherProfile,
        build_batter_probs,
        build_bullpen_profile,
        build_pitcher_profile_from_stats,
        simulate_game_with_pitcher_ks,
        MLB_AVG_PROBS,
    )
    from prop_calculator import PropCalculator, PropEdge, PropLine

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("baselinemlb.run_daily")


# ---------------------------------------------------------------------------
# Supabase helpers (standalone, no lib dependency)
# ---------------------------------------------------------------------------

SUPABASE_URL = os.environ.get("SUPABASE_URL", "").strip()
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_KEY", "").strip()
MLB_API_BASE = "https://statsapi.mlb.com/api/v1"

# Park K-factor adjustments (all 30 MLB stadiums)
PARK_K_FACTORS = {
    "Coors Field": -8, "Yankee Stadium": 3, "Oracle Park": 5,
    "Petco Park": 4, "Truist Park": 2, "Globe Life Field": 2,
    "Chase Field": 1, "T-Mobile Park": 3, "Guaranteed Rate Field": 0,
    "loanDepot park": 1, "Great American Ball Park": -2,
    "PNC Park": 1, "Minute Maid Park": 2, "Dodger Stadium": 4,
    "Angel Stadium": 0, "Fenway Park": -1, "Wrigley Field": -3,
    "Busch Stadium": 1, "Citizens Bank Park": -2,
    "Citi Field": 2, "Nationals Park": 1, "Target Field": 0,
    "Tropicana Field": 1, "Kauffman Stadium": -1, "Rogers Centre": 0,
    "Oakland Coliseum": 3, "Camden Yards": -1, "Comerica Park": 2,
    "American Family Field": -2, "Progressive Field": 0,
    "loanDepot Park": 1,
}

# Park HR-factor adjustments
PARK_HR_FACTORS = {
    "Coors Field": 1.30, "Yankee Stadium": 1.15, "Great American Ball Park": 1.18,
    "Fenway Park": 0.95, "Oracle Park": 0.85, "Petco Park": 0.88,
    "Dodger Stadium": 0.98, "Wrigley Field": 1.08, "Citizens Bank Park": 1.10,
    "Camden Yards": 1.05, "T-Mobile Park": 0.90, "Minute Maid Park": 1.02,
}


def sb_headers():
    return {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
    }


def sb_get(table, params):
    if not SUPABASE_URL:
        return []
    r = requests.get(
        f"{SUPABASE_URL}/rest/v1/{table}",
        headers=sb_headers(),
        params=params,
        timeout=15,
    )
    if r.ok:
        return r.json()
    log.warning(f"Supabase GET {table} failed: {r.status_code}")
    return []


# ---------------------------------------------------------------------------
# MLB Stats API — data fetching
# ---------------------------------------------------------------------------

def fetch_todays_games(game_date: str) -> list:
    """Fetch today's MLB schedule with probable pitchers."""
    url = f"{MLB_API_BASE}/schedule"
    params = {
        "date": game_date,
        "sportId": 1,
        "hydrate": "probablePitcher,team,venue,linescore",
    }
    try:
        r = requests.get(url, params=params, timeout=15)
        r.raise_for_status()
        data = r.json()
        games = []
        for d in data.get("dates", []):
            for g in d.get("games", []):
                if g.get("status", {}).get("abstractGameState") == "Final":
                    continue  # Skip completed games
                game = {
                    "game_pk": g["gamePk"],
                    "home_team": g["teams"]["home"]["team"]["name"],
                    "away_team": g["teams"]["away"]["team"]["name"],
                    "home_abbr": g["teams"]["home"]["team"].get("abbreviation", ""),
                    "away_abbr": g["teams"]["away"]["team"].get("abbreviation", ""),
                    "venue": g.get("venue", {}).get("name", "Unknown"),
                    "game_date": game_date,
                    "game_time": g.get("gameDate", ""),
                }
                # Probable pitchers
                home_pitcher = g["teams"]["home"].get("probablePitcher", {})
                away_pitcher = g["teams"]["away"].get("probablePitcher", {})
                game["home_pitcher_id"] = home_pitcher.get("id")
                game["home_pitcher_name"] = home_pitcher.get("fullName")
                game["away_pitcher_id"] = away_pitcher.get("id")
                game["away_pitcher_name"] = away_pitcher.get("fullName")
                games.append(game)
        return games
    except Exception as e:
        log.error(f"Failed to fetch schedule: {e}")
        return []


def fetch_lineup(game_pk: int, side: str = "home") -> list:
    """
    Fetch starting lineup for a game from the live feed.

    Returns list of dicts with mlbam_id, name, position, batting_order.
    Falls back to roster if lineup not yet posted.
    """
    try:
        url = f"{MLB_API_BASE}.1/game/{game_pk}/feed/live"
        r = requests.get(url, timeout=10)
        r.raise_for_status()
        data = r.json()

        players = (
            data.get("liveData", {})
            .get("boxscore", {})
            .get("teams", {})
            .get(side, {})
            .get("players", {})
        )

        lineup = []
        for pid_str, pdata in players.items():
            order = pdata.get("battingOrder")
            if order and int(str(order)[-1]) == 0:  # Starting lineup positions end in 0
                pos = int(str(order)[:-1])  # Extract batting order position
                lineup.append({
                    "mlbam_id": pdata["person"]["id"],
                    "name": pdata["person"]["fullName"],
                    "position": pdata.get("position", {}).get("abbreviation", ""),
                    "batting_order": pos,
                    "bats": pdata.get("person", {}).get("batSide", {}).get("code", "R"),
                })

        lineup.sort(key=lambda x: x["batting_order"])
        return lineup[:9]  # Ensure exactly 9

    except Exception as e:
        log.debug(f"Lineup fetch failed for game {game_pk} ({side}): {e}")
        return []


def fetch_batter_stats(mlbam_id: int, season: int = None) -> dict:
    """Fetch batter season stats from MLB Stats API."""
    if season is None:
        season = date.today().year
    try:
        url = f"{MLB_API_BASE}/people/{mlbam_id}/stats"
        r = requests.get(url, params={
            "stats": "season",
            "group": "hitting",
            "season": season,
            "sportId": 1,
        }, timeout=10)
        r.raise_for_status()
        stats_list = r.json().get("stats", [])
        if stats_list:
            splits = stats_list[0].get("splits", [])
            if splits:
                return splits[0].get("stat", {})
    except Exception as e:
        log.debug(f"Batter stats fetch failed for {mlbam_id}: {e}")
    return {}


def fetch_pitcher_stats(mlbam_id: int, season: int = None) -> dict:
    """Fetch pitcher season + career stats from MLB Stats API."""
    if season is None:
        season = date.today().year
    result = {"career_k9": 8.5, "season_k9": None, "avg_ip": 5.5, "recent_pitch_counts": []}

    try:
        # Career stats
        url = f"{MLB_API_BASE}/people/{mlbam_id}/stats"
        r = requests.get(url, params={
            "stats": "career", "group": "pitching", "sportId": 1,
        }, timeout=10)
        r.raise_for_status()
        splits = r.json().get("stats", [{}])[0].get("splits", [])
        if splits:
            stat = splits[0].get("stat", {})
            k = float(stat.get("strikeOuts", 0))
            ip_str = str(stat.get("inningsPitched", "0.0"))
            parts = ip_str.split(".")
            ip = int(parts[0]) + (int(parts[1]) / 3 if len(parts) > 1 and parts[1] else 0)
            if ip > 0:
                result["career_k9"] = round((k / ip) * 9, 2)
    except Exception as e:
        log.debug(f"Career stats fetch failed for {mlbam_id}: {e}")

    try:
        # Game log for recent pitch counts
        url = f"{MLB_API_BASE}/people/{mlbam_id}/stats"
        r = requests.get(url, params={
            "stats": "gameLog", "group": "pitching",
            "season": season, "sportId": 1,
        }, timeout=10)
        r.raise_for_status()
        splits = r.json().get("stats", [{}])[0].get("splits", [])
        pitch_counts = []
        total_ip = 0.0
        starts = 0
        for s in splits[-10:]:  # Last 10 appearances
            stat = s.get("stat", {})
            pc = stat.get("numberOfPitches", 0)
            if pc > 0:
                pitch_counts.append(pc)
            gs = stat.get("gamesStarted", 0)
            if gs:
                starts += 1
                ip_str = str(stat.get("inningsPitched", "0.0"))
                parts = ip_str.split(".")
                total_ip += int(parts[0]) + (int(parts[1]) / 3 if len(parts) > 1 and parts[1] else 0)

        result["recent_pitch_counts"] = pitch_counts
        if starts > 0 and total_ip > 0:
            result["avg_ip"] = round(total_ip / starts, 2)
    except Exception as e:
        log.debug(f"Game log fetch failed for {mlbam_id}: {e}")

    return result


def fetch_team_bullpen_stats(team_name: str, season: int = None) -> dict:
    """Fetch team bullpen aggregate stats."""
    if season is None:
        season = date.today().year
    try:
        url = f"{MLB_API_BASE}/teams"
        r = requests.get(url, params={"sportId": 1, "season": season}, timeout=10)
        r.raise_for_status()
        teams = r.json().get("teams", [])
        team_id = None
        for t in teams:
            if t.get("name") == team_name:
                team_id = t["id"]
                break
        if not team_id:
            return {"era": 4.0, "k9": 8.5, "bb9": 3.5}

        url = f"{MLB_API_BASE}/teams/{team_id}/stats"
        r = requests.get(url, params={
            "stats": "season", "group": "pitching",
            "season": season, "sportId": 1,
        }, timeout=10)
        r.raise_for_status()
        splits = r.json().get("stats", [{}])[0].get("splits", [])
        if splits:
            stat = splits[0].get("stat", {})
            era = float(stat.get("era", "4.00"))
            k = float(stat.get("strikeOuts", 0))
            ip_str = str(stat.get("inningsPitched", "0.0"))
            parts = ip_str.split(".")
            ip = int(parts[0]) + (int(parts[1]) / 3 if len(parts) > 1 and parts[1] else 0)
            k9 = (k / ip * 9) if ip > 0 else 8.5
            bb = float(stat.get("baseOnBalls", 0))
            bb9 = (bb / ip * 9) if ip > 0 else 3.5
            return {"era": era, "k9": round(k9, 2), "bb9": round(bb9, 2)}
    except Exception as e:
        log.debug(f"Bullpen stats fetch failed for {team_name}: {e}")
    return {"era": 4.0, "k9": 8.5, "bb9": 3.5}


def fetch_umpire_factor(game_pk: int) -> float:
    """Fetch umpire K-rate factor from game data or Supabase."""
    try:
        url = f"{MLB_API_BASE}.1/game/{game_pk}/feed/live"
        r = requests.get(url, timeout=10)
        r.raise_for_status()
        data = r.json()
        officials = data.get("liveData", {}).get("boxscore", {}).get("officials", [])
        for official in officials:
            if official.get("officialType") == "Home Plate":
                ump_name = official.get("official", {}).get("fullName")
                if ump_name and SUPABASE_URL:
                    rows = sb_get("umpire_framing", {
                        "umpire_name": f"eq.{ump_name}",
                        "select": "strike_rate",
                        "order": "game_date.desc",
                        "limit": "30",
                    })
                    if rows and len(rows) >= 5:
                        avg_sr = sum(r["strike_rate"] for r in rows) / len(rows)
                        return avg_sr / 0.32 if avg_sr > 0 else 1.0
                break
    except Exception as e:
        log.debug(f"Umpire factor fetch failed for game {game_pk}: {e}")
    return 1.0


def fetch_weather(venue: str) -> dict:
    """
    Fetch weather data for a venue.

    Returns dict with temperature_f, wind_mph, wind_direction, humidity.
    Falls back to neutral defaults if API key not set or fetch fails.
    """
    api_key = os.environ.get("OPENWEATHER_API_KEY", "")
    if not api_key:
        return {"temperature_f": 72, "wind_mph": 5, "humidity": 50, "source": "default"}

    # Approximate venue geocoding (simplified — production would use a full lookup)
    venue_coords = {
        "Coors Field": (39.76, -104.99), "Yankee Stadium": (40.83, -73.93),
        "Oracle Park": (37.78, -122.39), "Dodger Stadium": (34.07, -118.24),
        "Wrigley Field": (41.95, -87.66), "Fenway Park": (42.35, -71.10),
        "Petco Park": (32.71, -117.16), "Minute Maid Park": (29.76, -95.36),
        "Citi Field": (40.76, -73.85), "Truist Park": (33.89, -84.47),
    }

    coords = venue_coords.get(venue)
    if not coords:
        return {"temperature_f": 72, "wind_mph": 5, "humidity": 50, "source": "default"}

    try:
        r = requests.get(
            "https://api.openweathermap.org/data/2.5/weather",
            params={"lat": coords[0], "lon": coords[1], "appid": api_key, "units": "imperial"},
            timeout=10,
        )
        r.raise_for_status()
        data = r.json()
        return {
            "temperature_f": data["main"]["temp"],
            "wind_mph": data["wind"]["speed"],
            "humidity": data["main"]["humidity"],
            "source": "openweathermap",
        }
    except Exception as e:
        log.debug(f"Weather fetch failed for {venue}: {e}")
        return {"temperature_f": 72, "wind_mph": 5, "humidity": 50, "source": "default"}


def fetch_prop_lines(game_date: str) -> list:
    """
    Fetch prop lines from Supabase props table.

    Returns list of PropLine objects.
    """
    if not SUPABASE_URL:
        log.warning("No SUPABASE_URL — skipping prop line fetch")
        return []

    rows = sb_get("props", {
        "game_date": f"eq.{game_date}",
        "select": "mlbam_id,player_name,stat_type,line,over_odds,under_odds,bookmaker",
    })

    props = []
    for row in rows:
        if not row.get("mlbam_id") or not row.get("line"):
            continue
        props.append(PropLine(
            mlbam_id=row["mlbam_id"],
            player_name=row.get("player_name", "Unknown"),
            stat_type=_normalize_stat_type(row.get("stat_type", "")),
            line=float(row["line"]),
            over_odds=int(row.get("over_odds", -110)),
            under_odds=int(row.get("under_odds", -110)),
            book=row.get("bookmaker", "consensus"),
        ))

    log.info(f"Fetched {len(props)} prop lines for {game_date}")
    return props


def _normalize_stat_type(raw: str) -> str:
    """Map sportsbook stat type names to simulation stat keys."""
    mapping = {
        "pitcher_strikeouts": "K",
        "batter_strikeouts": "K",
        "strikeouts": "K",
        "hits": "H",
        "batter_hits": "H",
        "total_bases": "TB",
        "batter_total_bases": "TB",
        "home_runs": "HR",
        "batter_home_runs": "HR",
        "runs": "R",
        "batter_runs": "R",
        "rbis": "RBI",
        "batter_rbis": "RBI",
        "walks": "BB",
        "batter_walks": "BB",
    }
    return mapping.get(raw.lower(), raw.upper())


# ---------------------------------------------------------------------------
# Weather → simulation modifier
# ---------------------------------------------------------------------------

def weather_to_modifier(weather: dict) -> float:
    """
    Convert weather conditions to a HR/power modifier.

    Hot, humid, high-altitude = more HRs.
    Cold, windy (in), low humidity = fewer HRs.
    """
    temp = weather.get("temperature_f", 72)
    wind = weather.get("wind_mph", 5)

    # Temperature effect: ~1% per 10°F above/below 72
    temp_mod = 1.0 + (temp - 72) * 0.001

    # Wind effect: simplified — strong wind can add/subtract up to 5%
    wind_mod = 1.0
    if wind > 15:
        wind_mod = 0.97  # High wind = unpredictable, slight reduction
    elif wind > 10:
        wind_mod = 0.99

    return max(0.85, min(1.15, temp_mod * wind_mod))


# ---------------------------------------------------------------------------
# Build simulation profiles from raw data
# ---------------------------------------------------------------------------

def build_batter_profile(
    mlbam_id: int,
    name: str,
    position: int,
    stats: dict,
    bats: str = "R",
) -> BatterProfile:
    """Build a BatterProfile from MLB Stats API season stats."""
    pa = int(stats.get("plateAppearances", 0))

    if pa < 50:
        # Not enough data — use league average with slight adjustments
        return BatterProfile(
            mlbam_id=mlbam_id,
            name=name,
            lineup_position=position,
            bats=bats,
            probs=MLB_AVG_PROBS.copy(),
        )

    k = int(stats.get("strikeOuts", 0))
    bb = int(stats.get("baseOnBalls", 0))
    hbp = int(stats.get("hitByPitch", 0))
    singles = int(stats.get("hits", 0)) - int(stats.get("doubles", 0)) - int(stats.get("triples", 0)) - int(stats.get("homeRuns", 0))
    doubles = int(stats.get("doubles", 0))
    triples = int(stats.get("triples", 0))
    hr = int(stats.get("homeRuns", 0))

    # Calculate outs from PA - (K + BB + HBP + H)
    on_base = k + bb + hbp + singles + doubles + triples + hr
    outs = max(0, pa - on_base)

    # Distribute outs among out types (approximate split)
    flyout = int(outs * 0.32)
    groundout = int(outs * 0.42)
    lineout = int(outs * 0.18)
    popup = outs - flyout - groundout - lineout

    probs = build_batter_probs(
        k_rate=k / pa,
        bb_rate=bb / pa,
        hbp_rate=hbp / pa,
        single_rate=max(0, singles) / pa,
        double_rate=doubles / pa,
        triple_rate=triples / pa,
        hr_rate=hr / pa,
        flyout_rate=flyout / pa,
        groundout_rate=groundout / pa,
        lineout_rate=lineout / pa,
        popup_rate=popup / pa,
    )

    return BatterProfile(
        mlbam_id=mlbam_id,
        name=name,
        lineup_position=position,
        bats=bats,
        probs=probs,
    )


# ---------------------------------------------------------------------------
# Main orchestrator
# ---------------------------------------------------------------------------

def run_daily_simulations(
    game_date: str = None,
    n_sims: int = 3000,
    bankroll: float = 5000.0,
    kelly_fraction: float = 0.25,
    output_path: str = None,
) -> dict:
    """
    Run Monte Carlo simulations for all games on a given date.

    Steps:
    1. Fetch today's schedule and probable pitchers
    2. For each game, fetch lineups, weather, umpire data
    3. Build simulation profiles
    4. Run simulations (3,000 per game)
    5. Compare against prop lines
    6. Output JSON with all edges

    Returns:
        Dict with full simulation results and prop edges
    """
    if game_date is None:
        game_date = date.today().isoformat()

    log.info(f"{'='*60}")
    log.info(f"BaselineMLB Monte Carlo Daily Simulation")
    log.info(f"Date: {game_date} | Sims/game: {n_sims}")
    log.info(f"{'='*60}")

    start_time = time.time()

    # Step 1: Fetch schedule
    games = fetch_todays_games(game_date)
    log.info(f"Found {len(games)} games for {game_date}")

    if not games:
        log.info("No games found. Exiting.")
        return {"date": game_date, "games": [], "edges": [], "metadata": {}}

    # Step 2: Fetch prop lines
    prop_lines = fetch_prop_lines(game_date)

    # Step 3: Simulate each game
    all_results = []
    all_edges = []
    calc = PropCalculator(
        bankroll=bankroll,
        kelly_fraction=kelly_fraction,
        min_edge=0.02,
    )

    for game in games:
        game_pk = game["game_pk"]
        home_team = game["home_team"]
        away_team = game["away_team"]
        venue = game.get("venue", "Unknown")

        log.info(f"\n--- {away_team} @ {home_team} ({venue}) ---")

        # Skip games without probable pitchers
        if not game.get("away_pitcher_id") or not game.get("home_pitcher_id"):
            log.info(f"  Skipping: no probable pitchers announced")
            continue

        # Simulate both sides: away offense vs home pitcher, home offense vs away pitcher
        for side, pitcher_id, pitcher_name, batting_team, pitching_team in [
            ("away", game["home_pitcher_id"], game["home_pitcher_name"],
             away_team, home_team),
            ("home", game["away_pitcher_id"], game["away_pitcher_name"],
             home_team, away_team),
        ]:
            log.info(f"  Simulating {batting_team} vs {pitcher_name}")

            # Fetch pitcher stats
            p_stats = fetch_pitcher_stats(pitcher_id)
            pitcher_profile = build_pitcher_profile_from_stats(
                mlbam_id=pitcher_id,
                name=pitcher_name,
                career_k9=p_stats["career_k9"],
                recent_pitch_counts=p_stats["recent_pitch_counts"],
            )

            # Fetch lineup
            lineup_data = fetch_lineup(game_pk, side)
            if len(lineup_data) < 9:
                log.info(f"    Lineup not available for {batting_team}, using placeholder roster")
                # Create placeholder lineup with league-average batters
                lineup = [
                    BatterProfile(
                        mlbam_id=i, name=f"{batting_team} Batter {i}",
                        lineup_position=i,
                    )
                    for i in range(1, 10)
                ]
            else:
                lineup = []
                for i, b in enumerate(lineup_data):
                    stats = fetch_batter_stats(b["mlbam_id"])
                    profile = build_batter_profile(
                        mlbam_id=b["mlbam_id"],
                        name=b["name"],
                        position=i + 1,
                        stats=stats,
                        bats=b.get("bats", "R"),
                    )
                    lineup.append(profile)

            # Fetch bullpen stats
            bp_stats = fetch_team_bullpen_stats(pitching_team)
            bullpen = build_bullpen_profile(
                era=bp_stats["era"], k9=bp_stats["k9"], bb9=bp_stats["bb9"],
            )

            # Environmental factors
            park_k = PARK_K_FACTORS.get(venue, 0) / 100.0 + 1.0
            park_hr = PARK_HR_FACTORS.get(venue, 1.0)
            weather = fetch_weather(venue)
            weather_mod = weather_to_modifier(weather)
            umpire_k = fetch_umpire_factor(game_pk)

            # Build matchup
            matchup = GameMatchup(
                pitcher=pitcher_profile,
                lineup=lineup,
                bullpen=bullpen,
                park_factor=park_hr,
                weather_factor=weather_mod,
                umpire_k_factor=umpire_k,
            )

            # Run simulation
            try:
                game_results, pitcher_ks = simulate_game_with_pitcher_ks(
                    matchup, n_sims=n_sims,
                )

                # Collect results
                game_result_dict = {
                    "game_pk": game_pk,
                    "matchup": f"{batting_team} vs {pitcher_name}",
                    "venue": venue,
                    "pitcher": {
                        "mlbam_id": pitcher_id,
                        "name": pitcher_name,
                        "k_dist": {
                            "mean": round(float(np.mean(pitcher_ks)), 2),
                            "std": round(float(np.std(pitcher_ks)), 2),
                            "median": round(float(np.median(pitcher_ks)), 1),
                        },
                        "ip_dist": {
                            "mean": round(float(np.mean(game_results.pitcher_innings)), 2),
                        },
                        "pitch_count_dist": {
                            "mean": round(float(np.mean(game_results.pitcher_pitch_counts)), 1),
                        },
                    },
                    "batters": {
                        mid: pr.to_dict()
                        for mid, pr in game_results.player_results.items()
                    },
                    "team_runs": {
                        "mean": round(float(np.mean(game_results.team_runs)), 2),
                        "std": round(float(np.std(game_results.team_runs)), 2),
                    },
                    "environment": {
                        "park_hr_factor": park_hr,
                        "weather_modifier": round(weather_mod, 3),
                        "umpire_k_factor": round(umpire_k, 3),
                    },
                }
                all_results.append(game_result_dict)

                # Evaluate props for this matchup
                game_props = [
                    p for p in prop_lines
                    if p.mlbam_id == pitcher_id
                    or p.mlbam_id in game_results.player_results
                ]

                if game_props:
                    edges = calc.evaluate_props(
                        game_results, game_props,
                        pitcher_k_dist=pitcher_ks,
                        pitcher_mlbam_id=pitcher_id,
                        pitcher_name=pitcher_name,
                    )
                    all_edges.extend([e.to_dict() for e in edges])

                log.info(
                    f"    Pitcher Ks: {np.mean(pitcher_ks):.1f} avg | "
                    f"Team Runs: {np.mean(game_results.team_runs):.1f} avg"
                )

            except Exception as e:
                log.error(f"    Simulation failed: {e}")
                continue

    elapsed = time.time() - start_time

    # Step 4: Sort edges by absolute edge value
    all_edges.sort(key=lambda e: abs(e.get("edge", 0)), reverse=True)

    # Step 5: Build output
    output = {
        "date": game_date,
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "metadata": {
            "n_sims": n_sims,
            "n_games": len(games),
            "n_matchups_simulated": len(all_results),
            "n_props_evaluated": len(all_edges),
            "bankroll": bankroll,
            "kelly_fraction": kelly_fraction,
            "elapsed_seconds": round(elapsed, 2),
        },
        "simulations": all_results,
        "edges": all_edges,
        "top_plays": {
            "over": [e for e in all_edges if e.get("direction") == "OVER"][:5],
            "under": [e for e in all_edges if e.get("direction") == "UNDER"][:5],
        },
    }

    # Step 6: Write output
    if output_path is None:
        output_path = f"output/daily_edges_{game_date}.json"

    os.makedirs(os.path.dirname(output_path) if os.path.dirname(output_path) else ".", exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(output, f, indent=2, default=str)

    log.info(f"\n{'='*60}")
    log.info(f"Simulation complete in {elapsed:.1f}s")
    log.info(f"Games: {len(games)} | Matchups simulated: {len(all_results)}")
    log.info(f"Props evaluated: {len(all_edges)}")
    log.info(f"Output: {output_path}")
    log.info(f"{'='*60}")

    # Print top edges
    if all_edges:
        log.info("\nTop 5 Edges:")
        for i, e in enumerate(all_edges[:5], 1):
            log.info(
                f"  {i}. [{e['confidence_tier']}] {e['player_name']} "
                f"{e['stat_type']} {e['direction']} {e['line']} | "
                f"Edge: {e['edge_pct']:+.1f}% | EV: {e['expected_value']:+.3f}"
            )

    return output


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="BaselineMLB Monte Carlo Daily Simulator",
    )
    parser.add_argument(
        "--date", type=str, default=None,
        help="Game date (YYYY-MM-DD). Defaults to today.",
    )
    parser.add_argument(
        "--sims", type=int, default=3000,
        help="Number of simulations per game (default: 3000)",
    )
    parser.add_argument(
        "--bankroll", type=float, default=5000.0,
        help="Bankroll for Kelly sizing (default: $5000)",
    )
    parser.add_argument(
        "--kelly", type=float, default=0.25,
        help="Kelly fraction (default: 0.25 = quarter Kelly)",
    )
    parser.add_argument(
        "--output", type=str, default=None,
        help="Output JSON path (default: output/daily_edges_YYYY-MM-DD.json)",
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true",
        help="Enable verbose logging",
    )

    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    run_daily_simulations(
        game_date=args.date,
        n_sims=args.sims,
        bankroll=args.bankroll,
        kelly_fraction=args.kelly,
        output_path=args.output,
    )


if __name__ == "__main__":
    main()
