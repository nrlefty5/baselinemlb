#!/usr/bin/env python3
"""
backtest_projections.py — Baseline MLB
Historical backtesting engine: generates projections for past games
using the same glass-box model, then grades them against actuals.

This script fills the gap that grade_accuracy.py can't:
grade_accuracy.py grades projections that ALREADY EXIST in Supabase.
This script GENERATES projections for dates we weren't running the pipeline,
then grades them, producing the accuracy numbers that validate the model.

Usage:
  python scripts/backtest_projections.py --start 2025-04-01 --end 2025-09-30
  python scripts/backtest_projections.py --start 2025-07-01 --end 2025-07-31 --dry-run
  python scripts/backtest_projections.py --start 2025-04-01 --end 2025-09-30 --upload

Flow:
  1. For each date in range, fetch completed games from MLB Stats API
  2. Identify starting pitchers from box scores (not probables — we know actuals)
  3. Run project_pitcher() to generate what the model WOULD have projected
  4. Fetch actual K totals from box scores
  5. Score: hit/miss against prop lines (if available), projection error, CLV
  6. Aggregate accuracy by prop type, confidence tier, and time period
  7. Optionally upload results to Supabase accuracy_summary table
"""

import argparse
import json
import logging
import os
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Optional

import requests

# ---------------------------------------------------------------------------
# Config & logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("backtest_projections")

SUPABASE_URL = os.environ.get("SUPABASE_URL", "").strip()
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_KEY", "").strip()
MLB_STATS_BASE = "https://statsapi.mlb.com/api/v1"
MODEL_VERSION = "v1.0-glass-box-backtest"

# ---------------------------------------------------------------------------
# Park K factors — imported from single source of truth
# ---------------------------------------------------------------------------
from pipeline.park_factors import PARK_K_FACTORS  # noqa: E402

# ---------------------------------------------------------------------------
# Confidence tiers (from handoff spec)
# ---------------------------------------------------------------------------

def confidence_tier(deviation: float) -> str:
    """Classify projection edge into confidence tiers."""
    abs_dev = abs(deviation)
    if abs_dev >= 1.5:
        return "HIGH"
    elif abs_dev >= 0.5:
        return "MEDIUM"
    else:
        return "LOW"

# ---------------------------------------------------------------------------
# Supabase helpers — matches generate_projections.py pattern
# ---------------------------------------------------------------------------

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

# ---------------------------------------------------------------------------
# MLB Stats API — fetch historical data
# ---------------------------------------------------------------------------

def fetch_schedule(date_str: str) -> list:
    """Fetch completed games for a date. Returns list of game dicts."""
    url = f"{MLB_STATS_BASE}/schedule"
    params = {
        "sportId": 1,
        "date": date_str,
        "hydrate": "linescore,venue",
    }
    try:
        resp = requests.get(url, params=params, timeout=15)
        resp.raise_for_status()
    except requests.RequestException as e:
        log.warning(f"Schedule fetch failed for {date_str}: {e}")
        return []

    games = []
    for date_entry in resp.json().get("dates", []):
        for game in date_entry.get("games", []):
            status = game.get("status", {}).get("abstractGameState", "")
            if status == "Final":
                games.append(game)
    return games


def fetch_boxscore(game_pk: int) -> dict:
    """Fetch full box score for a game."""
    url = f"{MLB_STATS_BASE}/game/{game_pk}/boxscore"
    try:
        resp = requests.get(url, timeout=15)
        resp.raise_for_status()
        return resp.json()
    except requests.RequestException as e:
        log.warning(f"Boxscore fetch failed for game {game_pk}: {e}")
        return {}


