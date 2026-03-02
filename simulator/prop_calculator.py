"""
prop_calculator.py — Sportsbook prop-line edge calculator
==========================================================

Compares Monte Carlo simulation distributions against today's sportsbook
prop lines fetched from Supabase, computes over/under probabilities,
strips the vig to find true implied probabilities, calculates edges and
Kelly-criterion bet sizing, and attaches glass-box explanations for each
recommended wager.

Workflow
--------
1. Instantiate ``PropCalculator``.
2. Call ``fetch_todays_props(date)`` to load lines from Supabase.
3. Call ``calculate_prop_edges(sim_summary, prop_lines)`` to produce a
   ranked list of ``PropEdge`` objects.
4. Export with ``to_json()``, ``to_markdown()``, or ``to_text()``.

Notes
-----
- Odds are handled in American format (e.g. -110, +130).
- No-vig implied probability is computed via the standard two-line
  fair-odds formula.
- Kelly fractions are capped at ``max_kelly_fraction`` to prevent
  over-sizing on noisy estimates.
- Confidence is estimated via bootstrap standard error of the mean
  probability across 200 resamples.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
from dataclasses import asdict, dataclass, field
from datetime import date
from typing import TYPE_CHECKING, Any

import numpy as np
import requests

from .monte_carlo_engine import SimulationSummary

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Stat-type normalisation (Odds API -> internal engine names)
# ---------------------------------------------------------------------------

_PROP_TO_SIM_STAT: dict[str, str] = {
    "pitcher_strikeouts": "strikeouts",
    "pitcher_walks": "walks",
    "pitcher_hits_allowed": "hits_allowed",
    "pitcher_outs": "innings",
    "batter_total_bases": "total_bases",
    "batter_hits_runs_rbis": "rbis",
    "batter_hits": "hits",
    "batter_walks": "walks",
    "batter_strikeouts": "strikeouts",
    "batter_rbis": "rbis",
    "batter_runs": "runs",
    "batter_home_runs": "total_bases",
    # Pass-through for already-normalised names
    "strikeouts": "strikeouts",
    "total_bases": "total_bases",
    "hits": "hits",
    "walks": "walks",
    "rbis": "rbis",
    "runs": "runs",
}


def _normalise_stat_type(raw_stat: str) -> str:
    """Map a prop stat_type (e.g. 'pitcher_strikeouts') to the engine key."""
    return _PROP_TO_SIM_STAT.get(raw_stat, raw_stat)


# ---------------------------------------------------------------------------
# Supabase helpers
# ---------------------------------------------------------------------------

_SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
_SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_KEY", "")


def _supabase_headers() -> dict[str, str]:
    """Return standard Supabase REST API headers.

    Returns
    -------
    dict[str, str]
        Headers including API key, Bearer auth, content type, and
        merge-duplicate preference.
    """
    key = os.environ.get("SUPABASE_SERVICE_KEY", _SUPABASE_KEY)
    return {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "Prefer": "resolution=merge-duplicates",
    }


def _supabase_get(endpoint: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Perform a GET request against the Supabase REST API.

    Parameters
    ----------
    endpoint:
        Table or RPC endpoint, e.g. ``"/props"``.
    params:
        Optional query-string parameters (filters, selects, etc.).

    Returns
    -------
    list[dict[str, Any]]
        Parsed JSON response body.

    Raises
    ------
    RuntimeError
        On non-2xx HTTP status or missing environment variables.
    """
    base_url = os.environ.get("SUPABASE_URL", _SUPABASE_URL)
    if not base_url:
        raise RuntimeError("SUPABASE_URL environment variable is not set.")
    url = f"{base_url}/rest/v1{endpoint}"
    resp = requests.get(url, headers=_supabase_headers(), params=params, timeout=30)
    if not resp.ok:
        raise RuntimeError(
            f"Supabase GET {endpoint} failed [{resp.status_code}]: {resp.text[:400]}"
        )
    return resp.json()  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class PropLine:
    """A single sportsbook prop line for a player.

    Attributes
    ----------
    prop_id:
        Unique identifier from the ``props`` Supabase table.
    game_pk:
        MLB game identifier.
    player_id:
        Player identifier matching simulation keys.
    player_name:
        Display name.
    stat_type:
        E.g. ``"pitcher_strikeouts"``, ``"batter_hits"``, ``"total_bases"``.
    line:
        The over/under number (e.g. ``5.5``).
    over_odds:
        American odds for the OVER (e.g. ``-115``).
    under_odds:
        American odds for the UNDER (e.g. ``-105``).
    book:
        Sportsbook name.
    game_date:
        Date of the game.
    """

    prop_id: str
    game_pk: int
    player_id: str
    player_name: str
    stat_type: str
    line: float
    over_odds: int
    under_odds: int
    book: str = "unknown"
    game_date: str = ""


