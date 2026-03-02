#!/usr/bin/env python3
"""
generate_projections.py -- Baseline MLB
Glass-box pitcher strikeout projection engine v2.0.

Model factors (v2.0):
  1. Career K/9 (MLB Stats API)
  2. Recent form: 14-day K/9 weighted 30% vs career 70%
  3. Park K-factor adjustments (19 ballparks)
  4. Umpire tendencies: trailing 30-game strike_rate from umpire_framing table
  5. Catcher framing: trailing 30-game composite_score from umpire_framing table
  6. Opponent team K%: team strikeout rate as a multiplier
  7. Pitcher-specific expected IP: trailing season average (replaces hardcoded 5.5)

Reads games + players from Supabase, computes projections,
upserts results to the projections table.

Supports manual pitcher overrides via the `pitcher_overrides` table
for games where the MLB Stats API lacks probable pitcher data
(e.g., WBC, exhibitions).
"""

import json
import logging
import os
from datetime import date, timedelta

import requests

# from dotenv import load_dotenv  # DISABLED - GitHub Actions provides env vars
# load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("generate_projections")

SUPABASE_URL = os.environ.get("SUPABASE_URL", "").strip()
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_KEY", "").strip()
MODEL_VERSION = "v2.0-glass-box"

# Fail fast with a clear error instead of cryptic HTTP 400
if not SUPABASE_URL.startswith("https://") or not SUPABASE_URL.endswith(".supabase.co"):
    raise RuntimeError(f"Invalid SUPABASE_URL (length={len(SUPABASE_URL)}, repr={repr(SUPABASE_URL[:30])})")

PARK_K_FACTORS = {
    "Coors Field": -8, "Yankee Stadium": 3, "Oracle Park": 5,
    "Petco Park": 4, "Truist Park": 2, "Globe Life Field": 2,
    "Chase Field": 1, "T-Mobile Park": 3, "Guaranteed Rate Field": 0,
    "loanDepot park": 1, "Great American Ball Park": -2,
    "PNC Park": 1, "Minute Maid Park": 2, "Dodger Stadium": 4,
    "Angel Stadium": 0, "Fenway Park": -1, "Wrigley Field": -3,
    "Busch Stadium": 1, "Citizens Bank Park": -2,
}

# MLB average constants for fallbacks
MLB_AVG_K9 = 8.5        # 2024 MLB average K/9
MLB_AVG_K_PCT = 0.224    # 2024 MLB average K%
MLB_AVG_IP = 5.5         # Fallback IP when no data

# Recent form blending weights
RECENT_FORM_WEIGHT = 0.30
CAREER_WEIGHT = 0.70


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


# ---------------------------------------------------------------------------
# Factor 1: Career K/9
# ---------------------------------------------------------------------------

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
    return MLB_AVG_K9  # MLB average fallback


# ---------------------------------------------------------------------------
# Factor 2: Recent form (14-day K/9) — NEW in v2.0
# ---------------------------------------------------------------------------

def fetch_recent_k9(mlbam_id, season=None):
    """
    Fetch last-14-day K/9 from MLB Stats API game log.
    Returns (recent_k9, num_starts) or (None, 0) if unavailable.
    """
    if season is None:
        season = date.today().year
    try:
        url = f"https://statsapi.mlb.com/api/v1/people/{mlbam_id}/stats"
        r = requests.get(url, params={
            "stats": "gameLog",
            "group": "pitching",
            "season": season,
            "sportId": 1
        }, timeout=10)
        r.raise_for_status()
        splits = r.json().get("stats", [{}])[0].get("splits", [])
        if not splits:
            return None, 0

        cutoff = (date.today() - timedelta(days=14)).isoformat()
        recent_k = 0
        recent_ip = 0.0
        num_starts = 0

        for split in splits:
            game_date = split.get("date", "")
            if game_date < cutoff:
                continue
            stat = split.get("stat", {})
            recent_k += int(stat.get("strikeOuts", 0))
            ip_str = str(stat.get("inningsPitched", "0.0"))
            parts = ip_str.split(".")
            recent_ip += int(parts[0]) + (int(parts[1]) / 3 if len(parts) > 1 and parts[1] else 0)
            num_starts += 1

        if recent_ip >= 3.0:  # Need at least 3 IP for meaningful sample
            return round((recent_k / recent_ip) * 9, 2), num_starts
    except Exception as e:
        log.debug(f"Recent K/9 fetch failed for {mlbam_id}: {e}")
    return None, 0


