#!/usr/bin/env python3
"""
generate_backtest_report.py — BaselineMLB
Comprehensive Markdown report generator with matplotlib/seaborn charts
for the Monte Carlo backtest system.

Reads output from backtest_simulator.py:
  - backtest_predictions_{start}_{end}.json
  - backtest_summary_{start}_{end}.json
  - backtest_daily_{start}_{end}.json   (optional)
  - model_comparison.json               (optional, from compare_models.py)

Produces:
  - PNG chart files in --output-dir
  - Markdown report at --report-path

Usage:
  python scripts/generate_backtest_report.py \\
    --predictions output/backtest/backtest_predictions_2025-07-01_2025-07-31.json \\
    --summary     output/backtest/backtest_summary_2025-07-01_2025-07-31.json \\
    --daily       output/backtest/backtest_daily_2025-07-01_2025-07-31.json \\
    --output-dir  output/backtest \\
    --report-path docs/BACKTEST_REPORT.md \\
    --comparison  output/backtest/model_comparison.json

Can also be imported as a module:
  from scripts.generate_backtest_report import generate_report
  generate_report(predictions, summary, daily, output_dir, report_path)
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

import matplotlib

matplotlib.use("Agg")  # non-interactive backend — must come before pyplot import
import matplotlib.pyplot as plt
import numpy as np
import seaborn as sns

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("generate_backtest_report")

# ---------------------------------------------------------------------------
# Brand palette & chart defaults
# ---------------------------------------------------------------------------

COLORS = {
    "blue":   "#1a73e8",
    "green":  "#34a853",
    "red":    "#ea4335",
    "yellow": "#fbbc04",
    "purple": "#673ab7",
    "gray":   "#9e9e9e",
    "light_green": "#a8d5b5",
    "light_red":   "#f5b8b2",
}

PROP_COLORS = {
    "K":  COLORS["blue"],
    "TB": COLORS["green"],
    "H":  COLORS["yellow"],
    "HR": COLORS["red"],
}

PROP_LABELS = {
    "K":  "Strikeouts",
    "TB": "Total Bases",
    "H":  "Hits",
    "HR": "Home Runs",
}

CHART_STYLE = "seaborn-v0_8-darkgrid"
DPI = 150
TITLE_SIZE = 14
LABEL_SIZE = 12
TICK_SIZE = 10

# ---------------------------------------------------------------------------
# Demo data generator (used when no real data files are provided)
# ---------------------------------------------------------------------------

def _make_demo_predictions(n: int = 600, seed: int = 42) -> List[Dict]:
    """Generate synthetic predictions that match the real schema."""
    rng = np.random.default_rng(seed)
    prop_types = ["K", "TB", "H", "HR"]
    pitchers = [
        ("Gerrit Cole", 543037, "New York Yankees"),
        ("Shane McClanahan", 663886, "Tampa Bay Rays"),
        ("Spencer Strider", 675911, "Atlanta Braves"),
        ("Zack Wheeler", 554430, "Philadelphia Phillies"),
    ]
    batters = [
        ("Freddie Freeman", 518692, "Los Angeles Dodgers"),
        ("Rafael Devers", 646240, "Boston Red Sox"),
        ("Manny Machado", 592518, "San Diego Padres"),
        ("Trea Turner", 607208, "Philadelphia Phillies"),
        ("Paul Goldschmidt", 502671, "St. Louis Cardinals"),
        ("Pete Alonso", 624413, "New York Mets"),
    ]
    opponents = ["New York Yankees", "Boston Red Sox", "Houston Astros", "Chicago Cubs",
                 "Los Angeles Dodgers", "Atlanta Braves", "Tampa Bay Rays"]
    venues = ["Yankee Stadium", "Fenway Park", "Minute Maid Park", "Wrigley Field",
              "Dodger Stadium", "Truist Park", "Tropicana Field"]
    tiers = ["A", "B", "C", "D"]
    tier_weights = [0.25, 0.30, 0.30, 0.15]

    start = datetime(2025, 7, 1)
    predictions = []

    for i in range(n):
        pt = rng.choice(prop_types, p=[0.40, 0.25, 0.25, 0.10])
        if pt == "K":
            player_name, player_id, team = pitchers[rng.integers(0, len(pitchers))]
            mean = rng.uniform(3.5, 8.5)
            std = rng.uniform(1.5, 2.5)
            lines = ["3.5", "4.5", "5.5", "6.5", "7.5"]
        elif pt == "HR":
            player_name, player_id, team = batters[rng.integers(0, len(batters))]
            mean = rng.uniform(0.05, 0.25)
            std = rng.uniform(0.15, 0.35)
            lines = ["0.5"]
        elif pt == "TB":
            player_name, player_id, team = batters[rng.integers(0, len(batters))]
            mean = rng.uniform(0.8, 2.5)
            std = rng.uniform(0.8, 1.4)
            lines = ["0.5", "1.5", "2.5"]
        else:  # H
            player_name, player_id, team = batters[rng.integers(0, len(batters))]
            mean = rng.uniform(0.5, 1.8)
            std = rng.uniform(0.5, 1.0)
            lines = ["0.5", "1.5"]

        sim_samples = rng.normal(mean, std, 3000)
        sim_samples = np.maximum(sim_samples, 0)
        actual = float(rng.poisson(max(mean, 0.1)))
        abs_err = abs(actual - mean)

        # Common lines P(over)
        common_lines = {}
        for line in lines:
            p_over = float(np.mean(sim_samples > float(line)))
            p_over = np.clip(p_over, 0.01, 0.99)
            common_lines[line] = {"p_over": round(p_over, 3),
                                  "p_under": round(1 - p_over, 3)}

        # Pick best line (closest p_over to 0.5 but > 0.5)
        over_lines = [(k, v["p_over"]) for k, v in common_lines.items()
                      if v["p_over"] >= 0.50]
        if over_lines:
            best_line, p_model = max(over_lines, key=lambda x: x[1])
            direction = "OVER"
        else:
            best_line = lines[-1]
            p_model = common_lines[best_line]["p_under"]
            direction = "UNDER"

        edge_pct = round(float(p_model) - 0.524, 4)
        kelly = max(0.0, round((float(p_model) - 0.524) / (1.0 - float(p_model)) * 0.25, 4))

        actual_over = actual > float(best_line) if direction == "OVER" else actual < float(best_line)
        pnl = kelly * 0.909 if actual_over else -kelly

        tier = rng.choice(tiers, p=tier_weights)
        game_date = (start + timedelta(days=int(rng.integers(0, 31)))).strftime("%Y-%m-%d")

        # Brier components
        brier_comps = {}
        for line, vals in common_lines.items():
            outcome = 1 if actual > float(line) else 0
            brier_comps[f"line_{line}"] = {
                "forecast": vals["p_over"],
                "outcome": outcome,
                "brier": round((vals["p_over"] - outcome) ** 2, 4),
            }

        predictions.append({
            "game_date": game_date,
            "game_pk": 700000 + i,
            "prop_type": pt,
            "player_name": player_name,
            "player_id": player_id,
            "team": team,
            "opponent": opponents[rng.integers(0, len(opponents))],
            "venue": venues[rng.integers(0, len(venues))],
            "sim_mean": round(float(mean), 3),
            "sim_median": round(float(np.median(sim_samples)), 3),
            "sim_std": round(float(std), 3),
            "sim_percentiles": {
                "10": round(float(np.percentile(sim_samples, 10)), 2),
                "25": round(float(np.percentile(sim_samples, 25)), 2),
                "50": round(float(np.percentile(sim_samples, 50)), 2),
                "75": round(float(np.percentile(sim_samples, 75)), 2),
                "90": round(float(np.percentile(sim_samples, 90)), 2),
            },
            "common_lines": common_lines,
            "confidence_tier": tier,
            "actual_value": actual,
            "absolute_error": round(abs_err, 3),
            "model_config": {"umpire_enabled": True, "weather_enabled": False, "sims": 3000},
            "features": {},
            "kelly_results": {
                "best_line": best_line,
                "direction": direction,
                "edge_pct": round(edge_pct, 4),
                "kelly_fraction": kelly,
                "p_model": round(float(p_model), 3),
                "bet_result": "hit" if actual_over else "miss",
                "pnl_units": round(float(pnl), 4),
            },
            "brier_components": brier_comps,
            "_sim_samples": sim_samples.tolist(),  # kept for distribution plot
        })

    return predictions


def _make_demo_summary(predictions: List[Dict]) -> Dict:
    """Build a summary object from a list of predictions."""

    acc_by_type: Dict[str, Any] = defaultdict(lambda: {
        "count": 0, "mae_sum": 0.0, "errors": [], "within_1": 0, "within_2": 0,
        "brier_sum": 0.0, "brier_count": 0,
    })

    calibration_buckets: Dict[str, Any] = {
        "50-55": {"count": 0, "hits": 0},
        "55-60": {"count": 0, "hits": 0},
        "60-65": {"count": 0, "hits": 0},
        "65-70": {"count": 0, "hits": 0},
        "70+":   {"count": 0, "hits": 0},
    }
    calibration_by_type: Dict[str, Dict[str, Any]] = {}

    roi_by_tier: Dict[str, Any] = defaultdict(lambda: {
        "count": 0, "total_wagered": 0.0, "total_pnl": 0.0,
    })
    total_wagered = 0.0
    total_pnl = 0.0
    total_bets = 0

    for p in predictions:
        pt = p["prop_type"]
        ab = acc_by_type[pt]
        ab["count"] += 1
        ab["mae_sum"] += p["absolute_error"]
        ab["errors"].append(p["absolute_error"])
        if p["absolute_error"] <= 1.0:
            ab["within_1"] += 1
        if p["absolute_error"] <= 2.0:
            ab["within_2"] += 1

        for bc in p.get("brier_components", {}).values():
            ab["brier_sum"] += bc["brier"]
            ab["brier_count"] += 1

        # Calibration
        kr = p.get("kelly_results", {})
        if kr and kr.get("kelly_fraction", 0) > 0:
            p_model = kr.get("p_model", 0.5)
            outcome = 1 if kr.get("bet_result") == "hit" else 0
            pct = p_model * 100
            bucket = None
            if 50 <= pct < 55:
                bucket = "50-55"
            elif 55 <= pct < 60:
                bucket = "55-60"
            elif 60 <= pct < 65:
                bucket = "60-65"
            elif 65 <= pct < 70:
                bucket = "65-70"
            elif pct >= 70:
                bucket = "70+"
            if bucket:
                calibration_buckets[bucket]["count"] += 1
                calibration_buckets[bucket]["hits"] += outcome

                if pt not in calibration_by_type:
                    calibration_by_type[pt] = {k: {"count": 0, "hits": 0}
                                               for k in calibration_buckets}
                calibration_by_type[pt][bucket]["count"] += 1
                calibration_by_type[pt][bucket]["hits"] += outcome

            tier = p.get("confidence_tier", "D")
            k_frac = kr.get("kelly_fraction", 0.0)
            pnl = kr.get("pnl_units", 0.0)
            roi_by_tier[tier]["count"] += 1
            roi_by_tier[tier]["total_wagered"] += k_frac
            roi_by_tier[tier]["total_pnl"] += pnl
            total_wagered += k_frac
            total_pnl += pnl
            total_bets += 1

    # Build calibration structure
    calibration_out: Dict[str, Any] = {}
    for b, vals in calibration_buckets.items():
        hr = vals["hits"] / vals["count"] if vals["count"] else None
        calibration_out[b] = {"count": vals["count"], "actual_hit_rate": hr}

    calibration_by_type_out: Dict[str, Any] = {}
    for pt, buckets in calibration_by_type.items():
        calibration_by_type_out[pt] = {}
        for b, vals in buckets.items():
            hr = vals["hits"] / vals["count"] if vals["count"] else None
            calibration_by_type_out[pt][b] = {"count": vals["count"], "actual_hit_rate": hr}

    # Accuracy by type
    accuracy_out: Dict[str, Any] = {}
    for pt, ab in acc_by_type.items():
        count = ab["count"]
        brier = ab["brier_sum"] / ab["brier_count"] if ab["brier_count"] else None
        naive_brier = 0.25  # 50/50 coin flip
        skill = (1 - brier / naive_brier) if (brier is not None and naive_brier) else None
        accuracy_out[pt] = {
            "count": count,
            "mae": round(ab["mae_sum"] / count, 3) if count else None,
            "median_error": round(float(np.median(ab["errors"])), 3) if ab["errors"] else None,
            "within_1": round(ab["within_1"] / count * 100, 1) if count else None,
            "within_2": round(ab["within_2"] / count * 100, 1) if count else None,
        }
        brier_scores_out_entry = {
            "brier": round(brier, 4) if brier is not None else None,
            "naive_brier": naive_brier,
            "skill_score": round(skill, 4) if skill is not None else None,
        }
        accuracy_out[pt]["brier"] = brier_scores_out_entry["brier"]
        accuracy_out[pt]["brier_skill"] = brier_scores_out_entry["skill_score"]

    # ROI by tier
    roi_out: Dict[str, Any] = {}
    for tier, vals in roi_by_tier.items():
        wagered = vals["total_wagered"]
        pnl = vals["total_pnl"]
        roi_out[tier] = {
            "count": vals["count"],
            "total_wagered": round(wagered, 3),
            "total_pnl": round(pnl, 3),
            "roi_pct": round(pnl / wagered * 100, 2) if wagered else None,
        }

    # Daily P/L
    daily_pnl: Dict[str, Dict] = defaultdict(lambda: {"daily_pnl": 0.0, "bets": 0})
    for p in predictions:
        kr = p.get("kelly_results", {})
        if kr and kr.get("kelly_fraction", 0) > 0:
            d = p["game_date"]
            daily_pnl[d]["daily_pnl"] += kr.get("pnl_units", 0.0)
            daily_pnl[d]["bets"] += 1

    sorted_dates = sorted(daily_pnl.keys())
    cumulative = 0.0
    daily_list = []
    for d in sorted_dates:
        cumulative += daily_pnl[d]["daily_pnl"]
        daily_list.append({
            "date": d,
            "daily_pnl": round(daily_pnl[d]["daily_pnl"], 4),
            "cumulative_pnl": round(cumulative, 4),
            "bets": daily_pnl[d]["bets"],
        })

    # Best / worst predictions
    sorted_preds = sorted(predictions, key=lambda x: x["absolute_error"])
    best_preds = sorted_preds[:10]
    worst_preds = sorted_preds[-10:][::-1]

    dates = [p["game_date"] for p in predictions]
    date_start = min(dates) if dates else "N/A"
    date_end = max(dates) if dates else "N/A"

    brier_scores_by_type: Dict[str, Any] = {}
    for pt, ab in acc_by_type.items():
        brier = ab["brier_sum"] / ab["brier_count"] if ab["brier_count"] else None
        naive_brier = 0.25
        skill = (1 - brier / naive_brier) if brier is not None else None
        brier_scores_by_type[pt] = {
            "brier": round(brier, 4) if brier is not None else None,
            "naive_brier": naive_brier,
            "skill_score": round(skill, 4) if skill is not None else None,
        }

    return {
        "model_config": {"umpire_enabled": True, "weather_enabled": False, "sims": 3000},
        "date_range": {"start": date_start, "end": date_end},
        "total_predictions": len(predictions),
        "accuracy_by_type": accuracy_out,
        "calibration": calibration_out,
        "calibration_by_type": calibration_by_type_out,
        "roi_by_tier": roi_out,
        "brier_scores": brier_scores_by_type,
        "best_predictions": best_preds,
        "worst_predictions": worst_preds,
        "overall_pnl": {
            "total_bets": total_bets,
            "total_wagered": round(total_wagered, 3),
            "total_pnl": round(total_pnl, 3),
            "roi_pct": round(total_pnl / total_wagered * 100, 2) if total_wagered else None,
        },
        "daily_pnl": daily_list,
    }


def _make_demo_daily(summary: Dict) -> List[Dict]:
    return summary.get("daily_pnl", [])


# ---------------------------------------------------------------------------
# Chart generators
# ---------------------------------------------------------------------------

def _apply_style(style: str) -> None:
    try:
        plt.style.use(style)
    except OSError:
        plt.style.use("seaborn-v0_8-darkgrid")


def chart_calibration_curve(
    summary: Dict,
    predictions: List[Dict],
    output_dir: Path,
    style: str,
) -> Path:
    """Calibration curves: predicted P(over) vs actual hit rate, one line per prop type."""
    _apply_style(style)

    bucket_order = ["50-55", "55-60", "60-65", "65-70", "70+"]
    bucket_midpoints = [52.5, 57.5, 62.5, 67.5, 72.5]

    fig, ax = plt.subplots(figsize=(9, 6), dpi=DPI)

    # Perfect calibration diagonal
    ax.plot([50, 75], [0.50, 0.75], color=COLORS["gray"], linestyle="--",
            linewidth=1.5, label="Perfect Calibration", alpha=0.7, zorder=1)

    prop_types_avail = sorted(set(p["prop_type"] for p in predictions))
    calibration_by_type = summary.get("calibration_by_type", {})

    for pt in prop_types_avail:
        color = PROP_COLORS.get(pt, COLORS["gray"])
        label = PROP_LABELS.get(pt, pt)

        # Build per-type calibration from summary if available, else compute directly
        type_data = calibration_by_type.get(pt, {})

        xs, ys, ns = [], [], []
        for i, bucket in enumerate(bucket_order):
            bdata = type_data.get(bucket)
            if bdata is None:
                continue
            n = bdata.get("count", 0)
            hr = bdata.get("actual_hit_rate")
            if n > 0 and hr is not None:
                xs.append(bucket_midpoints[i])
                ys.append(hr * 100)
                ns.append(n)

        if not xs:
            continue

        ax.plot(xs, ys, marker="o", color=color, linewidth=2.0,
                markersize=7, label=label, zorder=3)

        for x, y, n in zip(xs, ys, ns):
            ax.annotate(f"n={n}", (x, y), textcoords="offset points",
                        xytext=(0, 9), ha="center", fontsize=8, color=color)

    # Overall calibration line
    overall = summary.get("calibration", {})
    xs_all, ys_all, ns_all = [], [], []
    for i, bucket in enumerate(bucket_order):
        bdata = overall.get(bucket)
        if bdata is None:
            continue
        n = bdata.get("count", 0)
        hr = bdata.get("actual_hit_rate")
        if n > 0 and hr is not None:
            xs_all.append(bucket_midpoints[i])
            ys_all.append(hr * 100)
            ns_all.append(n)

    if xs_all:
        ax.plot(xs_all, ys_all, marker="s", color="black", linewidth=2.0,
                markersize=8, linestyle="-.", label="Overall", zorder=4, alpha=0.8)

    ax.set_xlim(48, 76)
    ax.set_ylim(40, 85)
    ax.set_xlabel("Predicted P(Over) — %", fontsize=LABEL_SIZE)
    ax.set_ylabel("Actual Hit Rate — %", fontsize=LABEL_SIZE)
    ax.set_title("Monte Carlo Calibration — Predicted vs Actual Over Rates",
                 fontsize=TITLE_SIZE, fontweight="bold")
    ax.legend(fontsize=10, loc="upper left")
    ax.tick_params(labelsize=TICK_SIZE)
    ax.set_xticks(bucket_midpoints)
    ax.set_xticklabels(["50–55%", "55–60%", "60–65%", "65–70%", "70%+"])
    fig.tight_layout()

    out_path = output_dir / "calibration_curve.png"
    fig.savefig(out_path, dpi=DPI, bbox_inches="tight")
    plt.close(fig)
    log.info("Saved calibration_curve.png")
    return out_path


def chart_cumulative_pnl(
    summary: Dict,
    daily: List[Dict],
    output_dir: Path,
    style: str,
) -> Path:
    """Cumulative P/L over time with shaded area and bet-count bar chart."""
    _apply_style(style)

    if not daily:
        daily = summary.get("daily_pnl", [])

    if not daily:
        log.warning("No daily P/L data available — generating placeholder chart")
        fig, ax = plt.subplots(figsize=(11, 5), dpi=DPI)
        ax.text(0.5, 0.5, "No daily P/L data available.\nRun backtest_simulator.py first.",
                ha="center", va="center", transform=ax.transAxes, fontsize=14, color=COLORS["gray"])
        ax.set_title("Cumulative P/L — Kelly Criterion Betting (edges > 3%)",
                     fontsize=TITLE_SIZE, fontweight="bold")
        out_path = output_dir / "cumulative_pnl.png"
        fig.savefig(out_path, dpi=DPI, bbox_inches="tight")
        plt.close(fig)
        return out_path

    dates = [datetime.strptime(d["date"], "%Y-%m-%d") for d in daily]
    cum_pnl = [d["cumulative_pnl"] for d in daily]
    daily_bets = [d.get("bets", 0) for d in daily]

    fig, ax1 = plt.subplots(figsize=(12, 6), dpi=DPI)
    ax2 = ax1.twinx()

    # Bar chart: daily bet count (background)
    ax2.bar(dates, daily_bets, color=COLORS["blue"], alpha=0.20, width=0.8, label="Daily Bets")
    ax2.set_ylabel("Daily Bets", fontsize=LABEL_SIZE - 1, color=COLORS["blue"])
    ax2.tick_params(axis="y", labelcolor=COLORS["blue"], labelsize=TICK_SIZE)
    ax2.set_ylim(0, max(daily_bets) * 4 if daily_bets else 10)

    # Shaded area under the cumulative line
    zeros = [0.0] * len(dates)
    ax1.fill_between(dates, cum_pnl, zeros,
                     where=[v >= 0 for v in cum_pnl],
                     color=COLORS["light_green"], alpha=0.5, interpolate=True)
    ax1.fill_between(dates, cum_pnl, zeros,
                     where=[v < 0 for v in cum_pnl],
                     color=COLORS["light_red"], alpha=0.5, interpolate=True)
    ax1.plot(dates, cum_pnl, color=COLORS["green"], linewidth=2.0, zorder=5, label="Cumulative P/L")
    ax1.axhline(y=0, color=COLORS["gray"], linewidth=1.2, linestyle="--", alpha=0.8)

    # Annotate final value
    final_pnl = cum_pnl[-1] if cum_pnl else 0.0
    color_final = COLORS["green"] if final_pnl >= 0 else COLORS["red"]
    ax1.annotate(
        f"Final: {final_pnl:+.2f}u",
        xy=(dates[-1], final_pnl),
        xytext=(-70, 12),
        textcoords="offset points",
        fontsize=11,
        color=color_final,
        fontweight="bold",
        arrowprops=dict(arrowstyle="->", color=color_final, lw=1.2),
    )

    ax1.set_xlabel("Date", fontsize=LABEL_SIZE)
    ax1.set_ylabel("Cumulative P/L (units)", fontsize=LABEL_SIZE)
    ax1.set_title("Cumulative P/L — Kelly Criterion Betting (edges > 3%)",
                  fontsize=TITLE_SIZE, fontweight="bold")
    ax1.tick_params(labelsize=TICK_SIZE)
    fig.autofmt_xdate(rotation=30)

    lines1, labels1 = ax1.get_legend_handles_labels()
    lines2, labels2 = ax2.get_legend_handles_labels()
    ax1.legend(lines1 + lines2, labels1 + labels2, loc="upper left", fontsize=10)

    fig.tight_layout()
    out_path = output_dir / "cumulative_pnl.png"
    fig.savefig(out_path, dpi=DPI, bbox_inches="tight")
    plt.close(fig)
    log.info("Saved cumulative_pnl.png")
    return out_path


def chart_accuracy_heatmap(
    summary: Dict,
    output_dir: Path,
    style: str,
) -> Path:
    """Heatmap of model performance metrics by prop type."""
    _apply_style(style)

    acc = summary.get("accuracy_by_type", {})
    roi = summary.get("roi_by_tier", {})
    brier = summary.get("brier_scores", {})

    prop_types = sorted(acc.keys())
    if not prop_types:
        prop_types = ["K", "TB", "H", "HR"]

    metrics = ["MAE", "Within 1%", "Within 2%", "Brier Score", "Skill Score"]
    data_matrix = []
    display_matrix = []

    for pt in prop_types:
        a = acc.get(pt, {})
        b = brier.get(pt, {})
        row_vals = [
            a.get("mae"),
            a.get("within_1"),
            a.get("within_2"),
            b.get("brier"),
            b.get("skill_score"),
        ]
        data_matrix.append(row_vals)
        display_row = []
        for i, v in enumerate(row_vals):
            if v is None:
                display_row.append("N/A")
            elif i == 0:   # MAE
                display_row.append(f"{v:.2f}")
            elif i in (1, 2):  # Within pct
                display_row.append(f"{v:.1f}%")
            else:
                display_row.append(f"{v:.3f}")
        display_matrix.append(display_row)

    # Normalize each column 0–1 for coloring (direction-aware)
    # MAE, Brier: lower is better → invert
    # Within 1/2, Skill Score: higher is better
    norm_matrix = np.full((len(prop_types), len(metrics)), 0.5)
    for col_idx in range(len(metrics)):
        col_vals = [row[col_idx] for row in data_matrix if row[col_idx] is not None]
        if len(col_vals) < 2:
            continue
        mn, mx = min(col_vals), max(col_vals)
        rng = mx - mn if mx != mn else 1.0
        for row_idx, row in enumerate(data_matrix):
            v = row[col_idx]
            if v is None:
                continue
            normalized = (v - mn) / rng
            # Invert for metrics where lower is better
            if col_idx in (0, 3):  # MAE, Brier
                normalized = 1.0 - normalized
            norm_matrix[row_idx, col_idx] = normalized

    fig, ax = plt.subplots(figsize=(10, max(3, len(prop_types) * 1.2 + 1.5)), dpi=DPI)

    cmap = sns.diverging_palette(10, 133, as_cmap=True)  # red→green
    im = ax.imshow(norm_matrix, cmap=cmap, vmin=0, vmax=1, aspect="auto")

    # Axis labels
    ax.set_xticks(range(len(metrics)))
    ax.set_xticklabels(metrics, fontsize=LABEL_SIZE)
    ax.set_yticks(range(len(prop_types)))
    ax.set_yticklabels([PROP_LABELS.get(pt, pt) for pt in prop_types], fontsize=LABEL_SIZE)

    # Annotate cells
    for ri, row in enumerate(display_matrix):
        for ci, val in enumerate(row):
            text_color = "white" if norm_matrix[ri, ci] < 0.25 or norm_matrix[ri, ci] > 0.80 else "black"
            ax.text(ci, ri, val, ha="center", va="center",
                    fontsize=LABEL_SIZE, color=text_color, fontweight="bold")

    ax.set_title("Model Performance by Prop Type", fontsize=TITLE_SIZE, fontweight="bold", pad=15)
    plt.colorbar(im, ax=ax, label="Relative Performance (green = better)")
    fig.tight_layout()

    out_path = output_dir / "accuracy_heatmap.png"
    fig.savefig(out_path, dpi=DPI, bbox_inches="tight")
    plt.close(fig)
    log.info("Saved accuracy_heatmap.png")
    return out_path


def chart_best_worst_table(
    summary: Dict,
    output_dir: Path,
    style: str,
) -> Path:
    """Side-by-side tables of best and worst 10 predictions."""
    _apply_style(style)

    best = summary.get("best_predictions", [])[:10]
    worst = summary.get("worst_predictions", [])[:10]

    cols = ["Player", "Date", "Type", "Proj", "Actual", "Error"]

    def _rows(preds):
        rows = []
        for p in preds:
            rows.append([
                p.get("player_name", "—")[:20],
                p.get("game_date", "—"),
                p.get("prop_type", "—"),
                f"{p.get('sim_mean', 0):.1f}",
                f"{p.get('actual_value', 0):.1f}",
                f"{p.get('absolute_error', 0):.2f}",
            ])
        return rows

    best_rows = _rows(best)
    worst_rows = _rows(worst)
    n = max(len(best_rows), len(worst_rows))

    # Pad to same length
    while len(best_rows) < n:
        best_rows.append([""] * len(cols))
    while len(worst_rows) < n:
        worst_rows.append([""] * len(cols))

    fig, (ax_l, ax_r) = plt.subplots(1, 2, figsize=(16, max(4, n * 0.45 + 1.5)), dpi=DPI)

    for ax in (ax_l, ax_r):
        ax.axis("off")

    def _render_table(ax, title, rows, color):
        ax.set_title(title, fontsize=TITLE_SIZE - 1, fontweight="bold",
                     color=color, pad=8)
        if not rows:
            ax.text(0.5, 0.5, "No data", ha="center", va="center",
                    transform=ax.transAxes, fontsize=12)
            return
        tbl = ax.table(
            cellText=rows,
            colLabels=cols,
            cellLoc="center",
            loc="upper center",
        )
        tbl.auto_set_font_size(False)
        tbl.set_fontsize(9)
        tbl.auto_set_column_width(range(len(cols)))

        light = "#e8f5e9" if color == COLORS["green"] else "#fce8e6"
        for (row, col), cell in tbl.get_celld().items():
            if row == 0:
                cell.set_facecolor(color)
                cell.set_text_props(color="white", fontweight="bold")
            else:
                cell.set_facecolor(light)
            cell.set_edgecolor("#cccccc")

    _render_table(ax_l, "Best 10 Predictions (Lowest Error)", best_rows, COLORS["green"])
    _render_table(ax_r, "Worst 10 Predictions (Highest Error)", worst_rows, COLORS["red"])

    fig.suptitle("Best & Worst Predictions", fontsize=TITLE_SIZE, fontweight="bold", y=1.01)
    fig.tight_layout()

    out_path = output_dir / "best_worst_table.png"
    fig.savefig(out_path, dpi=DPI, bbox_inches="tight")
    plt.close(fig)
    log.info("Saved best_worst_table.png")
    return out_path


def chart_edge_distribution(
    predictions: List[Dict],
    output_dir: Path,
    style: str,
) -> Path:
    """2×2 histogram grid showing P(over)-0.5 edge per prop type."""
    _apply_style(style)

    prop_types = sorted(set(p["prop_type"] for p in predictions))
    n_types = len(prop_types)
    if n_types == 0:
        prop_types = ["K"]

    ncols = 2
    nrows = (n_types + 1) // 2

    fig, axes = plt.subplots(nrows, ncols,
                             figsize=(12, max(4, nrows * 4)),
                             dpi=DPI, squeeze=False)

    thresholds = [0.03, 0.05, 0.10]
    threshold_colors = [COLORS["yellow"], COLORS["green"], COLORS["purple"]]

    for idx, pt in enumerate(prop_types):
        row, col = divmod(idx, ncols)
        ax = axes[row][col]
        color = PROP_COLORS.get(pt, COLORS["blue"])

        preds_pt = [p for p in predictions if p["prop_type"] == pt]
        edges = []
        for p in preds_pt:
            kr = p.get("kelly_results", {})
            if kr:
                p_model = kr.get("p_model", 0.5)
                direction = kr.get("direction", "OVER")
                # Edge is distance from 50%
                edge = p_model - 0.5 if direction == "OVER" else (1 - p_model) - 0.5
                edges.append(edge)

        if not edges:
            ax.text(0.5, 0.5, "No data", ha="center", va="center",
                    transform=ax.transAxes, fontsize=12)
            ax.set_title(f"{PROP_LABELS.get(pt, pt)} ({pt})", fontsize=LABEL_SIZE)
            continue

        edges_arr = np.array(edges)
        ax.hist(edges_arr, bins=25, color=color, alpha=0.75, edgecolor="white", linewidth=0.5)

        for thresh, tcol in zip(thresholds, threshold_colors):
            count_above = int(np.sum(edges_arr >= thresh))
            ax.axvline(x=thresh, color=tcol, linewidth=1.8, linestyle="--", alpha=0.9)
            ax.annotate(
                f"≥{int(thresh*100)}%: {count_above}",
                xy=(thresh, ax.get_ylim()[1] * 0.85),
                xytext=(thresh + 0.003, ax.get_ylim()[1] * 0.80),
                fontsize=8,
                color=tcol,
                fontweight="bold",
            )

        ax.set_xlabel("Edge Magnitude (P(model) − 0.50)", fontsize=LABEL_SIZE - 1)
        ax.set_ylabel("Frequency", fontsize=LABEL_SIZE - 1)
        ax.set_title(f"{PROP_LABELS.get(pt, pt)} ({pt}) — n={len(edges)}", fontsize=LABEL_SIZE)
        ax.tick_params(labelsize=TICK_SIZE)

    # Hide any unused subplots
    for idx in range(n_types, nrows * ncols):
        row, col = divmod(idx, ncols)
        axes[row][col].set_visible(False)

    fig.suptitle("Edge Distribution by Prop Type", fontsize=TITLE_SIZE, fontweight="bold")
    fig.tight_layout()

    out_path = output_dir / "edge_distribution.png"
    fig.savefig(out_path, dpi=DPI, bbox_inches="tight")
    plt.close(fig)
    log.info("Saved edge_distribution.png")
    return out_path


def chart_mc_vs_point_comparison(
    comparison: Optional[Dict],
    summary: Dict,
    output_dir: Path,
    style: str,
) -> Path:
    """Bar chart comparing Monte Carlo vs Point Estimate on MAE, ROI%, Brier score."""
    _apply_style(style)

    has_comparison = comparison is not None and bool(comparison)

    if not has_comparison:
        fig, ax = plt.subplots(figsize=(9, 4), dpi=DPI)
        ax.axis("off")
        ax.text(
            0.5, 0.5,
            "Comparison data not available.\nRun compare_models.py to generate model_comparison.json",
            ha="center", va="center", transform=ax.transAxes,
            fontsize=13, color=COLORS["gray"],
            bbox=dict(boxstyle="round,pad=0.5", facecolor="#f5f5f5", edgecolor=COLORS["gray"]),
        )
        ax.set_title("Monte Carlo vs Point Estimate Comparison",
                     fontsize=TITLE_SIZE, fontweight="bold")
        out_path = output_dir / "mc_vs_point_comparison.png"
        fig.savefig(out_path, dpi=DPI, bbox_inches="tight")
        plt.close(fig)
        log.info("Saved mc_vs_point_comparison.png (placeholder)")
        return out_path

    # Extract comparison data
    # Expected keys: prop types → {mc: {mae, roi_pct, brier}, point: {mae, roi_pct, brier}}
    prop_types = sorted(comparison.keys())
    metrics = ["MAE", "ROI%", "Brier Score"]
    lower_better = [True, False, True]  # for color logic

    fig, axes = plt.subplots(1, 3, figsize=(15, 5), dpi=DPI)

    for ax_idx, (metric, lb) in enumerate(zip(metrics, lower_better)):
        ax = axes[ax_idx]
        metric_key = metric.lower().replace("%", "_pct").replace(" ", "_")
        mc_vals, pt_vals, labels = [], [], []

        for pt in prop_types:
            mc_v = comparison[pt].get("mc", {}).get(metric_key)
            pt_v = comparison[pt].get("point", {}).get(metric_key)
            if mc_v is not None and pt_v is not None:
                mc_vals.append(mc_v)
                pt_vals.append(pt_v)
                labels.append(PROP_LABELS.get(pt, pt))

        if not labels:
            ax.text(0.5, 0.5, "No data", ha="center", va="center",
                    transform=ax.transAxes, fontsize=12)
            ax.set_title(metric, fontsize=LABEL_SIZE)
            continue

        x = np.arange(len(labels))
        w = 0.35
        bars_mc = ax.bar(x - w / 2, mc_vals, w, label="Monte Carlo",
                         color=COLORS["blue"], alpha=0.85)
        bars_pt = ax.bar(x + w / 2, pt_vals, w, label="Point Estimate",
                         color=COLORS["yellow"], alpha=0.85)

        # Add value labels on bars
        for bar in bars_mc:
            h = bar.get_height()
            ax.annotate(f"{h:.2f}", xy=(bar.get_x() + bar.get_width() / 2, h),
                        xytext=(0, 3), textcoords="offset points",
                        ha="center", fontsize=8)
        for bar in bars_pt:
            h = bar.get_height()
            ax.annotate(f"{h:.2f}", xy=(bar.get_x() + bar.get_width() / 2, h),
                        xytext=(0, 3), textcoords="offset points",
                        ha="center", fontsize=8)

        ax.set_xticks(x)
        ax.set_xticklabels(labels, fontsize=TICK_SIZE)
        ax.set_title(metric, fontsize=LABEL_SIZE, fontweight="bold")
        ax.legend(fontsize=9)
        ax.tick_params(labelsize=TICK_SIZE)

    fig.suptitle("Monte Carlo vs Point Estimate — Model Comparison",
                 fontsize=TITLE_SIZE, fontweight="bold")
    fig.tight_layout()

    out_path = output_dir / "mc_vs_point_comparison.png"
    fig.savefig(out_path, dpi=DPI, bbox_inches="tight")
    plt.close(fig)
    log.info("Saved mc_vs_point_comparison.png")
    return out_path


def chart_sim_distribution_example(
    predictions: List[Dict],
    output_dir: Path,
    style: str,
) -> Path:
    """Show simulation distributions for 3–4 interesting predictions."""
    _apply_style(style)

    if not predictions:
        fig, ax = plt.subplots(figsize=(9, 4), dpi=DPI)
        ax.text(0.5, 0.5, "No predictions available.", ha="center", va="center",
                transform=ax.transAxes, fontsize=14, color=COLORS["gray"])
        ax.set_title("Simulation Distribution Examples", fontsize=TITLE_SIZE, fontweight="bold")
        out_path = output_dir / "sim_distribution_example.png"
        fig.savefig(out_path, dpi=DPI, bbox_inches="tight")
        plt.close(fig)
        return out_path

    # Select 4 interesting cases: highest confidence, biggest edge, biggest miss, most recent
    preds_with_edge = [
        p for p in predictions
        if p.get("kelly_results") and p["kelly_results"].get("kelly_fraction", 0) > 0
    ]

    selected: List[Dict] = []
    labels_used: List[str] = []

    # 1. Highest confidence (highest p_model)
    if preds_with_edge:
        p = max(preds_with_edge, key=lambda x: x["kelly_results"].get("p_model", 0))
        if p not in selected:
            selected.append(p)
            labels_used.append("Highest Confidence")

    # 2. Biggest edge
    if preds_with_edge:
        p = max(preds_with_edge, key=lambda x: x["kelly_results"].get("edge_pct", 0))
        if p not in selected:
            selected.append(p)
            labels_used.append("Biggest Edge")

    # 3. Biggest miss (highest absolute error)
    if predictions:
        p = max(predictions, key=lambda x: x.get("absolute_error", 0))
        if p not in selected:
            selected.append(p)
            labels_used.append("Biggest Miss")

    # 4. Best prediction (lowest absolute error)
    if predictions:
        p = min(predictions, key=lambda x: x.get("absolute_error", 0))
        if p not in selected:
            selected.append(p)
            labels_used.append("Best Prediction")

    selected = selected[:4]
    labels_used = labels_used[:4]
    n = len(selected)
    ncols = 2
    nrows = (n + 1) // 2

    fig, axes = plt.subplots(nrows, ncols,
                             figsize=(13, max(5, nrows * 4.5)),
                             dpi=DPI, squeeze=False)

    for idx, (pred, case_label) in enumerate(zip(selected, labels_used)):
        row, col = divmod(idx, ncols)
        ax = axes[row][col]
        pt = pred.get("prop_type", "K")
        color = PROP_COLORS.get(pt, COLORS["blue"])

        # Use stored sim samples if available, else reconstruct from mean/std/percentiles
        sim_samples = pred.get("_sim_samples")
        if sim_samples:
            sim_arr = np.array(sim_samples)
        else:
            mean = pred.get("sim_mean", 5.0)
            std = pred.get("sim_std", 1.5)
            rng = np.random.default_rng(pred.get("game_pk", 0) % (2**31))
            sim_arr = np.maximum(rng.normal(mean, std, 3000), 0)

        actual = pred.get("actual_value", 0)
        kr = pred.get("kelly_results", {})
        best_line = kr.get("best_line")
        p_over = kr.get("p_model", 0.5)
        direction = kr.get("direction", "OVER")

        ax.hist(sim_arr, bins=40, color=color, alpha=0.65, edgecolor="white",
                linewidth=0.4, density=True)

        # Actual value — red vertical line
        ax.axvline(x=actual, color=COLORS["red"], linewidth=2.2, linestyle="-",
                   label=f"Actual: {actual:.1f}", zorder=5)

        # Best prop line — dashed blue
        if best_line is not None:
            try:
                line_val = float(best_line)
                ax.axvline(x=line_val, color=COLORS["blue"], linewidth=1.8,
                           linestyle="--", label=f"Line: {best_line}", zorder=4)
            except ValueError:
                pass

        player = pred.get("player_name", "Unknown")[:22]
        date = pred.get("game_date", "")
        title = (f"{case_label}\n{player} ({pt}) — {date}\n"
                 f"P({direction}@{best_line}) = {p_over:.1%}")
        ax.set_title(title, fontsize=9.5, fontweight="bold")
        ax.set_xlabel(f"Simulated {PROP_LABELS.get(pt, pt)}", fontsize=LABEL_SIZE - 1)
        ax.set_ylabel("Density", fontsize=LABEL_SIZE - 1)
        ax.legend(fontsize=8.5)
        ax.tick_params(labelsize=TICK_SIZE)

    # Hide unused subplots
    for idx in range(n, nrows * ncols):
        r, c = divmod(idx, ncols)
        axes[r][c].set_visible(False)

    fig.suptitle("Monte Carlo Simulation Distribution Examples",
                 fontsize=TITLE_SIZE, fontweight="bold")
    fig.tight_layout()

    out_path = output_dir / "sim_distribution_example.png"
    fig.savefig(out_path, dpi=DPI, bbox_inches="tight")
    plt.close(fig)
    log.info("Saved sim_distribution_example.png")
    return out_path


# ---------------------------------------------------------------------------
# Markdown report builder
# ---------------------------------------------------------------------------

def _fmt_pct(v: Optional[float], decimals: int = 1) -> str:
    if v is None:
        return "N/A"
    return f"{v:.{decimals}f}%"


def _fmt_f(v: Optional[float], decimals: int = 2) -> str:
    if v is None:
        return "N/A"
    return f"{v:.{decimals}f}"


def _fmt_i(v: Optional[int]) -> str:
    if v is None:
        return "N/A"
    return str(int(v))


def _relative_path(target: Path, base: Path) -> str:
    """Return a relative path from base (file) to target (file)."""
    try:
        return str(target.relative_to(base.parent))
    except ValueError:
        # Fall back to relative_to project root heuristic
        parts_t = target.parts
        parts_b = base.parent.parts
        common = 0
        for a, b in zip(parts_t, parts_b):
            if a == b:
                common += 1
            else:
                break
        up = len(parts_b) - common
        rel = ("../" * up) + "/".join(parts_t[common:])
        return rel


def build_markdown_report(
    predictions: List[Dict],
    summary: Dict,
    daily: List[Dict],
    comparison: Optional[Dict],
    output_dir: Path,
    report_path: Path,
    is_demo: bool = False,
) -> str:
    """Build the full Markdown report string."""

    timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    dr = summary.get("date_range", {})
    date_start = dr.get("start", "N/A")
    date_end = dr.get("end", "N/A")
    cfg = summary.get("model_config", {})
    sims = cfg.get("sims", 3000)
    total_preds = summary.get("total_predictions", len(predictions))

    overall_pnl = summary.get("overall_pnl", {})
    total_bets = overall_pnl.get("total_bets", 0)
    total_pnl_val = overall_pnl.get("total_pnl", 0.0)
    roi_pct = overall_pnl.get("roi_pct")

    acc = summary.get("accuracy_by_type", {})
    prop_types = sorted(acc.keys()) or ["K", "TB", "H", "HR"]
    brier_data = summary.get("brier_scores", {})
    roi_tier = summary.get("roi_by_tier", {})

    # ---- Executive summary ----
    best_pt = None
    best_mae = float("inf")
    for pt, a in acc.items():
        mae = a.get("mae")
        if mae is not None and mae < best_mae:
            best_mae = mae
            best_pt = pt

    calibration = summary.get("calibration", {})
    calib_note = "calibration data unavailable"
    hi_bucket = calibration.get("70+", {})
    if hi_bucket.get("count", 0) > 0 and hi_bucket.get("actual_hit_rate") is not None:
        hr = hi_bucket["actual_hit_rate"]
        calib_note = (
            f"high-confidence (70%+) bets hit at a {hr:.1%} rate "
            f"(n={hi_bucket['count']})"
        )

    roi_summary = (
        f"Overall ROI is {_fmt_pct(roi_pct)} across {total_bets} Kelly-sized bets "
        f"({_fmt_f(total_pnl_val, 2)} units net)."
        if roi_pct is not None
        else "ROI data not available."
    )

    exec_summary = (
        f"The Monte Carlo backtest covers **{total_preds:,} predictions** "
        f"from **{date_start}** to **{date_end}** using {sims:,} simulations per game. "
        f"{'Best accuracy on ' + PROP_LABELS.get(best_pt, best_pt) + f' (MAE {best_mae:.2f}).' if best_pt else ''} "
        f"Calibration analysis shows {calib_note}. "
        f"{roi_summary}"
    )
    if is_demo:
        exec_summary = "**[DEMO DATA]** " + exec_summary

    # ---- Chart relative paths ----
    def chart_ref(filename: str) -> str:
        chart_path = output_dir / filename
        rel = _relative_path(chart_path, report_path)
        return rel

    # ---- Accuracy table rows ----
    acc_rows = []
    for pt in prop_types:
        a = acc.get(pt, {})
        b = brier_data.get(pt, {})
        r = roi_tier.get(pt, {})  # ROI by type isn't standard, use tier-level as fallback
        # Try to find an ROI-like figure from tier data (approximate)
        acc_rows.append(
            f"| {PROP_LABELS.get(pt, pt)} ({pt}) "
            f"| {_fmt_i(a.get('count'))} "
            f"| {_fmt_f(a.get('mae'), 2)} "
            f"| {_fmt_pct(a.get('within_1'))} "
            f"| {_fmt_pct(a.get('within_2'))} "
            f"| {_fmt_f(b.get('brier'), 3)} "
            f"| {_fmt_f(b.get('skill_score'), 3)} |"
        )

    # ---- ROI tier table ----
    tier_rows = []
    for tier in ["A", "B", "C", "D"]:
        r = roi_tier.get(tier, {})
        tier_rows.append(
            f"| {tier} "
            f"| {_fmt_i(r.get('count'))} "
            f"| {_fmt_f(r.get('total_wagered'), 2)} "
            f"| {_fmt_f(r.get('total_pnl'), 2)} "
            f"| {_fmt_pct(r.get('roi_pct'))} |"
        )

    # ---- Brier table ----
    brier_rows = []
    for pt in prop_types:
        b = brier_data.get(pt, {})
        brier_rows.append(
            f"| {PROP_LABELS.get(pt, pt)} ({pt}) "
            f"| {_fmt_f(b.get('brier'), 4)} "
            f"| {_fmt_f(b.get('naive_brier'), 4)} "
            f"| {_fmt_f(b.get('skill_score'), 4)} |"
        )

    # ---- Best/Worst predictions tables ----
    def _pred_table(preds: List[Dict]) -> str:
        if not preds:
            return "_No data available._"
        header = "| Player | Date | Type | Projected | Actual | Error |\n|--------|------|------|-----------|--------|-------|"
        rows = []
        for p in preds:
            rows.append(
                f"| {p.get('player_name', '—')} "
                f"| {p.get('game_date', '—')} "
                f"| {p.get('prop_type', '—')} "
                f"| {_fmt_f(p.get('sim_mean'), 2)} "
                f"| {_fmt_f(p.get('actual_value'), 1)} "
                f"| {_fmt_f(p.get('absolute_error'), 2)} |"
            )
        return header + "\n" + "\n".join(rows)

    best_table = _pred_table(summary.get("best_predictions", [])[:10])
    worst_table = _pred_table(summary.get("worst_predictions", [])[:10])

    # ---- Comparison section ----
    if comparison:
        comparison_section = f"""## Monte Carlo vs Point Estimate

