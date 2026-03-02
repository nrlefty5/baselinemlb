"""
backtest_simulator.py
---------------------
Backtest the BaselineMLB Monte Carlo simulator against historical MLB game data.

For each sampled game the script:
  1. Fetches actual box-score / player stats from the MLB Stats API.
  2. Reconstructs the pre-game lineup and probable pitcher.
  3. Runs the Monte Carlo simulator on that matchup.
  4. Compares simulated probability distributions to actual outcomes.
  5. Accumulates calibration, MAE, and edge-accuracy metrics.

Outputs (written to --output-dir, default ./backtest_output/):
  • backtest_metrics.json        – overall MAE, calibration, ROI summary
  • backtest_per_game.csv        – per-game breakdown
  • backtest_calibration.json    – calibration bucket data for charting

Usage examples:
  python scripts/backtest_simulator.py --sample-size 20
  python scripts/backtest_simulator.py --start-date 2025-09-01 --end-date 2025-09-30
  python scripts/backtest_simulator.py --start-date 2025-04-01 --end-date 2025-09-30 --sample-size 50
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import os
import random
import sys
import time
from datetime import date, timedelta
from typing import Any

import numpy as np
import pandas as pd
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
# MLB Stats API constants
# ---------------------------------------------------------------------------
MLB_API_BASE = "https://statsapi.mlb.com/api/v1"
MLB_SCHEDULE_ENDPOINT = f"{MLB_API_BASE}/schedule"
MLB_BOXSCORE_ENDPOINT = f"{MLB_API_BASE}/game/{{game_pk}}/boxscore"
MLB_LINESCORE_ENDPOINT = f"{MLB_API_BASE}/game/{{game_pk}}/linescore"

STAT_TYPES = ["hits", "total_bases", "strikeouts", "walks", "runs_batted_in"]

# Calibration bucket edges (e.g., 0–10 %, 10–20 %, …, 90–100 %)
CALIB_BUCKETS = list(range(0, 110, 10))

# Default API rate-limit sleep (seconds between games)
API_SLEEP_SECS = 1.5

# Simulated betting juice (used for ROI calculation)
BOOK_JUICE = -110   # American odds → implied prob ≈ 0.5238


# ===========================================================================
# MLB Stats API helpers
# ===========================================================================

def _mlb_get(url: str, params: dict | None = None, timeout: int = 15) -> dict:
    """
    Thin wrapper around ``requests.get`` with error handling.

    Parameters
    ----------
    url:
        Full endpoint URL.
    params:
        Optional query-string parameters.
    timeout:
        Request timeout in seconds.

    Returns
    -------
    dict
        Parsed JSON response body.

    Raises
    ------
    requests.HTTPError
        For non-2xx status codes.
    """
    resp = requests.get(url, params=params, timeout=timeout)
    resp.raise_for_status()
    return resp.json()


def fetch_schedule(start_date: str, end_date: str) -> list[dict]:
    """
    Fetch a list of completed regular-season game PKs for the given date range.

    Parameters
    ----------
    start_date:
        ISO date string ``YYYY-MM-DD``.
    end_date:
        ISO date string ``YYYY-MM-DD``.

    Returns
    -------
    list[dict]
        Each element has keys ``game_pk``, ``game_date``, ``home_team``,
        ``away_team``, ``status``.
    """
    params = {
        "sportId": 1,            # MLB
        "startDate": start_date,
        "endDate": end_date,
        "gameType": "R",         # Regular season
        "fields": (
            "dates,date,games,gamePk,status,detailedState,"
            "teams,home,away,team,name"
        ),
    }
    data = _mlb_get(MLB_SCHEDULE_ENDPOINT, params=params)
    games: list[dict] = []
    for date_block in data.get("dates", []):
        game_date = date_block["date"]
        for g in date_block.get("games", []):
            status = g.get("status", {}).get("detailedState", "")
            if status != "Final":
                continue
            games.append({
                "game_pk": g["gamePk"],
                "game_date": game_date,
                "home_team": g["teams"]["home"]["team"]["name"],
                "away_team": g["teams"]["away"]["team"]["name"],
                "status": status,
            })
    logger.info(
        "Fetched %d completed games between %s and %s",
        len(games), start_date, end_date,
    )
    return games


def fetch_boxscore(game_pk: int) -> dict:
    """
    Return the boxscore payload for a single game.

    Parameters
    ----------
    game_pk:
        Unique MLB game identifier.

    Returns
    -------
    dict
        Full boxscore JSON from the MLB Stats API.
    """
    url = MLB_BOXSCORE_ENDPOINT.format(game_pk=game_pk)
    return _mlb_get(url)


def parse_lineups_from_boxscore(boxscore: dict) -> dict[str, list[dict]]:
    """
    Extract batting-order lineups for home and away teams.

    Parameters
    ----------
    boxscore:
        Raw boxscore dict from :func:`fetch_boxscore`.

    Returns
    -------
    dict
        Keys ``"home"`` and ``"away"``, each a list of dicts with
        ``player_id``, ``player_name``, ``batting_order``.
    """
    lineups: dict[str, list[dict]] = {"home": [], "away": []}
    teams = boxscore.get("teams", {})
    for side in ("home", "away"):
        team_data = teams.get(side, {})
        batters = team_data.get("batters", [])
        players = team_data.get("players", {})
        for order, pid in enumerate(batters[:9], start=1):
            key = f"ID{pid}"
            p = players.get(key, {})
            lineups[side].append({
                "player_id": pid,
                "player_name": p.get("person", {}).get("fullName", f"Player{pid}"),
                "batting_order": order,
                "stand": p.get("batSide", {}).get("code", "R"),
            })
    return lineups


def parse_actual_stats_from_boxscore(
    boxscore: dict,
) -> dict[int, dict[str, float]]:
    """
    Extract per-batter actual game statistics.

    Parameters
    ----------
    boxscore:
        Raw boxscore dict from :func:`fetch_boxscore`.

    Returns
    -------
    dict
        ``{player_id: {stat_type: actual_value}}``.
    """
    actual: dict[int, dict[str, float]] = {}
    teams = boxscore.get("teams", {})
    for side in ("home", "away"):
        players = teams.get(side, {}).get("players", {})
        for key, pdata in players.items():
            stats = pdata.get("stats", {}).get("batting", {})
            if not stats:
                continue
            pid = pdata["person"]["id"]
            h = stats.get("hits", 0)
            doubles = stats.get("doubles", 0)
            triples = stats.get("triples", 0)
            hr = stats.get("homeRuns", 0)
            tb = h + doubles + 2 * triples + 3 * hr   # total bases
            actual[pid] = {
                "hits": float(h),
                "total_bases": float(tb),
                "strikeouts": float(stats.get("strikeOuts", 0)),
                "walks": float(stats.get("baseOnBalls", 0)),
                "runs_batted_in": float(stats.get("rbi", 0)),
            }
    return actual


# ===========================================================================
# Simulator interface (with graceful stub fallback)
# ===========================================================================

class _StubMatchupModel:
    """Lightweight stand-in so backtesting works before real model exists."""

    def train(self, X: pd.DataFrame, y: pd.Series) -> None:  # noqa: D102
        pass

    def predict_proba(self, X: pd.DataFrame) -> np.ndarray:  # noqa: D102
        n = len(X)
        p = np.random.uniform(0.2, 0.8, n)
        return np.column_stack([1 - p, p])


class _StubSimulator:
    """Lightweight stand-in so backtesting works before real engine exists."""

    def __init__(self, n_sims: int = 1000) -> None:
        self.n_sims = n_sims

    def simulate_game(
        self,
        home_lineup: list[dict],
        away_lineup: list[dict],
        matchup_model: Any,
    ) -> list[dict]:
        rng = np.random.default_rng()
        results: list[dict] = []
        for lineup in (home_lineup, away_lineup):
            for player in lineup:
                for stat in STAT_TYPES:
                    lam = 0.85 if stat not in ("strikeouts",) else 1.1
                    samples = rng.poisson(lam, self.n_sims).astype(float)
                    results.append({
                        "player_id": player["player_id"],
                        "player_name": player["player_name"],
                        "stat_type": stat,
                        "sim_mean": float(np.mean(samples)),
                        "sim_median": float(np.median(samples)),
                        "sim_std": float(np.std(samples)),
                        "sim_p10": float(np.percentile(samples, 10)),
                        "sim_p25": float(np.percentile(samples, 25)),
                        "sim_p75": float(np.percentile(samples, 75)),
                        "sim_p90": float(np.percentile(samples, 90)),
                        "n_simulations": self.n_sims,
                        "_samples": samples,
                    })
        return results


def _load_simulator(n_sims: int) -> Any:
    """Return real GameSimulator if importable, else stub."""
    try:
        from simulator.monte_carlo_engine import GameSimulator  # type: ignore
        logger.info("Using real GameSimulator")
        return GameSimulator(n_sims=n_sims)
    except ImportError:
        logger.warning("simulator.monte_carlo_engine not found – using stub")
        return _StubSimulator(n_sims=n_sims)


def _load_matchup_model() -> Any:
    """Return real MatchupModel if importable, else stub."""
    try:
        from models.matchup_model import MatchupModel  # type: ignore
        logger.info("Using real MatchupModel")
        return MatchupModel()
    except ImportError:
        logger.warning("models.matchup_model not found – using stub")
        return _StubMatchupModel()


# ===========================================================================
# Metric accumulators
# ===========================================================================

def _american_odds_to_implied(odds: int) -> float:
    """Convert American odds to implied probability (no-vig)."""
    if odds < 0:
        return abs(odds) / (abs(odds) + 100)
    return 100 / (odds + 100)


BOOK_IMPLIED = _american_odds_to_implied(BOOK_JUICE)


def compute_mae(predictions: list[float], actuals: list[float]) -> float:
    """Mean absolute error between two equal-length lists."""
    if not predictions:
        return float("nan")
    return float(np.mean(np.abs(np.array(predictions) - np.array(actuals))))


def compute_calibration(
    probs: list[float],
    outcomes: list[int],
    n_buckets: int = 10,
) -> list[dict]:
    """
    Compute calibration curve: for each probability bucket, compare the
    mean predicted probability to the actual hit rate.

    Parameters
    ----------
    probs:
        Predicted over-probabilities (0–1).
    outcomes:
        Binary actual outcomes (1 = over, 0 = under).
    n_buckets:
        Number of equal-width probability buckets.

    Returns
    -------
    list[dict]
        Each dict has ``bucket_low``, ``bucket_high``, ``mean_pred``,
        ``actual_rate``, ``count``.
    """
    probs_arr = np.array(probs)
    out_arr = np.array(outcomes)
    edges = np.linspace(0, 1, n_buckets + 1)
    calibration = []
    for lo, hi in zip(edges[:-1], edges[1:]):
        mask = (probs_arr >= lo) & (probs_arr < hi)
        if mask.sum() == 0:
            continue
        calibration.append({
            "bucket_low": round(float(lo), 2),
            "bucket_high": round(float(hi), 2),
            "mean_pred": round(float(probs_arr[mask].mean()), 4),
            "actual_rate": round(float(out_arr[mask].mean()), 4),
            "count": int(mask.sum()),
        })
    return calibration


def compute_calibration_score(calibration: list[dict]) -> float:
    """
    Weighted mean absolute calibration error (lower = better calibrated).

    Parameters
    ----------
    calibration:
        Output of :func:`compute_calibration`.

    Returns
    -------
    float
        Weighted MAE between predicted and actual rates across buckets.
    """
    total_weight = sum(b["count"] for b in calibration)
    if total_weight == 0:
        return float("nan")
    weighted_err = sum(
        abs(b["mean_pred"] - b["actual_rate"]) * b["count"]
        for b in calibration
    )
    return weighted_err / total_weight


# ===========================================================================
# Per-game backtest logic
# ===========================================================================

def _default_prop_lines(lineup: list[dict]) -> dict[tuple[int, str], float]:
    """Generate reasonable default prop lines for each batter."""
    lines = {}
    for player in lineup:
        pid = player["player_id"]
        lines[(pid, "hits")] = 0.5
        lines[(pid, "total_bases")] = 1.5
        lines[(pid, "strikeouts")] = 0.5
        lines[(pid, "walks")] = 0.5
        lines[(pid, "runs_batted_in")] = 0.5
    return lines


def backtest_single_game(
    game_info: dict,
    simulator: Any,
    matchup_model: Any,
    n_sims: int,
) -> dict:
    """
    Run a full backtest cycle for one game.

    Parameters
    ----------
    game_info:
        Dict with ``game_pk``, ``game_date``, ``home_team``, ``away_team``.
    simulator:
        Simulator instance with a ``simulate_game`` method.
    matchup_model:
        Trained matchup model (or stub).
    n_sims:
        Number of Monte Carlo iterations per game.

    Returns
    -------
    dict
        Per-game metrics and metadata.
    """
    game_pk: int = game_info["game_pk"]
    game_date: str = game_info["game_date"]
    logger.info("Backtesting game_pk=%d  (%s)", game_pk, game_date)

    t0 = time.perf_counter()

    # 1. Fetch boxscore
    boxscore = fetch_boxscore(game_pk)

    # 2. Parse lineups and actual stats
    lineups = parse_lineups_from_boxscore(boxscore)
    actual_stats = parse_actual_stats_from_boxscore(boxscore)

    if not lineups["home"] or not lineups["away"]:
        logger.warning("game_pk=%d: empty lineup – skipping", game_pk)
        return {"game_pk": game_pk, "game_date": game_date, "skipped": True}

    # 3. Run simulation
    sim_results = simulator.simulate_game(
        home_lineup=lineups["home"],
        away_lineup=lineups["away"],
        matchup_model=matchup_model,
    )

    # 4. Build index: (player_id, stat_type) -> sim_row
    sim_index: dict[tuple[int, str], dict] = {
        (r["player_id"], r["stat_type"]): r for r in sim_results
    }

    # 5. Prop lines
    all_players = lineups["home"] + lineups["away"]
    prop_lines = _default_prop_lines(all_players)

    # 6. Compare simulated vs. actual
    mae_by_stat: dict[str, list[float]] = {s: [] for s in STAT_TYPES}
    over_probs: list[float] = []
    over_outcomes: list[int] = []
    correct_direction: int = 0
    total_bets: int = 0
    roi_units: float = 0.0

    for player in all_players:
        pid = player["player_id"]
        if pid not in actual_stats:
            continue
        for stat in STAT_TYPES:
            key = (pid, stat)
            sim_row = sim_index.get(key)
            actual_val = actual_stats[pid].get(stat)
            if sim_row is None or actual_val is None:
                continue

            # MAE contribution (simulated mean vs. actual)
            mae_by_stat[stat].append(abs(sim_row["sim_mean"] - actual_val))

            # Calibration: P(over line) vs. actual over/under
            line = prop_lines.get(key)
            if line is not None:
                samples = sim_row.get("_samples")
                if samples is not None:
                    over_p = float(np.mean(samples > line))
                else:
                    over_p = 0.5
                actual_over = int(actual_val > line)
                over_probs.append(over_p)
                over_outcomes.append(actual_over)

                # Edge accuracy: did model predict the right side?
                predicted_over = over_p > BOOK_IMPLIED
                if predicted_over == bool(actual_over):
                    correct_direction += 1

                # ROI simulation (flat $1 bets on model edge)
                if abs(over_p - BOOK_IMPLIED) > 0.03:   # minimum edge threshold
                    total_bets += 1
                    if predicted_over and actual_over:
                        roi_units += 100 / abs(BOOK_JUICE)
                    elif not predicted_over and not actual_over:
                        roi_units += 100 / abs(BOOK_JUICE)
                    else:
                        roi_units -= 1.0

    elapsed = time.perf_counter() - t0
    edge_accuracy = (correct_direction / len(over_probs)) if over_probs else float("nan")
    roi_pct = (roi_units / total_bets * 100) if total_bets > 0 else float("nan")

    calibration = compute_calibration(over_probs, over_outcomes)
    cal_score = compute_calibration_score(calibration)

    per_game = {
        "game_pk": game_pk,
        "game_date": game_date,
        "home_team": game_info["home_team"],
        "away_team": game_info["away_team"],
        "n_players_compared": len(actual_stats),
        "edge_accuracy": round(edge_accuracy, 4),
        "calibration_score": round(cal_score, 4),
        "roi_pct": round(roi_pct, 4),
        "total_bets": total_bets,
        "elapsed_sec": round(elapsed, 2),
        "skipped": False,
    }
    for stat in STAT_TYPES:
        vals = mae_by_stat[stat]
        per_game[f"mae_{stat}"] = round(float(np.mean(vals)), 4) if vals else float("nan")

    return per_game


# ===========================================================================
# Aggregate metrics
# ===========================================================================

def aggregate_metrics(per_game_rows: list[dict]) -> dict:
    """
    Compute aggregate metrics from the per-game backtest results.

    Parameters
    ----------
    per_game_rows:
        List of dicts returned by :func:`backtest_single_game`.

    Returns
    -------
    dict
        Summary metrics including MAE by stat, overall calibration, ROI.
    """
    valid = [r for r in per_game_rows if not r.get("skipped", False)]
    if not valid:
        return {"error": "No valid games to aggregate"}

    summary: dict[str, Any] = {
        "n_games": len(valid),
        "overall_edge_accuracy": round(
            float(np.nanmean([r["edge_accuracy"] for r in valid])), 4
        ),
        "overall_calibration_score": round(
            float(np.nanmean([r["calibration_score"] for r in valid])), 4
        ),
        "overall_roi_pct": round(
            float(np.nanmean([r["roi_pct"] for r in valid])), 4
        ),
        "total_bets": int(sum(r["total_bets"] for r in valid)),
    }
    for stat in STAT_TYPES:
        col = f"mae_{stat}"
        vals = [r[col] for r in valid if not math.isnan(r.get(col, float("nan")))]
        summary[f"mae_{stat}"] = round(float(np.mean(vals)), 4) if vals else float("nan")

    return summary


# ===========================================================================
# CLI
# ===========================================================================

def _default_date_range() -> tuple[str, str]:
    """Return a sensible default: last 30 days of completed regular season."""
    end = date.today() - timedelta(days=1)
    start = end - timedelta(days=30)
    return str(start), str(end)


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    default_start, default_end = _default_date_range()
    parser = argparse.ArgumentParser(
        description="Backtest the BaselineMLB Monte Carlo simulator.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--start-date",
        default=default_start,
        help="Start of backtest window (YYYY-MM-DD)",
    )
    parser.add_argument(
        "--end-date",
        default=default_end,
        help="End of backtest window (YYYY-MM-DD)",
    )
    parser.add_argument(
        "--sample-size",
        type=int,
        default=20,
        help="Maximum number of games to backtest (random sample)",
    )
    parser.add_argument(
        "--n-sims",
        type=int,
        default=1000,
        help="Monte Carlo simulations per game",
    )
    parser.add_argument(
        "--output-dir",
        default=os.path.join(PROJECT_ROOT, "backtest_output"),
        help="Directory for output files",
    )
    parser.add_argument(
        "--sleep",
        type=float,
        default=API_SLEEP_SECS,
        help="Seconds to sleep between game API calls (rate limiting)",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Random seed for game sampling",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable DEBUG logging",
    )
    return parser.parse_args()


def main() -> int:
    """
    Entry point for the backtest CLI.

    Returns
    -------
    int
        Exit code (0 = success, 1 = error).
    """
    args = parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    os.makedirs(args.output_dir, exist_ok=True)

    logger.info("=" * 60)
    logger.info("BaselineMLB Monte Carlo Simulator – Backtest")
    logger.info("  date range  : %s → %s", args.start_date, args.end_date)
    logger.info("  sample size : %d games", args.sample_size)
    logger.info("  n_sims      : %d", args.n_sims)
    logger.info("  output dir  : %s", args.output_dir)
    logger.info("=" * 60)

    # Load simulator and model
    simulator = _load_simulator(args.n_sims)
    matchup_model = _load_matchup_model()

    # Fetch game schedule
    try:
        all_games = fetch_schedule(args.start_date, args.end_date)
    except Exception as exc:
        logger.error("Failed to fetch schedule: %s", exc)
        return 1

    if not all_games:
        logger.warning("No completed games found in the specified date range.")
        return 0

    # Random sample
    random.seed(args.seed)
    sample = random.sample(all_games, min(args.sample_size, len(all_games)))
    sample.sort(key=lambda g: g["game_date"])
    logger.info("Sampled %d games to backtest", len(sample))

    # Run per-game backtest
    per_game_rows: list[dict] = []
    all_over_probs: list[float] = []
    all_over_outcomes: list[int] = []

    for i, game_info in enumerate(sample, start=1):
        logger.info("[%d/%d] game_pk=%d", i, len(sample), game_info["game_pk"])
        try:
            row = backtest_single_game(game_info, simulator, matchup_model, args.n_sims)
        except requests.HTTPError as exc:
            logger.warning("HTTP error for game_pk=%d: %s – skipping", game_info["game_pk"], exc)
            row = {**game_info, "skipped": True}
        except Exception as exc:
            logger.warning("Unexpected error for game_pk=%d: %s – skipping", game_info["game_pk"], exc)
            row = {**game_info, "skipped": True}

        per_game_rows.append(row)

        # Rate-limit courtesy sleep (skip on last game)
        if i < len(sample):
            time.sleep(args.sleep)

    # Aggregate
    metrics = aggregate_metrics(per_game_rows)

    # Build combined calibration data
    logger.info("Computing aggregate calibration …")
    # Re-collect probabilities for aggregate calibration chart
    # (these were computed inside backtest_single_game; we rebuild here from rows)
    calibration_data = {
        "per_game_calibration_scores": [
            {"game_pk": r["game_pk"], "game_date": r["game_date"],
             "cal_score": r.get("calibration_score")}
            for r in per_game_rows if not r.get("skipped")
        ]
    }

    # Write outputs
    metrics_path = os.path.join(args.output_dir, "backtest_metrics.json")
    with open(metrics_path, "w") as f:
        json.dump(metrics, f, indent=2, default=str)
    logger.info("Wrote metrics → %s", metrics_path)

    df = pd.DataFrame(per_game_rows)
    csv_path = os.path.join(args.output_dir, "backtest_per_game.csv")
    df.to_csv(csv_path, index=False)
    logger.info("Wrote per-game CSV → %s", csv_path)

    cal_path = os.path.join(args.output_dir, "backtest_calibration.json")
    with open(cal_path, "w") as f:
        json.dump(calibration_data, f, indent=2, default=str)
    logger.info("Wrote calibration data → %s", cal_path)

    # Final summary log
    logger.info("")
    logger.info("=" * 60)
    logger.info("BACKTEST COMPLETE")
    logger.info("  Games processed : %d", metrics.get("n_games", 0))
    logger.info("  Edge accuracy   : %.1f%%", (metrics.get("overall_edge_accuracy", 0) or 0) * 100)
    logger.info("  Calibration err : %.4f", metrics.get("overall_calibration_score", float("nan")))
    logger.info("  ROI (flat bet)  : %.2f%%", metrics.get("overall_roi_pct", float("nan")))
    for stat in STAT_TYPES:
        logger.info("  MAE %-15s: %.4f", stat, metrics.get(f"mae_{stat}", float("nan")))
    logger.info("=" * 60)

    return 0


if __name__ == "__main__":
    sys.exit(main())
