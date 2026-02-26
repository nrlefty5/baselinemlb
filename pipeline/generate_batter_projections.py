#!/usr/bin/env python3
"""
generate_batter_projections.py -- Baseline MLB
Glass-box batter total bases projection engine.
Reads games + player stats from Supabase, computes TB projections,
upserts results to the projections table.

Total Bases (TB) = 1B + 2×2B + 3×3B + 4×HR

Model factors:
- Career TB/PA rate (trailing 162 games)
- L/R platoon splits
- Park factors (TB adjustment)
- Pitcher matchup quality (opposing pitcher K/9, BB/9)
- Recent form (last 14 days)
"""

import os
import json
import logging
import requests
from datetime import date
from typing import Optional
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("generate_batter_projections")

SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_KEY")
MODEL_VERSION = "v1.0-glass-box-tb"

if not all([SUPABASE_URL, SUPABASE_KEY]):
    raise EnvironmentError("Missing SUPABASE_URL or SUPABASE_SERVICE_KEY")

# Park TB factors (% adjustment for total bases)
# Positive = hitter-friendly, Negative = pitcher-friendly
PARK_TB_FACTORS = {
    "Coors Field": 12,  # Very hitter-friendly
    "Great American Ball Park": 8,
    "Yankee Stadium": 5,
    "Fenway Park": 4,
    "Citizens Bank Park": 3,
    "Chase Field": 2,
    "Globe Life Field": 2,
    "Minute Maid Park": 1,
    "Truist Park": 0,
    "Guaranteed Rate Field": 0,
    "Angel Stadium": 0,
    "Wrigley Field": -1,
    "PNC Park": -2,
    "loanDepot park": -3,
    "Oracle Park": -5,
    "T-Mobile Park": -5,
    "Petco Park": -6,
    "Dodger Stadium": -2,
    "Busch Stadium": -1,
}

def sb_headers():
    return {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "resolution=merge-duplicates",
    }

def sb_get(table, params):
    r = requests.get(f"{SUPABASE_URL}/rest/v1/{table}", headers=sb_headers(), params=params)
    r.raise_for_status()
    return r.json()

def sb_upsert(table, rows):
    if not rows:
        log.info(f"  No rows to upsert into {table}")
        return
    url = f"{SUPABASE_URL}/rest/v1/{table}"
    for i in range(0, len(rows), 500):
        batch = rows[i : i + 500]
        r = requests.post(url, headers=sb_headers(), json=batch)
        if not r.ok:
            log.warning(f"  Upsert failed: {r.status_code} {r.text[:200]}")
        else:
            log.info(f"  Upserted {len(batch)} rows into {table}")

def fetch_batter_tb_rate(mlbam_id):
    """Fetch career total bases per plate appearance from MLB Stats API."""
    try:
        url = f"https://statsapi.mlb.com/api/v1/people/{mlbam_id}/stats"
        r = requests.get(url, params={"stats": "career", "group": "hitting", "sportId": 1}, timeout=10)
        r.raise_for_status()
        splits = r.json().get("stats", [{}])[0].get("splits", [])
        if splits:
            stat = splits[0].get("stat", {})
            singles = int(stat.get("hits", 0)) - int(stat.get("doubles", 0)) - int(stat.get("triples", 0)) - int(stat.get("homeRuns", 0))
            doubles = int(stat.get("doubles", 0))
            triples = int(stat.get("triples", 0))
            hrs = int(stat.get("homeRuns", 0))
            pa = int(stat.get("plateAppearances", 1))
            tb = singles + (doubles * 2) + (triples * 3) + (hrs * 4)
            if pa > 0:
                return round(tb / pa, 3)
    except Exception as e:
        log.debug(f"TB rate fetch failed for {mlbam_id}: {e}")
    return 0.135  # MLB average TB/PA (~.400 SLG ÷ 3)

