"""
Shared Supabase helper module for BaselineMLB pipeline scripts.

Centralizes connection setup, header generation, and common operations
so individual scripts don't duplicate boilerplate.

Usage:
    from lib.supabase import get_client, sb_headers, sb_get, sb_upsert
    from lib.supabase import SimulationResultsAPI, BacktestAPI, ModelArtifactsAPI

Environment Variables (required):
    SUPABASE_URL            Your Supabase project URL
    SUPABASE_SERVICE_KEY    Supabase service role key (for pipeline writes)
"""

import logging
import os
import sys
from typing import Any, Dict, List, Optional

import requests

log = logging.getLogger("baselinemlb.supabase")


# ────────────────────────────────────────────────────────────
# Core helpers (unchanged)
# ────────────────────────────────────────────────────────────

def _require_env(name: str) -> str:
    """Return env var value or exit with a clear error."""
    val = os.environ.get(name, "").strip()
    if not val:
        sys.exit(f"Missing required environment variable: {name}")
    return val


def get_url() -> str:
    """Return validated SUPABASE_URL."""
    url = _require_env("SUPABASE_URL")
    if not url.startswith("https://") or not url.endswith(".supabase.co"):
        sys.exit(
            f"Invalid SUPABASE_URL — expected https://xxx.supabase.co, "
            f"got: {url[:30]}..."
        )
    return url


def get_key(prefer_service: bool = True) -> str:
    """
    Return Supabase key from environment.

    Args:
        prefer_service: If True (default), prefer SUPABASE_SERVICE_KEY for
                        pipeline writes.  Falls back to SUPABASE_ANON_KEY.
    """
    if prefer_service:
        key = os.environ.get("SUPABASE_SERVICE_KEY", "").strip()
        if key:
            return key

    key = os.environ.get("SUPABASE_ANON_KEY", "").strip()
    if key:
        return key

    sys.exit("Missing SUPABASE_SERVICE_KEY or SUPABASE_ANON_KEY")


def sb_headers(key: Optional[str] = None) -> dict:
    """Standard Supabase REST headers with merge-duplicates for upserts."""
    if key is None:
        key = get_key()
    return {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "Prefer": "resolution=merge-duplicates",
    }


def sb_get(table: str, params: dict, url: Optional[str] = None) -> list:
    """
    GET rows from a Supabase table via REST API.

    Args:
        table:  Table name (e.g. "games", "players").
        params: Query params dict (e.g. {"game_date": "eq.2026-03-01"}).
        url:    Override SUPABASE_URL (rarely needed).

    Returns:
        List of row dicts.
    """
    base = url or get_url()
    r = requests.get(
        f"{base}/rest/v1/{table}",
        headers=sb_headers(),
        params=params,
    )
    r.raise_for_status()
    return r.json()


def sb_upsert(
    table: str,
    rows: list,
    batch_size: int = 500,
    url: Optional[str] = None,
) -> None:
    """
    Upsert rows into a Supabase table in batches.

    Args:
        table:      Target table name.
        rows:       List of row dicts.
        batch_size: Max rows per request (default 500).
        url:        Override SUPABASE_URL.
    """
    if not rows:
        log.info(f"No rows to upsert into {table}")
        return

    base = url or get_url()
    endpoint = f"{base}/rest/v1/{table}"

    for i in range(0, len(rows), batch_size):
        batch = rows[i : i + batch_size]
        r = requests.post(endpoint, headers=sb_headers(), json=batch)
        if not r.ok:
            log.warning(f"Upsert failed: {r.status_code} {r.text[:200]}")
        else:
            log.info(f"Upserted {len(batch)} rows into {table}")


def get_client():
    """
    Return a supabase-py Client instance.

    Requires the `supabase` package (pip install supabase).
    """
    try:
        from supabase import create_client
    except ImportError:
        sys.exit("supabase-py required: pip install supabase")

    return create_client(get_url(), get_key())


def _call_rpc(
    function_name: str,
    params: Optional[dict] = None,
    url: Optional[str] = None,
) -> Any:
    """
    Call a Supabase database function (RPC) via REST.

    Args:
        function_name: Name of the Postgres function.
        params:        Dict of function arguments.
        url:           Override SUPABASE_URL.

    Returns:
        Parsed JSON response.
    """
    base = url or get_url()
    r = requests.post(
        f"{base}/rest/v1/rpc/{function_name}",
        headers=sb_headers(),
        json=params or {},
    )
    r.raise_for_status()
    return r.json()