# ---------------------------------------------------------------------------
# Factor 3: Opponent team K% — NEW in v2.0
# ---------------------------------------------------------------------------

def fetch_team_k_pct(team_name, season=None):
    """
    Fetch a team's strikeout rate (K%) from MLB Stats API.
    Returns K% as a decimal (e.g. 0.24 = 24%).
    """
    if season is None:
        season = date.today().year
    try:
        # First get team ID
        url = "https://statsapi.mlb.com/api/v1/teams"
        r = requests.get(url, params={"sportId": 1, "season": season}, timeout=10)
        r.raise_for_status()
        teams = r.json().get("teams", [])

        team_id = None
        for t in teams:
            if t.get("name") == team_name:
                team_id = t["id"]
                break

        if not team_id:
            return MLB_AVG_K_PCT

        # Fetch team hitting stats
        url = f"https://statsapi.mlb.com/api/v1/teams/{team_id}/stats"
        r = requests.get(url, params={
            "stats": "season",
            "group": "hitting",
            "season": season,
            "sportId": 1
        }, timeout=10)
        r.raise_for_status()
        splits = r.json().get("stats", [{}])[0].get("splits", [])
        if splits:
            stat = splits[0].get("stat", {})
            k = int(stat.get("strikeOuts", 0))
            pa = int(stat.get("plateAppearances", 1))
            if pa > 0:
                return round(k / pa, 3)
    except Exception as e:
        log.debug(f"Team K% fetch failed for {team_name}: {e}")
    return MLB_AVG_K_PCT


# ---------------------------------------------------------------------------
# Factor 4: Pitcher-specific expected IP — NEW in v2.0
# ---------------------------------------------------------------------------

def fetch_pitcher_avg_ip(mlbam_id, season=None):
    """
    Fetch pitcher's season average innings pitched per start.
    Returns trailing season average IP or MLB_AVG_IP as fallback.
    """
    if season is None:
        season = date.today().year
    try:
        url = f"https://statsapi.mlb.com/api/v1/people/{mlbam_id}/stats"
        r = requests.get(url, params={
            "stats": "season",
            "group": "pitching",
            "season": season,
            "sportId": 1
        }, timeout=10)
        r.raise_for_status()
        splits = r.json().get("stats", [{}])[0].get("splits", [])
        if splits:
            stat = splits[0].get("stat", {})
            gs = int(stat.get("gamesStarted", 0))
            ip_str = str(stat.get("inningsPitched", "0.0"))
            parts = ip_str.split(".")
            total_ip = int(parts[0]) + (int(parts[1]) / 3 if len(parts) > 1 and parts[1] else 0)
            if gs >= 3 and total_ip > 0:
                return round(total_ip / gs, 2)
    except Exception as e:
        log.debug(f"Avg IP fetch failed for {mlbam_id}: {e}")
    return MLB_AVG_IP


# ---------------------------------------------------------------------------
# Factor 5: Umpire tendencies — NEW in v2.0
# ---------------------------------------------------------------------------

def fetch_umpire_factor(umpire_name):
    """
    Query umpire_framing table for trailing 30-game average strike_rate.
    Returns adjustment factor: >1.0 = generous ump, <1.0 = tight ump.
    """
    if not umpire_name:
        return 1.0, None
    try:
        rows = sb_get("umpire_framing", {
            "umpire_name": f"eq.{umpire_name}",
            "select": "strike_rate",
            "order": "game_date.desc",
            "limit": "30",
        })
        if rows and len(rows) >= 5:
            avg_sr = sum(r["strike_rate"] for r in rows) / len(rows)
            # Normalize: MLB avg called strike rate is ~0.32
            # Factor: ump_rate / 0.32 => e.g. 0.35/0.32 = 1.09 (generous)
            factor = avg_sr / 0.32 if avg_sr > 0 else 1.0
            return round(factor, 3), round(avg_sr, 4)
    except Exception as e:
        log.debug(f"Umpire factor fetch failed for {umpire_name}: {e}")
    return 1.0, None