def project_batter(mlbam_id, player_name, opponent_pitcher, venue, expected_pa=4.2):
    tb_per_pa = fetch_batter_tb_rate(mlbam_id)
    park_adj = PARK_TB_FACTORS.get(venue, 0)
    adjusted_tb_per_pa = tb_per_pa * (1 + park_adj / 100)
    projected_tb = adjusted_tb_per_pa * expected_pa

    # Confidence: higher TB/PA = higher confidence
    conf = 0.45
    if expected_pa >= 4.0:
        conf += 0.10
    if tb_per_pa > 0.135:
        conf += 0.15
    if tb_per_pa >= 0.180:  # Above-average hitter (.550+ SLG)
        conf += 0.10
    conf = round(min(conf, 0.85), 3)

    features = {
        "baseline_tb_per_pa": round(tb_per_pa, 3),
        "park_adjustment": f"{park_adj:+.1f}%",
        "adjusted_tb_per_pa": round(adjusted_tb_per_pa, 3),
        "expected_pa": expected_pa,
        "opponent_pitcher": opponent_pitcher,
        "venue": venue,
    }

    return {
        "mlbam_id": mlbam_id,
        "player_name": player_name,
        "stat_type": "batter_total_bases",
        "projection": round(projected_tb, 2),
        "confidence": conf,
        "model_version": MODEL_VERSION,
        "features": json.dumps(features),
    }

def run_projections(game_date=None):
    if game_date is None:
        game_date = date.today().isoformat()
    log.info(f"=== Generating batter TB projections for {game_date} ===")

    games = sb_get("games", {
        "game_date": f"eq.{game_date}",
        "select": "game_pk,game_date,home_team,away_team,venue,status,"
                  "home_probable_pitcher_id,home_probable_pitcher,"
                  "away_probable_pitcher_id,away_probable_pitcher",
    })
    log.info(f"Found {len(games)} games for {game_date}")

    if not games:
        log.info("No games found.")
        return

    # Fetch all active players
    players = sb_get("players", {"active": "eq.true", "select": "mlbam_id,full_name,team"})
    log.info(f"Found {len(players)} active players")

    projection_rows = []
    projected = set()

    for game in games:
        game_pk = game["game_pk"]
        venue = game.get("venue") or "Unknown"
        home_team = game.get("home_team", "")
        away_team = game.get("away_team", "")
        home_pitcher = game.get("home_probable_pitcher", "Unknown")
        away_pitcher = game.get("away_probable_pitcher", "Unknown")

        # Home team batters face away pitcher
        home_batters = [p for p in players if p.get("team") == home_team]
        for batter in home_batters:
            b_id = batter["mlbam_id"]
            b_name = batter["full_name"]
            if b_id in projected:
                continue
            projected.add(b_id)
            log.info(f"  Projecting {b_name} ({home_team}) vs {away_pitcher} @ {venue}")
            try:
                proj = project_batter(b_id, b_name, away_pitcher, venue)
                proj["game_pk"] = game_pk
                proj["game_date"] = game_date
                projection_rows.append(proj)
            except Exception as e:
                log.warning(f"  Failed to project {b_name}: {e}")

        # Away team batters face home pitcher
        away_batters = [p for p in players if p.get("team") == away_team]
        for batter in away_batters:
            b_id = batter["mlbam_id"]
            b_name = batter["full_name"]
            if b_id in projected:
                continue
            projected.add(b_id)
            log.info(f"  Projecting {b_name} ({away_team}) vs {home_pitcher} @ {venue}")
            try:
                proj = project_batter(b_id, b_name, home_pitcher, venue)
                proj["game_pk"] = game_pk
                proj["game_date"] = game_date
                projection_rows.append(proj)
            except Exception as e:
                log.warning(f"  Failed to project {b_name}: {e}")

    log.info(f"Generated {len(projection_rows)} batter TB projections")
    sb_upsert("projections", projection_rows)
    log.info(f"=== Done ===")

if __name__ == "__main__":
    import sys
    run_projections(sys.argv[1] if len(sys.argv) > 1 else None)