![Model Comparison]({chart_ref('mc_vs_point_comparison.png')})

The chart above compares Monte Carlo simulation against a point-estimate baseline
across MAE, ROI%, and Brier score for each prop type.
"""
    else:
        comparison_section = f"""## Monte Carlo vs Point Estimate

![Model Comparison]({chart_ref('mc_vs_point_comparison.png')})

> Comparison data not yet available. Run `compare_models.py` to generate
> `model_comparison.json` and re-run this report.
"""

    # ---- Assemble full report ----
    umpire_note = "enabled" if cfg.get("umpire_enabled") else "disabled"
    weather_note = "enabled" if cfg.get("weather_enabled") else "disabled"
    demo_banner = "\n> **Note: This report was generated using synthetic demo data.**\n> Run `backtest_simulator.py` on real data to populate with actual results.\n" if is_demo else ""

    report = f"""# BaselineMLB Monte Carlo Backtest Report
{demo_banner}
**Generated:** {timestamp}  
**Date Range:** {date_start} to {date_end}  
**Model:** Monte Carlo Simulator v1.0  
**Simulations per game:** {sims:,}  
**Total Predictions:** {total_preds:,}  
**Umpire factor:** {umpire_note} | **Weather factor:** {weather_note}

---

## Executive Summary

{exec_summary.strip()}

