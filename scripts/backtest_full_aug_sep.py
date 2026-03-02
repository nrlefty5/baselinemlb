#!/usr/bin/env python3
"""
backtest_full_aug_sep.py — BaselineMLB
======================================
Expanded backtesting engine covering ALL Aug–Sep 2025 MLB regular-season games.

For each game day this script:
  1. Fetches actual box-score stats from the MLB Stats API.
  2. Generates Monte Carlo-style simulated predictions for 6 prop types:
     strikeouts (K), hits (H), total bases (TB), home runs (HR),
     walks (BB), and RBIs.
  3. Compares predictions against actuals.
  4. Computes per-prop-type calibration metrics:
     - Brier scores
     - ROI by edge bucket
     - Accuracy (hit rate) by prop type
     - Tier A/B/C ROI breakdowns
  5. Writes per-day rows into the Supabase `backtest_results` table.

Usage:
  python scripts/backtest_full_aug_sep.py
  python scripts/backtest_full_aug_sep.py --start 2025-08-01 --end 2025-09-30
  python scripts/backtest_full_aug_sep.py --upload --verbose
  python scripts/backtest_full_aug_sep.py --dry-run
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import os
import sys
import time
from collections import defaultdict
from datetime import date, datetime, timedelta
from typing import Any

import numpy as np
import requests

# ---------------------------------------------------------------------------
# Path setup
# ---------------------------------------------------------------------------
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
MLB_API_BASE = "https://statsapi.mlb.com/api/v1"
API_SLEEP = 0.5  # seconds between API calls
N_SIMS = 2000  # simulations per player per game

SUPABASE_URL = os.environ.get("SUPABASE_URL", "").strip()
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_KEY", "").strip()

# All prop types we backtest
PROP_TYPES = ["K", "H", "TB", "HR", "BB", "RBI"]

# Stat field mapping: prop_type -> boxscore batting field
BATTER_STAT_MAP = {
    "H": "hits",
    "HR": "homeRuns",
    "BB": "baseOnBalls",
    "RBI": "rbi",
}

# Standard prop lines by type (typical sportsbook lines)
DEFAULT_LINES = {
    "K": [4.5, 5.5, 6.5, 7.5],
    "H": [0.5, 1.5],
    "TB": [0.5, 1.5, 2.5],
    "HR": [0.5],
    "BB": [0.5, 1.5],
    "RBI": [0.5, 1.5],
}

# Edge buckets for ROI analysis
EDGE_BUCKETS = [
    (0.00, 0.03, "0-3%"),
    (0.03, 0.05, "3-5%"),
    (0.05, 0.10, "5-10%"),
    (0.10, 0.15, "10-15%"),
    (0.15, 0.20, "15-20%"),
    (0.20, 1.00, "20%+"),
]

# Expanded park K factors — all 30 MLB stadiums
PARK_K_FACTORS = {
    "Chase Field": 1, "Truist Park": 2, "Camden Yards": 0,
    "Fenway Park": -1, "Wrigley Field": -3, "Guaranteed Rate Field": 0,
    "Great American Ball Park": -2, "Progressive Field": 1,
    "Coors Field": -8, "Comerica Park": 2, "Minute Maid Park": 2,
    "Kauffman Stadium": 0, "Angel Stadium": 0, "Dodger Stadium": 4,
    "loanDepot park": 1, "American Family Field": -1,
    "Target Field": 0, "Citi Field": 1, "Yankee Stadium": 3,
    "Oakland Coliseum": 2, "Citizens Bank Park": -2, "PNC Park": 1,
    "Petco Park": 4, "Oracle Park": 5, "T-Mobile Park": 3,
    "Busch Stadium": 1, "Tropicana Field": 1, "Globe Life Field": 2,
    "Rogers Centre": 0, "Nationals Park": 1,
}

# Park TB/HR factors
PARK_HR_FACTORS = {
    "Chase Field": 3, "Truist Park": 0, "Camden Yards": 2,
    "Fenway Park": 2, "Wrigley Field": 3, "Guaranteed Rate Field": 1,
    "Great American Ball Park": 5, "Progressive Field": 0,
    "Coors Field": 10, "Comerica Park": -2, "Minute Maid Park": 3,
    "Kauffman Stadium": 0, "Angel Stadium": 1, "Dodger Stadium": -1,
    "loanDepot park": -1, "American Family Field": 2,
    "Target Field": 1, "Citi Field": -1, "Yankee Stadium": 5,
    "Oakland Coliseum": -2, "Citizens Bank Park": 3, "PNC Park": -1,
    "Petco Park": -3, "Oracle Park": -4, "T-Mobile Park": 0,
    "Busch Stadium": 0, "Tropicana Field": 0, "Globe Life Field": 1,
    "Rogers Centre": 2, "Nationals Park": 1,
}


# ===========================================================================
# MLB Stats API helpers
# ===========================================================================

def _mlb_get(url: str, params: dict | None = None, timeout: int = 20) -> dict:
    """GET from MLB Stats API with retry."""
    for attempt in range(3):
        try:
            resp = requests.get(url, params=params, timeout=timeout)
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as exc:
            if attempt < 2:
                time.sleep(2 ** attempt)
                continue
            raise exc
    return {}


def fetch_schedule(start_date: str, end_date: str) -> list[dict]:
    """Fetch completed regular-season games for a date range."""
    params = {
        "sportId": 1,
        "startDate": start_date,
        "endDate": end_date,
        "gameType": "R",
        "hydrate": "linescore,venue",
    }
    data = _mlb_get(f"{MLB_API_BASE}/schedule", params=params)
    games = []
    for date_block in data.get("dates", []):
        game_date = date_block["date"]
        for g in date_block.get("games", []):
            status = g.get("status", {}).get("abstractGameState", "")
            if status != "Final":
                continue
            venue = g.get("venue", {}).get("name", "Unknown")
            games.append({
                "game_pk": g["gamePk"],
                "game_date": game_date,
                "home_team": g["teams"]["home"]["team"]["name"],
                "away_team": g["teams"]["away"]["team"]["name"],
                "venue": venue,
            })
    return games


def fetch_boxscore(game_pk: int) -> dict:
    """Fetch boxscore for a single game."""
    return _mlb_get(f"{MLB_API_BASE}/game/{game_pk}/boxscore")


def parse_player_actuals(boxscore: dict) -> dict[int, dict]:
    """
    Extract per-player actual stats from boxscore.
    Returns {player_id: {name, team, side, stats...}}.
    """
    actuals = {}
    teams = boxscore.get("teams", {})

    for side in ("home", "away"):
        team_data = teams.get(side, {})
        team_name = team_data.get("team", {}).get("name", "Unknown")
        players = team_data.get("players", {})

        # Batters
        for key, pdata in players.items():
            batting = pdata.get("stats", {}).get("batting", {})
            if not batting:
                continue
            pid = pdata["person"]["id"]
            name = pdata["person"].get("fullName", f"Player{pid}")
            h = int(batting.get("hits", 0))
            doubles = int(batting.get("doubles", 0))
            triples = int(batting.get("triples", 0))
            hr = int(batting.get("homeRuns", 0))
            tb = h + doubles + 2 * triples + 3 * hr
            actuals[pid] = {
                "name": name,
                "team": team_name,
                "side": side,
                "H": float(h),
                "TB": float(tb),
                "HR": float(hr),
                "BB": float(batting.get("baseOnBalls", 0)),
                "RBI": float(batting.get("rbi", 0)),
                "K_batter": float(batting.get("strikeOuts", 0)),
                "AB": float(batting.get("atBats", 0)),
                "PA": float(batting.get("plateAppearances",
                            batting.get("atBats", 0))),
            }

        # Starting pitcher Ks
        pitchers_list = team_data.get("pitchers", [])
        if pitchers_list:
            starter_id = pitchers_list[0]
            pkey = f"ID{starter_id}"
            pdata = players.get(pkey, {})
            pitching = pdata.get("stats", {}).get("pitching", {})
            if pitching:
                ip_str = str(pitching.get("inningsPitched", "0.0"))
                parts = ip_str.split(".")
                ip_float = int(parts[0]) + (int(parts[1]) / 3 if len(parts) > 1 and parts[1] else 0)
                name = pdata["person"].get("fullName", f"Pitcher{starter_id}")
                # Store pitcher K data under a special key
                actuals[f"pitcher_{starter_id}_{side}"] = {
                    "name": name,
                    "team": team_name,
                    "side": side,
                    "pitcher_id": starter_id,
                    "K": float(pitching.get("strikeOuts", 0)),
                    "IP": round(ip_float, 2),
                    "pitches": int(pitching.get("numberOfPitches", 0)),
                    "is_pitcher": True,
                }
    return actuals


# ===========================================================================
# Pitcher K/9 cache
# ===========================================================================
_k9_cache: dict[int, float] = {}


def fetch_pitcher_career_k9(pitcher_id: int) -> float:
    """Fetch career K/9 for a pitcher. Cached."""
    if pitcher_id in _k9_cache:
        return _k9_cache[pitcher_id]
    try:
        url = f"{MLB_API_BASE}/people/{pitcher_id}/stats"
        data = _mlb_get(url, params={"stats": "career", "group": "pitching", "sportId": 1})
        splits = data.get("stats", [{}])[0].get("splits", [])
        if splits:
            stat = splits[0].get("stat", {})
            k = float(stat.get("strikeOuts", 0))
            ip_str = str(stat.get("inningsPitched", "0.0"))
            parts = ip_str.split(".")
            ip = int(parts[0]) + (int(parts[1]) / 3 if len(parts) > 1 and parts[1] else 0)
            if ip > 0:
                k9 = round((k / ip) * 9, 2)
                _k9_cache[pitcher_id] = k9
                return k9
    except Exception:
        pass
    _k9_cache[pitcher_id] = 7.5
    return 7.5


# ===========================================================================
# Monte Carlo simulation — lightweight but realistic
# ===========================================================================

def simulate_pitcher_ks(
    pitcher_id: int,
    venue: str,
    n_sims: int = N_SIMS,
) -> np.ndarray:
    """Simulate pitcher strikeout totals using K/9-based model."""
    k9 = fetch_pitcher_career_k9(pitcher_id)
    park_adj = PARK_K_FACTORS.get(venue, 0) / 100
    adjusted_k9 = k9 * (1 + park_adj)

    rng = np.random.default_rng()
    # Simulate IP: Normal(5.5, 1.0), clipped to [1, 9]
    ip_draws = np.clip(rng.normal(5.5, 1.0, n_sims), 1.0, 9.0)
    # K per inning from adjusted K/9
    k_per_inning = adjusted_k9 / 9.0
    # For each sim, K ~ Poisson(k_per_inning * IP)
    lam = k_per_inning * ip_draws
    k_draws = rng.poisson(np.maximum(lam, 0.1))
    return k_draws.astype(float)


def simulate_batter_stat(
    stat_type: str,
    pa: float,
    venue: str,
    n_sims: int = N_SIMS,
) -> np.ndarray:
    """
    Simulate a batter stat using PA-level Poisson/Binomial model.

    For H, TB, HR, BB, RBI — estimate per-PA rates from MLB averages
    and adjust for park factors.
    """
    rng = np.random.default_rng()
    pa_val = max(pa, 3.0)  # minimum 3 PA

    # League-average per-PA rates (2025 approximate)
    base_rates = {
        "H": 0.245,   # ~.245 BA
        "TB": 0.38,    # ~1.5 TB per game / ~4 PA
        "HR": 0.032,   # ~3.2% of PA
        "BB": 0.085,   # ~8.5% walk rate
        "RBI": 0.11,   # ~0.44 RBI per game / ~4 PA
    }

    rate = base_rates.get(stat_type, 0.1)

    # Park adjustments for TB and HR
    if stat_type in ("HR", "TB"):
        park_pct = PARK_HR_FACTORS.get(venue, 0) / 100
        rate *= (1 + park_pct)

    # Simulate PA count with slight variance
    pa_draws = np.clip(rng.normal(pa_val, 0.5, n_sims), 1, 7).astype(int)

    if stat_type == "HR":
        # Binomial — either you hit one or you don't
        samples = rng.binomial(pa_draws, min(rate, 0.15))
    elif stat_type == "TB":
        # TB has higher variance — use Poisson on expected TB
        lam = rate * pa_draws
        samples = rng.poisson(np.maximum(lam, 0.1))
    else:
        # H, BB, RBI — Poisson approximation
        lam = rate * pa_draws
        samples = rng.poisson(np.maximum(lam, 0.1))

    return samples.astype(float)


# ===========================================================================
# Evaluation metrics
# ===========================================================================

def brier_score(probs: list[float], outcomes: list[int]) -> float:
    """Brier score: mean squared error of probability forecasts."""
    if not probs:
        return float("nan")
    return float(np.mean((np.array(probs) - np.array(outcomes)) ** 2))


def compute_calibration(
    probs: list[float],
    outcomes: list[int],
    n_buckets: int = 10,
) -> list[dict]:
    """Calibration curve: predicted P vs actual hit rate by bucket."""
    p = np.array(probs)
    o = np.array(outcomes)
    edges = np.linspace(0, 1, n_buckets + 1)
    cal = []
    for lo, hi in zip(edges[:-1], edges[1:]):
        mask = (p >= lo) & (p < hi)
        if mask.sum() == 0:
            continue
        cal.append({
            "bucket_low": round(float(lo), 2),
            "bucket_high": round(float(hi), 2),
            "mean_pred": round(float(p[mask].mean()), 4),
            "actual_rate": round(float(o[mask].mean()), 4),
            "count": int(mask.sum()),
        })
    return cal


def classify_edge_bucket(edge: float) -> str:
    """Classify an edge into a bucket label."""
    for lo, hi, label in EDGE_BUCKETS:
        if lo <= abs(edge) < hi:
            return label
    return "20%+"


def confidence_tier(edge: float) -> str:
    """Classify edge into confidence tier A/B/C."""
    ae = abs(edge)
    if ae >= 0.10:
        return "A"
    elif ae >= 0.05:
        return "B"
    else:
        return "C"


# ===========================================================================
# Core backtest for a single game
# ===========================================================================

def backtest_game(
    game_info: dict,
    n_sims: int = N_SIMS,
) -> list[dict]:
    """
    Run full backtest for one game across all prop types.
    Returns a list of prediction dicts, one per (player, prop_type, line).
    """
    game_pk = game_info["game_pk"]
    game_date = game_info["game_date"]
    venue = game_info["venue"]

    boxscore = fetch_boxscore(game_pk)
    if not boxscore:
        return []

    actuals = parse_player_actuals(boxscore)
    predictions = []

    # --- Pitcher K predictions ---
    for key, pdata in actuals.items():
        if not isinstance(key, str) or not key.startswith("pitcher_"):
            continue
        if not pdata.get("is_pitcher"):
            continue

        pitcher_id = pdata["pitcher_id"]
        actual_k = pdata["K"]
        samples = simulate_pitcher_ks(pitcher_id, venue, n_sims)
        sim_mean = float(np.mean(samples))

        for line in DEFAULT_LINES["K"]:
            p_over = float(np.mean(samples > line))
            p_under = 1.0 - p_over
            actual_over = int(actual_k > line)
            actual_push = int(actual_k == line)
            edge = p_over - 0.5  # edge over implied 50%

            predictions.append({
                "game_pk": game_pk,
                "game_date": game_date,
                "player_name": pdata["name"],
                "player_id": pitcher_id,
                "team": pdata["team"],
                "prop_type": "K",
                "line": line,
                "sim_mean": round(sim_mean, 2),
                "p_over": round(p_over, 4),
                "p_under": round(p_under, 4),
                "actual_value": actual_k,
                "actual_over": actual_over,
                "actual_push": actual_push,
                "edge": round(edge, 4),
                "edge_bucket": classify_edge_bucket(edge),
                "tier": confidence_tier(edge),
                "venue": venue,
            })

    # --- Batter prop predictions ---
    for key, pdata in actuals.items():
        if isinstance(key, str) and key.startswith("pitcher_"):
            continue
        if not isinstance(key, int):
            continue
        # Skip batters with very few PA (pinch hitters, etc.)
        pa = pdata.get("PA", pdata.get("AB", 0))
        if pa < 2:
            continue

        for prop_type in ["H", "TB", "HR", "BB", "RBI"]:
            actual_val = pdata.get(prop_type)
            if actual_val is None:
                continue

            samples = simulate_batter_stat(prop_type, pa, venue, n_sims)
            sim_mean = float(np.mean(samples))

            for line in DEFAULT_LINES.get(prop_type, [0.5]):
                p_over = float(np.mean(samples > line))
                p_under = 1.0 - p_over
                actual_over = int(actual_val > line)
                actual_push = int(actual_val == line)
                edge = p_over - 0.5

                predictions.append({
                    "game_pk": game_pk,
                    "game_date": game_date,
                    "player_name": pdata["name"],
                    "player_id": key,
                    "team": pdata["team"],
                    "prop_type": prop_type,
                    "line": line,
                    "sim_mean": round(sim_mean, 2),
                    "p_over": round(p_over, 4),
                    "p_under": round(p_under, 4),
                    "actual_value": actual_val,
                    "actual_over": actual_over,
                    "actual_push": actual_push,
                    "edge": round(edge, 4),
                    "edge_bucket": classify_edge_bucket(edge),
                    "tier": confidence_tier(edge),
                    "venue": venue,
                })

    return predictions


# ===========================================================================
# Aggregate metrics per prop type and per day
# ===========================================================================

def aggregate_by_prop_type(
    all_preds: list[dict],
) -> dict[str, dict]:
    """
    Compute aggregate metrics for each prop type.
    Returns {prop_type: {metrics...}}.
    """
    by_type: dict[str, list[dict]] = defaultdict(list)
    for p in all_preds:
        by_type[p["prop_type"]].append(p)

    results = {}
    for prop_type, preds in by_type.items():
        # Filter out pushes for accuracy
        decided = [p for p in preds if p["actual_push"] == 0]
        all_probs = [p["p_over"] for p in preds]
        all_outcomes = [p["actual_over"] for p in preds]

        correct = sum(
            1 for p in decided
            if (p["p_over"] > 0.5 and p["actual_over"] == 1) or
               (p["p_over"] <= 0.5 and p["actual_over"] == 0)
        )
        total_decided = len(decided)
        accuracy = (correct / total_decided * 100) if total_decided > 0 else 0.0

        # Brier score
        bs = brier_score(all_probs, all_outcomes)

        # MAE
        errors = [abs(p["sim_mean"] - p["actual_value"]) for p in preds]
        mae = float(np.mean(errors)) if errors else float("nan")

        # ROI by edge bucket
        roi_by_bucket: dict[str, dict] = {}
        for lo, hi, label in EDGE_BUCKETS:
            bucket_preds = [
                p for p in decided
                if lo <= abs(p["edge"]) < hi
            ]
            if bucket_preds:
                wins = sum(
                    1 for p in bucket_preds
                    if (p["edge"] > 0 and p["actual_over"] == 1) or
                       (p["edge"] < 0 and p["actual_over"] == 0)
                )
                n = len(bucket_preds)
                # ROI: wins pay +0.909 (-110), losses pay -1.0
                units = wins * (100 / 110) - (n - wins) * 1.0
                roi_by_bucket[label] = {
                    "bets": n,
                    "wins": wins,
                    "hit_rate": round(wins / n * 100, 1),
                    "units": round(units, 2),
                    "roi_pct": round(units / n * 100, 1) if n > 0 else 0,
                }

        # ROI by tier
        tier_roi = {}
        for tier_label in ["A", "B", "C"]:
            tier_preds = [p for p in decided if p["tier"] == tier_label]
            if tier_preds:
                tw = sum(
                    1 for p in tier_preds
                    if (p["edge"] > 0 and p["actual_over"] == 1) or
                       (p["edge"] < 0 and p["actual_over"] == 0)
                )
                tn = len(tier_preds)
                tunits = tw * (100 / 110) - (tn - tw) * 1.0
                tier_roi[tier_label] = {
                    "bets": tn,
                    "wins": tw,
                    "hit_rate": round(tw / tn * 100, 1),
                    "roi_pct": round(tunits / tn * 100, 1) if tn > 0 else 0,
                }

        # Calibration
        cal = compute_calibration(all_probs, all_outcomes)

        results[prop_type] = {
            "total_predictions": len(preds),
            "correct_predictions": correct,
            "total_decided": total_decided,
            "accuracy_pct": round(accuracy, 1),
            "brier_score": round(bs, 4) if not math.isnan(bs) else None,
            "mae": round(mae, 3) if not math.isnan(mae) else None,
            "roi_by_edge_bucket": roi_by_bucket,
            "roi_by_tier": tier_roi,
            "calibration": cal,
        }

    return results


def aggregate_by_date(
    all_preds: list[dict],
) -> dict[str, dict[str, dict]]:
    """
    Group predictions by date and prop type for daily Supabase rows.
    Returns {game_date: {prop_type: {metrics...}}}.
    """
    by_date_type: dict[str, dict[str, list[dict]]] = defaultdict(lambda: defaultdict(list))
    for p in all_preds:
        by_date_type[p["game_date"]][p["prop_type"]].append(p)

    daily = {}
    for gdate, type_preds in by_date_type.items():
        daily[gdate] = {}
        for prop_type, preds in type_preds.items():
            decided = [p for p in preds if p["actual_push"] == 0]
            correct = sum(
                1 for p in decided
                if (p["p_over"] > 0.5 and p["actual_over"] == 1) or
                   (p["p_over"] <= 0.5 and p["actual_over"] == 0)
            )
            total = len(decided)

            # ROI
            edge_preds = [p for p in decided if abs(p["edge"]) >= 0.03]
            if edge_preds:
                wins = sum(
                    1 for p in edge_preds
                    if (p["edge"] > 0 and p["actual_over"] == 1) or
                       (p["edge"] < 0 and p["actual_over"] == 0)
                )
                units = wins * (100 / 110) - (len(edge_preds) - wins) * 1.0
                roi = units / len(edge_preds) * 100 if edge_preds else 0
            else:
                units = 0
                roi = 0

            # Tier ROI
            tier_rois = {}
            for tl in ["A", "B", "C"]:
                tp = [p for p in decided if p["tier"] == tl]
                if tp:
                    tw = sum(
                        1 for p in tp
                        if (p["edge"] > 0 and p["actual_over"] == 1) or
                           (p["edge"] < 0 and p["actual_over"] == 0)
                    )
                    tu = tw * (100 / 110) - (len(tp) - tw) * 1.0
                    tier_rois[tl] = round(tu / len(tp) * 100, 1)
                else:
                    tier_rois[tl] = 0.0

            avg_edge = float(np.mean([abs(p["edge"]) for p in preds])) if preds else 0

            daily[gdate][prop_type] = {
                "total_predictions": len(preds),
                "correct_predictions": correct,
                "accuracy_pct": round(correct / total * 100, 1) if total > 0 else 0,
                "profit_loss": round(units, 2),
                "roi_pct": round(roi, 1),
                "avg_edge": round(avg_edge, 4),
                "tier_a_roi": tier_rois.get("A", 0),
                "tier_b_roi": tier_rois.get("B", 0),
                "tier_c_roi": tier_rois.get("C", 0),
            }

    return daily


# ===========================================================================
# Supabase upload
# ===========================================================================

def _sb_headers() -> dict:
    return {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "resolution=merge-duplicates",
    }


def upload_backtest_results(daily_data: dict[str, dict[str, dict]]) -> int:
    """
    Upsert daily rows into backtest_results table.
    Each row = one (date, prop_type) combination.
    Returns number of rows upserted.
    """
    if not SUPABASE_URL or not SUPABASE_KEY:
        logger.warning("SUPABASE_URL or SUPABASE_SERVICE_KEY not set — skipping upload")
        return 0

    rows = []
    for gdate, type_data in daily_data.items():
        # Per-type rows
        for prop_type, metrics in type_data.items():
            rows.append({
                "date": gdate,
                "prop_type": prop_type,
                "total_predictions": metrics["total_predictions"],
                "correct_predictions": metrics["correct_predictions"],
                "accuracy_pct": metrics["accuracy_pct"],
                "profit_loss": metrics["profit_loss"],
                "roi_pct": metrics["roi_pct"],
                "avg_edge": metrics["avg_edge"],
                "tier_a_roi": metrics.get("tier_a_roi", 0),
                "tier_b_roi": metrics.get("tier_b_roi", 0),
                "tier_c_roi": metrics.get("tier_c_roi", 0),
            })

        # ALL-type aggregate row for this date
        all_total = sum(m["total_predictions"] for m in type_data.values())
        all_correct = sum(m["correct_predictions"] for m in type_data.values())
        all_pl = sum(m["profit_loss"] for m in type_data.values())
        all_edge = float(np.mean([m["avg_edge"] for m in type_data.values()])) if type_data else 0

        rows.append({
            "date": gdate,
            "prop_type": "ALL",
            "total_predictions": all_total,
            "correct_predictions": all_correct,
            "accuracy_pct": round(all_correct / all_total * 100, 1) if all_total > 0 else 0,
            "profit_loss": round(all_pl, 2),
            "roi_pct": round(all_pl / max(all_total, 1) * 100, 1),
            "avg_edge": round(all_edge, 4),
            "tier_a_roi": 0,
            "tier_b_roi": 0,
            "tier_c_roi": 0,
        })

    url = f"{SUPABASE_URL}/rest/v1/backtest_results"
    total_upserted = 0
    for i in range(0, len(rows), 200):
        batch = rows[i:i + 200]
        try:
            resp = requests.post(url, headers=_sb_headers(), json=batch, timeout=30)
            if resp.ok:
                total_upserted += len(batch)
                logger.info("Upserted %d backtest_results rows (batch %d)", len(batch), i // 200 + 1)
            else:
                logger.warning("Upsert failed: %d %s", resp.status_code, resp.text[:300])
        except requests.RequestException as exc:
            logger.warning("Upsert request failed: %s", exc)

    return total_upserted


# ===========================================================================
# Main entry point
# ===========================================================================

def run_backtest(
    start_date: str = "2025-08-01",
    end_date: str = "2025-09-30",
    upload: bool = False,
    dry_run: bool = False,
    verbose: bool = False,
    output_dir: str | None = None,
) -> dict:
    """
    Run the full Aug-Sep 2025 backtest.

    Returns summary dict with overall and per-prop-type metrics.
    """
    if verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    if output_dir is None:
        output_dir = os.path.join(PROJECT_ROOT, "backtest_output")
    os.makedirs(output_dir, exist_ok=True)

    logger.info("=" * 65)
    logger.info("BaselineMLB — Full Aug-Sep 2025 Backtest")
    logger.info("  Date range : %s → %s", start_date, end_date)
    logger.info("  Simulations: %d per player", N_SIMS)
    logger.info("  Prop types : %s", ", ".join(PROP_TYPES))
    logger.info("  Upload     : %s", upload)
    logger.info("=" * 65)

    # Fetch all games in range (in weekly chunks to avoid API limits)
    all_games = []
    current = datetime.strptime(start_date, "%Y-%m-%d")
    end_dt = datetime.strptime(end_date, "%Y-%m-%d")

    while current <= end_dt:
        chunk_end = min(current + timedelta(days=6), end_dt)
        games = fetch_schedule(
            current.strftime("%Y-%m-%d"),
            chunk_end.strftime("%Y-%m-%d"),
        )
        all_games.extend(games)
        logger.info(
            "  Fetched %d games for %s to %s",
            len(games),
            current.strftime("%Y-%m-%d"),
            chunk_end.strftime("%Y-%m-%d"),
        )
        current = chunk_end + timedelta(days=1)
        time.sleep(API_SLEEP)

    logger.info("Total games to backtest: %d", len(all_games))

    if not all_games:
        logger.warning("No completed games found in date range")
        return {"error": "No games found"}

    # Process each game
    all_predictions: list[dict] = []
    games_processed = 0
    games_failed = 0

    for i, game_info in enumerate(all_games, 1):
        if i % 25 == 0 or i == 1:
            logger.info(
                "[%d/%d] Processing game_pk=%d (%s) — %d predictions so far",
                i, len(all_games), game_info["game_pk"],
                game_info["game_date"], len(all_predictions),
            )

        try:
            preds = backtest_game(game_info)
            all_predictions.extend(preds)
            games_processed += 1
        except Exception as exc:
            logger.warning(
                "Failed game_pk=%d: %s — skipping",
                game_info["game_pk"], exc,
            )
            games_failed += 1

        # Rate limiting
        if i % 5 == 0:
            time.sleep(API_SLEEP)

    logger.info(
        "Backtest complete: %d games processed, %d failed, %d predictions",
        games_processed, games_failed, len(all_predictions),
    )

    # Compute aggregates
    by_type = aggregate_by_prop_type(all_predictions)
    by_date = aggregate_by_date(all_predictions)

    # Overall summary
    overall_brier_scores = {}
    overall_accuracy = {}
    overall_roi_by_bucket = {}
    overall_roi_by_tier = {}

    for pt, metrics in by_type.items():
        overall_brier_scores[pt] = metrics["brier_score"]
        overall_accuracy[pt] = {
            "total": metrics["total_predictions"],
            "correct": metrics["correct_predictions"],
            "accuracy_pct": metrics["accuracy_pct"],
            "mae": metrics["mae"],
        }
        overall_roi_by_bucket[pt] = metrics["roi_by_edge_bucket"]
        overall_roi_by_tier[pt] = metrics["roi_by_tier"]

    summary = {
        "date_range": {"start": start_date, "end": end_date},
        "games_processed": games_processed,
        "games_failed": games_failed,
        "total_predictions": len(all_predictions),
        "prop_types": PROP_TYPES,
        "brier_scores": overall_brier_scores,
        "accuracy_by_prop_type": overall_accuracy,
        "roi_by_edge_bucket": overall_roi_by_bucket,
        "roi_by_tier": overall_roi_by_tier,
        "calibration_by_prop_type": {
            pt: metrics["calibration"] for pt, metrics in by_type.items()
        },
    }

    # Save outputs
    summary_path = os.path.join(output_dir, "backtest_summary_aug_sep_2025.json")
    with open(summary_path, "w") as f:
        json.dump(summary, f, indent=2, default=str)
    logger.info("Wrote summary → %s", summary_path)

    # Save per-prediction detail (for debugging)
    detail_path = os.path.join(output_dir, "backtest_predictions_aug_sep_2025.json")
    with open(detail_path, "w") as f:
        json.dump(all_predictions[:1000], f, indent=2, default=str)  # First 1000 for size
    logger.info("Wrote prediction sample → %s", detail_path)

    # Upload to Supabase
    if upload and not dry_run:
        n_upserted = upload_backtest_results(by_date)
        logger.info("Uploaded %d rows to backtest_results", n_upserted)
    elif dry_run:
        logger.info("DRY RUN — no data uploaded")

    # Print summary
    print("\n" + "=" * 65)
    print("  BASELINEMLB — BACKTEST RESULTS (Aug-Sep 2025)")
    print("=" * 65)
    print(f"\n  Games: {games_processed}  |  Predictions: {len(all_predictions)}")
    print(f"\n  {'Prop':>4s}  {'Total':>7s}  {'Correct':>7s}  {'Acc%':>6s}  {'MAE':>6s}  {'Brier':>7s}")
    print("  " + "-" * 50)
    for pt in PROP_TYPES:
        if pt in by_type:
            m = by_type[pt]
            print(
                f"  {pt:>4s}  {m['total_predictions']:>7d}  "
                f"{m['correct_predictions']:>7d}  "
                f"{m['accuracy_pct']:>5.1f}%  "
                f"{m['mae'] or 0:>6.3f}  "
                f"{m['brier_score'] or 0:>7.4f}"
            )

    print(f"\n  ROI by Confidence Tier:")
    for pt in PROP_TYPES:
        if pt in by_type and by_type[pt]["roi_by_tier"]:
            tiers = by_type[pt]["roi_by_tier"]
            tier_str = "  ".join(
                f"{t}: {d['hit_rate']}% ({d['roi_pct']:+.1f}% ROI)"
                for t, d in sorted(tiers.items())
            )
            print(f"    {pt}: {tier_str}")

    print("=" * 65)

    return summary


# ===========================================================================
# CLI
# ===========================================================================

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="BaselineMLB full Aug-Sep 2025 backtest",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--start", default="2025-08-01", help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end", default="2025-09-30", help="End date (YYYY-MM-DD)")
    parser.add_argument("--upload", action="store_true", help="Upload results to Supabase")
    parser.add_argument("--dry-run", action="store_true", help="Run without uploading")
    parser.add_argument("--verbose", action="store_true", help="Enable debug logging")
    parser.add_argument("--output-dir", default=None, help="Output directory")
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    run_backtest(
        start_date=args.start,
        end_date=args.end,
        upload=args.upload,
        dry_run=args.dry_run,
        verbose=args.verbose,
        output_dir=args.output_dir,
    )
