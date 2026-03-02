#!/usr/bin/env python3
"""
compare_models.py — Baseline MLB
Multi-model comparison tool for the Monte Carlo backtest system.

Orchestrates multiple runs of backtest_simulator.py (and optionally
backtest_projections.py) with different configurations to quantify the
marginal value of each data source / model factor.

Usage:
  python scripts/compare_models.py \\
    --start 2025-07-01 --end 2025-07-31 \\
    --configs baseline,no_umpire,career_only,point_estimate \\
    --prop-types K \\
    --sample-days 10 \\
    --output-dir output/backtest/compare \\
    --generate-report

Outputs:
  output/backtest/compare/model_comparison.json   — comparison table
  output/backtest/compare/{config}/               — per-config backtest files
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("compare_models")

# ---------------------------------------------------------------------------
# Project root — scripts/ is one level below the project root
# ---------------------------------------------------------------------------

SCRIPTS_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPTS_DIR.parent

# ---------------------------------------------------------------------------
# Model configurations
# ---------------------------------------------------------------------------

CONFIGS: dict[str, dict[str, Any]] = {
    "baseline": {
        "label": "MC Full Model (3K sims)",
        "args": [],
        "description": "Monte Carlo with all factors enabled",
    },
    "no_umpire": {
        "label": "MC No Umpire",
        "args": ["--no-umpire"],
        "description": "Monte Carlo without umpire strike rate factor",
    },
    "no_weather": {
        "label": "MC No Weather",
        "args": ["--no-weather"],
        "description": "Monte Carlo without weather adjustments",
    },
    "no_recent_form": {
        "label": "MC No Recent Form",
        "args": ["--config", str(PROJECT_ROOT / "configs" / "career_only.json")],
        "description": "Monte Carlo with 100% career weight (no recent-form blend)",
    },
    "career_only": {
        "label": "MC Career Only",
        "args": ["--config", str(PROJECT_ROOT / "configs" / "career_only.json")],
        "description": "Monte Carlo with only career stats + park factors",
    },
    "low_sims": {
        "label": "MC 500 sims",
        "args": ["--sims", "500"],
        "description": "Monte Carlo with reduced simulation count",
    },
    "high_sims": {
        "label": "MC 10K sims",
        "args": ["--sims", "10000"],
        "description": "Monte Carlo with high simulation count",
    },
    "point_estimate": {
        "label": "Point Estimate v1.0",
        "args": None,  # Special handling — runs backtest_projections.py instead
        "description": "Existing simple point-estimate model (v1.0)",
    },
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _safe_float(val: Any, default: Any = None) -> Any:
    """Return float if val is a real number, else default."""
    if val is None:
        return default
    try:
        f = float(val)
        if math.isnan(f) or math.isinf(f):
            return default
        return f
    except (TypeError, ValueError):
        return default


def _fmt(val: Any, decimals: int = 3, suffix: str = "") -> str:
    """Format a numeric value or return 'N/A'."""
    f = _safe_float(val)
    if f is None:
        return "N/A"
    return f"{f:.{decimals}f}{suffix}"


def _mean_calibration_error(calibration: dict) -> Optional[float]:
    """
    Compute mean absolute calibration error from a calibration bucket dict
    (as produced by backtest_simulator.py).
    """
    errors = []
    for bucket in calibration.values():
        ce = _safe_float(bucket.get("calibration_error"))
        n = bucket.get("n", 0)
        if ce is not None and n > 0:
            errors.append(ce)
    if not errors:
        return None
    return round(sum(errors) / len(errors), 4)


def _extract_summary_metrics(
    summary: dict,
    prop_types: list[str],
) -> dict[str, Any]:
    """
    Pull the key comparison metrics out of a backtest_simulator.py summary JSON.

    Returns a dict with:
      overall.mae, overall.brier, overall.roi_pct, overall.total_pnl,
      overall.calibration_error
      accuracy_by_type.{K,TB,H,HR}.{mae, within_1, within_2, brier, roi_pct}
    """
    by_type_raw = summary.get("by_prop_type", {})
    summary.get("roi_by_confidence_tier", {})
    overall_pl = summary.get("overall_pl", {})
    calibration = summary.get("calibration", {})

    # ---- per-type metrics ----
    accuracy_by_type: dict[str, Any] = {}
    all_maes: list[float] = []
    all_briers: list[float] = []

    for pt in prop_types:
        pt_data = by_type_raw.get(pt, {})
        mae = _safe_float(pt_data.get("mae"))
        brier = _safe_float(pt_data.get("brier_score"))

        # within_1 / within_2: not directly in the summary JSON per-type,
        # so we approximate from MAE context. The full predictions JSON would
        # be needed for exact values; store as None and note limitation.
        accuracy_by_type[pt] = {
            "mae": mae,
            "brier": brier,
            "hit_rate": _safe_float(pt_data.get("hit_rate")),
            "total": pt_data.get("total"),
        }

        # Collect for overall
        if mae is not None:
            all_maes.append(mae)
        if brier is not None:
            all_briers.append(brier)

    # ---- overall ROI ----
    roi_raw = _safe_float(overall_pl.get("roi"))
    roi_pct = round(roi_raw * 100, 2) if roi_raw is not None else None
    total_pnl = _safe_float(overall_pl.get("total_units_won"))

    # ---- overall MAE / Brier (mean across prop types) ----
    overall_mae = round(sum(all_maes) / len(all_maes), 3) if all_maes else None
    overall_brier = round(sum(all_briers) / len(all_briers), 4) if all_briers else None

    # ---- calibration error ----
    cal_err = _mean_calibration_error(calibration)

    return {
        "accuracy_by_type": accuracy_by_type,
        "overall": {
            "mae": overall_mae,
            "brier": overall_brier,
            "roi_pct": roi_pct,
            "total_pnl": total_pnl,
            "calibration_error": cal_err,
        },
    }


def _extract_point_estimate_metrics(
    pe_summary: dict,
) -> dict[str, Any]:
    """
    Pull comparison metrics from a backtest_projections.py summary JSON.

    That script uses a different schema:
      projection_accuracy.mean_absolute_error
      projection_accuracy.within_1k
      projection_accuracy.within_2k
      overall.roi_pct  (if graded picks exist)

    Returns the same shape as _extract_summary_metrics but with N/A for
    probability-based fields (Brier, ROI, calibration) since point estimates
    don't produce probabilities.
    """
    proj_acc = pe_summary.get("projection_accuracy", {})
    mae = _safe_float(proj_acc.get("mean_absolute_error"))
    within_1 = _safe_float(proj_acc.get("within_1k"))
    within_2 = _safe_float(proj_acc.get("within_2k"))

    return {
        "accuracy_by_type": {
            "K": {
                "mae": mae,
                "within_1": within_1,
                "within_2": within_2,
                "brier": None,   # point estimates have no probabilities
                "roi_pct": None,
                "hit_rate": _safe_float(pe_summary.get("overall", {}).get("hit_rate_pct")),
            }
        },
        "overall": {
            "mae": mae,
            "brier": None,
            "roi_pct": None,
            "total_pnl": None,
            "calibration_error": None,
        },
    }


# ---------------------------------------------------------------------------
# Subprocess runners
# ---------------------------------------------------------------------------

def _build_env() -> dict[str, str]:
    """Build environment with PYTHONPATH set so child scripts can find each other."""
    env = os.environ.copy()
    existing = env.get("PYTHONPATH", "")
    paths = [str(PROJECT_ROOT), str(SCRIPTS_DIR)]
    if existing:
        paths.append(existing)
    env["PYTHONPATH"] = os.pathsep.join(paths)
    return env


def run_backtest_simulator(
    config_name: str,
    config_def: dict,
    start: str,
    end: str,
    prop_types: str,
    output_dir: Path,
    seed: int,
    sample_days: Optional[int],
    verbose: bool,
) -> dict[str, Any]:
    """
    Run backtest_simulator.py for a single model configuration.

    Returns a result dict with:
      status: "ok" | "error" | "skipped"
      runtime_seconds: float
      metrics: dict  (extracted from summary JSON)
      error: str     (if status == "error")
    """
    simulator_path = SCRIPTS_DIR / "backtest_simulator.py"
    if not simulator_path.exists():
        return {
            "status": "skipped",
            "error": f"backtest_simulator.py not found at {simulator_path}",
            "runtime_seconds": 0,
            "metrics": None,
        }

    config_output_dir = output_dir / config_name
    config_output_dir.mkdir(parents=True, exist_ok=True)

    cmd = [
        sys.executable,
        str(simulator_path),
        "--start", start,
        "--end", end,
        "--prop-types", prop_types,
        "--output-dir", str(config_output_dir),
        "--seed", str(seed),
    ]

    if sample_days:
        cmd += ["--sample-days", str(sample_days)]

    if verbose:
        cmd.append("-v")

    # Append config-specific extra args
    extra_args = config_def.get("args", [])
    if extra_args:
        # Resolve relative config paths to absolute (relative to project root)
        resolved_args = []
        i = 0
        while i < len(extra_args):
            arg = extra_args[i]
            if arg == "--config" and i + 1 < len(extra_args):
                cfg_path = Path(extra_args[i + 1])
                if not cfg_path.is_absolute():
                    cfg_path = PROJECT_ROOT / cfg_path
                resolved_args += ["--config", str(cfg_path)]
                i += 2
            else:
                resolved_args.append(arg)
                i += 1
        cmd += resolved_args

    log.debug("Running: %s", " ".join(cmd))
    t0 = time.monotonic()

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            env=_build_env(),
            cwd=str(PROJECT_ROOT),
        )
        elapsed = round(time.monotonic() - t0, 1)

        if result.returncode != 0:
            return {
                "status": "error",
                "error": (result.stderr or result.stdout or "non-zero exit")[-2000:],
                "runtime_seconds": elapsed,
                "metrics": None,
            }

        # Locate the summary JSON
        slug = f"{start}_{end}"
        summary_path = config_output_dir / f"backtest_summary_{slug}.json"
        if not summary_path.exists():
            return {
                "status": "error",
                "error": f"Expected summary file not found: {summary_path}",
                "runtime_seconds": elapsed,
                "metrics": None,
            }

        with open(summary_path) as fh:
            summary = json.load(fh)

        prop_type_list = [pt.strip().upper() for pt in prop_types.split(",")]
        metrics = _extract_summary_metrics(summary, prop_type_list)

        return {
            "status": "ok",
            "runtime_seconds": elapsed,
            "metrics": metrics,
            "summary_path": str(summary_path),
        }

    except FileNotFoundError as exc:
        elapsed = round(time.monotonic() - t0, 1)
        return {
            "status": "error",
            "error": f"Could not launch subprocess: {exc}",
            "runtime_seconds": elapsed,
            "metrics": None,
        }
    except Exception as exc:
        elapsed = round(time.monotonic() - t0, 1)
        return {
            "status": "error",
            "error": str(exc),
            "runtime_seconds": elapsed,
            "metrics": None,
        }


def run_point_estimate(
    start: str,
    end: str,
    verbose: bool,
) -> dict[str, Any]:
    """
    Run backtest_projections.py (v1.0 point-estimate model).

    Returns a result dict in the same shape as run_backtest_simulator.
    """
    projections_path = SCRIPTS_DIR / "backtest_projections.py"
    if not projections_path.exists():
        return {
            "status": "skipped",
            "error": f"backtest_projections.py not found at {projections_path}",
            "runtime_seconds": 0,
            "metrics": None,
        }

    cmd = [
        sys.executable,
        str(projections_path),
        "--start", start,
        "--end", end,
        "--dry-run",   # don't upload to Supabase
    ]

    log.debug("Running point estimate: %s", " ".join(cmd))
    t0 = time.monotonic()

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            env=_build_env(),
            cwd=str(PROJECT_ROOT),
        )
        elapsed = round(time.monotonic() - t0, 1)

        if result.returncode != 0:
            return {
                "status": "error",
                "error": (result.stderr or result.stdout or "non-zero exit")[-2000:],
                "runtime_seconds": elapsed,
                "metrics": None,
            }

        # backtest_projections.py writes to dashboard/data/
        dashboard_data = PROJECT_ROOT / "dashboard" / "data"
        summary_path = dashboard_data / f"backtest_summary_{start}_to_{end}.json"

        if not summary_path.exists():
            # Fallback: look for any matching file
            candidates = list(dashboard_data.glob(f"backtest_summary_{start}*.json"))
            if candidates:
                summary_path = sorted(candidates)[-1]
            else:
                return {
                    "status": "error",
                    "error": (
                        f"Point-estimate summary not found. "
                        f"Looked for: {summary_path}. "
                        f"stdout: {result.stdout[-500:]}"
                    ),
                    "runtime_seconds": elapsed,
                    "metrics": None,
                }

        with open(summary_path) as fh:
            pe_summary = json.load(fh)

        metrics = _extract_point_estimate_metrics(pe_summary)

        return {
            "status": "ok",
            "runtime_seconds": elapsed,
            "metrics": metrics,
            "summary_path": str(summary_path),
        }

    except FileNotFoundError as exc:
        elapsed = round(time.monotonic() - t0, 1)
        return {
            "status": "error",
            "error": f"Could not launch subprocess: {exc}",
            "runtime_seconds": elapsed,
            "metrics": None,
        }
    except Exception as exc:
        elapsed = round(time.monotonic() - t0, 1)
        return {
            "status": "error",
            "error": str(exc),
            "runtime_seconds": elapsed,
            "metrics": None,
        }


# ---------------------------------------------------------------------------
# Factor impact analysis
# ---------------------------------------------------------------------------

def _compute_factor_impact(results: dict[str, Any]) -> dict[str, Any]:
    """
    Compute pairwise deltas between related configurations.

    Returns a factor_impact dict with delta values and verdicts.
    """
    impact: dict[str, Any] = {}

    def _delta(config_a: str, config_b: str, metric: str) -> Optional[float]:
        """
        Compute results[config_a].overall[metric] - results[config_b].overall[metric].
        Positive delta = config_a has a higher value than config_b.
        """
        a = results.get(config_a, {})
        b = results.get(config_b, {})
        a_m = a.get("metrics") or {}
        b_m = b.get("metrics") or {}
        a_v = _safe_float((a_m.get("overall") or {}).get(metric))
        b_v = _safe_float((b_m.get("overall") or {}).get(metric))
        if a_v is None or b_v is None:
            return None
        return round(a_v - b_v, 4)

    # ---- Umpire: baseline vs no_umpire ----
    # Negative MAE delta = baseline has lower MAE = umpire helps
    # Positive ROI delta = baseline has higher ROI = umpire helps
    if "baseline" in results and "no_umpire" in results:
        mae_d = _delta("baseline", "no_umpire", "mae")
        roi_d = _delta("baseline", "no_umpire", "roi_pct")
        brier_d = _delta("baseline", "no_umpire", "brier")
        verdict_parts = []
        if mae_d is not None:
            direction = "improves" if mae_d < 0 else "hurts"
            verdict_parts.append(f"Umpire data {direction} MAE by {abs(mae_d):.3f}K")
        if roi_d is not None:
            roi_dir = "improves" if roi_d > 0 else "hurts"
            verdict_parts.append(f"{roi_dir} ROI by {abs(roi_d):.1f}%")
        impact["umpire"] = {
            "mae_delta": mae_d,
            "roi_delta": roi_d,
            "brier_delta": brier_d,
            "verdict": " | ".join(verdict_parts) if verdict_parts else "Insufficient data",
        }

    # ---- Weather: baseline vs no_weather ----
    if "baseline" in results and "no_weather" in results:
        mae_d = _delta("baseline", "no_weather", "mae")
        roi_d = _delta("baseline", "no_weather", "roi_pct")
        brier_d = _delta("baseline", "no_weather", "brier")
        verdict_parts = []
        if mae_d is not None:
            direction = "improves" if mae_d < 0 else "hurts"
            verdict_parts.append(f"Weather data {direction} MAE by {abs(mae_d):.3f}K")
        if roi_d is not None:
            roi_dir = "improves" if roi_d > 0 else "hurts"
            verdict_parts.append(f"{roi_dir} ROI by {abs(roi_d):.1f}%")
        impact["weather"] = {
            "mae_delta": mae_d,
            "roi_delta": roi_d,
            "brier_delta": brier_d,
            "verdict": " | ".join(verdict_parts) if verdict_parts else "Insufficient data",
        }

    # ---- Recent form: baseline vs no_recent_form (or career_only) ----
    rf_opponent = "no_recent_form" if "no_recent_form" in results else "career_only"
    if "baseline" in results and rf_opponent in results:
        mae_d = _delta("baseline", rf_opponent, "mae")
        roi_d = _delta("baseline", rf_opponent, "roi_pct")
        brier_d = _delta("baseline", rf_opponent, "brier")
        verdict_parts = []
        if mae_d is not None:
            direction = "improves" if mae_d < 0 else "hurts"
            verdict_parts.append(f"Recent form blend {direction} MAE by {abs(mae_d):.3f}K")
        if roi_d is not None:
            roi_dir = "improves" if roi_d > 0 else "hurts"
            verdict_parts.append(f"{roi_dir} ROI by {abs(roi_d):.1f}%")
        impact["recent_form"] = {
            "mae_delta": mae_d,
            "roi_delta": roi_d,
            "brier_delta": brier_d,
            "verdict": " | ".join(verdict_parts) if verdict_parts else "Insufficient data",
        }

    # ---- Sim count: 500 vs 3000 ----
    if "baseline" in results and "low_sims" in results:
        mae_d = _delta("baseline", "low_sims", "mae")
        brier_d = _delta("baseline", "low_sims", "brier")
        verdict_parts = []
        if mae_d is not None:
            direction = "improves" if mae_d < 0 else "hurts"
            verdict_parts.append(f"3K vs 500 sims {direction} MAE by {abs(mae_d):.3f}K")
        if brier_d is not None:
            brier_dir = "improves" if brier_d < 0 else "hurts"
            verdict_parts.append(f"{brier_dir} Brier by {abs(brier_d):.4f}")
        impact["sim_count_500_vs_3000"] = {
            "mae_delta": mae_d,
            "brier_delta": brier_d,
            "verdict": " | ".join(verdict_parts) if verdict_parts else "Insufficient data",
        }

    # ---- Sim count: 3000 vs 10000 ----
    if "baseline" in results and "high_sims" in results:
        mae_d = _delta("high_sims", "baseline", "mae")
        brier_d = _delta("high_sims", "baseline", "brier")
        verdict_parts = []
        if mae_d is not None:
            direction = "improves" if mae_d < 0 else "hurts"
            verdict_parts.append(f"10K vs 3K sims {direction} MAE by {abs(mae_d):.3f}K")
        impact["sim_count_3000_vs_10000"] = {
            "mae_delta": mae_d,
            "brier_delta": brier_d,
            "verdict": " | ".join(verdict_parts) if verdict_parts else "Insufficient data",
        }

    # ---- MC vs point estimate ----
    if "baseline" in results and "point_estimate" in results:
        mae_d = _delta("baseline", "point_estimate", "mae")
        verdict_parts = []
        if mae_d is not None:
            if mae_d < 0:
                verdict_parts.append(
                    f"Monte Carlo beats point estimates by {abs(mae_d):.3f} MAE"
                )
            elif mae_d > 0:
                verdict_parts.append(
                    f"Point estimates beat Monte Carlo by {abs(mae_d):.3f} MAE"
                )
            else:
                verdict_parts.append("Models are tied on MAE")
        impact["mc_vs_point_estimate"] = {
            "mae_delta": mae_d,
            "verdict": " | ".join(verdict_parts) if verdict_parts else "Insufficient data",
        }

    return impact


# ---------------------------------------------------------------------------
# Rankings
# ---------------------------------------------------------------------------

def _compute_rankings(results: dict[str, Any]) -> dict[str, list[str]]:
    """Rank configs by each key metric (ascending for error metrics)."""

    def _rank(metric: str, ascending: bool = True) -> list[str]:
        scored: list[tuple[float, str]] = []
        for cfg_name, res in results.items():
            if res.get("status") != "ok":
                continue
            m = res.get("metrics") or {}
            val = _safe_float((m.get("overall") or {}).get(metric))
            if val is not None:
                scored.append((val, cfg_name))
        scored.sort(key=lambda x: x[0], reverse=(not ascending))
        return [name for _, name in scored]

    return {
        "by_mae": _rank("mae", ascending=True),
        "by_brier": _rank("brier", ascending=True),
        "by_roi": _rank("roi_pct", ascending=False),
        "by_calibration": _rank("calibration_error", ascending=True),
    }


# ---------------------------------------------------------------------------
# Console output
# ---------------------------------------------------------------------------

def _print_header(
    start: str,
    end: str,
    selected_configs: list[str],
    prop_types: str,
    sample_days: Optional[int],
) -> None:
    print("\n=== BaselineMLB Model Comparison ===")
    print(f"Date range:  {start} to {end}")
    print(f"Configs:     {', '.join(selected_configs)}")
    print(f"Prop types:  {prop_types}")
    if sample_days:
        print(f"Sample days: {sample_days}")
    print()


def _print_progress(
    index: int,
    total: int,
    label: str,
    result: dict[str, Any],
) -> None:
    status = result.get("status", "?")
    elapsed = result.get("runtime_seconds", 0)
    metrics = result.get("metrics") or {}
    overall = metrics.get("overall") or {}

    if status == "ok":
        mae = _fmt(overall.get("mae"), 2)
        roi = _fmt(overall.get("roi_pct"), 2, "%")
        brier = _fmt(overall.get("brier"), 3)
        print(
            f"[{index}/{total}] Running: {label}...\n"
            f"  → Completed in {elapsed}s | MAE: {mae} | ROI: {roi} | Brier: {brier}"
        )
    elif status == "skipped":
        print(f"[{index}/{total}] SKIPPED: {label}  ({result.get('error', '')})")
    else:
        err_preview = (result.get("error") or "unknown error")[:120]
        print(f"[{index}/{total}] ERROR: {label}\n  → {err_preview}")


def _print_comparison_table(results: dict[str, Any]) -> None:
    """Print a Unicode box-drawing comparison table."""
    # Collect rows
    rows: list[tuple[str, str, str, str, str]] = []
    for cfg_name, res in results.items():
        label = CONFIGS.get(cfg_name, {}).get("label", cfg_name)
        if res.get("status") != "ok":
            rows.append((label[:22], "ERR", "ERR", "ERR", "ERR"))
            continue
        m = res.get("metrics") or {}
        ov = m.get("overall") or {}
        mae_s = _fmt(ov.get("mae"), 2)
        brier_s = _fmt(ov.get("brier"), 3)
        roi_s = _fmt(ov.get("roi_pct"), 2, "%")
        cal_s = _fmt(ov.get("calibration_error"), 3)
        rows.append((label[:22], mae_s, brier_s, roi_s, cal_s))

    col_w = [24, 7, 9, 8, 8]
    headers = ("Model", "MAE", "Brier", "ROI%", "Cal.Err")

    top    = "┌" + "┬".join("─" * (w + 2) for w in col_w) + "┐"
    mid    = "├" + "┼".join("─" * (w + 2) for w in col_w) + "┤"
    bottom = "└" + "┴".join("─" * (w + 2) for w in col_w) + "┘"

    def row_line(cells: tuple[str, ...]) -> str:
        parts = [f" {str(c):>{w}s} " for c, w in zip(cells, col_w)]
        return "│" + "│".join(parts) + "│"

    print("\n=== COMPARISON RESULTS ===")
    print(top)
    print(row_line(headers))
    print(mid)
    for row in rows:
        print(row_line(row))
    print(bottom)


def _print_factor_impact(factor_impact: dict[str, Any]) -> None:
    print("\nFactor Impact:")
    labels = {
        "umpire": "Umpire data:    ",
        "weather": "Weather data:   ",
        "recent_form": "Recent form:    ",
        "sim_count_500_vs_3000": "500 vs 3K sims: ",
        "sim_count_3000_vs_10000": "3K vs 10K sims: ",
        "mc_vs_point_estimate": "MC vs Point Est:",
    }
    for key, lbl in labels.items():
        if key not in factor_impact:
            continue
        fi = factor_impact[key]
        verdict = fi.get("verdict", "N/A")
        mae_d = fi.get("mae_delta")
        roi_d = fi.get("roi_delta")
        parts = []
        if mae_d is not None:
            arrow = "↓" if mae_d < 0 else "↑"
            parts.append(f"MAE {arrow}{abs(mae_d):.3f} ({'helps' if mae_d < 0 else 'hurts'})")
        if roi_d is not None:
            arrow = "↑" if roi_d > 0 else "↓"
            parts.append(f"ROI {arrow}{abs(roi_d):.1f}%")
        line = f"  {lbl} {verdict}"
        print(line)


# ---------------------------------------------------------------------------
# Report generation
# ---------------------------------------------------------------------------

def _invoke_report_generator(comparison_path: Path, verbose: bool) -> None:
    report_script = SCRIPTS_DIR / "generate_backtest_report.py"
    if not report_script.exists():
        log.warning(
            "--generate-report requested but generate_backtest_report.py not found at %s",
            report_script,
        )
        return

    cmd = [
        sys.executable,
        str(report_script),
        "--comparison", str(comparison_path),
    ]
    if verbose:
        cmd.append("-v")

    log.info("Invoking report generator: %s", " ".join(cmd))
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            env=_build_env(),
            cwd=str(PROJECT_ROOT),
        )
        if result.returncode != 0:
            log.warning(
                "generate_backtest_report.py returned non-zero (%d): %s",
                result.returncode,
                (result.stderr or result.stdout)[:300],
            )
        else:
            log.info("Report generator completed successfully.")
            if result.stdout.strip():
                print(result.stdout)
    except Exception as exc:
        log.warning("Could not invoke generate_backtest_report.py: %s", exc)


# ---------------------------------------------------------------------------
# Core orchestration
# ---------------------------------------------------------------------------

def run_comparison(
    start: str,
    end: str,
    selected_configs: list[str],
    prop_types: str,
    output_dir: Path,
    seed: int,
    sample_days: Optional[int],
    parallel: int,
    generate_report: bool,
    verbose: bool,
) -> dict[str, Any]:
    """
    Run all selected configurations and build the comparison output.

    Returns the full comparison dict (also written to disk).
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    _print_header(start, end, selected_configs, prop_types, sample_days)

    total = len(selected_configs)
    results: dict[str, Any] = {}

    # ------------------------------------------------------------------ #
    # Run configs — sequential or parallel
    # ------------------------------------------------------------------ #

    def _run_one(idx_cfg: tuple[int, str]) -> tuple[str, dict[str, Any]]:
        idx, cfg_name = idx_cfg
        cfg_def = CONFIGS[cfg_name]
        label = cfg_def["label"]

        print(f"[{idx}/{total}] Running: {label}...", flush=True)

        if cfg_name == "point_estimate":
            res = run_point_estimate(start, end, verbose)
        else:
            res = run_backtest_simulator(
                config_name=cfg_name,
                config_def=cfg_def,
                start=start,
                end=end,
                prop_types=prop_types,
                output_dir=output_dir,
                seed=seed,
                sample_days=sample_days,
                verbose=verbose,
            )
        return cfg_name, res

    indexed = list(enumerate(selected_configs, start=1))

    if parallel > 1:
        with ThreadPoolExecutor(max_workers=parallel) as executor:
            futures = {executor.submit(_run_one, item): item for item in indexed}
            ordered_results: list[tuple[int, str, dict]] = []
            for future in as_completed(futures):
                cfg_name, res = future.result()
                idx = futures[future][0]
                ordered_results.append((idx, cfg_name, res))
            ordered_results.sort(key=lambda x: x[0])
            for idx, cfg_name, res in ordered_results:
                results[cfg_name] = res
                _print_progress(idx, total, CONFIGS[cfg_name]["label"], res)
    else:
        for idx, cfg_name in indexed:
            _, res = _run_one((idx, cfg_name))
            results[cfg_name] = res
            _print_progress(idx, total, CONFIGS[cfg_name]["label"], res)

    # ------------------------------------------------------------------ #
    # Assemble comparison output
    # ------------------------------------------------------------------ #

    output_results: dict[str, Any] = {}
    for cfg_name in selected_configs:
        cfg_def = CONFIGS[cfg_name]
        res = results.get(cfg_name, {"status": "missing"})
        entry: dict[str, Any] = {
            "label": cfg_def["label"],
            "description": cfg_def["description"],
            "status": res.get("status", "unknown"),
            "runtime_seconds": res.get("runtime_seconds", 0),
        }
        if res.get("status") == "ok" and res.get("metrics"):
            entry["accuracy_by_type"] = res["metrics"].get("accuracy_by_type", {})
            entry["overall"] = res["metrics"].get("overall", {})
        elif res.get("status") in ("error", "skipped"):
            entry["error"] = res.get("error", "")
            entry["accuracy_by_type"] = {}
            entry["overall"] = {}
        output_results[cfg_name] = entry

    factor_impact = _compute_factor_impact(results)
    rankings = _compute_rankings(results)

    comparison: dict[str, Any] = {
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "date_range": {"start": start, "end": end},
        "prop_types": prop_types,
        "seed": seed,
        "sample_days": sample_days,
        "configs_tested": len(selected_configs),
        "configs_successful": sum(
            1 for cfg_name in selected_configs
            if results.get(cfg_name, {}).get("status") == "ok"
        ),
        "results": output_results,
        "rankings": rankings,
        "factor_impact": factor_impact,
    }

    # ------------------------------------------------------------------ #
    # Write output
    # ------------------------------------------------------------------ #

    comparison_path = output_dir / "model_comparison.json"
    with open(comparison_path, "w") as fh:
        json.dump(comparison, fh, indent=2, default=_json_default)

    # ------------------------------------------------------------------ #
    # Console summary
    # ------------------------------------------------------------------ #

    _print_comparison_table(output_results)
    _print_factor_impact(factor_impact)

    print(f"\nSaved comparison to {comparison_path}")

    # ------------------------------------------------------------------ #
    # Optional report generation
    # ------------------------------------------------------------------ #

    if generate_report:
        _invoke_report_generator(comparison_path, verbose)

    return comparison