# ---------------------------------------------------------------------------
# Factor 6: Catcher framing — NEW in v2.0
# ---------------------------------------------------------------------------

def fetch_catcher_factor(catcher_id):
    """
    Query umpire_framing table for catcher's trailing 30-game composite_score.
    Returns adjustment factor: >1.0 = good framer, <1.0 = poor framer.
    """
    if not catcher_id:
        return 1.0, None
    try:
        rows = sb_get("umpire_framing", {
            "catcher_id": f"eq.{catcher_id}",
            "select": "composite_score",
            "order": "game_date.desc",
            "limit": "30",
        })
        if rows and len(rows) >= 5:
            avg_cs = sum(r["composite_score"] for r in rows) / len(rows)
            # Normalize: MLB avg composite ~0.20
            # Factor: catcher_score / 0.20 => e.g. 0.25/0.20 = 1.25 (elite framer)
            # Dampen the effect: max ±5% adjustment
            raw_factor = avg_cs / 0.20 if avg_cs > 0 else 1.0
            factor = max(0.95, min(1.05, raw_factor))
            return round(factor, 3), round(avg_cs, 4)
    except Exception as e:
        log.debug(f"Catcher factor fetch failed for {catcher_id}: {e}")
    return 1.0, None


# ---------------------------------------------------------------------------
# Fetch game umpire & catcher from MLB API
# ---------------------------------------------------------------------------

def fetch_game_officials(game_pk):
    """
    Fetch the home plate umpire and starting catchers for a game.
    Returns (umpire_name, home_catcher_id, away_catcher_id).
    """
    umpire_name = None
    home_catcher_id = None
    away_catcher_id = None
    try:
        url = f"https://statsapi.mlb.com/api/v1.1/game/{game_pk}/feed/live"
        r = requests.get(url, timeout=10)
        r.raise_for_status()
        data = r.json()

        # Get home plate umpire
        officials = data.get("liveData", {}).get("boxscore", {}).get("officials", [])
        for official in officials:
            if official.get("officialType") == "Home Plate":
                umpire_name = official.get("official", {}).get("fullName")
                break

        # Get starting catchers from lineup
        for side in ["home", "away"]:
            players = data.get("liveData", {}).get("boxscore", {}).get("teams", {}).get(side, {}).get("players", {})
            for pid_str, pdata in players.items():
                pos = pdata.get("position", {}).get("abbreviation", "")
                if pos == "C" and pdata.get("stats", {}).get("batting", {}).get("plateAppearances", 0) >= 0:
                    # Check if they're in the starting lineup
                    batting_order = pdata.get("battingOrder")
                    if batting_order:
                        catcher_id = pdata.get("person", {}).get("id")
                        if side == "home":
                            home_catcher_id = catcher_id
                        else:
                            away_catcher_id = catcher_id
                        break

    except Exception as e:
        log.debug(f"Officials fetch failed for game {game_pk}: {e}")

    return umpire_name, home_catcher_id, away_catcher_id


# ---------------------------------------------------------------------------
# Core projection function — ENHANCED v2.0
# ---------------------------------------------------------------------------