# ────────────────────────────────────────────────────────────
# Simulation Results API
# ────────────────────────────────────────────────────────────

class SimulationResultsAPI:
    """
    CRUD helpers for the simulation_results table.

    Usage:
        api = SimulationResultsAPI()
        api.upsert_results([{...}, {...}])
        edges = api.get_todays_edges(min_edge=3.0)
        history = api.get_player_history(player_id=592450)
    """

    TABLE = "simulation_results"

    @staticmethod
    def upsert_results(rows: List[Dict[str, Any]], batch_size: int = 500) -> None:
        """Upsert simulation result rows (list of dicts)."""
        sb_upsert(SimulationResultsAPI.TABLE, rows, batch_size=batch_size)

    @staticmethod
    def get_by_date(
        simulation_date: str,
        prop_type: Optional[str] = None,
        confidence_tier: Optional[str] = None,
    ) -> List[dict]:
        """
        Fetch simulation results for a given date.

        Args:
            simulation_date: ISO date string (e.g. "2026-04-15").
            prop_type:       Optional filter (K, H, TB, etc.).
            confidence_tier: Optional filter (A, B, C, D).
        """
        params: Dict[str, str] = {
            "simulation_date": f"eq.{simulation_date}",
            "order": "edge_pct.desc",
        }
        if prop_type:
            params["prop_type"] = f"eq.{prop_type}"
        if confidence_tier:
            params["confidence_tier"] = f"eq.{confidence_tier}"
        return sb_get(SimulationResultsAPI.TABLE, params)

    @staticmethod
    def get_by_player(player_id: int, limit: int = 50) -> List[dict]:
        """Fetch recent simulation results for a specific player."""
        params = {
            "player_id": f"eq.{player_id}",
            "order": "simulation_date.desc",
            "limit": str(limit),
        }
        return sb_get(SimulationResultsAPI.TABLE, params)

    @staticmethod
    def get_by_game(game_id: int) -> List[dict]:
        """Fetch all simulation results for a specific game."""
        params = {
            "game_id": f"eq.{game_id}",
            "order": "confidence_tier.asc,edge_pct.desc",
        }
        return sb_get(SimulationResultsAPI.TABLE, params)

    @staticmethod
    def get_todays_edges(
        min_edge: float = 0,
        target_date: Optional[str] = None,
    ) -> List[dict]:
        """
        Call the get_todays_edges() database function.

        Args:
            min_edge:    Minimum absolute edge percentage.
            target_date: ISO date string (defaults to today in Postgres).
        """
        params: Dict[str, Any] = {"min_edge": min_edge}
        if target_date:
            params["target_date"] = target_date
        return _call_rpc("get_todays_edges", params)

    @staticmethod
    def get_player_history(
        player_id: int,
        lookback_days: int = 30,
    ) -> List[dict]:
        """
        Call the get_player_history() database function.

        Args:
            player_id:     MLB player ID.
            lookback_days: Number of days to look back (default 30).
        """
        return _call_rpc("get_player_history", {
            "p_player_id": player_id,
            "lookback_days": lookback_days,
        })


# ────────────────────────────────────────────────────────────
# Simulation Explanations API
# ────────────────────────────────────────────────────────────

class SimulationExplanationsAPI:
    """CRUD helpers for the simulation_explanations table."""

    TABLE = "simulation_explanations"

    @staticmethod
    def upsert_explanations(rows: List[Dict[str, Any]]) -> None:
        """Upsert SHAP explanation rows."""
        sb_upsert(SimulationExplanationsAPI.TABLE, rows)

    @staticmethod
    def get_by_result(result_id: int) -> List[dict]:
        """Fetch all explanations for a simulation result, ordered by impact."""
        params = {
            "result_id": f"eq.{result_id}",
            "order": "shap_value.desc",
        }
        return sb_get(SimulationExplanationsAPI.TABLE, params)


# ────────────────────────────────────────────────────────────
# Backtest Results API
# ────────────────────────────────────────────────────────────

