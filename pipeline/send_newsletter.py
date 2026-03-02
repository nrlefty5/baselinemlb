#!/usr/bin/env python3
"""
send_newsletter.py -- Baseline MLB
Daily email newsletter system using Resend API.

Reads today's best bets from Supabase, formats an HTML email,
and sends to all subscribers in the email_subscribers table.

Requires:
  - RESEND_API_KEY env var
  - email_subscribers table in Supabase with: email, subscribed_at, active
  - Run after morning projections pipeline (10:30 AM ET)

Usage:
  python pipeline/send_newsletter.py
  python pipeline/send_newsletter.py --dry-run  # Preview without sending
"""

import json
import logging
import os
from datetime import date

import requests

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("send_newsletter")

SUPABASE_URL = os.environ.get("SUPABASE_URL", "").strip()
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_KEY", "").strip()
RESEND_API_KEY = os.environ.get("RESEND_API_KEY", "").strip()

FROM_EMAIL = "Baseline MLB <newsletter@baselinemlb.com>"
SITE_URL = "https://baselinemlb.vercel.app"

STAT_LABELS = {
    "pitcher_strikeouts": "Strikeouts",
    "batter_total_bases": "Total Bases",
    "batter_hits": "Hits",
    "batter_home_runs": "Home Runs",
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


def fetch_subscribers():
    """Fetch all active email subscribers."""
    try:
        rows = sb_get("email_subscribers", {
            "active": "eq.true",
            "select": "email",
        })
        return [r["email"] for r in rows]
    except Exception as e:
        log.warning(f"Failed to fetch subscribers (table may not exist): {e}")
        return []


def fetch_best_bets(game_date: str):
    """Fetch today's high-confidence projections with edge."""
    projections = sb_get("projections", {
        "game_date": f"eq.{game_date}",
        "confidence": "gte.0.65",
        "select": "mlbam_id,player_name,stat_type,projection,confidence,features",
        "order": "confidence.desc",
        "limit": "50",
    })

    # Fetch props for edge calculation
    props = sb_get("props", {
        "game_date": f"eq.{game_date}",
        "select": "player_name,market_key,line,edge_pct",
    })

    edge_map = {}
    for p in props:
        key = f"{p['player_name']}__{p['market_key']}"
        edge_map[key] = p

    best_bets = []
    for proj in projections:
        market_key = proj["stat_type"]
        edge_key = f"{proj['player_name']}__{market_key}"
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
            features = {}
            try:
                features = json.loads(proj["features"]) if isinstance(proj["features"], str) else (proj["features"] or {})
            except:
                pass

            best_bets.append({
                "player_name": proj["player_name"],
                "stat_type": proj["stat_type"],
                "projection": proj["projection"],
                "confidence": proj["confidence"],
                "line": line,
                "edge": edge,
                "direction": "OVER" if proj["projection"] > line else "UNDER",
                "venue": features.get("venue", ""),
                "opponent": features.get("opponent", ""),
            })

    best_bets.sort(key=lambda x: abs(x["edge"]), reverse=True)
    return best_bets[:10]  # Top 10


def build_email_html(best_bets: list, game_date: str) -> str:
    """Build the HTML email body."""
    date_display = date.fromisoformat(game_date).strftime("%A, %B %d")

    if not best_bets:
        return f"""
        <html>
        <body style="font-family: -apple-system, BlinkMacSystemFont, sans-serif; background: #f8f9fa; padding: 20px;">
            <div style="max-width: 600px; margin: 0 auto; background: white; padding: 30px; border-radius: 8px;">
                <h1 style="color: #1a1a2e;">Baseline MLB — {date_display}</h1>
                <p>No strong plays today. The model confidence is below our threshold across all available markets.</p>
                <p>Check back tomorrow!</p>
                <p><a href="{SITE_URL}/projections">View all projections →</a></p>
            </div>
        </body>
        </html>
        """

    cards = []
    for bet in best_bets:
        stat_label = STAT_LABELS.get(bet["stat_type"], bet["stat_type"])
        edge_color = "#16a34a" if bet["edge"] > 0 else "#dc2626"
        direction_bg = "#dcfce7" if bet["direction"] == "OVER" else "#fee2e2"
        direction_color = "#15803d" if bet["direction"] == "OVER" else "#b91c1c"

        card = f"""
        <div style="border: 1px solid #e5e7eb; border-radius: 8px; padding: 20px; margin-bottom: 16px;">
            <div style="display: flex; justify-content: space-between; align-items: center;">
                <h3 style="margin: 0; color: #1a1a2e; font-size: 18px;">{bet['player_name']}</h3>
                <span style="background: {direction_bg}; color: {direction_color}; padding: 4px 12px;
                    border-radius: 20px; font-weight: bold; font-size: 14px;">
                    {bet['direction']} {bet.get('line', '?')} {stat_label}
                </span>
            </div>
            <div style="margin-top: 12px; display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px;">
                <div>
                    <div style="font-size: 12px; color: #6b7280; text-transform: uppercase;">Projection</div>
                    <div style="font-size: 20px; font-weight: bold; color: #1a1a2e;">{bet['projection']:.1f}</div>
                </div>
                <div>
                    <div style="font-size: 12px; color: #6b7280; text-transform: uppercase;">Edge</div>
                    <div style="font-size: 20px; font-weight: bold; color: {edge_color};">{'+' if bet['edge'] > 0 else ''}{bet['edge']:.1f}%</div>
                </div>
                <div>
                    <div style="font-size: 12px; color: #6b7280; text-transform: uppercase;">Confidence</div>
                    <div style="font-size: 20px; font-weight: bold; color: #1a1a2e;">{round(bet['confidence'] * 100)}%</div>
                </div>
            </div>
            {f'<p style="margin-top: 12px; font-size: 13px; color: #6b7280;">{bet["venue"]} vs {bet["opponent"]}</p>' if bet.get('venue') else ''}
        </div>
        """
        cards.append(card)

    cards_html = "\n".join(cards)

    return f"""
    <!DOCTYPE html>
    <html>
    <head><meta charset="UTF-8"></head>
    <body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: #f8f9fa; padding: 20px; margin: 0;">
        <div style="max-width: 600px; margin: 0 auto;">
            <!-- Header -->
            <div style="background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%); padding: 30px; border-radius: 12px 12px 0 0; text-align: center;">
                <h1 style="margin: 0; color: white; font-size: 28px; font-weight: 800;">Baseline MLB</h1>
                <p style="margin: 8px 0 0; color: #94a3b8; font-size: 16px;">{date_display} Best Bets</p>
            </div>

            <!-- Content -->
            <div style="background: white; padding: 30px; border-radius: 0 0 12px 12px; box-shadow: 0 4px 6px rgba(0,0,0,0.1);">
                <p style="color: #374151; font-size: 16px; margin-top: 0;">
                    Here are today's top <strong>{len(best_bets)} plays</strong> from our glass-box model.
                    All projections are generated transparently — every factor logged, every result graded.
                </p>

                {cards_html}

                <!-- CTA -->
                <div style="margin-top: 24px; padding: 20px; background: #f0f9ff; border-radius: 8px; text-align: center;">
                    <p style="margin: 0 0 12px; color: #374151;">View full analysis and historical accuracy:</p>
                    <a href="{SITE_URL}/best-bets" style="display: inline-block; background: #2563eb; color: white; padding: 12px 24px;
                        border-radius: 6px; text-decoration: none; font-weight: bold; margin: 4px;">
                        📊 Today's Best Bets
                    </a>
                    <a href="{SITE_URL}/accuracy" style="display: inline-block; background: #16a34a; color: white; padding: 12px 24px;
                        border-radius: 6px; text-decoration: none; font-weight: bold; margin: 4px;">
                        📈 Model Accuracy
                    </a>
                </div>
            </div>

            <!-- Footer -->
            <div style="padding: 20px; text-align: center; color: #9ca3af; font-size: 12px;">
                <p>Baseline MLB &bull; Glass-box player prop model</p>
                <p>Questions? Reply to this email.</p>
                <p><a href="{SITE_URL}/unsubscribe" style="color: #9ca3af;">Unsubscribe</a></p>
            </div>
        </div>
    </body>
    </html>
    """


def send_email(to_email: str, subject: str, html_body: str) -> bool:
    """Send a single email via Resend API."""
    if not RESEND_API_KEY:
        log.warning("RESEND_API_KEY not set. Skipping email send.")
        return False

    r = requests.post(
        "https://api.resend.com/emails",
        headers={
            "Authorization": f"Bearer {RESEND_API_KEY}",
            "Content-Type": "application/json",
        },
        json={
            "from": FROM_EMAIL,
            "to": [to_email],
            "subject": subject,
            "html": html_body,
        },
    )
    if r.status_code == 200:
        return True
    log.warning(f"  Resend error {r.status_code}: {r.text[:200]}")
    return False


def main(dry_run=False):
    game_date = date.today().isoformat()
    date_display = date.today().strftime("%b %d")
    log.info(f"=== Baseline MLB Newsletter for {game_date} ===")

    subscribers = fetch_subscribers()
    log.info(f"Found {len(subscribers)} active subscribers")

    if not subscribers and not dry_run:
        log.info("No subscribers. Exiting.")
        return

    best_bets = fetch_best_bets(game_date)
    log.info(f"Found {len(best_bets)} best bets to include")

    html_body = build_email_html(best_bets, game_date)
    subject = f"Baseline MLB Best Bets — {date_display} ({len(best_bets)} plays)"

    if dry_run:
        log.info("DRY RUN - Email preview:")
        print(f"Subject: {subject}")
        print(f"Subscribers: {subscribers[:3]}... ({len(subscribers)} total)")
        print(f"HTML length: {len(html_body)} chars")
        print("\n--- HTML Preview (first 500 chars) ---")
        print(html_body[:500])
        return

    sent = 0
    failed = 0
    for email in subscribers:
        if send_email(email, subject, html_body):
            sent += 1
        else:
            failed += 1

    log.info(f"Newsletter sent: {sent} success, {failed} failed")
    log.info("=== Done ===")


if __name__ == "__main__":
    import sys
    dry_run = "--dry-run" in sys.argv
    main(dry_run=dry_run)