def _json_default(obj: Any) -> Any:
    """JSON serializer fallback — converts numpy types and other non-serializables."""
    try:
        import numpy as np  # noqa: F401 — optional dependency
        if isinstance(obj, (np.integer,)):
            return int(obj)
        if isinstance(obj, (np.floating,)):
            return float(obj)
        if isinstance(obj, np.ndarray):
            return obj.tolist()
    except ImportError:
        pass
    if isinstance(obj, Path):
        return str(obj)
    raise TypeError(f"Object of type {type(obj)} is not JSON serializable")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="BaselineMLB — Multi-model comparison tool",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--start", required=True, metavar="YYYY-MM-DD",
        help="Backtest start date (inclusive)",
    )
    parser.add_argument(
        "--end", required=True, metavar="YYYY-MM-DD",
        help="Backtest end date (inclusive)",
    )
    parser.add_argument(
        "--configs",
        default=",".join(CONFIGS.keys()),
        metavar="NAMES",
        help=(
            "Comma-separated list of config names to test "
            f"(default: all). Available: {', '.join(CONFIGS.keys())}"
        ),
    )
    parser.add_argument(
        "--prop-types", default="K",
        help="Comma-separated prop types: K,TB,H,HR (default: K)",
    )
    parser.add_argument(
        "--sample-days", type=int, default=None, metavar="N",
        help="Sample N evenly-spaced days for speed (default: all days)",
    )
    parser.add_argument(
        "--output-dir", default="output/backtest/compare",
        help="Output directory (default: output/backtest/compare)",
    )
    parser.add_argument(
        "--generate-report", action="store_true",
        help="After comparison, invoke generate_backtest_report.py with comparison data",
    )
    parser.add_argument(
        "--seed", type=int, default=42,
        help="Random seed for reproducibility (default: 42)",
    )
    parser.add_argument(
        "--parallel", type=int, default=1, metavar="N",
        help="Run N configs in parallel (default: 1 = sequential)",
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true",
        help="Verbose logging",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    if args.verbose:
        log.setLevel(logging.DEBUG)

    # ---- Validate configs ----
    raw_configs = [c.strip() for c in args.configs.split(",") if c.strip()]
    unknown = [c for c in raw_configs if c not in CONFIGS]
    if unknown:
        log.error(
            "Unknown config name(s): %s\nAvailable: %s",
            ", ".join(unknown),
            ", ".join(CONFIGS.keys()),
        )
        return 1

    # ---- Validate dates ----
    try:
        from datetime import datetime as _dt
        _dt.strptime(args.start, "%Y-%m-%d")
        _dt.strptime(args.end, "%Y-%m-%d")
    except ValueError as exc:
        log.error("Invalid date: %s", exc)
        return 1

    # ---- Ensure configs directory exists ----
    configs_dir = PROJECT_ROOT / "configs"
    configs_dir.mkdir(parents=True, exist_ok=True)

    output_dir = Path(args.output_dir)
    if not output_dir.is_absolute():
        output_dir = PROJECT_ROOT / output_dir

    run_comparison(
        start=args.start,
        end=args.end,
        selected_configs=raw_configs,
        prop_types=args.prop_types,
        output_dir=output_dir,
        seed=args.seed,
        sample_days=args.sample_days,
        parallel=args.parallel,
        generate_report=args.generate_report,
        verbose=args.verbose,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