class BacktestAPI:
    """CRUD helpers for the backtest_results table."""

    TABLE = "backtest_results"

    @staticmethod
    def upsert_results(rows: List[Dict[str, Any]]) -> None:
        """Upsert backtest result rows."""
        sb_upsert(BacktestAPI.TABLE, rows)

    @staticmethod
    def get_by_date_range(
        start_date: str,
        end_date: str,
        prop_type: Optional[str] = None,
    ) -> List[dict]:
        """
        Fetch backtest results within a date range.

        Args:
            start_date: ISO date string.
            end_date:   ISO date string.
            prop_type:  Optional filter.
        """
        # PostgREST requires tuple list for AND on same column
        params_list = [
            ("date", f"gte.{start_date}"),
            ("date", f"lte.{end_date}"),
            ("order", "date.desc"),
        ]
        if prop_type:
            params_list.append(("prop_type", f"eq.{prop_type}"))

        base = get_url()
        r = requests.get(
            f"{base}/rest/v1/{BacktestAPI.TABLE}",
            headers=sb_headers(),
            params=params_list,
        )
        r.raise_for_status()
        return r.json()

    @staticmethod
    def get_summary(
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> List[dict]:
        """
        Call the get_backtest_summary() database function.

        Args:
            start_date: ISO date string (default: 30 days ago in Postgres).
            end_date:   ISO date string (default: today in Postgres).
        """
        params: Dict[str, Any] = {}
        if start_date:
            params["start_date"] = start_date
        if end_date:
            params["end_date"] = end_date
        return _call_rpc("get_backtest_summary", params)


# ────────────────────────────────────────────────────────────
# Model Artifacts API
# ────────────────────────────────────────────────────────────

class ModelArtifactsAPI:
    """CRUD helpers for the model_artifacts table."""

    TABLE = "model_artifacts"

    @staticmethod
    def upsert_artifact(row: Dict[str, Any]) -> None:
        """Upsert a single model artifact row."""
        sb_upsert(ModelArtifactsAPI.TABLE, [row])

    @staticmethod
    def get_active_model() -> Optional[dict]:
        """Fetch the currently active model artifact."""
        results = sb_get(ModelArtifactsAPI.TABLE, {
            "is_active": "eq.true",
            "limit": "1",
        })
        return results[0] if results else None

    @staticmethod
    def get_all(order_by: str = "trained_date.desc") -> List[dict]:
        """Fetch all model artifacts, ordered by trained date."""
        return sb_get(ModelArtifactsAPI.TABLE, {"order": order_by})

    @staticmethod
    def deactivate_all() -> None:
        """
        Set is_active = FALSE for all model artifacts.
        Call this before activating a new model.
        """
        base = get_url()
        r = requests.patch(
            f"{base}/rest/v1/{ModelArtifactsAPI.TABLE}",
            headers=sb_headers(),
            params={"is_active": "eq.true"},
            json={"is_active": False},
        )
        r.raise_for_status()
        log.info("Deactivated all model artifacts")

    @staticmethod
    def activate_model(model_version: str) -> None:
        """
        Activate a specific model version (deactivates all others first).

        Args:
            model_version: Version string of the model to activate.
        """
        ModelArtifactsAPI.deactivate_all()
        base = get_url()
        r = requests.patch(
            f"{base}/rest/v1/{ModelArtifactsAPI.TABLE}",
            headers=sb_headers(),
            params={"model_version": f"eq.{model_version}"},
            json={"is_active": True},
        )
        r.raise_for_status()
        log.info(f"Activated model: {model_version}")


# ────────────────────────────────────────────────────────────
# Player Rolling Stats API
# ────────────────────────────────────────────────────────────

class PlayerRollingStatsAPI:
    """CRUD helpers for the player_rolling_stats table."""

    TABLE = "player_rolling_stats"

    @staticmethod
    def upsert_stats(rows: List[Dict[str, Any]], batch_size: int = 500) -> None:
        """Upsert rolling stat rows."""
        sb_upsert(PlayerRollingStatsAPI.TABLE, rows, batch_size=batch_size)

    @staticmethod
    def get_latest(player_id: int) -> Optional[dict]:
        """Fetch the most recent rolling stats for a player."""
        results = sb_get(PlayerRollingStatsAPI.TABLE, {
            "player_id": f"eq.{player_id}",
            "order": "stat_date.desc",
            "limit": "1",
        })
        return results[0] if results else None

    @staticmethod
    def get_by_date(stat_date: str) -> List[dict]:
        """Fetch all player rolling stats for a specific date."""
        return sb_get(PlayerRollingStatsAPI.TABLE, {
            "stat_date": f"eq.{stat_date}",
            "order": "player_id.asc",
        })

    @staticmethod
    def get_player_trend(
        player_id: int,
        days: int = 30,
    ) -> List[dict]:
        """Fetch rolling stats trend for a player over N days."""
        return sb_get(PlayerRollingStatsAPI.TABLE, {
            "player_id": f"eq.{player_id}",
            "order": "stat_date.desc",
            "limit": str(days),
        })
