#!/usr/bin/env python3
"""
generate_daily_content.py — Baseline MLB
Daily content automation: formats today's projections into
Twitter-ready and email-ready text using the glass-box template.

Every adjustment factor is visible. That's the differentiator.

Usage:
  python scripts/generate_daily_content.py
  python scripts/generate_daily_content.py --date 2026-03-27
  python scripts/generate_daily_content.py --format twitter
  python scripts/generate_daily_content.py --format email
  python scripts/generate_daily_content.py --top 3

Designed to run as the final step in the 8am and 4:30pm GitHub Actions
workflows, after generate_projections.py completes.

Output:
  - stdout: formatted content for CI/CD capture
  - dashboard/data/daily_content_{date}.json: structured data for frontend
"""

import os
import sys
import json
import logging
import argparse
import requests
from datetime import date, datetime
from typing import Optional

# ---------------------------------------------------------------------------
# Config & logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("generate_daily_content")

SUPABASE_URL = os.environ.get("SUPABASE_URL", "").strip()
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_KEY", "").strip()

# Validate Supabase URL
if SUPABASE_URL and (not SUPABASE_URL.startswith("https://") or ".supabase.co" not in SUPABASE_URL):
    raise RuntimeError(f"Invalid SUPABASE_URL (length={len(SUPABASE_URL)}, repr={repr(SUPABASE_URL[:30])})")

# ---------------------------------------------------------------------------
# Confidence tiers
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

def confidence_emoji(tier: str) -> str:
    return {"HIGH": "🔥", "MEDIUM": "⚡", "LOW": "📊"}.get(tier, "📊")

# ---------------------------------------------------------------------------
# Supabase helpers — matches existing pipeline patterns
# ---------------------------------------------------------------------------

def sb_headers():
    return {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
    }

def sb_get(table, params):
    r = requests.get(f"{SUPABASE_URL}/rest/v1/{table}", headers=sb_headers(), params=params)
    r.raise_for_status()
    return r.json()

# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def load_projections(game_date: str) -> list:
    """Load today's projections from Supabase."""
    rows = sb_get("projections", {
        "game_date": f"eq.{game_date}",
        "select": "*",
    })
    log.info(f"Loaded {len(rows)} projections for {game_date}")
    return rows


def load_games(game_date: str) -> dict:
    """Load games for the date, indexed by game_pk."""
    rows = sb_get("games", {
        "game_date": f"eq.{game_date}",
        "select": "game_pk,game_date,home_team,away_team,venue,status,"
        "home_probable_pitcher_id,home_probable_pitcher,"
        "away_probable_pitcher_id,away_probable_pitcher",
    })
    return {g["game_pk"]: g for g in rows}


def load_props(game_date: str) -> dict:
    """
    Load prop lines for the date.
    Returns dict keyed by pitcher_id → {line, over_odds, under_odds, book}.
    """
    rows = sb_get("props", {
        "game_date": f"eq.{game_date}",
        "select": "*",
        "order": "timestamp.desc",
    })

    props = {}
    for row in rows:
        player_id = row.get("player_id") or row.get("pitcher_id")
        if not player_id:
            continue

        pid = int(player_id)
        if pid not in props:  # Keep most recent
            props[pid] = {
                "line": row.get("line"),
                "over_odds": row.get("over_odds", row.get("odds")),
                "under_odds": row.get("under_odds"),
                "book": row.get("bookmaker", row.get("book_name", "")),
            }

    log.info(f"Loaded prop lines for {len(props)} pitchers")
    return props


def load_umpire_framing(game_date: str) -> dict:
    """
    Load umpire framing data for today's games.
    Returns dict keyed by game_pk → {umpire_name, k_adjustment, catcher_name, framing_adj}.
    """
    try:
        rows = sb_get("umpire_framing", {
            "game_date": f"eq.{game_date}",
            "select": "*",
        })
    except Exception:
        # Table may not have data yet — graceful fallback
        log.info("No umpire_framing data available for this date")
        return {}

    framing = {}
    for row in rows:
        gpk = row.get("game_pk")
        if gpk:
            framing[gpk] = {
                "umpire_name": row.get("umpire_name", "TBD"),
                "k_adjustment": row.get("k_adjustment", 0),
                "catcher_name": row.get("catcher_name", ""),
                "framing_adj": row.get("framing_adjustment", 0),
            }

    log.info(f"Loaded umpire/framing data for {len(framing)} games")
    return framing


# ---------------------------------------------------------------------------
# Content enrichment
# ---------------------------------------------------------------------------

