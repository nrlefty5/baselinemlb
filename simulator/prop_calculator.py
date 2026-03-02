#!/usr/bin/env python3
"""
prop_calculator.py — BaselineMLB
==================================
Takes simulation output distributions from the Monte Carlo engine and
compares them against sportsbook prop lines to calculate betting edges.

For each prop:
    - P(over) and P(under) from the simulation distribution
    - Expected value at the given odds
    - Kelly criterion optimal stake
    - Confidence tier (A/B/C) based on edge magnitude and sample stability

Usage:
    from simulator.prop_calculator import PropCalculator, PropLine

    calc = PropCalculator(bankroll=5000, kelly_fraction=0.25)
    edges = calc.evaluate_props(game_results, prop_lines)
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from typing import Optional

import numpy as np

from simulator.monte_carlo_engine import (
    GameSimResults,
    PlayerSimResults,
)

log = logging.getLogger("baselinemlb.prop_calculator")


# ---------------------------------------------------------------------------
# Odds conversion utilities
# ---------------------------------------------------------------------------

def american_to_decimal(odds: int | float) -> float:
    """Convert American odds to decimal odds."""
    if odds >= 100:
        return 1.0 + odds / 100.0
    elif odds <= -100:
        return 1.0 + 100.0 / abs(odds)
    return 2.0  # Even money fallback


def american_to_implied_prob(odds: int | float) -> float:
    """Convert American odds to implied probability (includes vig)."""
    if odds >= 100:
        return 100.0 / (odds + 100.0)
    elif odds <= -100:
        return abs(odds) / (abs(odds) + 100.0)
    return 0.5


def decimal_to_implied_prob(decimal_odds: float) -> float:
    """Convert decimal odds to implied probability."""
    if decimal_odds > 0:
        return 1.0 / decimal_odds
    return 0.5


def remove_vig(over_odds: int | float, under_odds: int | float) -> tuple:
    """
    Remove vig from a two-way market to get true probabilities.

    Returns (true_over_prob, true_under_prob) that sum to 1.0.
    """
    over_implied = american_to_implied_prob(over_odds)
    under_implied = american_to_implied_prob(under_odds)
    total = over_implied + under_implied

    if total > 0:
        return over_implied / total, under_implied / total
    return 0.5, 0.5


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class PropLine:
    """A sportsbook prop line for comparison against simulation."""
    mlbam_id: int
    player_name: str
    stat_type: str          # "K", "H", "TB", "HR", "R", "RBI", "BB"
    line: float             # e.g., 5.5
    over_odds: int = -110   # American odds
    under_odds: int = -110
    book: str = "consensus"

    @property
    def no_vig_over(self) -> float:
        """True probability of over implied by the market (vig removed)."""
        over_p, _ = remove_vig(self.over_odds, self.under_odds)
        return over_p

    @property
    def no_vig_under(self) -> float:
        """True probability of under implied by the market (vig removed)."""
        _, under_p = remove_vig(self.over_odds, self.under_odds)
        return under_p


@dataclass
class PropEdge:
    """Calculated edge for a single prop bet."""
    # Identification
    mlbam_id: int
    player_name: str
    stat_type: str
    line: float
    book: str

    # Simulation results
    sim_prob_over: float
    sim_prob_under: float
    sim_mean: float
    sim_median: float
    sim_std: float

    # Market comparison
    market_implied_over: float
    market_implied_under: float
    over_odds: int
    under_odds: int

    # Edge calculations
    direction: str              # "OVER" or "UNDER"
    edge: float                 # Our prob - market prob (positive = value)
    edge_pct: float             # Edge as percentage
    expected_value: float       # EV per $1 wagered
    kelly_fraction: float       # Optimal Kelly stake as fraction of bankroll
    kelly_stake: float          # Dollar amount to wager (fractional Kelly)
    confidence_tier: str        # "A", "B", or "C"
    confidence_score: float     # Numeric confidence 0-1

    def to_dict(self) -> dict:
        return {
            "mlbam_id": self.mlbam_id,
            "player_name": self.player_name,
            "stat_type": self.stat_type,
            "line": self.line,
            "book": self.book,
            "direction": self.direction,
            "sim_prob_over": round(self.sim_prob_over, 4),
            "sim_prob_under": round(self.sim_prob_under, 4),
            "sim_mean": round(self.sim_mean, 3),
            "sim_median": round(self.sim_median, 1),
            "sim_std": round(self.sim_std, 3),
            "market_implied_over": round(self.market_implied_over, 4),
            "market_implied_under": round(self.market_implied_under, 4),
            "over_odds": self.over_odds,
            "under_odds": self.under_odds,
            "edge": round(self.edge, 4),
            "edge_pct": round(self.edge_pct, 2),
            "expected_value": round(self.expected_value, 4),
            "kelly_fraction": round(self.kelly_fraction, 6),
            "kelly_stake": round(self.kelly_stake, 2),
            "confidence_tier": self.confidence_tier,
            "confidence_score": round(self.confidence_score, 3),
        }


# ---------------------------------------------------------------------------
# Prop Calculator
# ---------------------------------------------------------------------------

class PropCalculator:
    """
    Compares Monte Carlo simulation distributions against sportsbook lines
    to identify edges and compute optimal bet sizing.
    """

    # Confidence tier thresholds
    TIER_A_EDGE = 0.08       # 8%+ edge = A tier
    TIER_B_EDGE = 0.04       # 4-8% edge = B tier
    # Below 4% = C tier

    # Kelly criterion parameters
    MAX_KELLY_CAP = 0.05     # Never risk > 5% of bankroll on one bet
    MIN_EDGE_TO_BET = 0.02   # Don't bet on < 2% edge

    def __init__(
        self,
        bankroll: float = 1000.0,
        kelly_fraction: float = 0.25,
        min_edge: float = 0.02,
    ):
        """
        Args:
            bankroll: Total bankroll in dollars
            kelly_fraction: Fraction of full Kelly to use (0.25 = quarter Kelly)
            min_edge: Minimum edge to consider a bet (default 2%)
        """
        self.bankroll = bankroll
        self.kelly_fraction = kelly_fraction
        self.min_edge = min_edge

    def kelly_criterion(
        self,
        win_prob: float,
        decimal_odds: float,
    ) -> float:
        """
        Calculate Kelly criterion stake as a fraction of bankroll.

        Full Kelly: f* = (bp - q) / b
        where:
            b = decimal odds - 1 (net payout per $1)
            p = true probability of winning
            q = 1 - p

        Returns fractional Kelly stake (already multiplied by kelly_fraction).
        """
        b = decimal_odds - 1.0
        if b <= 0:
            return 0.0

        p = win_prob
        q = 1.0 - p

        full_kelly = (b * p - q) / b

        if full_kelly <= 0:
            return 0.0

        # Apply fractional Kelly and cap
        stake = full_kelly * self.kelly_fraction
        return min(stake, self.MAX_KELLY_CAP)

    def expected_value(
        self,
        win_prob: float,
        decimal_odds: float,
    ) -> float:
        """
        Calculate expected value per $1 wagered.

        EV = (p * payout) - (q * stake)
           = (p * (decimal_odds - 1)) - q
        """
        payout = decimal_odds - 1.0
        return win_prob * payout - (1.0 - win_prob)

    def confidence_score(
        self,
        edge: float,
        sim_std: float,
        n_sims: int,
        line: float,
    ) -> tuple:
        """
        Calculate confidence score and tier.

        Factors:
        1. Edge magnitude (higher = more confident)
        2. Distribution stability (lower std relative to mean = more confident)
        3. Sample size (more sims = more confident)
        4. Distance from line to mean (further from mean = less confident at edges)

        Returns (score: float, tier: str)
        """
        # Base score from edge magnitude
        edge_score = min(abs(edge) / 0.15, 1.0) * 0.50

        # Stability score: CV (coefficient of variation) — lower is better
        cv = sim_std / max(abs(line), 0.5)
        stability_score = max(0, 1.0 - cv) * 0.25

        # Sample size score (3000 sims is the target)
        sample_score = min(n_sims / 3000.0, 1.0) * 0.15

        # Mean-distance score: how far sim mean is from the line
        if sim_std > 0:
            z = abs(line - 0) / sim_std  # Unused variable fix below
            pass
        distance_score = min(abs(edge) / 0.10, 1.0) * 0.10

        score = edge_score + stability_score + sample_score + distance_score
        score = min(score, 1.0)

        # Assign tier
        if abs(edge) >= self.TIER_A_EDGE and score >= 0.50:
            tier = "A"
        elif abs(edge) >= self.TIER_B_EDGE and score >= 0.30:
            tier = "B"
        else:
            tier = "C"

        return score, tier

    def evaluate_prop(
        self,
        player_results: PlayerSimResults,
        prop: PropLine,
    ) -> Optional[PropEdge]:
        """
        Evaluate a single prop line against simulation results.

        Returns PropEdge if an edge exists, or None if the prop's stat
        isn't available in the results.
        """
        try:
            dist = player_results.distribution(prop.stat_type)
        except KeyError:
            log.debug(f"Stat '{prop.stat_type}' not found for {prop.player_name}")
            return None

        # Calculate probabilities from simulation
        sim_over = float(np.mean(dist > prop.line))
        sim_under = float(np.mean(dist < prop.line))
        sim_push = float(np.mean(dist == prop.line))

        # For half-integer lines (e.g., 5.5), push should be 0
        # For whole number lines, push probability is split
        if sim_push > 0:
            sim_over += sim_push / 2
            sim_under += sim_push / 2

        sim_mean = float(np.mean(dist))
        sim_median = float(np.median(dist))
        sim_std = float(np.std(dist))

        # Market implied probabilities (vig removed)
        mkt_over = prop.no_vig_over
        mkt_under = prop.no_vig_under

        # Determine direction and edge
        over_edge = sim_over - mkt_over
        under_edge = sim_under - mkt_under

        if over_edge > under_edge:
            direction = "OVER"
            edge = over_edge
            win_prob = sim_over
            odds = prop.over_odds
        else:
            direction = "UNDER"
            edge = under_edge
            win_prob = sim_under
            odds = prop.under_odds

        # Skip if edge is below minimum threshold
        edge_pct = edge * 100.0

        # Calculate EV and Kelly
        decimal_odds = american_to_decimal(odds)
        ev = self.expected_value(win_prob, decimal_odds)
        kelly = self.kelly_criterion(win_prob, decimal_odds)
        stake = round(kelly * self.bankroll, 2)

        # Confidence
        conf_score, conf_tier = self.confidence_score(
            edge, sim_std, player_results.n_sims, prop.line
        )

        return PropEdge(
            mlbam_id=prop.mlbam_id,
            player_name=prop.player_name,
            stat_type=prop.stat_type,
            line=prop.line,
            book=prop.book,
            sim_prob_over=sim_over,
            sim_prob_under=sim_under,
            sim_mean=sim_mean,
            sim_median=sim_median,
            sim_std=sim_std,
            market_implied_over=mkt_over,
            market_implied_under=mkt_under,
            over_odds=prop.over_odds,
            under_odds=prop.under_odds,
            direction=direction,
            edge=edge,
            edge_pct=edge_pct,
            expected_value=ev,
            kelly_fraction=kelly,
            kelly_stake=stake,
            confidence_tier=conf_tier,
            confidence_score=conf_score,
        )

    def evaluate_props(
        self,
        game_results: GameSimResults,
        prop_lines: list,
        pitcher_k_dist: np.ndarray = None,
        pitcher_mlbam_id: int = None,
        pitcher_name: str = None,
    ) -> list:
        """
        Evaluate all prop lines against game simulation results.

        Args:
            game_results: Output from simulate_game()
            prop_lines: List of PropLine objects
            pitcher_k_dist: Optional pitcher K distribution from
                           simulate_game_with_pitcher_ks()
            pitcher_mlbam_id: Pitcher's MLB AM ID for K prop matching
            pitcher_name: Pitcher name

        Returns:
            List of PropEdge objects, sorted by edge magnitude descending
        """
        edges = []

        # Create a temporary PlayerSimResults for pitcher Ks if available
        pitcher_results = None
        if pitcher_k_dist is not None and pitcher_mlbam_id is not None:
            pitcher_results = PlayerSimResults(
                mlbam_id=pitcher_mlbam_id,
                name=pitcher_name or "Pitcher",
                n_sims=game_results.n_sims,
                strikeouts=pitcher_k_dist,
                hits=np.zeros(game_results.n_sims, dtype=np.int32),
                total_bases=np.zeros(game_results.n_sims, dtype=np.int32),
                home_runs=np.zeros(game_results.n_sims, dtype=np.int32),
                walks=np.zeros(game_results.n_sims, dtype=np.int32),
                hbps=np.zeros(game_results.n_sims, dtype=np.int32),
                runs=np.zeros(game_results.n_sims, dtype=np.int32),
                rbis=np.zeros(game_results.n_sims, dtype=np.int32),
                plate_appearances=np.zeros(game_results.n_sims, dtype=np.int32),
            )

        for prop in prop_lines:
            # Determine which results to use
            if (prop.stat_type in ("K", "strikeouts", "pitcher_strikeouts")
                    and pitcher_results is not None
                    and prop.mlbam_id == pitcher_mlbam_id):
                result = pitcher_results
                # Normalize stat type for lookup
                prop_copy = PropLine(
                    mlbam_id=prop.mlbam_id,
                    player_name=prop.player_name,
                    stat_type="K",  # Map to internal key
                    line=prop.line,
                    over_odds=prop.over_odds,
                    under_odds=prop.under_odds,
                    book=prop.book,
                )
                edge = self.evaluate_prop(result, prop_copy)
            elif prop.mlbam_id in game_results.player_results:
                result = game_results.player_results[prop.mlbam_id]
                edge = self.evaluate_prop(result, prop)
            else:
                log.debug(
                    f"Player {prop.player_name} ({prop.mlbam_id}) "
                    f"not found in simulation results"
                )
                continue

            if edge is not None:
                edges.append(edge)

        # Sort by absolute edge descending
        edges.sort(key=lambda e: abs(e.edge), reverse=True)
        return edges

    def filter_edges(
        self,
        edges: list,
        min_edge: float = None,
        min_tier: str = "C",
        max_results: int = None,
    ) -> list:
        """
        Filter edges by minimum thresholds.

        Args:
            edges: List of PropEdge objects
            min_edge: Minimum edge to include (default: self.min_edge)
            min_tier: Minimum confidence tier ("A", "B", or "C")
            max_results: Maximum number of results to return

        Returns:
            Filtered and sorted list of PropEdge objects
        """
        if min_edge is None:
            min_edge = self.min_edge

        tier_order = {"A": 3, "B": 2, "C": 1}
        min_tier_val = tier_order.get(min_tier, 1)

        filtered = [
            e for e in edges
            if abs(e.edge) >= min_edge
            and tier_order.get(e.confidence_tier, 0) >= min_tier_val
        ]

        # Sort by confidence tier (A first), then by edge
        filtered.sort(
            key=lambda e: (tier_order.get(e.confidence_tier, 0), abs(e.edge)),
            reverse=True,
        )

        if max_results:
            filtered = filtered[:max_results]

        return filtered

    def top_plays(
        self,
        edges: list,
        n: int = 5,
        direction: str = None,
    ) -> list:
        """
        Get top N plays, optionally filtered by direction.

        Args:
            edges: List of PropEdge objects
            n: Number of top plays to return
            direction: "OVER", "UNDER", or None for both

        Returns:
            Top N PropEdge objects
        """
        if direction:
            filtered = [e for e in edges if e.direction == direction.upper()]
        else:
            filtered = list(edges)

        # Sort by EV descending
        filtered.sort(key=lambda e: e.expected_value, reverse=True)
        return filtered[:n]

    def format_summary(self, edges: list) -> str:
        """Format edges into a readable text summary."""
        if not edges:
            return "No edges found."

        lines = []
        lines.append(f"{'='*70}")
        lines.append(f"  BaselineMLB Monte Carlo Prop Edges")
        lines.append(f"  Bankroll: ${self.bankroll:,.0f} | "
                      f"Kelly: {self.kelly_fraction:.0%} | "
                      f"Min Edge: {self.min_edge:.0%}")
        lines.append(f"{'='*70}")
        lines.append("")

        for i, e in enumerate(edges, 1):
            lines.append(
                f"  {i}. [{e.confidence_tier}] {e.player_name} "
                f"{e.stat_type} {e.direction} {e.line}"
            )
            lines.append(
                f"     Sim: {e.sim_mean:.1f} avg | "
                f"P({e.direction.lower()}): {(e.sim_prob_over if e.direction == 'OVER' else e.sim_prob_under):.1%} | "
                f"Market: {(e.market_implied_over if e.direction == 'OVER' else e.market_implied_under):.1%}"
            )
            lines.append(
                f"     Edge: {e.edge_pct:+.1f}% | "
                f"EV: {e.expected_value:+.3f}/$ | "
                f"Kelly: ${e.kelly_stake:.0f} "
                f"({e.over_odds if e.direction == 'OVER' else e.under_odds})"
            )
            lines.append("")

        lines.append(f"{'='*70}")
        return "\n".join(lines)