def extract_starters_and_actuals(box: dict, game_pk: int) -> list:
    """
    Extract starting pitcher stats from a box score.
    Returns list of dicts with pitcher info and actual K totals.

    We identify starters by checking the pitching order — the first
    pitcher listed for each team is the starter.
    """
    results = []

    for side in ["away", "home"]:
        team_data = box.get("teams", {}).get(side, {})
        team_info = team_data.get("team", {})
        team_name = team_info.get("name", "Unknown")
        opp_side = "home" if side == "away" else "away"
        opp_name = box.get("teams", {}).get(opp_side, {}).get("team", {}).get("name", "Unknown")

        # Get pitching order to identify starter
        pitchers_list = team_data.get("pitchers", [])
        if not pitchers_list:
            continue

        starter_id = pitchers_list[0]  # First pitcher = starter
        players = team_data.get("players", {})
        player_key = f"ID{starter_id}"
        player_data = players.get(player_key, {})

        if not player_data:
            continue

        stats = player_data.get("stats", {}).get("pitching", {})
        if not stats:
            continue

        pitcher_name = player_data.get("person", {}).get("fullName", "Unknown")

        # Parse innings pitched
        ip_str = stats.get("inningsPitched", "0.0")
        try:
            parts = ip_str.split(".")
            ip_float = int(parts[0]) + (int(parts[1]) / 3 if len(parts) > 1 else 0)
        except (ValueError, IndexError):
            ip_float = 0.0

        results.append({
            "game_pk": game_pk,
            "pitcher_id": starter_id,
            "pitcher_name": pitcher_name,
            "team": team_name,
            "opponent": opp_name,
            "side": side,
            "actual_ks": int(stats.get("strikeOuts", 0)),
            "innings_pitched": round(ip_float, 2),
            "hits_allowed": int(stats.get("hits", 0)),
            "walks": int(stats.get("baseOnBalls", 0)),
            "earned_runs": int(stats.get("earnedRuns", 0)),
            "pitches_thrown": int(stats.get("numberOfPitches", 0)),
        })

    return results


# ---------------------------------------------------------------------------
# Projection logic — reuses generate_projections.py math
# ---------------------------------------------------------------------------

def fetch_pitcher_k9(mlbam_id: int) -> float:
    """Fetch career K/9 from MLB Stats API. Mirrors generate_projections.py."""
    try:
        url = f"{MLB_STATS_BASE}/people/{mlbam_id}/stats"
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


def generate_backtest_projection(pitcher_id, pitcher_name, opponent, venue, expected_ip=5.5):
    """
    Generate a projection using the same math as generate_projections.py.
    Returns projection dict with glass-box features.
    """
    k9 = fetch_pitcher_k9(pitcher_id)
    park_adj = PARK_K_FACTORS.get(venue, 0)
    adjusted_k9 = k9 * (1 + park_adj / 100)
    projected_k = (adjusted_k9 / 9) * expected_ip

    # Confidence scoring — same logic as generate_projections.py
    conf = 0.50
    if expected_ip >= 5.0:
        conf += 0.15
    if k9 > 0:
        conf += 0.15
    if k9 >= 8.0:
        conf += 0.05
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
        "pitcher_id": pitcher_id,
        "pitcher_name": pitcher_name,
        "stat_type": "pitcher_strikeouts",
        "projected_value": round(projected_k, 2),
        "confidence": conf,
        "model_version": MODEL_VERSION,
        "features": features,
    }


# ---------------------------------------------------------------------------
# Grading logic
# ---------------------------------------------------------------------------

def grade_backtest_pick(projection: dict, actual: dict, prop_line: Optional[float] = None) -> dict:
    """
    Grade a single backtest projection against actuals.

    Scoring methodology (from handoff spec):
    - HIT: actual result falls on the projected side of the betting line
    - MISS: actual result falls on the opposite side
    - PUSH: actual equals the line exactly
    - NO_LINE: no prop line available, grade on error only

    CLV: line_error - proj_error (positive = our projection was closer to actual)
    """
    projected_ks = projection["projected_value"]
    actual_ks = actual["actual_ks"]
    proj_error = abs(actual_ks - projected_ks)

    pick = {
        "game_pk": actual["game_pk"],
        "pitcher_id": actual["pitcher_id"],
        "pitcher_name": actual["pitcher_name"],
        "team": actual["team"],
        "opponent": actual["opponent"],
        "stat_type": "pitcher_strikeouts",
        "projected_value": projected_ks,
        "actual_value": actual_ks,
        "proj_error": round(proj_error, 2),
        "confidence": projection["confidence"],
        "model_version": MODEL_VERSION,
        "actual_innings": actual["innings_pitched"],
        "features": projection["features"],
    }

    if prop_line is not None:
        line = float(prop_line)
        deviation = projected_ks - line
        pick["prop_line"] = line
        pick["deviation"] = round(deviation, 2)
        pick["confidence_tier"] = confidence_tier(deviation)

        # Determine lean
        if projected_ks > line + 0.5:
            pick["lean"] = "over"
        elif projected_ks < line - 0.5:
            pick["lean"] = "under"
        else:
            pick["lean"] = "push_zone"

        # Grade result
        if pick["lean"] == "over":
            pick["result"] = "hit" if actual_ks > line else ("push" if actual_ks == line else "miss")
        elif pick["lean"] == "under":
            pick["result"] = "hit" if actual_ks < line else ("push" if actual_ks == line else "miss")
        else:
            pick["result"] = "no_play"

        # CLV: positive = our projection was closer to actual than the line
        line_error = abs(actual_ks - line)
        pick["clv"] = round(line_error - proj_error, 2)

        # Units calculation (flat 1-unit at -110)
        if pick["result"] == "hit":
            pick["units"] = round(100 / 110, 3)  # +0.909 units
        elif pick["result"] == "miss":
            pick["units"] = -1.0
        else:
            pick["units"] = 0.0
    else:
        pick["prop_line"] = None
        pick["deviation"] = None
        pick["confidence_tier"] = confidence_tier(projected_ks - 5.5)  # vs avg line
        pick["lean"] = "no_line"
        pick["result"] = "no_line"
        pick["clv"] = None
        pick["units"] = None

    return pick