---

## Model Performance Overview

### Accuracy by Prop Type

![Accuracy Heatmap]({chart_ref('accuracy_heatmap.png')})

| Prop Type | Predictions | MAE | Within 1 | Within 2 | Brier | Skill Score |
|-----------|------------|-----|----------|----------|-------|-------------|
{chr(10).join(acc_rows)}

> **MAE** = mean absolute error (projected vs actual).  
> **Within 1 / Within 2** = % of predictions within 1 or 2 of the actual value.  
> **Skill Score** = 1 − (Brier / Naive Brier); positive = better than baseline.

---

## Calibration Analysis

![Calibration Curves]({chart_ref('calibration_curve.png')})

The calibration chart plots predicted P(Over) buckets against observed hit rates.
A perfectly calibrated model follows the dashed diagonal. Points above the diagonal
indicate under-confidence (the model is more right than it thinks); points below
indicate over-confidence.

---

## Betting Performance

### Cumulative P/L

![Cumulative P/L Over Time]({chart_ref('cumulative_pnl.png')})

> Kelly criterion at quarter-Kelly (25%) on edges > 3%, capped at 5% of bankroll.  
> Standard juice assumed: −110 (implied 52.4% breakeven).

### ROI by Confidence Tier

| Tier | Definition | Bets | Wagered | P/L | ROI% |
|------|-----------|------|---------|-----|------|
| A    | P > 65%   | {_fmt_i(roi_tier.get('A', {}).get('count'))} | {_fmt_f(roi_tier.get('A', {}).get('total_wagered'), 2)} | {_fmt_f(roi_tier.get('A', {}).get('total_pnl'), 2)} | {_fmt_pct(roi_tier.get('A', {}).get('roi_pct'))} |
| B    | P 60–65%  | {_fmt_i(roi_tier.get('B', {}).get('count'))} | {_fmt_f(roi_tier.get('B', {}).get('total_wagered'), 2)} | {_fmt_f(roi_tier.get('B', {}).get('total_pnl'), 2)} | {_fmt_pct(roi_tier.get('B', {}).get('roi_pct'))} |
| C    | P 55–60%  | {_fmt_i(roi_tier.get('C', {}).get('count'))} | {_fmt_f(roi_tier.get('C', {}).get('total_wagered'), 2)} | {_fmt_f(roi_tier.get('C', {}).get('total_pnl'), 2)} | {_fmt_pct(roi_tier.get('C', {}).get('roi_pct'))} |
| D    | P < 55%   | {_fmt_i(roi_tier.get('D', {}).get('count'))} | {_fmt_f(roi_tier.get('D', {}).get('total_wagered'), 2)} | {_fmt_f(roi_tier.get('D', {}).get('total_pnl'), 2)} | {_fmt_pct(roi_tier.get('D', {}).get('roi_pct'))} |
| **Overall** | All tiers | **{_fmt_i(overall_pnl.get('total_bets'))}** | **{_fmt_f(overall_pnl.get('total_wagered'), 2)}** | **{_fmt_f(overall_pnl.get('total_pnl'), 2)}** | **{_fmt_pct(overall_pnl.get('roi_pct'))}** |

