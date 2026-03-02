#!/usr/bin/env python3
"""
post_to_twitter.py -- Baseline MLB
Auto-publish daily best bets to X/Twitter.

Reads today's top plays from Supabase and posts a formatted thread.
Uses the Twitter API v2 (tweepy) to post.

Requires:
  - TWITTER_API_KEY, TWITTER_API_SECRET, TWITTER_ACCESS_TOKEN, TWITTER_ACCESS_SECRET env vars
  - Run after morning projections pipeline (10:30 AM ET)

Usage:
  python pipeline/post_to_twitter.py
  python pipeline/post_to_twitter.py --dry-run  # Preview without posting
"""

import logging
import os
from datetime import date

import requests

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("post_to_twitter")

SUPABASE_URL = os.environ.get("SUPABASE_URL", "").strip()
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_KEY", "").strip()

# Twitter API v2 credentials
TWITTER_API_KEY = os.environ.get("TWITTER_API_KEY", "").strip()
TWITTER_API_SECRET = os.environ.get("TWITTER_API_SECRET", "").strip()
TWITTER_ACCESS_TOKEN = os.environ.get("TWITTER_ACCESS_TOKEN", "").strip()
TWITTER_ACCESS_SECRET = os.environ.get("TWITTER_ACCESS_SECRET", "").strip()

SITE_URL = "https://baselinemlb.vercel.app"

STAT_EMOJI = {
    "pitcher_strikeouts": "🔥",
    "batter_total_bases": "💣",
    "batter_hits": "🎯",
    "batter_home_runs": "🏠",
}

STAT_SHORT = {
    "pitcher_strikeouts": "Ks",
    "batter_total_bases": "TB",
    "batter_hits": "Hits",
    "batter_home_runs": "HRs",
}


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


def fetch_top_plays(game_date: str, limit=5):
    """Fetch today's top plays for Twitter."""
    projections = sb_get("projections", {
        "game_date": f"eq.{game_date}",
        "confidence": "gte.0.70",
        "select": "mlbam_id,player_name,stat_type,projection,confidence,features",
        "order": "confidence.desc",
        "limit": "30",
    })

    props = sb_get("props", {
        "game_date": f"eq.{game_date}",
        "select": "player_name,market_key,line,edge_pct",
    })

    edge_map = {}
    for p in props:
        key = f"{p['player_name']}__{p['market_key']}"
        edge_map[key] = p

    plays = []
    for proj in projections:
        edge_key = f"{proj['player_name']}__{proj['stat_type']}"
        match = edge_map.get(edge_key)

        edge = None
        line = None
        if match:
            line = match.get("line")
            edge = match.get("edge_pct")
            if edge is None and line and proj["projection"]:
                diff = proj["projection"] - line
                edge = (diff / line) * 100 if line > 0 else None

        if edge and abs(edge) >= 5:
            plays.append({
                "player_name": proj["player_name"],
                "stat_type": proj["stat_type"],
                "projection": proj["projection"],
                "confidence": proj["confidence"],
                "line": line,
                "edge": edge,
                "direction": "OVER" if proj["projection"] > (line or 0) else "UNDER",
            })

    plays.sort(key=lambda x: abs(x.get("edge", 0)), reverse=True)
    return plays[:limit]


