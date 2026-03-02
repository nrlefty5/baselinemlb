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

import os
import json
import logging
import requests
from datetime import date
from typing import Optional

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
        <body style="font-family: -apple-system, BlinkMacSystemFont, sans-serif; background: #0a0e1a; color: #e2e8f0; padding: 20px;">
        <div style="max-width: 600px; margin: 0 auto;">
            <h1 style="color: #60a5fa;">Baseline MLB</h1>
            <p>No strong plays found for {date_display}. Check back tomorrow.</p>
            <p style="color: #64748b; font-size: 12px;">
                <a href="{SITE_URL}" style="color: #60a5fa;">View full projections</a>
            </p>
        </div>
        </body>
        </html>
        """

    rows_html = ""
    for bet in best_bets:
        stat_label = STAT_LABELS.get(bet["stat_type"], bet["stat_type"])
        edge_color = "#4ade80" if bet["edge"] > 0 else "#f87171"
        dir_color = "#4ade80" if bet["direction"] == "OVER" else "#f87171"

        rows_html += f"""
        <tr>
            <td style="padding: 12px; border-bottom: 1px solid #1e293b;">
                <strong style="color: white;">{bet['player_name']}</strong>
                <br><span style="color: #94a3b8; font-size: 12px;">{stat_label} &bull; {bet.get('venue', '')}</span>
            </td>
            <td style="padding: 12px; border-bottom: 1px solid #1e293b; text-align: center;">
                <strong style="color: {dir_color};">{bet['direction']}</strong>
            </td>
            <td style="padding: 12px; border-bottom: 1px solid #1e293b; text-align: center; color: white;">
                {bet['projection']:.1f}
            </td>
            <td style="padding: 12px; border-bottom: 1px solid #1e293b; text-align: center; color: #94a3b8;">
                {bet.get('line', '--')}
            </td>
            <td style="padding: 12px; border-bottom: 1px solid #1e293b; text-align: center;">
                <strong style="color: {edge_color};">{'+' if bet['edge'] > 0 else ''}{bet['edge']:.1f}%</strong>
            </td>
            <td style="padding: 12px; border-bottom: 1px solid #1e293b; text-align: center; color: #60a5fa;">
                {round(bet['confidence'] * 100)}%
            </td>
        </tr>
        """

    return f"""
    <html>
    <body style="font-family: -apple-system, BlinkMacSystemFont, sans-serif; background: #0a0e1a; color: #e2e8f0; padding: 20px;">
    <div style="max-width: 700px; margin: 0 auto;">
        <div style="text-align: center; margin-bottom: 24px;">
            <h1 style="color: #60a5fa; margin: 0;">BASELINE <span style="color: white;">MLB</span></h1>
            <p style="color: #94a3b8; margin: 4px 0;">Daily Best Bets &bull; {date_display}</p>
        </div>

        <table style="width: 100%; border-collapse: collapse; background: #1e293b; border-radius: 8px; overflow: hidden;">
        <thead>
            <tr style="background: #0f172a;">
                <th style="padding: 8px 12px; text-align: left; color: #94a3b8; font-size: 11px; text-transform: uppercase;">Player</th>
                <th style="padding: 8px 12px; text-align: center; color: #94a3b8; font-size: 11px; text-transform: uppercase;">Pick</th>
                <th style="padding: 8px 12px; text-align: center; color: #94a3b8; font-size: 11px; text-transform: uppercase;">Proj</th>
                <th style="padding: 8px 12px; text-align: center; color: #94a3b8; font-size: 11px; text-transform: uppercase;">Line</th>
                <th style="padding: 8px 12px; text-align: center; color: #94a3b8; font-size: 11px; text-transform: uppercase;">Edge</th>
                <th style="padding: 8px 12px; text-align: center; color: #94a3b8; font-size: 11px; text-transform: uppercase;">Conf</th>
            </tr>
        </thead>
        <tbody>
            {rows_html}
        </tbody>
        </table>

        <div style="text-align: center; margin-top: 24px;">
            <a href="{SITE_URL}/best-bets" style="display: inline-block; padding: 10px 24px; background: #2563eb; color: white; text-decoration: none; border-radius: 6px; font-weight: 600;">
                View Full Analysis
            </a>
        </div>

        <p style="color: #475569; font-size: 11px; text-align: center; margin-top: 24px;">
            Baseline MLB &bull; Glass-box analytics &bull; For informational use only
            <br>
            <a href="{SITE_URL}/unsubscribe" style="color: #475569;">Unsubscribe</a>
        </p>
    </div>
    </body>
    </html>
    """


def send_email(to_email: str, subject: str, html_body: str) -> bool:
    """Send an email via Resend API."""
    if not RESEND_API_KEY:
        log.warning("RESEND_API_KEY not set. Skipping email send.")
        return False

    try:
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
            timeout=15,
        )
        if r.ok:
            log.info(f"  Sent email to {to_email}")
            return True
        else:
            log.warning(f"  Failed to send to {to_email}: {r.status_code} {r.text[:200]}")
            return False
    except Exception as e:
        log.warning(f"  Email send error for {to_email}: {e}")
        return False


def main(dry_run=False):
    game_date = date.today().isoformat()
    log.info(f"=== Baseline MLB Newsletter for {game_date} ===")

    subscribers = fetch_subscribers()
    log.info(f"Found {len(subscribers)} active subscribers")

    if not subscribers:
        log.info("No subscribers. Exiting.")
        return

    best_bets = fetch_best_bets(game_date)
    log.info(f"Found {len(best_bets)} best bets for today")

    subject = f"Baseline MLB Best Bets - {date.today().strftime('%B %d')}"
    if best_bets:
        top_bet = best_bets[0]
        subject = f"{top_bet['player_name']} {top_bet['direction']} + {len(best_bets)-1} more | Baseline MLB"

    html_body = build_email_html(best_bets, game_date)

    if dry_run:
        log.info("DRY RUN - Preview email:")
        print(html_body[:500])
        log.info(f"Would send to {len(subscribers)} subscribers")
        return

    sent = 0
    failed = 0
    for email in subscribers:
        if send_email(email, subject, html_body):
            sent += 1
        else:
            failed += 1

    log.info(f"=== Done. Sent: {sent}, Failed: {failed} ===")


if __name__ == "__main__":
    import sys
    dry_run = "--dry-run" in sys.argv
    main(dry_run=dry_run)