def enrich_projection(proj: dict, games: dict, props: dict, framing: dict) -> dict:
    """
    Combine projection with game context, prop line, and umpire/framing data
    into a single enriched record for content generation.
    """
    # Handle field name variations between pipeline versions
    pitcher_id = proj.get("mlbam_id") or proj.get("pitcher_id")
    pitcher_name = proj.get("player_name") or proj.get("pitcher_name", "Unknown")
    projected_value = proj.get("projection") or proj.get("projected_value", 0)
    confidence = proj.get("confidence", 0)
    game_pk = proj.get("game_pk")

    # Parse features
    features = proj.get("features", {})
    if isinstance(features, str):
        try:
            features = json.loads(features)
        except (json.JSONDecodeError, TypeError):
            features = {}

    # Game context
    game = games.get(game_pk, {})
    venue = game.get("venue", features.get("venue", ""))
    opponent = features.get("opponent", "")

    # Prop line
    prop = props.get(pitcher_id, {})
    prop_line = prop.get("line")

    # Umpire/framing
    frame = framing.get(game_pk, {})

    # Calculate edge
    deviation = None
    lean = None
    tier = None
    if prop_line is not None:
        deviation = round(projected_value - float(prop_line), 2)
        lean = "over" if deviation > 0 else "under"
        tier = confidence_tier(deviation)

    return {
        "pitcher_id": pitcher_id,
        "pitcher_name": pitcher_name,
        "projected_value": projected_value,
        "confidence": confidence,
        "game_pk": game_pk,
        "venue": venue,
        "opponent": opponent,
        "prop_line": prop_line,
        "prop_book": prop.get("book", ""),
        "deviation": deviation,
        "lean": lean,
        "confidence_tier": tier,
        "umpire_name": frame.get("umpire_name", "TBD"),
        "k_adjustment": frame.get("k_adjustment", 0),
        "catcher_name": frame.get("catcher_name", ""),
        "framing_adj": frame.get("framing_adj", 0),
        "baseline_k9": features.get("baseline_k9", 0),
        "park_adjustment": features.get("park_adjustment", "0%"),
    }


# ---------------------------------------------------------------------------
# Twitter format
# ---------------------------------------------------------------------------

def format_twitter(enriched: dict) -> Optional[str]:
    """
    Format a single projection as a tweet.
    Returns None if edge is below LOW confidence (not worth posting).

    Template:
    {PlayerName} Strikeouts Projection:
    📊 Model: {value} | Line: O/U {line}
    🔍 Ump {name}: {adj}K adj
    🧤 Catcher {name}: {framing}K framing
    ⚡ Edge: {tier} ({dev} units {lean})
    #MLB #BaselineMLB
    """
    # Only surface projections with genuine edge
    if enriched["deviation"] is None:
        return None
    if abs(enriched["deviation"]) < 0.5:
        return None  # Below LOW threshold — no play

    name = enriched["pitcher_name"]
    proj = enriched["projected_value"]
    line = enriched["prop_line"]
    tier = enriched["confidence_tier"]
    emoji = confidence_emoji(tier)
    lean = enriched["lean"].upper()
    dev = abs(enriched["deviation"])

    # Build umpire line
    ump_name = enriched["umpire_name"]
    ump_adj = enriched["k_adjustment"]
    ump_line = f"🔍 Ump {ump_name}: {ump_adj:+.1f}K adj" if ump_name != "TBD" else ""

    # Build catcher line
    catcher = enriched["catcher_name"]
    framing = enriched["framing_adj"]
    catcher_line = f"🧤 Catcher {catcher}: {framing:+.1f}K framing" if catcher else ""

    # Assemble tweet
    lines = [
        f"{name} Strikeouts Projection:",
        f"📊 Model: {proj}K | Line: O/U {line}K",
    ]
    if ump_line:
        lines.append(ump_line)
    if catcher_line:
        lines.append(catcher_line)
    lines.append(f"{emoji} Edge: {tier} ({dev:.1f} units {lean})")
    lines.append("#MLB #BaselineMLB")

    tweet = "\n".join(lines)

    # Twitter hard limit
    if len(tweet) > 280:
        # Truncate to fit — drop catcher line first, then ump line
        lines_short = [
            f"{name} K Projection:",
            f"📊 {proj}K | Line: O/U {line}K",
            f"{emoji} {tier} ({dev:.1f}u {lean})",
            "#MLB #BaselineMLB",
        ]
        tweet = "\n".join(lines_short)

    return tweet


# ---------------------------------------------------------------------------
# Email / newsletter format
# ---------------------------------------------------------------------------

def format_email_entry(enriched: dict) -> str:
    """
    Format a single projection as an email/newsletter entry (markdown).
    """
    name = enriched["pitcher_name"]
    opp = enriched["opponent"]
    proj = enriched["projected_value"]
    line = enriched["prop_line"]
    tier = enriched["confidence_tier"] or "N/A"
    lean = enriched["lean"] or "N/A"
    dev = enriched["deviation"]

    entry = f"### {name} vs {opp}\n"

    if line is not None:
        entry += f"**Prop:** Strikeouts O/U {line}K\n"
    entry += f"**Model Projection:** {proj}K\n"

    entry += "**Key Adjustments:**\n"
    entry += f"- Baseline K/9: {enriched['baseline_k9']}\n"
    entry += f"- Park Factor: {enriched['park_adjustment']}\n"

    if enriched["umpire_name"] != "TBD":
        entry += f"- Umpire ({enriched['umpire_name']}): {enriched['k_adjustment']:+.1f}K\n"
    if enriched["catcher_name"]:
        entry += f"- Catcher Framing ({enriched['catcher_name']}): {enriched['framing_adj']:+.1f}K\n"

    if dev is not None:
        entry += f"**Confidence:** {tier} | **Edge:** {abs(dev):.1f} units {lean}\n"

    return entry