### Edge Distribution

![Edge Distribution by Prop Type]({chart_ref('edge_distribution.png')})

---

{comparison_section}

---

## Brier Score Analysis

| Prop | MC Brier | Naive Brier | Skill Score |
|------|----------|-------------|-------------|
{chr(10).join(brier_rows)}

> **Brier Score** = mean squared error of probability forecasts (lower = better).  
> **Naive Brier** = score of a 50/50 coin-flip baseline (0.25).  
> **Skill Score** = 1 − (Brier / Naive); positive means the model beats the baseline.

---

## Simulation Examples

![Simulation Distribution Examples]({chart_ref('sim_distribution_example.png')})

Each panel shows the full distribution of {sims:,} Monte Carlo simulated outcomes for a
selected prediction. The **red line** marks the actual outcome; the **dashed blue line**
marks the prop line used for the Kelly bet. P(direction@line) shows the model's
forecast probability.

---

## Top Predictions

### Best 10 (Lowest Absolute Error)

{best_table}

### Worst 10 (Highest Absolute Error)

{worst_table}

---

## Methodology Notes

- **Simulations:** {sims:,} per game using NumPy random generation with fixed seed for reproducibility
- **Pitcher K model:** Blended K/PA (career 70% + recent-14d 30%), opponent K%, park K factor, umpire factor
- **Batter TB/H/HR model:** Career hit-type rates (1B/2B/3B/HR per PA), park TB factor, platoon splits
- **Kelly criterion:** Quarter-Kelly (25%) on edges > 3%, capped at 5% of bankroll
- **Standard juice:** −110 on all bets (implied breakeven: 52.4%)
- **Confidence tiers:** A (P > 65%), B (60–65%), C (55–60%), D (< 55%)
- **Brier score baseline:** 0.25 (random 50/50 forecast)
- **Umpire factor:** {umpire_note}
- **Weather factor:** {weather_note}

