"""
prop_analyzer.py — BaselineMLB Monte Carlo Simulator
=====================================================
Compares simulated probability distributions to sportsbook prop lines and
identifies edges.

Exposes:
  PropLine       — dataclass representing a single sportsbook player prop
  PropAnalysis   — dataclass for the full edge analysis result
  PropAnalyzer   — main engine: converts SimulationResult + prop lines → PropAnalysis
  PropReporter   — formats PropAnalysis objects for markdown, JSON, Supabase, Twitter

Usage example
-------------
>>> from simulation.config import SimulationConfig
>>> from simulation.prop_analyzer import PropAnalyzer, PropLine, PropReporter
>>> analyzer = PropAnalyzer(SimulationConfig())
>>> analysis = analyzer.analyze_prop(prop, sim_result)
>>> reporter = PropReporter()
>>> print(reporter.format_markdown([analysis], game_info))
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any

from simulation.config import SimulationConfig
from simulation.game_engine import SimulationResult

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Module-level constants
# ---------------------------------------------------------------------------

MODEL_VERSION = "mc-v1.0"

# Mapping from sportsbook stat_type strings to the stat keys used in PlayerStats
_STAT_TYPE_MAP: dict[str, str] = {
    "pitcher_strikeouts": "strikeouts",
    "batter_hits": "hits",
    "batter_total_bases": "total_bases",
    "batter_home_runs": "home_runs",
    "batter_strikeouts": "strikeouts",
    "batter_walks": "walks",
    "batter_runs": "runs_scored",
    "batter_rbis": "rbis",
}

# Minimum sample PA to qualify for HIGH confidence tier
_HIGH_CONFIDENCE_MIN_PA = 100


# ===========================================================================
# PropLine
# ===========================================================================


@dataclass
class PropLine:
    """
    A single sportsbook player prop line.

    Attributes
    ----------
    player_id:
        MLBAM player ID.
    player_name:
        Human-readable player name (e.g. ``"Corbin Burnes"``).
    stat_type:
        Canonical stat identifier used by the book (e.g.
        ``"pitcher_strikeouts"``, ``"batter_hits"``).  Must be one of the
        keys in ``_STAT_TYPE_MAP``.
    line:
        The over/under line number (e.g. ``5.5``).
    over_odds:
        American odds for the over (e.g. ``-115``).
    under_odds:
        American odds for the under (e.g. ``-105``).
    sportsbook:
        Name of the sportsbook (e.g. ``"fanduel"``, ``"draftkings"``).
    """

    player_id: int
    player_name: str
    stat_type: str
    line: float
    over_odds: int
    under_odds: int
    sportsbook: str


# ===========================================================================
# PropAnalysis
# ===========================================================================


@dataclass
class PropAnalysis:
    """
    Full edge analysis for one player prop.

    Attributes
    ----------
    prop:
        The source :class:`PropLine`.
    simulated_mean:
        Mean of the simulated stat distribution.
    simulated_median:
        Median of the simulated stat distribution.
    p_over:
        Simulated P(stat > line).
    p_under:
        Simulated P(stat <= line).
    implied_prob_over:
        No-vig implied probability for the over, derived from book odds.
    implied_prob_under:
        No-vig implied probability for the under.
    edge_over:
        ``p_over - implied_prob_over``.
    edge_under:
        ``p_under - implied_prob_under``.
    recommended_side:
        ``'over'``, ``'under'``, or ``'pass'``.
    kelly_fraction:
        Raw Kelly fraction (before multiplier and cap).
    kelly_wager_pct:
        Final wager percentage of bankroll (Kelly × KELLY_FRACTION, capped at
        MAX_KELLY_BET).
    confidence_tier:
        ``'HIGH'``, ``'MEDIUM'``, ``'LOW'``, or ``'PASS'``.
    ev_pct:
        Expected value percentage (``edge * 100``).
    factors:
        Glass-box factor breakdown from the matchup model
        (keyed by factor name; may be empty if no explain data was attached to
        the SimulationResult).
    distribution:
        Full probability distribution from the simulation
        (``{value: probability}`` mapping, values are integers).
    """

    prop: PropLine
    simulated_mean: float
    simulated_median: float
    p_over: float
    p_under: float
    implied_prob_over: float
    implied_prob_under: float
    edge_over: float
    edge_under: float
    recommended_side: str
    kelly_fraction: float
    kelly_wager_pct: float
    confidence_tier: str
    ev_pct: float
    factors: dict = field(default_factory=dict)
    distribution: dict = field(default_factory=dict)


# ===========================================================================
# PropAnalyzer
# ===========================================================================


class PropAnalyzer:
    """
    Core engine for comparing simulated distributions to sportsbook prop lines.

    Parameters
    ----------
    config:
        :class:`~simulation.config.SimulationConfig` instance.  Thresholds
        (``EV_THRESHOLD``, ``KELLY_FRACTION``, ``MAX_KELLY_BET``) are read
        from this object.

    Example
    -------
    >>> cfg = SimulationConfig()
    >>> analyzer = PropAnalyzer(cfg)
    >>> result = simulator.simulate_game(game_data)
    >>> analyses = analyzer.analyze_game(result, prop_lines)
    >>> top = analyzer.get_top_plays(analyses)
    """

    def __init__(self, config: SimulationConfig) -> None:
        self._config = config

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def analyze_prop(
        self,
        prop: PropLine,
        sim_result: SimulationResult,
    ) -> PropAnalysis:
        """
        Analyze a single player prop against the simulation results.

        Parameters
        ----------
        prop:
            The sportsbook prop to evaluate.
        sim_result:
            Completed :class:`~simulation.game_engine.SimulationResult`.

        Returns
        -------
        PropAnalysis
            Full edge analysis.  If the player is not found in the simulation
            results, returns a ``'pass'`` analysis with zeroed probabilities.
        """
        # 1. Map stat_type to simulation stat key
        stat_key = _STAT_TYPE_MAP.get(prop.stat_type)
        if stat_key is None:
            logger.warning(
                "Unknown stat_type '%s' for player %s; returning PASS.",
                prop.stat_type,
                prop.player_name,
            )
            return self._pass_analysis(prop)

        # Look up the PlayerStats object
        ps = sim_result.player_results.get(prop.player_id)
        if ps is None:
            logger.warning(
                "player_id=%d (%s) not found in simulation results; returning PASS.",
                prop.player_id,
                prop.player_name,
            )
            return self._pass_analysis(prop)

        # 2. Get P(over) and P(under) from simulation
        p_over = ps.get_p_over(stat_key, prop.line)
        p_under = 1.0 - p_over

        # Simulated distribution as {value: probability}
        raw_dist = ps.get_distribution(stat_key)
        total_sims = sum(raw_dist.values()) if raw_dist else 0
        distribution: dict[int, float] = {}
        if total_sims > 0:
            distribution = {
                int(k): round(v / total_sims, 6)
                for k, v in sorted(raw_dist.items())
            }

        simulated_mean = round(ps.get_mean(stat_key), 4)
        simulated_median = ps.get_median(stat_key)

        # 3. Convert American odds to no-vig implied probabilities
        implied_prob_over, implied_prob_under = self._no_vig_probs(
            prop.over_odds, prop.under_odds
        )

        # 4. Calculate edge
        edge_over = p_over - implied_prob_over
        edge_under = p_under - implied_prob_under

        # 5. Recommended side
        ev_threshold = self._config.EV_THRESHOLD
        best_edge = max(edge_over, edge_under)

        if best_edge < ev_threshold:
            recommended_side = "pass"
            active_sim_prob = 0.5
            active_decimal_odds = 2.0
        elif edge_over >= edge_under:
            recommended_side = "over"
            active_sim_prob = p_over
            active_decimal_odds = self._american_to_decimal(prop.over_odds)
        else:
            recommended_side = "under"
            active_sim_prob = p_under
            active_decimal_odds = self._american_to_decimal(prop.under_odds)

        # 6. Kelly criterion
        # f* = (edge * decimal_odds - (1 - sim_prob)) / decimal_odds
        # Simplified: f* = (sim_prob * decimal_odds - 1) / (decimal_odds - 1)
        # We use the standard Kelly formula: f* = (b*p - q) / b
        # where b = decimal_odds - 1, p = sim_prob, q = 1 - p
        if recommended_side == "pass":
            raw_kelly = 0.0
        else:
            b = active_decimal_odds - 1.0
            p = active_sim_prob
            q = 1.0 - p
            raw_kelly = (b * p - q) / b if b > 0 else 0.0
            raw_kelly = max(raw_kelly, 0.0)

        kelly_fraction = raw_kelly
        kelly_wager_pct = min(
            raw_kelly * self._config.KELLY_FRACTION,
            self._config.MAX_KELLY_BET,
        )

        # 7. Confidence tier
        # HIGH requires edge >= 0.08 AND sufficient sample PA
        sample_pa = total_sims  # proxy: total simulation count
        if best_edge >= 0.08 and sample_pa >= _HIGH_CONFIDENCE_MIN_PA:
            confidence_tier = "HIGH"
        elif best_edge >= 0.05:
            confidence_tier = "MEDIUM"
        elif best_edge >= ev_threshold:
            confidence_tier = "LOW"
        else:
            confidence_tier = "PASS"

        # 8. EV%
        ev_pct = round(best_edge * 100, 4) if recommended_side != "pass" else 0.0

        # Factors: try to pull from sim_result game_info if matchup explain data
        # was stored there (by convention under 'explain_data')
        factors: dict = {}
        explain_data = sim_result.game_info.get("explain_data", {})
        player_explain = explain_data.get(prop.player_id, {})
        if player_explain:
            # Extract the outcome-specific factors for the target stat
            outcome_map = player_explain.get("outcomes", {})
            # Flatten to a human-readable summary keyed by factor name
            for outcome_name, detail in outcome_map.items():
                if isinstance(detail, dict) and "adjustments" in detail:
                    factors[outcome_name] = detail["adjustments"]

        return PropAnalysis(
            prop=prop,
            simulated_mean=simulated_mean,
            simulated_median=simulated_median,
            p_over=round(p_over, 6),
            p_under=round(p_under, 6),
            implied_prob_over=round(implied_prob_over, 6),
            implied_prob_under=round(implied_prob_under, 6),
            edge_over=round(edge_over, 6),
            edge_under=round(edge_under, 6),
            recommended_side=recommended_side,
            kelly_fraction=round(kelly_fraction, 6),
            kelly_wager_pct=round(kelly_wager_pct, 6),
            confidence_tier=confidence_tier,
            ev_pct=round(ev_pct, 4),
            factors=factors,
            distribution=distribution,
        )

    def analyze_game(
        self,
        sim_result: SimulationResult,
        prop_lines: list[PropLine],
    ) -> list[PropAnalysis]:
        """
        Analyze all prop lines for a simulated game.

        Parameters
        ----------
        sim_result:
            Completed :class:`~simulation.game_engine.SimulationResult`.
        prop_lines:
            List of :class:`PropLine` objects to evaluate.

        Returns
        -------
        list[PropAnalysis]
            One analysis per prop line, in the same order as *prop_lines*.
        """
        analyses: list[PropAnalysis] = []
        for prop in prop_lines:
            try:
                analysis = self.analyze_prop(prop, sim_result)
            except Exception:
                logger.exception(
                    "analyze_prop failed for player=%s stat=%s",
                    prop.player_name,
                    prop.stat_type,
                )
                analysis = self._pass_analysis(prop)
            analyses.append(analysis)
        return analyses

    def get_top_plays(
        self,
        analyses: list[PropAnalysis],
        top_n: int = 10,
    ) -> dict[str, list[PropAnalysis]]:
        """
        Return the top N over and under plays sorted by absolute edge.

        Only plays where ``recommended_side`` is ``'over'`` or ``'under'``
        (i.e. not ``'pass'``) are included.

        Parameters
        ----------
        analyses:
            Full list of :class:`PropAnalysis` objects from
            :meth:`analyze_game`.
        top_n:
            Maximum number of plays to return per side (default 10).

        Returns
        -------
        dict
            ``{'over': list[PropAnalysis], 'under': list[PropAnalysis]}``
            Each list is sorted descending by edge magnitude.
        """
        over_plays = sorted(
            [a for a in analyses if a.recommended_side == "over"],
            key=lambda a: a.edge_over,
            reverse=True,
        )[:top_n]

        under_plays = sorted(
            [a for a in analyses if a.recommended_side == "under"],
            key=lambda a: a.edge_under,
            reverse=True,
        )[:top_n]

        return {"over": over_plays, "under": under_plays}

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _american_to_implied(odds: int) -> float:
        """
        Convert American odds to raw implied probability (includes vig).

        Parameters
        ----------
        odds:
            American odds integer (e.g. -115 or +130).

        Returns
        -------
        float
            Implied probability in [0, 1].
        """
        if odds < 0:
            return abs(odds) / (abs(odds) + 100)
        return 100.0 / (odds + 100)

    @staticmethod
    def _american_to_decimal(odds: int) -> float:
        """
        Convert American odds to decimal odds.

        Parameters
        ----------
        odds:
            American odds integer.

        Returns
        -------
        float
            Decimal odds (e.g. -115 → ~1.8696, +130 → 2.30).
        """
        if odds < 0:
            return 1.0 + 100.0 / abs(odds)
        return 1.0 + odds / 100.0

    def _no_vig_probs(
        self, over_odds: int, under_odds: int
    ) -> tuple[float, float]:
        """
        Convert over and under American odds to no-vig implied probabilities.

        The vig is removed by normalising both raw implied probabilities so
        they sum to exactly 1.0.

        Parameters
        ----------
        over_odds:
            American odds for the over side.
        under_odds:
            American odds for the under side.

        Returns
        -------
        tuple[float, float]
            ``(no_vig_over, no_vig_under)`` — both values sum to 1.0.
        """
        over_imp = self._american_to_implied(over_odds)
        under_imp = self._american_to_implied(under_odds)
        total = over_imp + under_imp
        if total <= 0:
            return 0.5, 0.5
        return over_imp / total, under_imp / total

    @staticmethod
    def _pass_analysis(prop: PropLine) -> PropAnalysis:
        """
        Return a zeroed-out PASS PropAnalysis for a prop that cannot be
        evaluated (player not found, unknown stat type, etc.).

        Parameters
        ----------
        prop:
            The source :class:`PropLine`.

        Returns
        -------
        PropAnalysis
            All probabilities zeroed and ``recommended_side = 'pass'``.
        """
        return PropAnalysis(
            prop=prop,
            simulated_mean=0.0,
            simulated_median=0.0,
            p_over=0.0,
            p_under=0.0,
            implied_prob_over=0.5,
            implied_prob_under=0.5,
            edge_over=0.0,
            edge_under=0.0,
            recommended_side="pass",
            kelly_fraction=0.0,
            kelly_wager_pct=0.0,
            confidence_tier="PASS",
            ev_pct=0.0,
            factors={},
            distribution={},
        )


# ===========================================================================
# PropReporter
# ===========================================================================


class PropReporter:
    """
    Formats :class:`PropAnalysis` results for various output channels.

    All methods are pure functions of their inputs (no state).
    """

    # ------------------------------------------------------------------
    # Markdown
    # ------------------------------------------------------------------

    def format_markdown(
        self,
        analyses: list[PropAnalysis],
        game_info: dict,
    ) -> str:
        """
        Render a markdown table of prop analyses plus glass-box factor
        explanations for HIGH-confidence plays.

        Parameters
        ----------
        analyses:
            List of :class:`PropAnalysis` results.
        game_info:
            Game metadata dict (same structure as
            ``SimulationResult.game_info``).  Used for the section header.

        Returns
        -------
        str
            Multi-line markdown string ready for display or file output.
        """
        away = game_info.get("away_team", "Away")
        home = game_info.get("home_team", "Home")
        venue = game_info.get("venue", "Unknown Venue")
        game_date = game_info.get("game_date", "")
        num_sims = game_info.get("num_simulations", "?")

        lines: list[str] = [
            f"# BaselineMLB Prop Analysis — {away} @ {home}",
            f"**Date:** {game_date}  |  **Venue:** {venue}  |  **Simulations:** {num_sims}",
            "",
            "| Player | Prop | Line | Sim Mean | P(Over) | Book Imp | Edge | Side | Kelly% | Confidence |",
            "|--------|------|------|----------|---------|----------|------|------|--------|------------|",
        ]

        high_confidence_plays: list[PropAnalysis] = []

        for a in analyses:
            prop = a.prop
            # Determine the active edge and implied prob for display
            if a.recommended_side == "over":
                edge_str = f"+{a.edge_over * 100:.1f}%"
                book_imp_str = f"{a.implied_prob_over * 100:.1f}%"
                p_over_str = f"{a.p_over * 100:.1f}%"
            elif a.recommended_side == "under":
                edge_str = f"+{a.edge_under * 100:.1f}%"
                book_imp_str = f"{a.implied_prob_under * 100:.1f}%"
                p_over_str = f"{a.p_over * 100:.1f}%"
            else:
                edge_str = "—"
                book_imp_str = f"{a.implied_prob_over * 100:.1f}%"
                p_over_str = f"{a.p_over * 100:.1f}%"

            side_str = a.recommended_side.upper() if a.recommended_side != "pass" else "PASS"
            kelly_str = f"{a.kelly_wager_pct * 100:.1f}%" if a.recommended_side != "pass" else "—"
            conf_badge = {
                "HIGH": "✦ HIGH",
                "MEDIUM": "MEDIUM",
                "LOW": "LOW",
                "PASS": "—",
            }.get(a.confidence_tier, a.confidence_tier)

            lines.append(
                f"| {prop.player_name} "
                f"| {_fmt_stat_type(prop.stat_type)} "
                f"| {prop.line} "
                f"| {a.simulated_mean:.2f} "
                f"| {p_over_str} "
                f"| {book_imp_str} "
                f"| {edge_str} "
                f"| {side_str} "
                f"| {kelly_str} "
                f"| {conf_badge} |"
            )

            if a.confidence_tier == "HIGH":
                high_confidence_plays.append(a)

        # Inline summary lines for all playable props
        playable = [a for a in analyses if a.recommended_side != "pass"]
        if playable:
            lines.extend(["", "## Play Summaries"])
            for a in playable:
                prop = a.prop
                side = a.recommended_side
                edge_val = a.edge_over if side == "over" else a.edge_under
                p_sim = a.p_over if side == "over" else a.p_under
                imp = a.implied_prob_over if side == "over" else a.implied_prob_under
                side_label = "O" if side == "over" else "U"
                lines.append(
                    f"**{prop.player_name} {side_label}{prop.line} "
                    f"{_fmt_stat_type(prop.stat_type)}**: "
                    f"sim P({side})={p_sim * 100:.1f}%, "
                    f"book implied={imp * 100:.1f}%, "
                    f"edge=+{edge_val * 100:.1f}%, "
                    f"Kelly={a.kelly_wager_pct * 100:.2f}%"
                )

        # Glass-box factor explanations for HIGH-confidence plays
        if high_confidence_plays:
            lines.extend(["", "## High-Confidence Play Factors"])
            for a in high_confidence_plays:
                prop = a.prop
                side = a.recommended_side
                edge_val = a.edge_over if side == "over" else a.edge_under
                side_label = "O" if side == "over" else "U"
                lines.append(
                    f"\n### {prop.player_name} {side_label}{prop.line} "
                    f"— edge=+{edge_val * 100:.1f}%"
                )
                if a.factors:
                    factor_parts = _flatten_factors_to_strings(a.factors)
                    if factor_parts:
                        lines.append("**Factors:** " + " | ".join(factor_parts))
                    else:
                        lines.append("*No factor detail available.*")
                else:
                    lines.append("*No factor detail available.*")

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # JSON
    # ------------------------------------------------------------------

    def format_json(self, analyses: list[PropAnalysis]) -> str:
        """
        Serialize analyses to a JSON string compatible with the BaselineMLB
        projections table format.

        Parameters
        ----------
        analyses:
            List of :class:`PropAnalysis` results.

        Returns
        -------
        str
            Pretty-printed JSON string.
        """
        rows: list[dict[str, Any]] = []
        for a in analyses:
            prop = a.prop
            rows.append(
                {
                    "player_id": prop.player_id,
                    "player_name": prop.player_name,
                    "stat_type": prop.stat_type,
                    "sportsbook": prop.sportsbook,
                    "line": prop.line,
                    "over_odds": prop.over_odds,
                    "under_odds": prop.under_odds,
                    "simulated_mean": a.simulated_mean,
                    "simulated_median": a.simulated_median,
                    "p_over": a.p_over,
                    "p_under": a.p_under,
                    "implied_prob_over": a.implied_prob_over,
                    "implied_prob_under": a.implied_prob_under,
                    "edge_over": a.edge_over,
                    "edge_under": a.edge_under,
                    "recommended_side": a.recommended_side,
                    "kelly_fraction": a.kelly_fraction,
                    "kelly_wager_pct": a.kelly_wager_pct,
                    "confidence_tier": a.confidence_tier,
                    "ev_pct": a.ev_pct,
                    "factors": a.factors,
                    "distribution": {str(k): v for k, v in a.distribution.items()},
                    "model_version": MODEL_VERSION,
                }
            )
        return json.dumps(rows, indent=2, default=str)

    # ------------------------------------------------------------------
    # Supabase rows
    # ------------------------------------------------------------------

    def format_supabase_rows(
        self,
        analyses: list[PropAnalysis],
        game_date: str,
    ) -> list[dict[str, Any]]:
        """
        Return rows ready to upsert into the Supabase ``projections`` table.

        Parameters
        ----------
        analyses:
            List of :class:`PropAnalysis` results.
        game_date:
            ISO-format date string (``"YYYY-MM-DD"``).

        Returns
        -------
        list[dict]
            Each dict has the columns expected by the Supabase projections
            table: ``game_date``, ``mlbam_id``, ``player_name``,
            ``stat_type``, ``projection``, ``confidence``,
            ``model_version``, ``features``.

            Additional betting fields (``line``, ``sportsbook``,
            ``recommended_side``, ``edge``, ``kelly_wager_pct``,
            ``ev_pct``) are included as supplementary columns.
        """
        rows: list[dict[str, Any]] = []
        for a in analyses:
            prop = a.prop
            active_edge = (
                a.edge_over if a.recommended_side == "over" else a.edge_under
            )
            # Full glass-box breakdown as JSON for the 'features' column
            features_payload = {
                "stat_key": _STAT_TYPE_MAP.get(prop.stat_type, prop.stat_type),
                "sportsbook": prop.sportsbook,
                "line": prop.line,
                "over_odds": prop.over_odds,
                "under_odds": prop.under_odds,
                "p_over": a.p_over,
                "p_under": a.p_under,
                "implied_prob_over": a.implied_prob_over,
                "implied_prob_under": a.implied_prob_under,
                "edge_over": a.edge_over,
                "edge_under": a.edge_under,
                "kelly_fraction": a.kelly_fraction,
                "kelly_wager_pct": a.kelly_wager_pct,
                "ev_pct": a.ev_pct,
                "simulated_median": a.simulated_median,
                "distribution": {str(k): v for k, v in a.distribution.items()},
                "factors": a.factors,
            }
            rows.append(
                {
                    "game_date": game_date,
                    "mlbam_id": prop.player_id,
                    "player_name": prop.player_name,
                    "stat_type": prop.stat_type,
                    "projection": a.simulated_mean,
                    "confidence": a.confidence_tier,
                    "model_version": MODEL_VERSION,
                    "features": json.dumps(features_payload, default=str),
                    # Supplementary betting columns
                    "line": prop.line,
                    "sportsbook": prop.sportsbook,
                    "recommended_side": a.recommended_side,
                    "edge": round(active_edge, 6),
                    "kelly_wager_pct": a.kelly_wager_pct,
                    "ev_pct": a.ev_pct,
                }
            )
        return rows

    # ------------------------------------------------------------------
    # Twitter / X
    # ------------------------------------------------------------------

    def format_twitter(self, top_plays: dict[str, list[PropAnalysis]]) -> str:
        """
        Format the top 3 over + top 3 under plays as a compact Twitter/X post.

        Parameters
        ----------
        top_plays:
            Dict returned by :meth:`PropAnalyzer.get_top_plays`.

        Returns
        -------
        str
            Short-form post text (≤ ~280 characters per block).
        """
        parts: list[str] = ["⚾ BaselineMLB Prop Edges\n"]

        over_plays = top_plays.get("over", [])[:3]
        under_plays = top_plays.get("under", [])[:3]

        if over_plays:
            parts.append("🔼 OVERS")
            for a in over_plays:
                prop = a.prop
                parts.append(
                    f"  {prop.player_name} O{prop.line} "
                    f"{_fmt_stat_type_short(prop.stat_type)} "
                    f"+{a.edge_over * 100:.1f}% edge "
                    f"[{prop.sportsbook}]"
                )

        if under_plays:
            parts.append("🔽 UNDERS")
            for a in under_plays:
                prop = a.prop
                parts.append(
                    f"  {prop.player_name} U{prop.line} "
                    f"{_fmt_stat_type_short(prop.stat_type)} "
                    f"+{a.edge_under * 100:.1f}% edge "
                    f"[{prop.sportsbook}]"
                )

        if not over_plays and not under_plays:
            parts.append("No edges found today. Model says sit tight.")

        parts.append("\n#MLB #Props #BaselineMLB")
        return "\n".join(parts)


# ===========================================================================
# Module-level helpers
# ===========================================================================


def _fmt_stat_type(stat_type: str) -> str:
    """
    Convert a snake_case stat_type key to a short display label.

    Example: ``'pitcher_strikeouts'`` → ``'Pitcher K'``
    """
    _labels: dict[str, str] = {
        "pitcher_strikeouts": "Pitcher K",
        "batter_hits": "Hits",
        "batter_total_bases": "Total Bases",
        "batter_home_runs": "HR",
        "batter_strikeouts": "Batter K",
        "batter_walks": "Walks",
        "batter_runs": "Runs",
        "batter_rbis": "RBIs",
    }
    return _labels.get(stat_type, stat_type.replace("_", " ").title())


def _fmt_stat_type_short(stat_type: str) -> str:
    """
    Convert a snake_case stat_type key to a very short label for Twitter.

    Example: ``'pitcher_strikeouts'`` → ``'K'``
    """
    _short: dict[str, str] = {
        "pitcher_strikeouts": "K",
        "batter_hits": "H",
        "batter_total_bases": "TB",
        "batter_home_runs": "HR",
        "batter_strikeouts": "K",
        "batter_walks": "BB",
        "batter_runs": "R",
        "batter_rbis": "RBI",
    }
    return _short.get(stat_type, stat_type[:4].upper())


def _flatten_factors_to_strings(factors: dict) -> list[str]:
    """
    Flatten a nested factors dict into a list of human-readable strings.

    Parameters
    ----------
    factors:
        The ``factors`` field from a :class:`PropAnalysis` object.

    Returns
    -------
    list[str]
        Each element is a short factor summary, e.g.
        ``"strikeouts: park_factor=+0.03, platoon=+0.02"``.
    """
    parts: list[str] = []
    for outcome_name, adjustments in factors.items():
        if isinstance(adjustments, dict):
            adj_str = ", ".join(
                f"{k}={v:+.3f}" if isinstance(v, float) else f"{k}={v}"
                for k, v in adjustments.items()
            )
            parts.append(f"{outcome_name}: {adj_str}")
        else:
            parts.append(f"{outcome_name}: {adjustments}")
    return parts