def format_email(enriched_list: list, game_date: str) -> str:
    """Format all projections as a complete email/newsletter."""
    header = f"## Today's Top Projections — {game_date}\n\n"
    header += "*Every factor visible. Every number explained. That's the Baseline MLB glass-box model.*\n\n"
    header += "---\n\n"

    entries = [format_email_entry(e) for e in enriched_list]
    body = "\n---\n\n".join(entries)

    footer = "\n\n---\n\n"
    footer += "*Projections by Baseline MLB | baselinemlb.com | @baselinemlb*\n"

    return header + body + footer


# ---------------------------------------------------------------------------
# Thread format (for analytical Twitter threads)
# ---------------------------------------------------------------------------

def format_thread(enriched_list: list, game_date: str) -> list:
    """
    Format top projections as a Twitter thread (list of tweets).
    Thread format for higher engagement — first tweet is the hook,
    subsequent tweets are individual projections.
    """
    tweets = []

    # Hook tweet
    count = len(enriched_list)
    high_conf = sum(1 for e in enriched_list if e.get("confidence_tier") == "HIGH")
    hook = (
        f"⚾ Baseline MLB Projections — {game_date}\n\n"
        f"{count} pitcher K projections today"
    )
    if high_conf > 0:
        hook += f", {high_conf} HIGH confidence edges"
    hook += ".\n\nFull glass-box breakdown in thread 🧵\n#MLB #BaselineMLB"
    tweets.append(hook)

    # Individual projection tweets
    for enriched in enriched_list:
        tweet = format_twitter(enriched)
        if tweet:
            tweets.append(tweet)

    return tweets


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run(game_date: str, fmt: str = "all", top_n: int = 10):
    """
    Generate daily content for the given date.
    """
    log.info(f"=== Generating content for {game_date} ===")

    if not SUPABASE_URL or not SUPABASE_KEY:
        log.error("SUPABASE_URL or SUPABASE_SERVICE_KEY not set. Cannot load data.")
        sys.exit(1)

    # Load all data
    projections = load_projections(game_date)
    if not projections:
        log.info("No projections found. Exiting.")
        print(f"No projections available for {game_date}")
        return

    games = load_games(game_date)
    props = load_props(game_date)
    framing = load_umpire_framing(game_date)

    # Enrich projections with context
    enriched = []
    for proj in projections:
        e = enrich_projection(proj, games, props, framing)
        enriched.append(e)

    # Sort by absolute deviation (largest edges first)
    enriched.sort(key=lambda x: abs(x["deviation"]) if x["deviation"] is not None else 0, reverse=True)

    # Apply top-N filter
    top = enriched[:top_n]

    # --- Output ---

    if fmt in ("twitter", "all"):
        print("\n" + "=" * 50)
        print("  TWITTER CONTENT")
        print("=" * 50)
        for i, e in enumerate(top, 1):
            tweet = format_twitter(e)
            if tweet:
                print(f"\n--- Tweet {i} ---")
                print(tweet)
                print(f"({len(tweet)} chars)")

    if fmt in ("thread", "all"):
        print("\n" + "=" * 50)
        print("  TWITTER THREAD")
        print("=" * 50)
        thread = format_thread(top, game_date)
        for i, tweet in enumerate(thread):
            print(f"\n--- Thread {i+1}/{len(thread)} ---")
            print(tweet)
            print(f"({len(tweet)} chars)")

    if fmt in ("email", "all"):
        print("\n" + "=" * 50)
        print("  EMAIL / NEWSLETTER")
        print("=" * 50)
        email = format_email(top, game_date)
        print(email)

    # Export structured JSON for dashboard/frontend
    output_dir = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "dashboard", "data"
    )
    os.makedirs(output_dir, exist_ok=True)

    content_file = os.path.join(output_dir, f"daily_content_{game_date}.json")
    export_data = {
        "game_date": game_date,
        "generated_at": datetime.utcnow().isoformat(),
        "total_projections": len(enriched),
        "top_projections": top,
        "tweets": [format_twitter(e) for e in top if format_twitter(e)],
    }
    with open(content_file, "w") as f:
        json.dump(export_data, f, indent=2, default=str)
    log.info(f"Exported content to {content_file}")

    log.info(f"=== Content generation complete ===")


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Generate daily content from Baseline MLB projections"
    )
    parser.add_argument(
        "--date", type=str, default=None,
        help="Date to generate content for (YYYY-MM-DD). Defaults to today."
    )
    parser.add_argument(
        "--format", type=str, default="all",
        choices=["twitter", "thread", "email", "all"],
        help="Output format (default: all)"
    )
    parser.add_argument(
        "--top", type=int, default=10,
        help="Number of top projections to include (default: 10)"
    )
    args = parser.parse_args()

    game_date = args.date or date.today().isoformat()
    run(game_date, fmt=args.format, top_n=args.top)
