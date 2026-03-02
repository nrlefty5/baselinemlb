#!/usr/bin/env python3
"""
generate_batter_projections.py -- Baseline MLB
Glass-box batter total bases projection engine v2.0.

Model factors (v2.0):
  1. Career TB/PA rate, blended with league average (early-season ramp-up)
  2. Platoon split adjustments (L/R matchups) — NEW in v2.0
  3. Park TB factors
  4. Likely starter filtering (position players only, no bench/bullpen) — NEW in v2.0

Total Bases (TB) = 1B + 2x2B + 3x3B + 4xHR
"""
import json
import logging
import os
from datetime import date

import requests

# from dotenv import load_dotenv  # DISABLED - GitHub Actions provides env vars

# load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("generate_batter_projections")

SUPABASE_URL = os.environ.get("SUPABASE_URL", "").strip()

# Fail fast with a clear error instead of cryptic HTTP 400
if not SUPABASE_URL.startswith("https://") or not SUPABASE_URL.endswith(".supabase.co"):
    raise RuntimeError(f"Invalid SUPABASE_URL (length={len(SUPABASE_URL)}, repr={repr(SUPABASE_URL[:30])})")

SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_KEY", "").strip()
MODEL_VERSION = "v2.0-glass-box-tb"

# Early-season ramp-up constants
MLB_AVG_TB_PA = 0.135  # League average (~.400 SLG / 3 PA per AB)
RAMP_UP_GAMES = 30     # Games until full career rate is trusted

# Platoon split multipliers (based on MLB historical splits)
# These represent the TB/PA boost or penalty for same/opposite hand matchups
PLATOON_SPLITS = {
    # Batter vs Pitcher hand -> TB/PA multiplier
    ("L", "R"): 1.06,   # LHB vs RHP: slight advantage (see more RHP, comfortable)
    ("L", "L"): 0.88,   # LHB vs LHP: significant disadvantage (same-side)
    ("R", "L"): 1.08,   # RHB vs LHP: significant advantage (opposite-side)
    ("R", "R"): 0.96,   # RHB vs RHP: slight disadvantage (same-side, but more familiar)
    ("S", "R"): 1.03,   # Switch-hitter vs RHP: slight advantage (bats left)
    ("S", "L"): 1.05,   # Switch-hitter vs LHP: advantage (bats right vs lefty)
}

# Positions that are likely starters (excludes pure relievers and some utility)
STARTER_POSITIONS = {"C", "1B", "2B", "3B", "SS", "LF", "CF", "RF", "DH", "OF", "IF"}