---
*Generated by BaselineMLB Monte Carlo Backtest System — generate_backtest_report.py*
"""
    return report


# ---------------------------------------------------------------------------
# Main orchestrator
# ---------------------------------------------------------------------------

def generate_report(
    predictions: List[Dict],
    summary: Dict,
    daily: List[Dict],
    output_dir: Path,
    report_path: Path,
    comparison: Optional[Dict] = None,
    style: str = "seaborn-v0_8-darkgrid",
    is_demo: bool = False,
) -> Path:
    """
    Generate all charts and write the Markdown report.

    Returns the path to the written report file.
    Can be imported and called from other scripts (e.g. compare_models.py).
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    report_path.parent.mkdir(parents=True, exist_ok=True)

    log.info("Generating calibration curve chart...")
    chart_calibration_curve(summary, predictions, output_dir, style)

    log.info("Generating cumulative P/L chart...")
    chart_cumulative_pnl(summary, daily, output_dir, style)

    log.info("Generating accuracy heatmap...")
    chart_accuracy_heatmap(summary, output_dir, style)

    log.info("Generating best/worst table chart...")
    chart_best_worst_table(summary, output_dir, style)

    log.info("Generating edge distribution chart...")
    chart_edge_distribution(predictions, output_dir, style)

    log.info("Generating model comparison chart...")
    chart_mc_vs_point_comparison(comparison, summary, output_dir, style)

    log.info("Generating simulation distribution examples...")
    chart_sim_distribution_example(predictions, output_dir, style)

    log.info("Building Markdown report...")
    report_md = build_markdown_report(
        predictions=predictions,
        summary=summary,
        daily=daily,
        comparison=comparison,
        output_dir=output_dir,
        report_path=report_path,
        is_demo=is_demo,
    )

    report_path.write_text(report_md, encoding="utf-8")
    log.info(f"Report written to: {report_path}")
    return report_path


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def _load_json(path: Optional[str], label: str) -> Optional[Any]:
    if not path:
        return None
    p = Path(path)
    if not p.exists():
        log.warning(f"{label} file not found: {path}")
        return None
    try:
        with open(p, encoding="utf-8") as fh:
            data = json.load(fh)
        log.info(f"Loaded {label}: {path} ({len(data) if isinstance(data, list) else 'object'})")
        return data
    except (json.JSONDecodeError, OSError) as exc:
        log.error(f"Failed to load {label}: {exc}")
        return None


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate comprehensive Markdown backtest report with charts.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--predictions", metavar="PATH",
                        help="Path to backtest_predictions_*.json")
    parser.add_argument("--summary", metavar="PATH",
                        help="Path to backtest_summary_*.json")
    parser.add_argument("--daily", metavar="PATH",
                        help="Path to backtest_daily_*.json (optional)")
    parser.add_argument("--output-dir", metavar="DIR", default="output/backtest",
                        help="Directory to save PNG charts (default: output/backtest)")
    parser.add_argument("--report-path", metavar="PATH", default="docs/BACKTEST_REPORT.md",
                        help="Path for the generated Markdown report (default: docs/BACKTEST_REPORT.md)")
    parser.add_argument("--comparison", metavar="PATH",
                        help="Optional path to model_comparison.json from compare_models.py")
    parser.add_argument("--style", default="seaborn-v0_8-darkgrid",
                        help="Matplotlib style (default: seaborn-v0_8-darkgrid)")
    parser.add_argument("--demo", action="store_true",
                        help="Generate a demo report with synthetic data (ignores missing files)")
    parser.add_argument("-v", "--verbose", action="store_true",
                        help="Enable DEBUG logging")

    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    # Resolve paths relative to CWD (or project root)
    output_dir = Path(args.output_dir)
    report_path = Path(args.report_path)

    # Load data
    predictions = _load_json(args.predictions, "predictions")
    summary = _load_json(args.summary, "summary")
    daily_raw = _load_json(args.daily, "daily")
    comparison = _load_json(args.comparison, "comparison")

    is_demo = False

    # Determine if we need to generate demo data
    missing_predictions = predictions is None
    missing_summary = summary is None

    if args.demo or (missing_predictions and missing_summary):
        if not args.demo:
            log.warning(
                "No predictions or summary files provided/found. "
                "Generating DEMO report with synthetic data. "
                "Use --predictions and --summary for a real report."
            )
        log.info("Generating demo data (600 synthetic predictions)...")
        predictions = _make_demo_predictions(n=600)
        summary = _make_demo_summary(predictions)
        daily_raw = _make_demo_daily(summary)
        is_demo = True
    else:
        # Partial data: build summary from predictions if summary missing
        if missing_predictions:
            log.error("--predictions file is required when --summary is provided alone.")
            return 1
        if missing_summary:
            log.info("Summary file not found — deriving from predictions...")
            summary = _make_demo_summary(predictions)

    daily: List[Dict] = []
    if daily_raw:
        if isinstance(daily_raw, list):
            daily = daily_raw
        elif isinstance(daily_raw, dict):
            daily = daily_raw.get("daily_pnl", [])
    else:
        # Derive from summary
        daily = summary.get("daily_pnl", [])

    generate_report(
        predictions=predictions,
        summary=summary,
        daily=daily,
        output_dir=output_dir,
        report_path=report_path,
        comparison=comparison,
        style=args.style,
        is_demo=is_demo,
    )

    print(f"\nReport generated: {report_path}")
    print(f"Charts saved to:  {output_dir}/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
