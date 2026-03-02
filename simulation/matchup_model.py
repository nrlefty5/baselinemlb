"""
BaselineMLB — matchup_model.py
=================================================
Pure-Python matchup simulation model.

This module is deliberately kept free of any heavy ML
dependencies so the CI/testing layer stays lean.
The full stochastic simulation lives in game_engine.py;
this file focuses on *player-vs-player* probability
computations used to drive pitch-outcome sampling.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from typing import Optional

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# League-average rates (2024 season)
MLB_AVG_BA = 0.243
MLB_AVG_OBP = 0.315
MLB_AVG_SLG = 0.392
MLB_AVG_K_PCT = 0.224
MLB_AVG_BB_PCT = 0.085
MLB_AVG_HR_PER_FB = 0.138
MLB_AVG_FB_PCT = 0.360
MLB_AVG_GB_PCT = 0.440
MLB_AVG_LD_PCT = 0.200

# Hit probability by contact type
HIT_PROB = {
    "ground_ball": 0.238,
    "fly_ball": 0.185,
    "line_drive": 0.685,
    "popup": 0.020,
}

# Extra-base hit probability given a hit (by type)
XBH_PROB = {
    "ground_ball": {"2B": 0.05, "3B": 0.01, "HR": 0.00},
    "fly_ball": {"2B": 0.08, "3B": 0.01, "HR": 0.20},
    "line_drive": {"2B": 0.30, "3B": 0.03, "HR": 0.05},
    "popup": {"2B": 0.00, "3B": 0.00, "HR": 0.00},
}

# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class PitcherProfile:
    """Statistical profile for a pitcher."""

    mlbam_id: int
    name: str
    # Rate stats
    k_pct: float = MLB_AVG_K_PCT
    bb_pct: float = MLB_AVG_BB_PCT
    hr_per_fb: float = MLB_AVG_HR_PER_FB
    # Batted ball mix
    fb_pct: float = MLB_AVG_FB_PCT
    gb_pct: float = MLB_AVG_GB_PCT
    ld_pct: float = MLB_AVG_LD_PCT
    # Pitch mix (proportion of each pitch type)
    pitch_mix: dict = field(default_factory=lambda: {
        "FF": 0.40, "SI": 0.15, "SL": 0.20,
        "CH": 0.12, "CU": 0.10, "FC": 0.03,
    })
    # Stuff+ / Location+ (100 = average)
    stuff_plus: float = 100.0
    location_plus: float = 100.0
    # Handedness
    throws: str = "R"  # "R" or "L"

    def popup_pct(self) -> float:
        return max(0.0, 1.0 - self.fb_pct - self.gb_pct - self.ld_pct)


@dataclass
class BatterProfile:
    """Statistical profile for a batter."""

    mlbam_id: int
    name: str
    # Rate stats
    k_pct: float = MLB_AVG_K_PCT
    bb_pct: float = MLB_AVG_BB_PCT
    ba: float = MLB_AVG_BA
    obp: float = MLB_AVG_OBP
    slg: float = MLB_AVG_SLG
    # Batted ball tendencies
    fb_pct: float = MLB_AVG_FB_PCT
    gb_pct: float = MLB_AVG_GB_PCT
    ld_pct: float = MLB_AVG_LD_PCT
    # Pull/oppo tendencies
    pull_pct: float = 0.40
    oppo_pct: float = 0.25
    # Platoon split (additional OBP vs same-handed pitcher)
    platoon_obp_adj: float = 0.000
    # Handedness
    bats: str = "R"  # "R", "L", or "S" (switch)
    # Sprint speed (ft/s) for baserunning
    sprint_speed: float = 27.0

    def popup_pct(self) -> float:
        return max(0.0, 1.0 - self.fb_pct - self.gb_pct - self.ld_pct)


@dataclass
class MatchupResult:
    """Result of a single plate appearance simulation."""

    outcome: str  # "K", "BB", "HBP", "1B", "2B", "3B", "HR", "out"
    contact_type: Optional[str] = None  # "ground_ball", "fly_ball", "line_drive", "popup"
    is_hard_hit: bool = False
    pitch_count: int = 0
    details: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Log5 / odds-ratio blending
# ---------------------------------------------------------------------------


def log5_rate(p_batter: float, p_pitcher: float, p_league: float) -> float:
    """
    Bill James Log5 formula for matchup probability.

    Combines batter rate, pitcher rate, and league average
    to produce a matchup-specific probability.

    Args:
        p_batter:  Batter's rate for the event (e.g. K%)
        p_pitcher: Pitcher's rate for the event
        p_league:  League-average rate for the event

    Returns:
        Blended matchup probability [0, 1]
    """
    if p_league <= 0 or p_league >= 1:
        return (p_batter + p_pitcher) / 2.0

    # Odds form: o = p / (1 - p)
    o_b = p_batter / (1.0 - p_batter) if p_batter < 1.0 else 1e6
    o_p = p_pitcher / (1.0 - p_pitcher) if p_pitcher < 1.0 else 1e6
    o_l = p_league / (1.0 - p_league)

    # Log5: o_matchup = o_b * o_p / o_l
    o_m = (o_b * o_p) / o_l
    return o_m / (1.0 + o_m)


def clamp(value: float, lo: float = 0.0, hi: float = 1.0) -> float:
    """Clamp a probability to [lo, hi]."""
    return max(lo, min(hi, value))


# ---------------------------------------------------------------------------
# Pitch-outcome simulator
# ---------------------------------------------------------------------------


def _stuff_adjustment(stuff_plus: float) -> float:
    """
    Convert Stuff+ to a K-rate multiplier.
    Each 10 Stuff+ points ≈ 1.5 pp K-rate change.
    """
    return 1.0 + (stuff_plus - 100.0) * 0.0015


def _location_adjustment(location_plus: float) -> float:
    """
    Convert Location+ to a BB-rate multiplier (inverse).
    Each 10 Location+ points ≈ 1 pp BB-rate improvement.
    """
    return 1.0 - (location_plus - 100.0) * 0.0010


def simulate_plate_appearance(
    pitcher: PitcherProfile,
    batter: BatterProfile,
    *,
    rng: Optional[random.Random] = None,
    count_factor: float = 1.0,
) -> MatchupResult:
    """
    Simulate a single plate appearance between *pitcher* and *batter*.

    Uses Log5 blending to compute matchup-specific outcome probabilities,
    then samples a result from those probabilities.

    Args:
        pitcher:      Pitcher's statistical profile.
        batter:       Batter's statistical profile.
        rng:          Optional seeded random.Random instance.
        count_factor: Multiplier for count-based adjustments (1.0 = neutral count).

    Returns:
        A MatchupResult with the outcome and metadata.
    """
    rng = rng or random

    # --- Step 1: Compute matchup K%, BB%, HBP% via Log5 ---
    k_pct = clamp(
        log5_rate(batter.k_pct, pitcher.k_pct, MLB_AVG_K_PCT)
        * _stuff_adjustment(pitcher.stuff_plus)
        * count_factor
    )
    bb_pct = clamp(
        log5_rate(batter.bb_pct, pitcher.bb_pct, MLB_AVG_BB_PCT)
        * _location_adjustment(pitcher.location_plus)
    )
    hbp_pct = 0.009  # flat MLB average

    # Platoon adjustment on BB
    same_hand = (
        (pitcher.throws == "R" and batter.bats == "R")
        or (pitcher.throws == "L" and batter.bats == "L")
    )
    if same_hand:
        bb_pct = clamp(bb_pct + batter.platoon_obp_adj * 0.5)
        k_pct = clamp(k_pct + batter.platoon_obp_adj * 0.3)

    # --- Step 2: Resolve terminal outcome ---
    roll = rng.random()

    if roll < k_pct:
        return MatchupResult(outcome="K", pitch_count=_sample_pitch_count(rng, "K"))

    roll -= k_pct
    if roll < bb_pct:
        return MatchupResult(outcome="BB", pitch_count=_sample_pitch_count(rng, "BB"))

    roll -= bb_pct
    if roll < hbp_pct:
        return MatchupResult(outcome="HBP", pitch_count=_sample_pitch_count(rng, "HBP"))

    # --- Step 3: Ball in play ---
    contact_type = _sample_contact_type(pitcher, batter, rng)
    is_hard_hit = rng.random() < 0.38  # ~38% hard-hit rate on BIP

    hit_prob = HIT_PROB[contact_type]
    if is_hard_hit:
        hit_prob = min(hit_prob * 1.35, 0.95)  # hard contact boost

    if rng.random() < hit_prob:
        # Determine hit type
        xbh = XBH_PROB[contact_type]
        r2 = rng.random()
        if r2 < xbh["HR"] * (pitcher.hr_per_fb / MLB_AVG_HR_PER_FB if contact_type == "fly_ball" else 1.0):
            outcome = "HR"
        elif r2 < xbh["HR"] + xbh["3B"]:
            outcome = "3B"
        elif r2 < xbh["HR"] + xbh["3B"] + xbh["2B"]:
            outcome = "2B"
        else:
            outcome = "1B"
    else:
        outcome = "out"

    return MatchupResult(
        outcome=outcome,
        contact_type=contact_type,
        is_hard_hit=is_hard_hit,
        pitch_count=_sample_pitch_count(rng, outcome),
    )


def _sample_contact_type(
    pitcher: PitcherProfile,
    batter: BatterProfile,
    rng: random.Random,
) -> str:
    """
    Sample a contact type blending pitcher and batter tendencies.
    Uses a 50/50 blend of pitcher and batter batted-ball mix.
    """
    fb = (pitcher.fb_pct + batter.fb_pct) / 2
    gb = (pitcher.gb_pct + batter.gb_pct) / 2
    ld = (pitcher.ld_pct + batter.ld_pct) / 2
    pu = max(0.0, 1.0 - fb - gb - ld)

    r = rng.random()
    if r < gb:
        return "ground_ball"
    r -= gb
    if r < fb:
        return "fly_ball"
    r -= fb
    if r < ld:
        return "line_drive"
    return "popup"


def _sample_pitch_count(rng: random.Random, outcome: str) -> int:
    """Sample a realistic pitch count for an at-bat given its outcome."""
    distributions = {
        "K": (4, 7),
        "BB": (5, 8),
        "HBP": (2, 5),
        "out": (2, 5),
        "1B": (3, 6),
        "2B": (3, 6),
        "3B": (4, 7),
        "HR": (3, 7),
    }
    lo, hi = distributions.get(outcome, (3, 6))
    return rng.randint(lo, hi)


# ---------------------------------------------------------------------------
# Multi-PA / inning simulation helpers
# ---------------------------------------------------------------------------


def simulate_inning(
    pitcher: PitcherProfile,
    lineup: list[BatterProfile],
    start_batter_idx: int = 0,
    *,
    rng: Optional[random.Random] = None,
) -> dict:
    """
    Simulate a single half-inning.

    Args:
        pitcher:          Pitcher profile.
        lineup:           List of batter profiles (at least 9).
        start_batter_idx: Index of the first batter in the lineup.
        rng:              Optional seeded RNG.

    Returns:
        dict with keys: runs, hits, strikeouts, walks, hbp,
                        batters_faced, pitch_count, end_batter_idx
    """
    rng = rng or random
    outs = 0
    runs = 0
    hits = 0
    strikeouts = 0
    walks = 0
    hbp = 0
    batters_faced = 0
    pitch_count = 0
    bases = [False, False, False]  # 1B, 2B, 3B

    batter_idx = start_batter_idx % len(lineup)

    while outs < 3:
        batter = lineup[batter_idx % len(lineup)]
        result = simulate_plate_appearance(pitcher, batter, rng=rng)
        batters_faced += 1
        pitch_count += result.pitch_count
        batter_idx += 1

        if result.outcome == "K":
            outs += 1
            strikeouts += 1

        elif result.outcome in ("BB", "HBP"):
            if result.outcome == "BB":
                walks += 1
            else:
                hbp += 1
            # Force advance runners
            if bases[2] and bases[1] and bases[0]:
                runs += 1
            elif bases[1] and bases[0]:
                bases[2] = True
            elif bases[0]:
                bases[1] = True
            else:
                bases[0] = True

        elif result.outcome == "out":
            outs += 1
            # Possible sac fly (simplification: 10% of fly ball outs with runner on 3B)
            if (
                result.contact_type == "fly_ball"
                and bases[2]
                and outs < 3
                and rng.random() < 0.10
            ):
                runs += 1
                bases[2] = False

        elif result.outcome == "1B":
            hits += 1
            # Advance all runners 1 base; runner on 3B scores
            if bases[2]:
                runs += 1
            bases[2] = bases[1]
            bases[1] = bases[0]
            bases[0] = True

        elif result.outcome == "2B":
            hits += 1
            # Runners on 2B+ score; batter on 2B
            runs += sum(1 for b in bases[1:] if b)
            bases[2] = bases[0]
            bases[1] = True
            bases[0] = False

        elif result.outcome == "3B":
            hits += 1
            runs += sum(1 for b in bases if b)
            bases = [False, False, True]

        elif result.outcome == "HR":
            hits += 1
            runs += 1 + sum(1 for b in bases if b)
            bases = [False, False, False]

    return {
        "runs": runs,
        "hits": hits,
        "strikeouts": strikeouts,
        "walks": walks,
        "hbp": hbp,
        "batters_faced": batters_faced,
        "pitch_count": pitch_count,
        "end_batter_idx": batter_idx % len(lineup),
    }


# ---------------------------------------------------------------------------
# Aggregated matchup scoring
# ---------------------------------------------------------------------------


def compute_matchup_edge(
    pitcher: PitcherProfile,
    batter: BatterProfile,
    n_sims: int = 1000,
    seed: Optional[int] = None,
) -> dict:
    """
    Run *n_sims* plate-appearance simulations and return aggregate edge metrics.

    Returns a dict with:
        k_rate, bb_rate, hit_rate, xba, edge_score
    """
    rng = random.Random(seed)
    totals = {"K": 0, "BB": 0, "HBP": 0, "hit": 0, "out": 0}

    for _ in range(n_sims):
        result = simulate_plate_appearance(pitcher, batter, rng=rng)
        if result.outcome == "K":
            totals["K"] += 1
        elif result.outcome in ("BB", "HBP"):
            totals[result.outcome] += 1
        elif result.outcome in ("1B", "2B", "3B", "HR"):
            totals["hit"] += 1
        else:
            totals["out"] += 1

    n = n_sims
    k_rate = totals["K"] / n
    bb_rate = (totals["BB"] + totals["HBP"]) / n
    hit_rate = totals["hit"] / n

    # Edge score: how much does pitcher dominate this batter?
    # Positive = pitcher advantage, negative = batter advantage
    edge_score = (k_rate - MLB_AVG_K_PCT) - (hit_rate - MLB_AVG_BA)

    return {
        "k_rate": round(k_rate, 4),
        "bb_rate": round(bb_rate, 4),
        "hit_rate": round(hit_rate, 4),
        "xba": round(hit_rate, 4),
        "edge_score": round(edge_score, 4),
    }


# ---------------------------------------------------------------------------
# Lineup vs pitcher aggregate
# ---------------------------------------------------------------------------


def score_pitcher_vs_lineup(
    pitcher: PitcherProfile,
    lineup: list[BatterProfile],
    n_sims: int = 500,
    seed: Optional[int] = None,
) -> dict:
    """
    Compute aggregate edge scores for a pitcher against a full lineup.

    Returns dict with per-batter edges and overall lineup score.
    """
    rng_seed = seed
    results = []
    total_edge = 0.0

    for i, batter in enumerate(lineup):
        edge = compute_matchup_edge(pitcher, batter, n_sims=n_sims, seed=rng_seed)
        results.append({"order": i + 1, "batter": batter.name, **edge})
        total_edge += edge["edge_score"]
        if rng_seed is not None:
            rng_seed += 1

    avg_edge = total_edge / len(lineup) if lineup else 0.0

    return {
        "pitcher": pitcher.name,
        "per_batter": results,
        "avg_edge": round(avg_edge, 4),
        "projected_k_pct": round(
            sum(r["k_rate"] for r in results) / len(results) if results else 0, 4
        ),
    }


# ---------------------------------------------------------------------------
# Strikeout projection
# ---------------------------------------------------------------------------


def project_strikeouts(
    pitcher: PitcherProfile,
    lineup: list[BatterProfile],
    expected_ip: float = 5.5,
    n_sims: int = 1000,
    seed: Optional[int] = None,
) -> dict:
    """
    Project strikeout total for a pitcher over *expected_ip* innings.

    Args:
        pitcher:     Pitcher profile.
        lineup:      Opposing lineup (list of BatterProfile).
        expected_ip: Expected innings pitched.
        n_sims:      Number of Monte Carlo simulations.
        seed:        RNG seed for reproducibility.

    Returns:
        dict with projection, confidence_interval, and per-sim distribution.
    """
    rng = random.Random(seed)
    sim_k_totals = []

    for _ in range(n_sims):
        total_k = 0
        total_outs = 0
        target_outs = int(expected_ip * 3)
        batter_idx = 0

        while total_outs < target_outs:
            batter = lineup[batter_idx % len(lineup)]
            result = simulate_plate_appearance(pitcher, batter, rng=rng)
            batter_idx += 1

            if result.outcome == "K":
                total_k += 1
                total_outs += 1
            elif result.outcome in ("out",):
                total_outs += 1
            elif result.outcome in ("1B", "2B", "3B", "HR"):
                pass  # runners on base, don't increment outs
            # BB/HBP: batter reaches, outs unchanged

            # Safety valve
            if batter_idx > 200:
                break

        sim_k_totals.append(total_k)

    sim_k_totals.sort()
    mean_k = sum(sim_k_totals) / n_sims
    p10 = sim_k_totals[int(n_sims * 0.10)]
    p25 = sim_k_totals[int(n_sims * 0.25)]
    p75 = sim_k_totals[int(n_sims * 0.75)]
    p90 = sim_k_totals[int(n_sims * 0.90)]

    # Variance-based confidence
    variance = sum((k - mean_k) ** 2 for k in sim_k_totals) / n_sims
    std_dev = math.sqrt(variance)
    cv = std_dev / mean_k if mean_k > 0 else 1.0
    confidence = max(0.40, min(0.95, 1.0 - cv * 0.5))

    return {
        "projection": round(mean_k, 2),
        "p10": p10,
        "p25": p25,
        "p75": p75,
        "p90": p90,
        "std_dev": round(std_dev, 3),
        "confidence": round(confidence, 3),
    }