# Park TB factors (% adjustment for total bases)
PARK_TB_FACTORS = {
    "Coors Field": 12,
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
    return 0.135  # MLB average TB/PA (~.400 SLG / 3)


def get_platoon_factor(batter_hand, pitcher_hand):
    """
    Return platoon split multiplier for a batter/pitcher handedness matchup.
    If handedness data is missing, returns 1.0 (no adjustment).
    """
    if not batter_hand or not pitcher_hand:
        return 1.0, "unknown"
    key = (batter_hand, pitcher_hand)
    factor = PLATOON_SPLITS.get(key, 1.0)
    matchup = f"{batter_hand}HB vs {pitcher_hand}HP"
    return factor, matchup


def fetch_pitcher_hand(mlbam_id):
    """Fetch a pitcher's throwing hand from MLB Stats API."""
    try:
        url = f"https://statsapi.mlb.com/api/v1/people/{mlbam_id}"
        r = requests.get(url, timeout=10)
        r.raise_for_status()
        people = r.json().get("people", [])
        if people:
            return people[0].get("pitchHand", {}).get("code")
    except Exception as e:
        log.debug(f"Pitcher hand fetch failed for {mlbam_id}: {e}")
    return None


def is_likely_starter(player):
    """
    Filter to likely starters only. Excludes:
    - Pitchers (P, SP, RP) — they have their own projection model
    - Players without a recognized position
    """
    pos = (player.get("position") or "").strip().upper()
    if not pos:
        return False
    if pos in ("P", "SP", "RP"):
        return False
    return pos in STARTER_POSITIONS


def project_batter(mlbam_id, player_name, opponent_pitcher, venue,
                   expected_pa=4.2, games_played=0,
                   batter_hand=None, pitcher_hand=None):
    """
    Project total bases for a batter using v2.0 multi-factor model.

    New in v2.0:
    - Platoon split adjustments based on batter/pitcher handedness
    - Filtered to likely starters only (at caller level)
    """
    career_tb_per_pa = fetch_batter_tb_rate(mlbam_id)

    # Early-season ramp-up
    weight = min(games_played / RAMP_UP_GAMES, 1.0) if games_played < RAMP_UP_GAMES else 1.0
    blended_tb_pa = (1 - weight) * MLB_AVG_TB_PA + weight * career_tb_per_pa

    # Park factor
    park_adj = PARK_TB_FACTORS.get(venue, 0)
    park_factor = 1 + park_adj / 100

    # Platoon split adjustment (NEW in v2.0)
    platoon_factor, matchup_desc = get_platoon_factor(batter_hand, pitcher_hand)

    # Apply all factors
    adjusted_tb_per_pa = blended_tb_pa * park_factor * platoon_factor
    projected_tb = adjusted_tb_per_pa * expected_pa

    # Confidence scoring
    conf = 0.45
    if expected_pa >= 4.0:
        conf += 0.10
    if career_tb_per_pa > 0.135:
        conf += 0.15
    if career_tb_per_pa >= 0.180:
        conf += 0.10
    if batter_hand and pitcher_hand:
        conf += 0.03  # Bonus for having platoon data
    if games_played < RAMP_UP_GAMES:
        conf -= 0.05 * (1 - weight)
    conf = round(min(max(conf, 0.30), 0.85), 3)

    features = {
        "career_tb_per_pa": round(career_tb_per_pa, 3),
        "games_played": games_played,
        "rampup_weight": round(weight, 3),
        "blended_tb_per_pa": round(blended_tb_pa, 3),
        "park_adjustment": f"{park_adj:+.1f}%",
        "platoon_factor": round(platoon_factor, 3),
        "platoon_matchup": matchup_desc,
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
    log.info(f"=== Generating v2.0 batter TB projections for {game_date} ===")

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

    # Fetch all players — filter to likely starters (Task 6)
    players = sb_get("players", {"select": "mlbam_id,full_name,team,position,bats,throws"})
    all_count = len(players)
    players = [p for p in players if is_likely_starter(p)]
    log.info(f"Filtered {all_count} players to {len(players)} likely starters")

    # Cache pitcher handedness lookups
    pitcher_hands = {}

    projection_rows = []
    projected = set()

    for game in games:
        game_pk = game["game_pk"]
        venue = game.get("venue") or "Unknown"
        home_team = game.get("home_team", "")
        away_team = game.get("away_team", "")
        home_pitcher_name = game.get("home_probable_pitcher", "Unknown")
        away_pitcher_name = game.get("away_probable_pitcher", "Unknown")
        home_pitcher_id = game.get("home_probable_pitcher_id")
        away_pitcher_id = game.get("away_probable_pitcher_id")

        # Fetch pitcher handedness for platoon splits
        for pid in [home_pitcher_id, away_pitcher_id]:
            if pid and pid not in pitcher_hands:
                pitcher_hands[pid] = fetch_pitcher_hand(pid)

        home_pitcher_hand = pitcher_hands.get(home_pitcher_id)
        away_pitcher_hand = pitcher_hands.get(away_pitcher_id)

        # Home team batters face away pitcher
        home_batters = [p for p in players if p.get("team") == home_team]
        for batter in home_batters:
            b_id = batter["mlbam_id"]
            b_name = batter["full_name"]
            b_games = batter.get("games_played") or 0
            b_hand = batter.get("bats")
            if b_id in projected:
                continue
            projected.add(b_id)
            log.info(f"  Projecting {b_name} ({home_team}, {b_hand or '?'}HB) vs {away_pitcher_name} ({away_pitcher_hand or '?'}HP) @ {venue}")
            try:
                proj = project_batter(
                    b_id, b_name, away_pitcher_name, venue,
                    games_played=b_games,
                    batter_hand=b_hand,
                    pitcher_hand=away_pitcher_hand,
                )
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
            b_games = batter.get("games_played") or 0
            b_hand = batter.get("bats")
            if b_id in projected:
                continue
            projected.add(b_id)
            log.info(f"  Projecting {b_name} ({away_team}, {b_hand or '?'}HB) vs {home_pitcher_name} ({home_pitcher_hand or '?'}HP) @ {venue}")
            try:
                proj = project_batter(
                    b_id, b_name, home_pitcher_name, venue,
                    games_played=b_games,
                    batter_hand=b_hand,
                    pitcher_hand=home_pitcher_hand,
                )
                proj["game_pk"] = game_pk
                proj["game_date"] = game_date
                projection_rows.append(proj)
            except Exception as e:
                log.warning(f"  Failed to project {b_name}: {e}")

    log.info(f"Generated {len(projection_rows)} batter TB projections")
    sb_upsert("projections", projection_rows)
    log.info("=== Done ===")


if __name__ == "__main__":
    import sys
    run_projections(sys.argv[1] if len(sys.argv) > 1 else None)
