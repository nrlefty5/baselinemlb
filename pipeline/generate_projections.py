#!/usr/bin/env python3
"""
generate_projections.py -- Baseline MLB
Glass-box pitcher strikeout projection engine.
Reads games + players from Supabase, computes projections,
upserts results to the projections table.

Supports manual pitcher overrides via the `pitcher_overrides` table
for games where the MLB Stats API lacks probable pitcher data
(e.g., WBC, exhibitions).
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

SUPABASE_URL = os.environ.get("SUPABASE_URL", "").strip()
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_KEY", "").strip()
MODEL_VERSION = "v1.0-glass-box"

# Fail fast with a clear error instead of cryptic HTTP 400
if not SUPABASE_URL.startswith("https://") or not SUPABASE_URL.endswith(".supabase.co"):
    raise RuntimeError(f"Invalid SUPABASE_URL (length={len(SUPABASE_URL)}, repr={repr(SUPABASE_URL[:30])})")

# ── Park K Factors (all 30 MLB stadiums) ────────────────────────────────────
# Percentage adjustment to K/9 rate.  Positive = more Ks, negative = fewer.
# Sources: Baseball Savant park factors, 3-year rolling average (2023-2025).
PARK_K_FACTORS = {
    # AL East
    "Yankee Stadium": 3,                # NYY — short porch, high K environment
    "Fenway Park": -1,                  # BOS — wide open, less K-friendly
    "Rogers Centre": 1,                 # TOR
    "Tropicana Field": 2,               # TB
    "Oriole Park at Camden Yards": 0,   # BAL

    # AL Central
    "Guaranteed Rate Field": 0,         # CWS
    "Progressive Field": 1,             # CLE
    "Comerica Park": 2,                 # DET
    "Kauffman Stadium": -1,             # KC
    "Target Field": 0,                  # MIN

    # AL West
    "T-Mobile Park": 3,                 # SEA — pitcher-friendly, high Ks
    "Minute Maid Park": 2,              # HOU
    "Angel Stadium": 0,                 # LAA
    "Oakland Coliseum": 2,              # OAK — large foul territory
    "Globe Life Field": 2,              # TEX

    # NL East
    "Truist Park": 2,                   # ATL
    "Citi Field": 3,                    # NYM — pitcher-friendly
    "Citizens Bank Park": -2,           # PHI — hitter-friendly
    "Nationals Park": 1,                # WSH
    "loanDepot park": 1,                # MIA

    # NL Central
    "Wrigley Field": -3,                # CHC — wind-dependent
    "Great American Ball Park": -2,     # CIN — small park, few Ks
    "American Family Field": -1,        # MIL
    "PNC Park": 1,                      # PIT
    "Busch Stadium": 1,                 # STL

    # NL West
    "Dodger Stadium": 4,                # LAD — high K environment
    "Oracle Park": 5,                   # SF — very pitcher-friendly
    "Petco Park": 4,                    # SD — pitcher-friendly
    "Chase Field": 1,                   # ARI
    "Coors Field": -8,                  # COL — extreme hitter park
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
        log.info(f" No rows to upsert into {table}")
        return
    url = f"{SUPABASE_URL}/rest/v1/{table}"
    for i in range(0, len(rows), 500):
        batch = rows[i:i+500]
        r = requests.post(url, headers=sb_headers(), json=batch)
        if not r.ok:
            log.warning(f" Upsert failed: {r.status_code} {r.text[:200]}")
        else:
            log.info(f" Upserted {len(batch)} rows into {table}")

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


# ---------------------------------------------------------------------------
# Pitcher override helpers
# ---------------------------------------------------------------------------

def fetch_pitcher_overrides(game_date: str) -> dict:
    """
    Fetch manual pitcher overrides for a given date.
    Returns dict keyed by (game_pk, side) -> {pitcher_id, pitcher_name}.
    """
    try:
        rows = sb_get("pitcher_overrides", {
            "game_date": f"eq.{game_date}",
            "select": "game_pk,side,pitcher_id,pitcher_name",
        })
    except Exception as e:
        log.warning(f"Failed to fetch pitcher_overrides (table may not exist): {e}")
        return {}

    overrides = {}
    for row in rows:
        key = (row["game_pk"], row["side"])
        overrides[key] = {
            "pitcher_id": row["pitcher_id"],
            "pitcher_name": row.get("pitcher_name") or f"Player {row['pitcher_id']}",
        }

    if overrides:
        log.info(f"Loaded {len(overrides)} pitcher overrides for {game_date}")

    return overrides


def apply_overrides(games: list, overrides: dict) -> list:
    """
    Patch games list with manual pitcher overrides.
    Overrides take precedence over API-provided probable pitchers.
    """
    patched = 0
    for game in games:
        game_pk = game["game_pk"]

        home_override = overrides.get((game_pk, "home"))
        if home_override:
            game["home_probable_pitcher_id"] = home_override["pitcher_id"]
            game["home_probable_pitcher"] = home_override["pitcher_name"]
            patched += 1

        away_override = overrides.get((game_pk, "away"))
        if away_override:
            game["away_probable_pitcher_id"] = away_override["pitcher_id"]
            game["away_probable_pitcher"] = away_override["pitcher_name"]
            patched += 1

    if patched:
        log.info(f"Applied {patched} pitcher overrides to games")

    return games


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

    # --- Pitcher overrides: patch games with manual assignments ---
    overrides = fetch_pitcher_overrides(game_date)
    if overrides:
        games = apply_overrides(games, overrides)

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
        game_pk = game["game_pk"]
        venue = game.get("venue") or "Unknown"
        home_team = game.get("home_team", "")
        away_team = game.get("away_team", "")

        for pid_key, pname_key, opp in [
            ("home_probable_pitcher_id", "home_probable_pitcher", away_team),
            ("away_probable_pitcher_id", "away_probable_pitcher", home_team),
        ]:
            pid = game.get(pid_key)
            pname = game.get(pname_key)
            if not pid or not pname or pid in projected:
                continue

            projected.add(pid)
            log.info(f" Projecting {pname} ({pid}) vs {opp} @ {venue}")

            try:
                proj = project_pitcher(pid, pname, opp, venue)
                proj["game_pk"] = game_pk
                proj["game_date"] = game_date
                projection_rows.append(proj)
            except Exception as e:
                log.warning(f" Failed to project {pname}: {e}")

    log.info(f"Generated {len(projection_rows)} projections")
    sb_upsert("projections", projection_rows)
    log.info(f"=== Done ===")

if __name__ == "__main__":
    import sys
    run_projections(sys.argv[1] if len(sys.argv) > 1 else None)
