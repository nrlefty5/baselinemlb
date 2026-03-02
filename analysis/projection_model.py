#!/usr/bin/env python3
"""
projection_model.py  [DEPRECATED]

Original glass-box MLB prop projection prototype.

.. deprecated::
    Superseded by ``pipeline/generate_projections.py`` (v2.0) which adds:
    - Recent form weighting (14-day trailing K/9)
    - Opponent team K% factor
    - Pitcher-specific expected IP (trailing average)
    - Umpire strike rate from Supabase ``umpire_framing`` table
    - Catcher composite framing score
    - All 30 MLB park factors
    - Home/away adjustment
    - Early-season ramp-up blending

    Use ``pipeline/generate_projections.py`` for production projections.
"""

import json
import os
from datetime import date
from typing import Dict, List


class PitcherStrikeoutModel:
    """Projects pitcher strikeouts using glass-box factors."""

    def __init__(self, player_stats: dict, statcast_summary: dict, opponent_team: str):
        self.stats = player_stats
        self.umpire_data = statcast_summary.get("umpire_accuracy", [])
        self.catcher_data = statcast_summary.get("catcher_framing", [])
        self.opponent = opponent_team

    def baseline_k_rate(self) -> float:
        """Pitcher's season K/9 (baseline)."""
        pitching = self.stats.get("pitching_stats", {})
        k = pitching.get("strikeOuts", 0)
        ip = pitching.get("inningsPitched", 0)
        if ip == 0:
            return 0.0
        return (k / ip) * 9

    def umpire_adjustment(self, umpire_name: str) -> float:
        """
        Umpire strike zone impact.
        Returns % adjustment to K rate based on umpire's called-strike accuracy.
        """
        for ump in self.umpire_data:
            if ump.get("umpire") == umpire_name:
                ump.get("accuracy", 0.0)
                cs_rate = ump.get("cs_rate", 0.0)
                league_avg_cs = 0.52  # league average called-strike rate
                return (cs_rate - league_avg_cs) * 100  # % adjustment
        return 0.0

    def catcher_framing_adjustment(self, catcher_id: int) -> float:
        """
        Catcher framing impact.
        Returns % adjustment based on shadow-zone strike conversion.
        """
        for catcher in self.catcher_data:
            if catcher.get("catcher_id") == catcher_id:
                framing_rate = catcher.get("framing_rate", 0.0)
                league_avg_framing = 0.48  # league average shadow-zone conversion
                return (framing_rate - league_avg_framing) * 100
        return 0.0

    def park_factor_adjustment(self, park_name: str) -> float:
        """
        Ballpark K factor.
        Higher altitude + larger parks = more Ks.
        """
        k_friendly_parks = {
            "Coors Field": -8,  # harder to K at altitude
            "Yankee Stadium": +3,
            "Oracle Park": +5,
            "Petco Park": +4,
        }
        return k_friendly_parks.get(park_name, 0)

    def opponent_k_rate(self) -> float:
        """
        Opponent team's K% (league-adjusted).
        TODO: Pull actual team K% from database.
        """
        return 0.0  # placeholder

    def project_strikeouts(self, expected_ip: float, umpire: str,
                          catcher_id: int, park: str) -> Dict:
        """
        Glass-box projection with all factors logged.
        """
        baseline_k9 = self.baseline_k_rate()
        umpire_adj = self.umpire_adjustment(umpire)
        catcher_adj = self.catcher_framing_adjustment(catcher_id)
        park_adj = self.park_factor_adjustment(park)

        # Combine adjustments (additive for transparency)
        total_adj = umpire_adj + catcher_adj + park_adj
        adjusted_k9 = baseline_k9 * (1 + total_adj / 100)

        # Project total Ks for expected innings
        projected_k = (adjusted_k9 / 9) * expected_ip

        return {
            "projected_strikeouts": round(projected_k, 1),
            "confidence": self._calculate_confidence(expected_ip),
            "factors": {
                "baseline_k9": round(baseline_k9, 2),
                "umpire_adjustment": f"{umpire_adj:+.1f}%",
                "catcher_adjustment": f"{catcher_adj:+.1f}%",
                "park_adjustment": f"{park_adj:+.1f}%",
                "total_adjustment": f"{total_adj:+.1f}%",
                "adjusted_k9": round(adjusted_k9, 2),
                "expected_innings": expected_ip,
            },
            "umpire": umpire,
            "catcher_id": catcher_id,
            "park": park,
        }

    def _calculate_confidence(self, expected_ip: float) -> int:
        """Confidence score (0-100) based on data quality."""
        confidence = 50  # baseline
        if expected_ip >= 5.0:
            confidence += 20
        if self.stats.get("pitching_stats", {}).get("inningsPitched", 0) > 30:
            confidence += 20
        if len(self.umpire_data) > 0:
            confidence += 10
        return min(confidence, 95)  # cap at 95%