def project_pitcher(mlbam_id, player_name, opponent, venue, game_pk=None):
    """
    Project pitcher strikeouts using the v2.0 multi-factor model.

    Factors:
      1. Blended K/9 (career 70% + recent 14-day 30%)
      2. Park K-factor
      3. Umpire strike tendency
      4. Catcher framing quality
      5. Opponent team K%
      6. Pitcher-specific expected IP
    """
    # Factor 1: Career K/9
    career_k9 = fetch_pitcher_k9(mlbam_id)

    # Factor 2: Recent form (14-day K/9)
    recent_k9, recent_starts = fetch_recent_k9(mlbam_id)
    if recent_k9 is not None and recent_starts >= 2:
        blended_k9 = (CAREER_WEIGHT * career_k9) + (RECENT_FORM_WEIGHT * recent_k9)
    else:
        blended_k9 = career_k9
        recent_k9 = None  # Mark as unavailable for features

    # Factor 3: Park adjustment
    park_adj = PARK_K_FACTORS.get(venue, 0)
    park_factor = 1 + park_adj / 100

    # Factor 4: Pitcher-specific expected IP
    expected_ip = fetch_pitcher_avg_ip(mlbam_id)

    # Factor 5: Opponent team K%
    opp_k_pct = fetch_team_k_pct(opponent)
    opp_k_factor = opp_k_pct / MLB_AVG_K_PCT  # >1 = high-K team, <1 = low-K team

    # Factors 6 & 7: Umpire + Catcher (need game_pk)
    umpire_factor = 1.0
    catcher_factor = 1.0
    umpire_name = None
    umpire_sr = None
    catcher_cs = None

    if game_pk:
        ump_name, home_catcher_id, away_catcher_id = fetch_game_officials(game_pk)
        if ump_name:
            umpire_name = ump_name
            umpire_factor, umpire_sr = fetch_umpire_factor(ump_name)
        # Use the opposing catcher for the pitcher (they're catching vs this pitcher)
        # For simplicity, try both catchers — the one we have data for
        for cid in [home_catcher_id, away_catcher_id]:
            if cid:
                cf, cs = fetch_catcher_factor(cid)
                if cs is not None:
                    catcher_factor = cf
                    catcher_cs = cs
                    break

    # Compute final projection
    adjusted_k9 = blended_k9 * park_factor * umpire_factor * catcher_factor * opp_k_factor
    projected_k = (adjusted_k9 / 9) * expected_ip

    # Confidence scoring
    conf = 0.50
    if expected_ip >= 5.0:
        conf += 0.10
    if career_k9 > 0:
        conf += 0.10
    if career_k9 >= 9.0:
        conf += 0.05
    if recent_k9 is not None:
        conf += 0.05  # More confident with recent data
    if umpire_sr is not None:
        conf += 0.03  # More confident with umpire data
    if catcher_cs is not None:
        conf += 0.02  # More confident with catcher data
    if opp_k_pct != MLB_AVG_K_PCT:
        conf += 0.03  # Have actual team data
    conf = round(min(conf, 0.95), 3)

    features = {
        "baseline_k9": round(career_k9, 2),
        "recent_k9": recent_k9,
        "recent_starts": recent_starts,
        "blended_k9": round(blended_k9, 2),
        "park_adjustment": f"{park_adj:+.1f}%",
        "adjusted_k9": round(adjusted_k9, 2),
        "expected_innings": expected_ip,
        "opponent": opponent,
        "opp_k_pct": round(opp_k_pct, 3),
        "opp_k_factor": round(opp_k_factor, 3),
        "venue": venue,
        "umpire_name": umpire_name,
        "umpire_factor": umpire_factor,
        "umpire_strike_rate": umpire_sr,
        "catcher_factor": catcher_factor,
        "catcher_composite": catcher_cs,
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

    log.info(f"=== Generating v2.0 projections for {game_date} ===")

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
                proj = project_pitcher(pid, pname, opp, venue, game_pk=game_pk)
                proj["game_pk"] = game_pk
                proj["game_date"] = game_date
                projection_rows.append(proj)
            except Exception as e:
                log.warning(f" Failed to project {pname}: {e}")

    log.info(f"Generated {len(projection_rows)} projections")
    sb_upsert("projections", projection_rows)
    log.info("=== Done ===")

if __name__ == "__main__":
    import sys
    run_projections(sys.argv[1] if len(sys.argv) > 1 else None)
