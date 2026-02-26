#!/usr/bin/env python3
"""
generate_projections.py -- Baseline MLB
Glass-box pitcher strikeout projection engine.
Reads games + players from Supabase, computes projections,
upserts results to the projections table.
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
log = logging.getLogger("generate_projections")

SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_KEY")
MODEL_VERSION = "v1.0-glass-box"

if not all([SUPABASE_URL, SUPABASE_KEY]):
    raise EnvironmentError("Missing SUPABASE_URL or SUPABASE_SERVICE_KEY")

PARK_K_FACTORS = {
    "Coors Field": -8, "Yankee Stadium": 3, "Oracle Park": 5,
    "Petco Park": 4, "Truist Park": 2, "Globe Life Field": 2,
    "Chase Field": 1, "T-Mobile Park": 3, "Guaranteed Rate Field": 0,
    "loanDepot park": 1, "Great American Ball Park": -2,
    "PNC Park": 1, "Minute Maid Park": 2, "Dodger Stadium": 4,
    "Angel Stadium": 0, "Fenway Park": -1, "Wrigley Field": -3,
    "Busch Stadium": 1, "Citizens Bank Park": -2,
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


def fetch_pitcher_k9(mlbam_id):
    """Fetch career K/9 from MLB Stats API."""
    try:
        url = f"https://statsapi.mlb.com/api/v1/people/{mlbam_id}/stats"
        r = requests.get(url, params={"stats": "career", "group": "pitching", "sportId": 1}, timeout=10)
        r.raise_for_status()
        splits = r.json().get("stats", [{}])[0].get("splits", [])
        if splits:
            stat = splits[0].get("stat", {})
            k = float(stat.get("strikeOuts", 0))
            ip_str = str(stat.get("inningsPitched", "0.0"))
            parts = ip_str.split(".")
            ip = int(parts[0]) + (int(parts[1]) / 3 if len(parts) > 1 and parts[1] else 0)
            if ip > 0:
                return round((k / ip) * 9, 2)
    except Exception as e:
        log.debug(f"K/9 fetch failed for {mlbam_id}: {e}")
    return 7.5  # MLB average fallback


def project_pitcher(mlbam_id, player_name, opponent, venue, expected_ip=5.5):
    k9 = fetch_pitcher_k9(mlbam_id)
    park_adj = PARK_K_FACTORS.get(venue, 0)
    adjusted_k9 = k9 * (1 + park_adj / 100)
    projected_k = (adjusted_k9 / 9) * expected_ip

    conf = 0.50
    if expected_ip >= 5.0: conf += 0.15
    if k9 > 0: conf += 0.15
    if k9 >= 8.0: conf += 0.05
    conf = round(min(conf, 0.95), 3)

    features = {
        "baseline_k9": round(k9, 2),
        "park_adjustment": f"{park_adj:+.1f}%",
        "adjusted_k9": round(adjusted_k9, 2),
        "expected_innings": expected_ip,
        "opponent": opponent,
        "venue": venue,
    }
    return {
        "mlbam_id": mlbam_id,
        "player_name": player_name,
        "stat_type": "pitcher_strikeouts",
        "projection": round(projected_k, 2),
        "confidence": conf,
        "model_version": MODEL_VERSION,
        "features": json.dumps(features),
    }


def run_projections(game_date=None):
    if game_date is None:
        game_date = date.today().isoformat()

    log.info(f"=== Generating projections for {game_date} ===")

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

    has_pitchers = any(
        g.get("home_probable_pitcher_id") or g.get("away_probable_pitcher_id")
        for g in games
    )
    if not has_pitchers:
        log.info("No probable pitchers announced yet. Skipping projections.")
        return

    projection_rows = []
    projected = set()

    for game in games:
        game_pk   = game["game_pk"]
        venue     = game.get("venue") or "Unknown"
        home_team = game.get("home_team", "")
        away_team = game.get("away_team", "")

        for pid_key, pname_key, opp in [
            ("home_probable_pitcher_id", "home_probable_pitcher", away_team),
            ("away_probable_pitcher_id", "away_probable_pitcher", home_team),
        ]:
            pid   = game.get(pid_key)
            pname = game.get(pname_key)
            if not pid or not pname or pid in projected:
                continue
            projected.add(pid)
            log.info(f"  Projecting {pname} ({pid}) vs {opp} @ {venue}")
            try:
                proj = project_pitcher(pid, pname, opp, venue)
                proj["game_pk"]   = game_pk
                proj["game_date"] = game_date
                projection_rows.append(proj)
            except Exception as e:
                log.warning(f"  Failed to project {pname}: {e}")

    log.info(f"Generated {len(projection_rows)} projections")
    sb_upsert("projections", projection_rows)
    log.info(f"=== Done ===")


if __name__ == "__main__":
    import sys
    run_projections(sys.argv[1] if len(sys.argv) > 1 else None)