def generate_projections_for_date(game_date: str = None) -> List[Dict]:
    """
    Generate all prop projections for a given date.
    Combines data from games/, players/, props/, statcast/.
    """
    if game_date is None:
        game_date = date.today().isoformat()

    # Load data
    games = load_json(f"data/games/games_{game_date}.json")
    players = load_json(f"data/players/players_{game_date}.json")
    load_json(f"data/props/props_{game_date}.json")
    statcast = load_json(f"data/statcast/statcast_summary_{game_date}.json")

    projections = []

    for game in games:
        game_pk = game["game_pk"]
        home_pitcher_id = game.get("home_pitcher_id")
        away_pitcher_id = game.get("away_pitcher_id")

        # Project home pitcher Ks
        if home_pitcher_id:
            pitcher_stats = find_player(players, home_pitcher_id)
            if pitcher_stats:
                model = PitcherStrikeoutModel(pitcher_stats, statcast, game["away_team"])
                proj = model.project_strikeouts(
                    expected_ip=5.5,  # TODO: dynamic IP estimate
                    umpire=game.get("umpire", "Unknown"),
                    catcher_id=game.get("home_catcher_id", 0),
                    park=game["venue"]
                )
                proj["game_pk"] = game_pk
                proj["pitcher"] = game["home_probable_pitcher"]
                proj["team"] = game["home_team"]
                projections.append(proj)

        # Project away pitcher Ks
        if away_pitcher_id:
            pitcher_stats = find_player(players, away_pitcher_id)
            if pitcher_stats:
                model = PitcherStrikeoutModel(pitcher_stats, statcast, game["home_team"])
                proj = model.project_strikeouts(
                    expected_ip=5.5,
                    umpire=game.get("umpire", "Unknown"),
                    catcher_id=game.get("away_catcher_id", 0),
                    park=game["venue"]
                )
                proj["game_pk"] = game_pk
                proj["pitcher"] = game["away_probable_pitcher"]
                proj["team"] = game["away_team"]
                projections.append(proj)

    return projections


def load_json(path: str) -> List:
    """Load JSON file, return empty list if not found."""
    if not os.path.exists(path):
        return []
    with open(path) as f:
        return json.load(f)


def find_player(players: List, player_id: int) -> Dict:
    """Find player by ID in players list."""
    for p in players:
        if p.get("info", {}).get("id") == player_id:
            return p
    return {}


def save_projections(projections: List, game_date: str) -> None:
    """Save projections to data/projections/."""
    out_dir = os.path.join("data", "projections")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, f"projections_{game_date}.json")
    with open(out_path, "w") as f:
        json.dump(projections, f, indent=2)
    print(f"Saved {len(projections)} projections to {out_path}")


if __name__ == "__main__":
    today = date.today().isoformat()
    print(f"Generating prop projections for {today}...")
    projections = generate_projections_for_date(today)
    save_projections(projections, today)
    print("Done. Projections saved.")

    # Print sample projection
    if projections:
        print("\nSample projection:")
        print(json.dumps(projections[0], indent=2))