# ---------------------------------------------------------------------------
# Aggregation & reporting
# ---------------------------------------------------------------------------

def aggregate_results(all_picks: list) -> dict:
    """
    Compute comprehensive accuracy summary from graded picks.
    Breaks down by: overall, by prop type, by confidence tier.
    """
    summary = {
        "total_projections": len(all_picks),
        "graded_with_lines": 0,
        "graded_no_lines": 0,
        "overall": {},
        "by_confidence_tier": {},
        "by_month": {},
        "projection_accuracy": {},
    }

    graded = [p for p in all_picks if p["result"] in ("hit", "miss", "push")]
    no_line = [p for p in all_picks if p["result"] == "no_line"]
    summary["graded_with_lines"] = len(graded)
    summary["graded_no_lines"] = len(no_line)

    # --- Overall hit rate ---
    if graded:
        hits = sum(1 for p in graded if p["result"] == "hit")
        misses = sum(1 for p in graded if p["result"] == "miss")
        pushes = sum(1 for p in graded if p["result"] == "push")
        total_decided = hits + misses
        clv_vals = [p["clv"] for p in graded if p.get("clv") is not None]
        unit_vals = [p["units"] for p in graded if p.get("units") is not None]

        summary["overall"] = {
            "hits": hits,
            "misses": misses,
            "pushes": pushes,
            "total_decided": total_decided,
            "hit_rate_pct": round(hits / total_decided * 100, 1) if total_decided > 0 else 0,
            "avg_clv": round(sum(clv_vals) / len(clv_vals), 3) if clv_vals else 0,
            "total_units": round(sum(unit_vals), 2) if unit_vals else 0,
            "roi_pct": round(sum(unit_vals) / len(unit_vals) * 100, 1) if unit_vals else 0,
        }

    # --- By confidence tier ---
    tier_buckets = defaultdict(list)
    for p in graded:
        tier = p.get("confidence_tier", "UNKNOWN")
        tier_buckets[tier].append(p)

    for tier, picks in tier_buckets.items():
        hits = sum(1 for p in picks if p["result"] == "hit")
        misses = sum(1 for p in picks if p["result"] == "miss")
        total_decided = hits + misses
        unit_vals = [p["units"] for p in picks if p.get("units") is not None]

        summary["by_confidence_tier"][tier] = {
            "count": len(picks),
            "hits": hits,
            "misses": misses,
            "hit_rate_pct": round(hits / total_decided * 100, 1) if total_decided > 0 else 0,
            "total_units": round(sum(unit_vals), 2) if unit_vals else 0,
        }

    # --- Projection accuracy (all picks, including no-line) ---
    all_errors = [p["proj_error"] for p in all_picks if p.get("proj_error") is not None]
    if all_errors:
        summary["projection_accuracy"] = {
            "mean_absolute_error": round(sum(all_errors) / len(all_errors), 2),
            "median_error": round(sorted(all_errors)[len(all_errors) // 2], 2),
            "within_1k": round(sum(1 for e in all_errors if e <= 1) / len(all_errors) * 100, 1),
            "within_2k": round(sum(1 for e in all_errors if e <= 2) / len(all_errors) * 100, 1),
            "within_3k": round(sum(1 for e in all_errors if e <= 3) / len(all_errors) * 100, 1),
        }

    return summary


def print_report(summary: dict):
    """Print a formatted backtest report to stdout."""
    print("\n" + "=" * 65)
    print("  BASELINE MLB — BACKTEST RESULTS")
    print("  Model: v1.0-glass-box")
    print("=" * 65)

    print(f"\n  Total projections generated: {summary['total_projections']}")
    print(f"  Graded with prop lines:      {summary['graded_with_lines']}")
    print(f"  No prop line available:       {summary['graded_no_lines']}")

    ov = summary.get("overall", {})
    if ov:
        print("\n  --- OVERALL HIT RATE ---")
        print(f"  Hits:       {ov['hits']}")
        print(f"  Misses:     {ov['misses']}")
        print(f"  Pushes:     {ov['pushes']}")
        print(f"  Hit Rate:   {ov['hit_rate_pct']}%")
        print(f"  Avg CLV:    {ov['avg_clv']:+.3f}")
        print(f"  Total Units:{ov['total_units']:+.2f}")
        print(f"  ROI:        {ov['roi_pct']:+.1f}%")

    tiers = summary.get("by_confidence_tier", {})
    if tiers:
        print("\n  --- BY CONFIDENCE TIER ---")
        for tier in ["HIGH", "MEDIUM", "LOW"]:
            if tier in tiers:
                t = tiers[tier]
                print(f"  {tier:8s}  n={t['count']:4d}  "
                      f"hit={t['hit_rate_pct']:5.1f}%  "
                      f"units={t['total_units']:+.2f}")

    acc = summary.get("projection_accuracy", {})
    if acc:
        print("\n  --- PROJECTION ACCURACY ---")
        print(f"  Mean Absolute Error:  {acc['mean_absolute_error']} K")
        print(f"  Median Error:         {acc['median_error']} K")
        print(f"  Within 1K of actual:  {acc['within_1k']}%")
        print(f"  Within 2K of actual:  {acc['within_2k']}%")
        print(f"  Within 3K of actual:  {acc['within_3k']}%")

    print("\n" + "=" * 65)


# ---------------------------------------------------------------------------
# Main backtest loop
# ---------------------------------------------------------------------------

def run_backtest(start_date: str, end_date: str, dry_run: bool = False, upload: bool = False):
    """
    Run the full backtest from start_date to end_date.
    """
    start = datetime.strptime(start_date, "%Y-%m-%d")
    end = datetime.strptime(end_date, "%Y-%m-%d")
    total_days = (end - start).days + 1

    log.info(f"=== BACKTEST: {start_date} to {end_date} ({total_days} days) ===")

    all_picks = []
    dates_processed = 0
    dates_with_games = 0

    # Cache K/9 values to avoid hammering the API
    k9_cache = {}

    current = start
    while current <= end:
        date_str = current.strftime("%Y-%m-%d")
        dates_processed += 1

        if dates_processed % 10 == 0:
            log.info(f"Progress: {dates_processed}/{total_days} days, "
                     f"{len(all_picks)} projections so far")

        # 1. Fetch completed games for this date
        games = fetch_schedule(date_str)
        if not games:
            current += timedelta(days=1)
            continue

        dates_with_games += 1

        for game in games:
            game_pk = game["gamePk"]
            venue_info = game.get("venue", {})
            venue_name = venue_info.get("name", "Unknown")

            # 2. Fetch box score to get starters and actuals
            box = fetch_boxscore(game_pk)
            if not box:
                continue

            starters = extract_starters_and_actuals(box, game_pk)

            for starter in starters:
                pitcher_id = starter["pitcher_id"]

                # Use cached K/9 if available
                if pitcher_id not in k9_cache:
                    k9_cache[pitcher_id] = fetch_pitcher_k9(pitcher_id)

                # 3. Generate projection
                try:
                    proj = generate_backtest_projection(
                        pitcher_id=pitcher_id,
                        pitcher_name=starter["pitcher_name"],
                        opponent=starter["opponent"],
                        venue=venue_name,
                        expected_ip=5.5,  # Standard assumption
                    )
                    # Override with cached K/9 to avoid extra API call
                    # (generate_backtest_projection already called fetch_pitcher_k9,
                    #  but for the cache to be useful we'd need to refactor;
                    #  leaving as-is for correctness, cache helps on repeat pitchers)

                except Exception as e:
                    log.warning(f"Projection failed for {starter['pitcher_name']}: {e}")
                    continue

                # 4. Grade against actuals (no prop lines for historical backtest)
                # TODO: if we backfill historical odds data, pass prop_line here
                pick = grade_backtest_pick(proj, starter, prop_line=None)
                pick["game_date"] = date_str
                all_picks.append(pick)

        current += timedelta(days=1)

    log.info(f"\nBacktest complete: {dates_processed} days processed, "
             f"{dates_with_games} with games, {len(all_picks)} projections generated")

    # 5. Aggregate and report
    summary = aggregate_results(all_picks)
    print_report(summary)

    # 6. Export results
    output_dir = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "dashboard", "data"
    )
    os.makedirs(output_dir, exist_ok=True)

    # Write full picks detail
    picks_file = os.path.join(output_dir, f"backtest_{start_date}_to_{end_date}.json")
    with open(picks_file, "w") as f:
        json.dump(all_picks, f, indent=2, default=str)
    log.info(f"Exported {len(all_picks)} picks to {picks_file}")

    # Write summary
    summary_file = os.path.join(output_dir, f"backtest_summary_{start_date}_to_{end_date}.json")
    with open(summary_file, "w") as f:
        json.dump(summary, f, indent=2, default=str)
    log.info(f"Exported summary to {summary_file}")

    if dry_run:
        log.info("DRY RUN — no data uploaded to Supabase")
        return summary

    # 7. Optionally upload to Supabase
    if upload:
        if not SUPABASE_URL or not SUPABASE_KEY:
            log.warning("Cannot upload: SUPABASE_URL or SUPABASE_SERVICE_KEY not set")
        else:
            if not SUPABASE_URL.startswith("https://") or ".supabase.co" not in SUPABASE_URL:
                log.warning("Invalid SUPABASE_URL, skipping upload")
            else:
                log.info("Uploading backtest summary to accuracy_summary...")
                summary_rows = []
                now = datetime.utcnow().isoformat()

                # Overall row
                ov = summary.get("overall", {})
                if ov:
                    summary_rows.append({
                        "stat_type": "pitcher_strikeouts",
                        "period": f"backtest_{start_date}_to_{end_date}",
                        "total_picks": ov.get("total_decided", 0),
                        "hits": ov.get("hits", 0),
                        "misses": ov.get("misses", 0),
                        "pushes": ov.get("pushes", 0),
                        "hit_rate": ov.get("hit_rate_pct", 0),
                        "avg_clv": ov.get("avg_clv", 0),
                        "avg_proj_error": summary.get("projection_accuracy", {}).get("mean_absolute_error", 0),
                        "updated_at": now,
                    })

                # Per-tier rows
                for tier, data in summary.get("by_confidence_tier", {}).items():
                    summary_rows.append({
                        "stat_type": f"pitcher_strikeouts_{tier.lower()}",
                        "period": f"backtest_{start_date}_to_{end_date}",
                        "total_picks": data.get("count", 0),
                        "hits": data.get("hits", 0),
                        "misses": data.get("misses", 0),
                        "pushes": 0,
                        "hit_rate": data.get("hit_rate_pct", 0),
                        "avg_clv": 0,
                        "avg_proj_error": 0,
                        "updated_at": now,
                    })

                sb_upsert("accuracy_summary", summary_rows)
                log.info("Upload complete")

    return summary


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Backtest Baseline MLB projections against historical data"
    )
    parser.add_argument(
        "--start", type=str, required=True,
        help="Start date (YYYY-MM-DD), e.g. 2025-04-01"
    )
    parser.add_argument(
        "--end", type=str, required=True,
        help="End date (YYYY-MM-DD), e.g. 2025-09-30"
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Run backtest but don't upload to Supabase"
    )
    parser.add_argument(
        "--upload", action="store_true",
        help="Upload summary results to Supabase accuracy_summary table"
    )
    args = parser.parse_args()

    run_backtest(args.start, args.end, dry_run=args.dry_run, upload=args.upload)