def build_tweets(plays: list, game_date: str) -> list:
    """Build a thread of tweets."""
    date_display = date.fromisoformat(game_date).strftime("%b %d")
    tweets = []

    if not plays:
        tweets.append(f"📊 Baseline MLB - {date_display}\n\nNo strong plays today. Model confidence too low across the board.\n\nFull projections: {SITE_URL}/projections")
        return tweets

    # Opening tweet
    header = f"📊 Baseline MLB Best Bets - {date_display}\n\n{len(plays)} plays with 5%+ edge:\n\n"
    lines = []
    for p in plays[:3]:
        emoji = STAT_EMOJI.get(p["stat_type"], "📈")
        stat = STAT_SHORT.get(p["stat_type"], p["stat_type"])
        lines.append(
            f"{emoji} {p['player_name']} {p['direction']} {p.get('line', '?')} {stat} "
            f"(Proj: {p['projection']:.1f}, Edge: {'+' if p['edge'] > 0 else ''}{p['edge']:.1f}%)"
        )
    header += "\n".join(lines)
    header += "\n\n🧵 Thread below with full analysis..."
    tweets.append(header)

    # Individual play tweets
    for i, p in enumerate(plays):
        emoji = STAT_EMOJI.get(p["stat_type"], "📈")
        stat = STAT_SHORT.get(p["stat_type"], p["stat_type"])
        conf_pct = round(p["confidence"] * 100)

        tweet = (
            f"{emoji} Play {i+1}: {p['player_name']}\n\n"
            f"Pick: {p['direction']} {p.get('line', '?')} {stat}\n"
            f"Projection: {p['projection']:.1f}\n"
            f"Edge: {'+' if p['edge'] > 0 else ''}{p['edge']:.1f}%\n"
            f"Confidence: {conf_pct}%\n\n"
            f"Full breakdown: {SITE_URL}/players/{p.get('mlbam_id', '')}"
        )
        tweets.append(tweet)

    # Closing tweet
    tweets.append(
        f"All projections generated by our open glass-box model.\n\n"
        f"Every factor logged. Every result graded publicly.\n\n"
        f"📊 Full analysis: {SITE_URL}/best-bets\n"
        f"📈 Accuracy: {SITE_URL}/accuracy\n\n"
        f"#MLB #BaseballBetting #PlayerProps"
    )

    return tweets


def post_tweet(text: str, reply_to_id: str = None) -> str:
    """Post a tweet using Twitter API v2 via OAuth 1.0a."""
    if not all([TWITTER_API_KEY, TWITTER_API_SECRET, TWITTER_ACCESS_TOKEN, TWITTER_ACCESS_SECRET]):
        log.warning("Twitter credentials not configured. Skipping post.")
        return None

    try:
        import tweepy
        client = tweepy.Client(
            consumer_key=TWITTER_API_KEY,
            consumer_secret=TWITTER_API_SECRET,
            access_token=TWITTER_ACCESS_TOKEN,
            access_token_secret=TWITTER_ACCESS_SECRET,
        )

        kwargs = {"text": text}
        if reply_to_id:
            kwargs["in_reply_to_tweet_id"] = reply_to_id

        response = client.create_tweet(**kwargs)
        tweet_id = response.data["id"]
        log.info(f"  Posted tweet {tweet_id}")
        return tweet_id

    except ImportError:
        log.warning("tweepy not installed. Run: pip install tweepy")
        return None
    except Exception as e:
        log.warning(f"  Failed to post tweet: {e}")
        return None


def main(dry_run=False):
    game_date = date.today().isoformat()
    log.info(f"=== Baseline MLB Twitter Post for {game_date} ===")

    plays = fetch_top_plays(game_date)
    log.info(f"Found {len(plays)} plays for Twitter")

    tweets = build_tweets(plays, game_date)
    log.info(f"Built {len(tweets)} tweets")

    if dry_run:
        log.info("DRY RUN - Tweet preview:")
        for i, tweet in enumerate(tweets):
            print(f"\n--- Tweet {i+1} ({len(tweet)} chars) ---")
            print(tweet)
        return

    last_id = None
    for i, tweet in enumerate(tweets):
        tweet_id = post_tweet(tweet, reply_to_id=last_id)
        if tweet_id:
            last_id = tweet_id
        else:
            log.warning(f"  Failed at tweet {i+1}, stopping thread.")
            break

    log.info("=== Done ===")


if __name__ == "__main__":
    import sys
    dry_run = "--dry-run" in sys.argv
    main(dry_run=dry_run)