@dataclass
class PropEdge:
    """An analysed prop line with edge and sizing information.

    Attributes
    ----------
    player_id:
        Player identifier.
    player_name:
        Display name.
    stat_type:
        Stat category.
    line:
        The over/under number.
    over_prob:
        Simulated P(stat > line).
    under_prob:
        Simulated P(stat < line).
    best_direction:
        ``"over"`` or ``"under"`` -- direction with positive edge.
    edge_pct:
        Edge percentage (simulated_prob - implied_prob), as a fraction.
    kelly_fraction:
        Kelly-criterion bet size, already scaled by ``kelly_multiplier``.
    wager_pct:
        Recommended wager as a percentage of bankroll (``kelly_fraction * 100``).
    confidence:
        Bootstrap confidence score in [0, 1]; higher = more stable estimate.
    book:
        Sportsbook this edge was found on.
    explanation:
        Glass-box dict with keys: ``top_factors``, ``histogram_data``,
        ``plain_english``, ``bootstrap_std``.
    """

    player_id: str
    player_name: str
    stat_type: str
    line: float
    over_prob: float
    under_prob: float
    best_direction: str
    edge_pct: float
    kelly_fraction: float
    wager_pct: float
    confidence: float
    book: str = "unknown"
    explanation: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serialisable representation of this edge."""
        return asdict(self)


# ---------------------------------------------------------------------------
# Probability / odds utilities
# ---------------------------------------------------------------------------


def american_to_decimal(american_odds: int) -> float:
    """Convert American odds to decimal (European) format.

    Parameters
    ----------
    american_odds:
        Odds in American format, e.g. -110 or +130.

    Returns
    -------
    float
        Decimal odds (e.g. 1.909 for -110, 2.300 for +130).
    """
    if american_odds >= 0:
        return 1.0 + american_odds / 100.0
    return 1.0 + 100.0 / abs(american_odds)


def american_to_implied_prob(american_odds: int) -> float:
    """Convert American odds to raw implied probability (includes vig).

    Parameters
    ----------
    american_odds:
        Odds in American format.

    Returns
    -------
    float
        Implied probability in [0, 1].
    """
    if american_odds >= 0:
        return 100.0 / (american_odds + 100.0)
    return abs(american_odds) / (abs(american_odds) + 100.0)


def no_vig_probabilities(over_odds: int, under_odds: int) -> tuple[float, float]:
    """Remove the sportsbook vig and return fair over/under probabilities.

    Uses the standard additive method: divide each implied probability by
    the total implied probability (overround).

    Parameters
    ----------
    over_odds:
        American odds for the over.
    under_odds:
        American odds for the under.

    Returns
    -------
    tuple[float, float]
        ``(fair_over_prob, fair_under_prob)`` summing to 1.0.
    """
    raw_over = american_to_implied_prob(over_odds)
    raw_under = american_to_implied_prob(under_odds)
    overround = raw_over + raw_under
    return raw_over / overround, raw_under / overround


def kelly_fraction(
    edge: float,
    decimal_odds: float,
    multiplier: float = 0.25,
    cap: float = 0.05,
) -> float:
    """Compute fractional Kelly criterion bet size.

    Parameters
    ----------
    edge:
        Win probability minus no-vig implied probability.
    decimal_odds:
        Decimal odds for the chosen direction.
    multiplier:
        Kelly fraction multiplier (default 0.25 = quarter-Kelly).
    cap:
        Maximum allowed fraction of bankroll (default 5 %).

    Returns
    -------
    float
        Fraction of bankroll to wager; 0.0 if Kelly is negative.
    """
    if decimal_odds <= 1.0 or edge <= 0:
        return 0.0
    b = decimal_odds - 1.0  # net profit per unit staked
    # Full Kelly: (b * p - q) / b where q = 1 - p
    p = edge + (1.0 / decimal_odds)  # approximate win prob
    q = 1.0 - p
    full_kelly = (b * p - q) / b
    if full_kelly <= 0:
        return 0.0
    return min(full_kelly * multiplier, cap)


def bootstrap_confidence(
    arr: np.ndarray,
    threshold: float,
    direction: str = "over",
    n_bootstrap: int = 200,
    rng_seed: int = 0,
) -> float:
    """Estimate confidence via bootstrap standard error of the mean probability.

    Parameters
    ----------
    arr:
        Raw simulation outcome array.
    threshold:
        The prop line value.
    direction:
        ``"over"`` or ``"under"``.
    n_bootstrap:
        Number of bootstrap resamples.
    rng_seed:
        NumPy seed for reproducibility.

    Returns
    -------
    float
        Confidence score in [0, 1]; higher = lower standard error.
    """
    rng = np.random.default_rng(rng_seed)
    n = len(arr)
    boot_probs = np.empty(n_bootstrap)
    for i in range(n_bootstrap):
        sample = rng.choice(arr, size=n, replace=True)
        if direction == "over":
            boot_probs[i] = np.mean(sample > threshold)
        else:
            boot_probs[i] = np.mean(sample < threshold)
    se = float(np.std(boot_probs))
    # Map std-error to a 0-1 confidence score (lower SE = higher confidence)
    # SE of 0 -> 1.0 confidence; SE of 0.1 -> ~0.0 confidence
    return float(max(0.0, 1.0 - se / 0.10))


# ---------------------------------------------------------------------------
# Histogram helper for frontend display
# ---------------------------------------------------------------------------


def _build_histogram_data(arr: np.ndarray, bins: int = 20) -> dict[str, Any]:
    """Compute histogram data for frontend chart rendering.

    Parameters
    ----------
    arr:
        Raw simulation array.
    bins:
        Number of histogram bins.

    Returns
    -------
    dict[str, Any]
        Keys: ``counts``, ``bin_edges``, ``bin_centers``.
    """
    counts, edges = np.histogram(arr, bins=bins)
    centers = (edges[:-1] + edges[1:]) / 2
    return {
        "counts": counts.tolist(),
        "bin_edges": edges.tolist(),
        "bin_centers": centers.tolist(),
    }


# ---------------------------------------------------------------------------
# SHAP-style top factors (simplified feature importance)
# ---------------------------------------------------------------------------

# Map stat types to human-readable driving factors
_STAT_FACTORS: dict[str, list[str]] = {
    "pitcher_strikeouts": [
        "Pitcher strikeout rate vs. handedness",
        "Opposing lineup K% last 14 days",
        "Park factor for strikeouts",
        "Weather: wind speed & direction",
        "Pitcher workload last 5 starts",
    ],
    "pitcher_walks": [
        "Pitcher walk rate vs. handedness",
        "Opposing lineup walk% last 14 days",
        "Pitcher control metrics (BB/9)",
        "Weather: humidity & temperature",
    ],
    "batter_hits": [
        "Batter BA vs. pitcher handedness",
        "Opposing pitcher WHIP last 21 days",
        "Park hit factor",
        "Batter recent form (last 10 games)",
        "Weather: wind to/from CF",
    ],
    "total_bases": [
        "Batter SLG vs. pitcher handedness",
        "Opposing pitcher HR/9 last 21 days",
        "Park HR factor",
        "Exit velocity percentile (Statcast)",
    ],
    "batter_strikeouts": [
        "Batter K% vs. handedness",
        "Opposing pitcher K/9 last 21 days",
        "Pitcher swing-and-miss rate (Statcast)",
    ],
    "rbis": [
        "Lineup position / run-environment",
        "Batter RBI rate in scoring position",
        "Team run-scoring expectation (sim)",
    ],
}


def _top_factors(
    stat_type: str,
    sim_mean: float,
    line: float,
    direction: str,
) -> list[str]:
    """Return the most relevant factors driving a prop prediction.

    Parameters
    ----------
    stat_type:
        Prop stat category.
    sim_mean:
        Simulated mean value.
    line:
        The over/under threshold.
    direction:
        Chosen direction (``"over"`` or ``"under"``).

    Returns
    -------
    list[str]
        Up to 3 plain-English factor strings.
    """
    base_factors = _STAT_FACTORS.get(stat_type, ["Matchup model projection"])
    diff = abs(sim_mean - line)
    strength = "strongly" if diff > 1.0 else "slightly"
    trend = "above" if sim_mean > line else "below"
    summary = (
        f"Simulation mean ({sim_mean:.2f}) is {strength} {trend} the line ({line}); "
        f"recommendation is {direction}."
    )
    return [summary] + base_factors[:2]


def _plain_english(
    player_name: str,
    stat_type: str,
    line: float,
    direction: str,
    edge_pct: float,
    sim_mean: float,
) -> str:
    """Generate a one-sentence plain-English explanation.

    Parameters
    ----------
    player_name / stat_type / line / direction:
        Prop metadata.
    edge_pct:
        Edge as a fraction (e.g. 0.07 = 7 %).
    sim_mean:
        Simulated mean stat value.

    Returns
    -------
    str
        Readable explanation string.
    """
    stat_readable = stat_type.replace("_", " ").replace("pitcher ", "").replace("batter ", "")
    return (
        f"Our model projects {player_name} to average {sim_mean:.1f} {stat_readable} "
        f"vs. a line of {line}, giving a {edge_pct*100:.1f}% edge on the {direction}."
    )


# ---------------------------------------------------------------------------
# PropCalculator
# ---------------------------------------------------------------------------


class PropCalculator:
    """Calculate sportsbook edges by comparing simulation distributions to prop lines.

    Parameters
    ----------
    kelly_multiplier:
        Fractional Kelly multiplier (default 0.25x).
    max_kelly_cap:
        Maximum Kelly fraction of bankroll (default 0.05 = 5 %).
    min_edge_threshold:
        Minimum edge percentage required to include a prop (default 0.03 = 3 %).
    n_bootstrap:
        Bootstrap resamples for confidence estimation (default 200).
    """

    def __init__(
        self,
        kelly_multiplier: float = 0.25,
        max_kelly_cap: float = 0.05,
        min_edge_threshold: float = 0.03,
        n_bootstrap: int = 200,
    ) -> None:
        """Initialise the calculator with configurable sizing parameters."""
        self.kelly_multiplier = kelly_multiplier
        self.max_kelly_cap = max_kelly_cap
        self.min_edge_threshold = min_edge_threshold
        self.n_bootstrap = n_bootstrap

    # ------------------------------------------------------------------
    # Supabase data fetching
    # ------------------------------------------------------------------

    def fetch_todays_props(
        self,
        game_date: str | None = None,
        game_pks: list[int] | None = None,
    ) -> list[PropLine]:
        """Fetch today's prop lines from the Supabase ``props`` table.

        Parameters
        ----------
        game_date:
            ISO date string (e.g. ``"2026-04-01"``).  Defaults to today.
        game_pks:
            Optional filter to specific game IDs.

        Returns
        -------
        list[PropLine]
            Parsed prop lines.
        """
        target_date = game_date or date.today().isoformat()
        params: dict[str, Any] = {
            "select": "*",
            "game_date": f"eq.{target_date}",
        }
        if game_pks:
            pks_str = ",".join(str(pk) for pk in game_pks)
            params["game_pk"] = f"in.({pks_str})"

        logger.info("Fetching props for date=%s from Supabase", target_date)
        rows = _supabase_get("/props", params=params)
        props = [self._row_to_prop_line(r) for r in rows]
        logger.info("Fetched %d prop lines", len(props))
        return props

    @staticmethod
    def _row_to_prop_line(row: dict[str, Any]) -> PropLine:
        """Convert a Supabase ``props`` row to a ``PropLine`` object.

        Parameters
        ----------
        row:
            Raw dict from Supabase REST response.

        Returns
        -------
        PropLine
        """
        return PropLine(
            prop_id=str(row.get("id", "")),
            game_pk=int(row.get("game_pk", 0)),
            player_id=str(row.get("player_id", "")),
            player_name=str(row.get("player_name", "")),
            stat_type=str(row.get("stat_type", "")),
            line=float(row.get("line", 0.0)),
            over_odds=int(row.get("over_odds", -110)),
            under_odds=int(row.get("under_odds", -110)),
            book=str(row.get("book", "unknown")),
            game_date=str(row.get("game_date", "")),
        )

    # ------------------------------------------------------------------
    # Edge calculation
    # ------------------------------------------------------------------

    def calculate_prop_edges(
        self,
        sim_summary: SimulationSummary,
        prop_lines: list[PropLine],
    ) -> list[PropEdge]:
        """Compare simulation distributions against sportsbook prop lines.

        For each ``PropLine``:

        1. Retrieve the simulated outcome distribution from *sim_summary*.
        2. Compute P(over) and P(under) empirically.
        3. Convert sportsbook odds to no-vig fair probabilities.
        4. Compute edge = simulated_prob - implied_prob.
        5. Size with Kelly criterion (fractional).
        6. Attach glass-box explanation.

        Parameters
        ----------
        sim_summary:
            Aggregated simulation output for a single game.
        prop_lines:
            List of sportsbook props to evaluate.

        Returns
        -------
        list[PropEdge]
            All edges with positive edge, sorted by absolute edge descending.
        """
        edges: list[PropEdge] = []

        for prop in prop_lines:
            edge = self._evaluate_single_prop(sim_summary, prop)
            if edge is not None and abs(edge.edge_pct) >= self.min_edge_threshold:
                edges.append(edge)

        # Sort by absolute edge descending
        edges.sort(key=lambda e: abs(e.edge_pct), reverse=True)
        logger.info(
            "Found %d props with edge >= %.1f%%",
            len(edges),
            self.min_edge_threshold * 100,
        )
        return edges

    def _evaluate_single_prop(
        self, sim_summary: SimulationSummary, prop: PropLine
    ) -> PropEdge | None:
        """Evaluate one prop line against simulation data.

        Parameters
        ----------
        sim_summary:
            Simulation summary (must contain ``raw`` arrays).
        prop:
            The prop line to evaluate.

        Returns
        -------
        PropEdge | None
            Populated edge object, or None if simulation data unavailable.
        """
        if sim_summary.raw is None:
            logger.warning("SimulationSummary has no raw arrays; skipping prop %s", prop.prop_id)
            return None

        sim_stat = _normalise_stat_type(prop.stat_type)
        raw_arr = sim_summary._get_raw_array(prop.player_id, sim_stat)
        if raw_arr is None:
            logger.debug(
                "No simulation data for player_id=%s stat=%s", prop.player_id, prop.stat_type
            )
            return None

        sim_over = float(np.mean(raw_arr > prop.line))
        sim_under = float(np.mean(raw_arr < prop.line))

        # No-vig book probabilities
        fair_over, fair_under = no_vig_probabilities(prop.over_odds, prop.under_odds)

        over_edge = sim_over - fair_over
        under_edge = sim_under - fair_under

        if over_edge >= under_edge:
            best_dir = "over"
            best_edge = over_edge
            best_odds = prop.over_odds
        else:
            best_dir = "under"
            best_edge = under_edge
            best_odds = prop.under_odds

        dec_odds = american_to_decimal(best_odds)
        kf = kelly_fraction(
            edge=best_edge,
            decimal_odds=dec_odds,
            multiplier=self.kelly_multiplier,
            cap=self.max_kelly_cap,
        )

        conf = bootstrap_confidence(
            raw_arr, prop.line, best_dir, self.n_bootstrap
        )

        sim_mean = float(np.mean(raw_arr))
        hist_data = _build_histogram_data(raw_arr)
        factors = _top_factors(prop.stat_type, sim_mean, prop.line, best_dir)
        plain = _plain_english(
            prop.player_name, prop.stat_type, prop.line, best_dir, best_edge, sim_mean
        )

        explanation: dict[str, Any] = {
            "top_factors": factors,
            "histogram_data": hist_data,
            "plain_english": plain,
            "bootstrap_std": float(1.0 - conf) * 0.10,
            "sim_mean": sim_mean,
            "fair_over_prob": round(fair_over, 4),
            "fair_under_prob": round(fair_under, 4),
        }

        return PropEdge(
            player_id=prop.player_id,
            player_name=prop.player_name,
            stat_type=prop.stat_type,
            line=prop.line,
            over_prob=round(sim_over, 4),
            under_prob=round(sim_under, 4),
            best_direction=best_dir,
            edge_pct=round(best_edge, 4),
            kelly_fraction=round(kf, 4),
            wager_pct=round(kf * 100, 2),
            confidence=round(conf, 4),
            book=prop.book,
            explanation=explanation,
        )

    # ------------------------------------------------------------------
    # Output formatters
    # ------------------------------------------------------------------

    def to_json(self, edges: list[PropEdge], indent: int = 2) -> str:
        """Serialise a list of ``PropEdge`` objects to a JSON string.

        Parameters
        ----------
        edges:
            Output of ``calculate_prop_edges``.
        indent:
            JSON indentation level.

        Returns
        -------
        str
            JSON-encoded edge list.
        """
        return json.dumps([e.to_dict() for e in edges], indent=indent, default=str)

    def to_markdown(self, edges: list[PropEdge]) -> str:
        """Format edges as a Markdown table.

        Parameters
        ----------
        edges:
            Output of ``calculate_prop_edges``.

        Returns
        -------
        str
            Markdown table string.
        """
        if not edges:
            return "_No edges found above threshold._\n"
        lines = [
            "| Player | Stat | Line | Dir | Sim P | Edge | Kelly | Conf | Book |",
            "|--------|------|------|-----|-------|------|-------|------|------|",
        ]
        for e in edges:
            sim_p = e.over_prob if e.best_direction == "over" else e.under_prob
            lines.append(
                f"| {e.player_name} | {e.stat_type} | {e.line} "
                f"| {e.best_direction} | {sim_p:.3f} | {e.edge_pct*100:.1f}% "
                f"| {e.wager_pct:.2f}% | {e.confidence:.2f} | {e.book} |"
            )
        return "\n".join(lines) + "\n"

    def to_text(self, edges: list[PropEdge]) -> str:
        """Format edges as a plain-text report.

        Parameters
        ----------
        edges:
            Output of ``calculate_prop_edges``.

        Returns
        -------
        str
            Human-readable multi-line report.
        """
        if not edges:
            return "No edges found above threshold.\n"
        sep = "-" * 60
        parts = [sep, f"  PROP EDGE REPORT -- {len(edges)} edges found", sep]
        for i, e in enumerate(edges, 1):
            sim_p = e.over_prob if e.best_direction == "over" else e.under_prob
            parts.append(
                f"\n#{i}  {e.player_name}  |  {e.stat_type}  |  {e.best_direction.upper()} {e.line}"
            )
            parts.append(f"     Sim prob  : {sim_p*100:.1f}%")
            parts.append(f"     Edge      : {e.edge_pct*100:.1f}%")
            parts.append(f"     Kelly     : {e.wager_pct:.2f}% of bankroll")
            parts.append(f"     Confidence: {e.confidence:.2f}")
            parts.append(f"     Book      : {e.book}")
            parts.append(f"     Why       : {e.explanation.get('plain_english', '')}")
        parts.append("\n" + sep)
        return "\n".join(parts)


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Calculate sportsbook prop edges from a simulation summary."
    )
    parser.add_argument(
        "--date",
        type=str,
        default=date.today().isoformat(),
        help="Game date (YYYY-MM-DD, default: today)",
    )
    parser.add_argument(
        "--game-pk",
        type=int,
        nargs="*",
        help="Optional game PKs to filter props",
    )
    parser.add_argument(
        "--min-edge",
        type=float,
        default=0.03,
        help="Minimum edge threshold (default: 0.03 = 3%%)",
    )
    parser.add_argument(
        "--kelly",
        type=float,
        default=0.25,
        help="Kelly fraction multiplier (default: 0.25)",
    )
    parser.add_argument(
        "--output",
        choices=["json", "markdown", "text"],
        default="text",
        help="Output format",
    )
    args = parser.parse_args()

    calc = PropCalculator(
        kelly_multiplier=args.kelly,
        min_edge_threshold=args.min_edge,
    )
    try:
        props = calc.fetch_todays_props(
            game_date=args.date,
            game_pks=args.game_pk,
        )
    except RuntimeError as exc:
        logger.error("Failed to fetch props: %s", exc)
        raise SystemExit(1) from exc

    logger.info("Fetched %d props; use calculate_prop_edges() with a SimulationSummary.", len(props))
    print(f"Loaded {len(props)} props for {args.date}. "
          "Pipe a SimulationSummary in to compute edges.")


# ===========================================================================
# PROP CALCULATOR COMPATIBILITY LAYER
# ===========================================================================
# New interfaces expected by test_simulator.py
# ===========================================================================

if TYPE_CHECKING:
    from .monte_carlo_engine import GameSimResults, PlayerSimResults


def remove_vig(over_odds: int, under_odds: int) -> tuple[float, float]:
    """Remove vig and return fair (over_prob, under_prob).

    Wrapper around ``no_vig_probabilities`` with the name tests expect.
    """
    return no_vig_probabilities(over_odds, under_odds)


# ---------------------------------------------------------------------------
# New PropLine  (tests use mlbam_id instead of player_id/prop_id)
# ---------------------------------------------------------------------------

@dataclass
class PropLine:  # type: ignore[no-redef]  # noqa: F811
    """Sportsbook prop line -- new interface used by tests.

    Attributes
    ----------
    mlbam_id : int
        MLB Advanced Media player ID.
    player_name : str
        Display name.
    stat_type : str
        E.g. ``"K"``, ``"H"``, ``"TB"``.
    line : float
        The over/under number.
    over_odds : int
        American odds for the OVER (default -110).
    under_odds : int
        American odds for the UNDER (default -110).
    """
    mlbam_id: int
    player_name: str
    stat_type: str
    line: float
    over_odds: int = -110
    under_odds: int = -110


# ---------------------------------------------------------------------------
# New PropEdge  (tests use .direction, .edge, .confidence_tier, etc.)
# ---------------------------------------------------------------------------

@dataclass
class PropEdge:  # type: ignore[no-redef]  # noqa: F811
    """Analysed prop line -- new interface used by tests.

    Attributes
    ----------
    mlbam_id : int
    player_name : str
    stat_type : str
    line : float
    direction : str
        ``"OVER"`` or ``"UNDER"``.
    edge : float
        Signed edge (positive = value exists).
    sim_prob : float
        Simulated probability for the chosen direction.
    fair_prob : float
        No-vig implied probability.
    kelly_stake : float
        Recommended wager (dollar amount if bankroll provided, else fraction).
    confidence_score : float
        Bootstrap confidence in [0, 1].
    confidence_tier : str
        ``"A"`` (>= 0.7), ``"B"`` (>= 0.4), or ``"C"`` otherwise.
    """
    mlbam_id: int
    player_name: str
    stat_type: str
    line: float
    direction: str
    edge: float
    sim_prob: float
    fair_prob: float
    kelly_stake: float
    confidence_score: float
    confidence_tier: str

    def to_dict(self) -> dict:
        """Return a JSON-serialisable dict."""
        return {
            "mlbam_id": self.mlbam_id,
            "player_name": self.player_name,
            "stat_type": self.stat_type,
            "line": self.line,
            "direction": self.direction,
            "edge": self.edge,
            "sim_prob": self.sim_prob,
            "fair_prob": self.fair_prob,
            "kelly_stake": self.kelly_stake,
            "confidence_score": self.confidence_score,
            "confidence_tier": self.confidence_tier,
        }


# Stat alias map: test uses short stat keys
_NEW_STAT_ALIASES: dict[str, str] = {
    "K": "strikeouts",
    "H": "hits",
    "TB": "total_bases",
    "HR": "home_runs",
    "BB": "walks",
    "R": "runs",
    "RBI": "rbis",
    "PA": "plate_appearances",
    "strikeouts": "strikeouts",
    "hits": "hits",
    "total_bases": "total_bases",
    "home_runs": "home_runs",
    "walks": "walks",
    "runs": "runs",
    "rbis": "rbis",
    "plate_appearances": "plate_appearances",
}


# ---------------------------------------------------------------------------
# New PropCalculator
# ---------------------------------------------------------------------------

class PropCalculator:  # type: ignore[no-redef]
    """Calculate sportsbook prop edges against simulation distributions.

    Parameters
    ----------
    bankroll : float
        Total bankroll for Kelly sizing (dollar amount).
    kelly_fraction : float
        Fractional Kelly multiplier (default 0.25).
    max_kelly_pct : float
        Cap on Kelly fraction (default 0.05 = 5%).
    min_edge : float
        Minimum absolute edge to include (default 0.0).
    n_bootstrap : int
        Bootstrap resamples for confidence (default 200).
    """

    MAX_KELLY_CAP: float = 50.0  # max dollar stake regardless of bankroll

    def __init__(
        self,
        bankroll: float = 1000.0,
        kelly_fraction: float = 0.25,
        max_kelly_pct: float = 0.05,
        min_edge: float = 0.03,
        n_bootstrap: int = 200,
    ) -> None:
        self.bankroll = bankroll
        self.kelly_fraction = kelly_fraction
        self.max_kelly_pct = max_kelly_pct
        self.min_edge = min_edge
        self.n_bootstrap = n_bootstrap

    # ------------------------------------------------------------------
    # Core evaluation
    # ------------------------------------------------------------------

    def evaluate_prop(
        self,
        player_sim: "PlayerSimResults",
        prop: "PropLine",
    ) -> "PropEdge | None":
        """Evaluate a single prop line against a player's simulation results.

        Returns ``None`` if the stat type is unknown.
        """
        stat_key = _NEW_STAT_ALIASES.get(prop.stat_type)
        if stat_key is None:
            return None

        try:
            arr = player_sim.distribution(prop.stat_type)
        except KeyError:
            return None

        over_p = float(np.mean(arr > prop.line))
        under_p = float(np.mean(arr < prop.line))

        fair_over, fair_under = no_vig_probabilities(prop.over_odds, prop.under_odds)

        over_edge = over_p - fair_over
        under_edge = under_p - fair_under

        if over_edge >= under_edge:
            direction = "OVER"
            edge = over_edge
            sim_p = over_p
            fair_p = fair_over
            odds = prop.over_odds
        else:
            direction = "UNDER"
            edge = under_edge
            sim_p = under_p
            fair_p = fair_under
            odds = prop.under_odds

        dec_odds = american_to_decimal(odds)
        kf = kelly_fraction(
            edge=edge,
            decimal_odds=dec_odds,
            multiplier=self.kelly_fraction,
            cap=self.max_kelly_pct,
        )
        stake = min(float(kf * self.bankroll), self.MAX_KELLY_CAP)

        conf = bootstrap_confidence(
            arr, prop.line,
            direction.lower(),
            self.n_bootstrap,
        )
        if conf >= 0.7:
            tier = "A"
        elif conf >= 0.4:
            tier = "B"
        else:
            tier = "C"

        return PropEdge(
            mlbam_id=prop.mlbam_id,
            player_name=prop.player_name,
            stat_type=prop.stat_type,
            line=prop.line,
            direction=direction,
            edge=round(edge, 4),
            sim_prob=round(sim_p, 4),
            fair_prob=round(fair_p, 4),
            kelly_stake=round(stake, 2),
            confidence_score=round(conf, 4),
            confidence_tier=tier,
        )

    def evaluate_props(
        self,
        game_results: "GameSimResults",
        props: list["PropLine"],
        pitcher_k_dist: "np.ndarray | None" = None,
        pitcher_mlbam_id: int | None = None,
        pitcher_name: str | None = None,
    ) -> list["PropEdge"]:
        """Evaluate a list of prop lines against game simulation results.

        Optionally includes a pitcher K prop from ``pitcher_k_dist``.

        Returns edges sorted by absolute edge descending.
        """
        from .monte_carlo_engine import PlayerSimResults as _PSR

        edges: list[PropEdge] = []

        # Build a lookup of pitcher PlayerSimResults if provided
        if pitcher_k_dist is not None and pitcher_mlbam_id is not None:
            # Wrap pitcher K array into a PlayerSimResults-like object
            n = len(pitcher_k_dist)
            zeros = np.zeros(n, dtype=np.int32)
            pitcher_pr = _PSR(
                mlbam_id=pitcher_mlbam_id,
                name=pitcher_name or "Pitcher",
                n_sims=n,
                strikeouts=pitcher_k_dist.astype(np.int32),
                hits=zeros, total_bases=zeros, home_runs=zeros,
                walks=zeros, runs=zeros, rbis=zeros, plate_appearances=zeros,
            )
        else:
            pitcher_pr = None

        for prop in props:
            # Look for player in batter results first
            player_sim = game_results.player_results.get(prop.mlbam_id)

            # Fall back to pitcher profile if mlbam_id matches pitcher
            if player_sim is None and pitcher_pr is not None:
                if prop.mlbam_id == pitcher_mlbam_id:
                    player_sim = pitcher_pr

            if player_sim is None:
                continue

            edge = self.evaluate_prop(player_sim, prop)
            if edge is not None:
                edges.append(edge)

        edges.sort(key=lambda e: abs(e.edge), reverse=True)
        return edges

    def kelly_criterion(
        self,
        win_prob: float,
        decimal_odds: float,
    ) -> float:
        """Compute fractional Kelly stake (dollar amount).

        Returns 0.0 if Kelly is non-positive.
        """
        if decimal_odds <= 1.0:
            return 0.0
        b = decimal_odds - 1.0
        q = 1.0 - win_prob
        full_kelly = (b * win_prob - q) / b
        if full_kelly <= 0:
            return 0.0
        stake = min(full_kelly * self.kelly_fraction * self.bankroll, self.MAX_KELLY_CAP)
        return float(stake)

    def expected_value(self, win_prob: float, decimal_odds: float) -> float:
        """Return expected value per unit staked: win_prob * (odds-1) - loss_prob."""
        return win_prob * (decimal_odds - 1.0) - (1.0 - win_prob)

    def filter_edges(
        self,
        edges: list["PropEdge"],
        min_edge: float = 0.03,
    ) -> list["PropEdge"]:
        """Return only edges with |edge| >= *min_edge*."""
        return [e for e in edges if abs(e.edge) >= min_edge]

    def top_plays(
        self,
        edges: list["PropEdge"],
        n: int = 5,
        direction: str | None = None,
    ) -> list["PropEdge"]:
        """Return top *n* plays, optionally filtered by direction."""
        filtered = edges
        if direction is not None:
            filtered = [e for e in edges if e.direction == direction]
        return filtered[:n]

    def format_summary(self, edges: list["PropEdge"]) -> str:
        """Return a plain-text summary of the top edges."""
        if not edges:
            return "BaselineMLB -- No edges found.\n"
        sep = "-" * 60
        lines = [sep, "  BaselineMLB Prop Edge Summary", sep]
        for i, e in enumerate(edges, 1):
            lines.append(
                f"#{i:2d} {e.player_name:20s}  {e.stat_type:4s} {e.direction:5s} "
                f"{e.line:5.1f}  edge={e.edge*100:+.1f}%  "
                f"kelly=${e.kelly_stake:.2f}  tier={e.confidence_tier}"
            )
        lines.append(sep)
        return "\n".join(lines)
