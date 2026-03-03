"""
models/predict.py
=================
Game-day inference script for the BaselineMLB XGBoost matchup model.

For each game (or all games today), fetches live pitcher/batter stats from the
MLB Stats API, builds feature vectors that match the training schema, and returns
per-matchup outcome-probability dicts keyed by (pitcher_id, batter_id).

Falls back to league-average outcome probabilities when the trained model file
cannot be found.

Usage
-----
    # All games today
    python -m models.predict

    # Specific date
    python -m models.predict --date 2025-07-04

    # Specific game
    python -m models.predict --game-pk 745401

    # Print probabilities as JSON
    python -m models.predict --date 2025-07-04 --output json
"""

import argparse
import json
import logging
import os
from datetime import date, datetime
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
import requests

try:
    from models.matchup_model import OUTCOME_CLASSES, MatchupModel  # noqa: F401
except ImportError:
    from matchup_model import OUTCOME_CLASSES, MatchupModel

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_MODEL_PATH: str = "models/trained/matchup_model.joblib"

MLB_STATS_BASE: str = "https://statsapi.mlb.com/api/v1"

# League-average outcome probability fallback (2024 MLB season approximation)
LEAGUE_AVG_PROBA: Dict[str, float] = {
    "K":   0.225,
    "BB":  0.085,
    "1B":  0.140,
    "2B":  0.048,
    "3B":  0.006,
    "HR":  0.038,
    "HBP": 0.011,
    "out": 0.447,
}

# Park factor defaults when park data is unavailable
DEFAULT_PARK_FACTOR: float = 1.0

# API request timeout seconds
API_TIMEOUT: int = 10

# ---------------------------------------------------------------------------
# In-process caches (reset per process run)
# ---------------------------------------------------------------------------

_player_stats_cache: Dict[int, Dict[str, Any]] = {}
_park_factor_cache: Dict[int, float] = {}

# ---------------------------------------------------------------------------
# Supabase helpers (for optional supplemental data retrieval)
# ---------------------------------------------------------------------------

def _supabase_headers() -> Dict[str, str]:
    """Build Supabase REST API request headers from environment variables.

    Returns:
        Headers dict with apikey, Authorization, Content-Type, and Prefer fields.

    Raises:
        EnvironmentError: If SUPABASE_URL or SUPABASE_SERVICE_KEY are not set.
    """
    key = os.environ.get("SUPABASE_SERVICE_KEY")
    if not key:
        raise EnvironmentError("SUPABASE_SERVICE_KEY environment variable is not set.")
    return {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "Prefer": "resolution=merge-duplicates",
    }


def fetch_supabase_park_factors(venue_id: int) -> Optional[float]:
    """Fetch a park factor for a venue from Supabase if available.

    Args:
        venue_id: MLB venue/stadium identifier.

    Returns:
        Park factor float, or None if not found or Supabase is not configured.
    """
    url = os.environ.get("SUPABASE_URL")
    if not url:
        return None
    try:
        endpoint = f"{url}/rest/v1/park_factors"
        params = {"venue_id": f"eq.{venue_id}", "select": "park_factor"}
        resp = requests.get(
            endpoint,
            headers=_supabase_headers(),
            params=params,
            timeout=API_TIMEOUT,
        )
        resp.raise_for_status()
        rows = resp.json()
        if rows:
            return float(rows[0]["park_factor"])
    except Exception as exc:  # noqa: BLE001
        logger.debug("Supabase park factor lookup failed for venue %d: %s", venue_id, exc)
    return None


# ---------------------------------------------------------------------------
# MLB Stats API helpers
# ---------------------------------------------------------------------------

def _mlb_get(path: str, params: Optional[Dict[str, Any]] = None) -> Any:
    """Perform a GET request against the MLB Stats API.

    Args:
        path: Relative path, e.g. ``"/schedule"``.
        params: Optional query parameters dict.

    Returns:
        Parsed JSON response body.

    Raises:
        requests.HTTPError: On non-2xx responses.
    """
    url = f"{MLB_STATS_BASE}{path}"
    resp = requests.get(url, params=params or {}, timeout=API_TIMEOUT)
    resp.raise_for_status()
    return resp.json()


def fetch_games_for_date(game_date: str) -> List[Dict[str, Any]]:
    """Return a list of game dicts scheduled on *game_date*.

    Args:
        game_date: ISO-8601 date string, e.g. ``"2025-07-04"``.

    Returns:
        List of game dicts, each containing at minimum:
        ``gamePk``, ``teams``, ``venue``.
    """
    data = _mlb_get("/schedule", params={"sportId": 1, "date": game_date})
    games: List[Dict[str, Any]] = []
    for date_entry in data.get("dates", []):
        for game in date_entry.get("games", []):
            games.append(game)
    logger.info("Found %d games on %s", len(games), game_date)
    return games


def fetch_lineups(game_pk: int) -> Tuple[List[Dict], List[Dict], int, int]:
    """Fetch starting lineups and pitcher IDs for a game.

    Args:
        game_pk: MLB game primary key.

    Returns:
        Tuple of (away_batters, home_batters, away_pitcher_id, home_pitcher_id).
        Each batter entry is a dict with at least ``id`` and ``hand`` keys.
    """
    data = _mlb_get(f"/game/{game_pk}/boxscore")
    teams = data.get("teams", {})

    def extract_lineup(team_data: Dict) -> Tuple[List[Dict], int]:
        """Extract the batting order and starting pitcher ID from a team boxscore block."""
        batters = []
        pitcher_id = 0
        players = team_data.get("players", {})
        batting_order = team_data.get("battingOrder", [])
        pitchers = team_data.get("pitchers", [])

        if pitchers:
            pitcher_id = pitchers[0]

        for pid in batting_order:
            key = f"ID{pid}"
            player = players.get(key, {})
            pos = player.get("position", {}).get("abbreviation", "")
            if pos != "P":
                batters.append({
                    "id": pid,
                    "hand": player.get("batSide", {}).get("code", "R"),
                    "name": player.get("person", {}).get("fullName", str(pid)),
                })
        return batters, pitcher_id

    away_batters, away_pitcher = extract_lineup(teams.get("away", {}))
    home_batters, home_pitcher = extract_lineup(teams.get("home", {}))
    return away_batters, home_batters, away_pitcher, home_pitcher


def fetch_player_stats(player_id: int, player_type: str = "pitching") -> Dict[str, Any]:
    """Fetch career aggregate stats for a player with in-process caching.

    Args:
        player_id: MLB player ID.
        player_type: ``"pitching"`` or ``"hitting"`` -- determines the stat group.

    Returns:
        Dict of stat name -> value. Returns empty dict on API failure.
    """
    cache_key = (player_id, player_type)
    if cache_key in _player_stats_cache:
        return _player_stats_cache[cache_key]  # type: ignore[return-value]

    try:
        data = _mlb_get(
            f"/people/{player_id}/stats",
            params={"stats": "career", "group": player_type, "sportId": 1},
        )
        stats_list = data.get("stats", [])
        splits = stats_list[0].get("splits", []) if stats_list else []
        stat_dict = splits[0].get("stat", {}) if splits else {}
        result: Dict[str, Any] = stat_dict
    except Exception as exc:  # noqa: BLE001
        logger.debug("Failed to fetch %s stats for player %d: %s", player_type, player_id, exc)
        result = {}

    _player_stats_cache[cache_key] = result  # type: ignore[assignment]
    return result


def fetch_savant_stats(player_id: int, player_type: str = "pitcher") -> Dict[str, Any]:
    """Fetch Statcast-derived metrics via the MLB Stats API advanced stats endpoint.

    Covers: avg_velocity, fb_pct, sl_pct, cu_pct, ch_pct, whiff_rate,
    chase_rate, zone_rate, avg_launch_angle, avg_launch_speed.

    Args:
        player_id: MLB player ID.
        player_type: ``"pitcher"`` or ``"batter"``.

    Returns:
        Dict with Statcast field names as keys.  Missing fields default to 0.0.
    """
    cache_key = (player_id, f"savant_{player_type}")
    if cache_key in _player_stats_cache:
        return _player_stats_cache[cache_key]  # type: ignore[return-value]

    try:
        data = _mlb_get(
            f"/people/{player_id}/stats",
            params={
                "stats": "statsSingleSeason",
                "group": "pitching" if player_type == "pitcher" else "hitting",
                "sportId": 1,
                "season": datetime.now().year,
            },
        )
        splits = []
        for block in data.get("stats", []):
            splits.extend(block.get("splits", []))
        stat = splits[0].get("stat", {}) if splits else {}
    except Exception as exc:  # noqa: BLE001
        logger.debug("Savant stats fetch failed for %s %d: %s", player_type, player_id, exc)
        stat = {}

    # Map MLB API field names to our feature schema (best-effort; missing -> 0.0)
    if player_type == "pitcher":
        result = {
            "avg_velocity": float(stat.get("avgPitchVelocity", 0.0) or 0.0),
            "fb_pct": float(stat.get("fourSeamFBPct", 0.0) or 0.0),
            "sl_pct": float(stat.get("sliderPct", 0.0) or 0.0),
            "cu_pct": float(stat.get("curvePct", 0.0) or 0.0),
            "ch_pct": float(stat.get("changeupPct", 0.0) or 0.0),
            "whiff_rate": float(stat.get("swingAndMissRate", 0.0) or 0.0),
            "chase_rate": float(stat.get("chaseRate", 0.0) or 0.0),
            "zone_rate": float(stat.get("zoneRate", 0.0) or 0.0),
        }
    else:
        result = {
            "avg_launch_angle": float(stat.get("launchAngle", 0.0) or 0.0),
            "avg_launch_speed": float(stat.get("exitVelocityAvg", 0.0) or 0.0),
            "chase_rate_batter": float(stat.get("chaseRate", 0.0) or 0.0),
            "whiff_rate_batter": float(stat.get("swingAndMissRate", 0.0) or 0.0),
        }

    _player_stats_cache[cache_key] = result  # type: ignore[assignment]
    return result


def get_park_factor(venue_id: int) -> float:
    """Return the park factor for a venue (with caching).

    First checks Supabase; falls back to DEFAULT_PARK_FACTOR.

    Args:
        venue_id: MLB venue identifier.

    Returns:
        Float park factor (1.0 = neutral).
    """
    if venue_id in _park_factor_cache:
        return _park_factor_cache[venue_id]
    pf = fetch_supabase_park_factors(venue_id) or DEFAULT_PARK_FACTOR
    _park_factor_cache[venue_id] = pf
    return pf


# ---------------------------------------------------------------------------
# Feature vector construction
# ---------------------------------------------------------------------------

def build_feature_row(
    pitcher_id: int,
    batter: Dict[str, Any],
    home_away: str,
    park_factor: float,
) -> Dict[str, Any]:
    """Assemble a single feature-vector dict for one pitcher-batter matchup.

    Args:
        pitcher_id: MLB pitcher player ID.
        batter: Dict with keys ``id`` (int) and ``hand`` (str: R/L/S).
        home_away: ``"home"`` or ``"away"`` from the batting team's perspective.
        park_factor: Numeric park factor for the game's venue.

    Returns:
        Dict mapping every column in ALL_FEATURES to a numeric value.
    """
    pitcher_career = fetch_player_stats(pitcher_id, "pitching")
    pitcher_savant = fetch_savant_stats(pitcher_id, "pitcher")
    batter_career = fetch_player_stats(batter["id"], "hitting")
    batter_savant = fetch_savant_stats(batter["id"], "batter")

    # Pitcher hand (from people endpoint cache if available)
    pitcher_hand_str = _player_stats_cache.get((pitcher_id, "hand"), "R")  # type: ignore[arg-type]
    pitcher_hand_enc = {"R": 0, "L": 1, "S": 2}.get(str(pitcher_hand_str), 0)
    batter_hand_enc = {"R": 0, "L": 1, "S": 2}.get(str(batter.get("hand", "R")), 0)

    # Platoon advantage: pitcher and batter on opposite sides
    platoon_advantage = int(pitcher_hand_enc != batter_hand_enc and batter_hand_enc != 2)

    # Prior PA count (plate appearances faced this season -- use career SO as proxy or 0)
    prior_pa_count = int(pitcher_career.get("battersFaced", 0) or 0)

    # Derived pitcher stats from career (standard API)
    ip_raw = pitcher_career.get("inningsPitched", "0.0") or "0.0"
    try:
        ip = float(str(ip_raw))
    except ValueError:
        ip = 0.0
    ip = max(ip, 1.0)  # avoid division by zero

    career_k9 = float(pitcher_career.get("strikeOuts", 0) or 0) * 9.0 / ip
    career_bb9 = float(pitcher_career.get("baseOnBalls", 0) or 0) * 9.0 / ip

    # Derived batter stats from career
    ab = float(batter_career.get("atBats", 1) or 1)
    pa = float(batter_career.get("plateAppearances", 1) or 1)
    hits = float(batter_career.get("hits", 0) or 0)
    doubles = float(batter_career.get("doubles", 0) or 0)
    triples = float(batter_career.get("triples", 0) or 0)
    hr = float(batter_career.get("homeRuns", 0) or 0)
    bb_b = float(batter_career.get("baseOnBalls", 0) or 0)
    so_b = float(batter_career.get("strikeOuts", 0) or 0)

    k_pct = so_b / pa
    bb_pct = bb_b / pa
    slg_num = (hits - doubles - triples - hr) + 2 * doubles + 3 * triples + 4 * hr
    slg = slg_num / max(ab, 1.0)
    avg = hits / max(ab, 1.0)
    iso = slg - avg
    # wOBA approximation using standard weights
    woba_num = 0.69 * bb_b + 0.888 * (hits - doubles - triples - hr) + 1.267 * doubles + 1.602 * triples + 2.101 * hr
    woba = woba_num / max(pa, 1.0)

    home_away_enc = 1 if home_away.lower() == "home" else 0

    return {
        # Pitcher
        "career_k9": round(career_k9, 4),
        "career_bb9": round(career_bb9, 4),
        "avg_velocity": pitcher_savant.get("avg_velocity", 93.0),
        "fb_pct": pitcher_savant.get("fb_pct", 0.35),
        "sl_pct": pitcher_savant.get("sl_pct", 0.20),
        "cu_pct": pitcher_savant.get("cu_pct", 0.12),
        "ch_pct": pitcher_savant.get("ch_pct", 0.15),
        "whiff_rate": pitcher_savant.get("whiff_rate", 0.25),
        "chase_rate": pitcher_savant.get("chase_rate", 0.32),
        "zone_rate": pitcher_savant.get("zone_rate", 0.47),
        "pitcher_hand_enc": pitcher_hand_enc,
        # Batter
        "k_pct": round(k_pct, 4),
        "bb_pct": round(bb_pct, 4),
        "iso": round(iso, 4),
        "woba": round(woba, 4),
        "avg_launch_angle": batter_savant.get("avg_launch_angle", 12.0),
        "avg_launch_speed": batter_savant.get("avg_launch_speed", 88.0),
        "chase_rate_batter": batter_savant.get("chase_rate_batter", 0.30),
        "whiff_rate_batter": batter_savant.get("whiff_rate_batter", 0.24),
        "batter_hand_enc": batter_hand_enc,
        # Matchup
        "platoon_advantage": platoon_advantage,
        "prior_pa_count": prior_pa_count,
        # Context
        "home_away_enc": home_away_enc,
        "park_factor": park_factor,
    }


# ---------------------------------------------------------------------------
# Core inference
# ---------------------------------------------------------------------------

def predict_matchups(
    model: Optional[MatchupModel],
    matchup_rows: List[Tuple[int, int, Dict[str, Any]]],
) -> Dict[Tuple[int, int], Dict[str, float]]:
    """Generate outcome probabilities for a batch of pitcher-batter matchups.

    Args:
        model: Fitted MatchupModel, or None to use league-average fallback.
        matchup_rows: List of (pitcher_id, batter_id, feature_dict) tuples.

    Returns:
        Dict keyed by (pitcher_id, batter_id) mapping to outcome probability
        dicts, e.g. ``{("K": 0.22, "BB": 0.09, ..., "out": 0.44)}``.
    """
    if model is None:
        logger.warning("No model loaded -- returning league-average probabilities for all matchups.")
        return {
            (pitcher_id, batter_id): {**LEAGUE_AVG_PROBA}
            for pitcher_id, batter_id, _ in matchup_rows
        }

    rows = [feat_dict for _, _, feat_dict in matchup_rows]
    df = pd.DataFrame(rows)
    proba_matrix = model.predict_proba(df)  # shape (n, 8)

    results: Dict[Tuple[int, int], Dict[str, float]] = {}
    for i, (pitcher_id, batter_id, _) in enumerate(matchup_rows):
        proba_dict = {cls: round(float(proba_matrix[i, j]), 6) for j, cls in enumerate(OUTCOME_CLASSES)}
        results[(pitcher_id, batter_id)] = proba_dict

    return results


def run_game(
    game: Dict[str, Any],
    model: Optional[MatchupModel],
) -> Dict[Tuple[int, int], Dict[str, float]]:
    """Generate matchup probabilities for all lineup combinations in one game.

    Args:
        game: Game dict from fetch_games_for_date (must contain ``gamePk`` and
              ``venue.id``).
        model: Fitted MatchupModel or None for league-average fallback.

    Returns:
        Merged probability dict for all matchups encountered in this game.
    """
    game_pk = game["gamePk"]
    venue_id = game.get("venue", {}).get("id", 0)
    park_factor = get_park_factor(venue_id)

    logger.info("Processing gamePk=%d  venue=%d  park_factor=%.3f", game_pk, venue_id, park_factor)

    try:
        away_batters, home_batters, away_pitcher, home_pitcher = fetch_lineups(game_pk)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not fetch lineup for gamePk=%d: %s", game_pk, exc)
        return {}

    matchup_rows: List[Tuple[int, int, Dict[str, Any]]] = []

    # Home pitcher faces away batters
    if home_pitcher and away_batters:
        for batter in away_batters:
            row = build_feature_row(home_pitcher, batter, "away", park_factor)
            matchup_rows.append((home_pitcher, batter["id"], row))

    # Away pitcher faces home batters
    if away_pitcher and home_batters:
        for batter in home_batters:
            row = build_feature_row(away_pitcher, batter, "home", park_factor)
            matchup_rows.append((away_pitcher, batter["id"], row))

    if not matchup_rows:
        logger.warning("No valid matchup rows built for gamePk=%d", game_pk)
        return {}

    return predict_matchups(model, matchup_rows)


def run_predict(
    game_date: str,
    game_pk: Optional[int],
    model_path: str,
    output_format: str,
) -> Dict[str, Any]:
    """Top-level inference runner.

    Args:
        game_date: Date string (YYYY-MM-DD) for which to generate predictions.
        game_pk: Optional specific game PK; if provided, only that game is processed.
        model_path: Path to the joblib model file.
        output_format: ``"text"`` or ``"json"``.

    Returns:
        Dict mapping game_pk strings to matchup probability dicts.
    """
    # Load model (fall back gracefully)
    model: Optional[MatchupModel] = None
    try:
        model = MatchupModel.load(model_path)
    except FileNotFoundError:
        logger.warning("Model not found at %s -- using league-average fallback.", model_path)

    # Fetch games
    if game_pk:
        games = [{"gamePk": game_pk, "venue": {}}]
    else:
        try:
            games = fetch_games_for_date(game_date)
        except Exception as exc:  # noqa: BLE001
            logger.error("Could not fetch schedule for %s: %s", game_date, exc)
            return {}

    all_results: Dict[str, Any] = {}
    for game in games:
        pk = game["gamePk"]
        probs = run_game(game, model)
        # Convert tuple keys to string for JSON serialisability
        all_results[str(pk)] = {
            f"{p_id},{b_id}": v for (p_id, b_id), v in probs.items()
        }
        logger.info("gamePk=%d -- %d matchup vectors generated", pk, len(probs))

    if output_format == "json":
        print(json.dumps(all_results, indent=2))
    else:
        _print_text_summary(all_results)

    return all_results


def _print_text_summary(results: Dict[str, Any]) -> None:
    """Print a human-readable summary of matchup probabilities to stdout.

    Args:
        results: Nested dict from run_predict().
    """
    sep = "=" * 68
    print(sep)
    print("  BaselineMLB -- Matchup Probabilities")
    print(sep)
    for game_pk, matchups in results.items():
        print(f"\n  Game PK: {game_pk}")
        header = f"  {'Pitcher':<12s} {'Batter':<12s}" + "".join(
            f"  {cls:<6s}" for cls in OUTCOME_CLASSES
        )
        print(header)
        print("  " + "-" * (len(header) - 2))
        for key, proba in matchups.items():
            pitcher_id, batter_id = key.split(",")
            row = f"  {pitcher_id:<12s} {batter_id:<12s}" + "".join(
                f"  {proba.get(cls, 0.0):<6.3f}" for cls in OUTCOME_CLASSES
            )
            print(row)
    print(sep)


# ---------------------------------------------------------------------------
# __main__
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Generate XGBoost matchup probabilities for MLB games.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--date",
        default=date.today().isoformat(),
        help="Game date (YYYY-MM-DD). Defaults to today.",
    )
    parser.add_argument(
        "--game-pk",
        type=int,
        default=None,
        help="Target a single game by its MLB gamePk.",
    )
    parser.add_argument(
        "--model-path",
        default=DEFAULT_MODEL_PATH,
        help="Path to the trained MatchupModel joblib file.",
    )
    parser.add_argument(
        "--output",
        choices=["text", "json"],
        default="text",
        help="Output format: 'text' (human-readable) or 'json'.",
    )
    args = parser.parse_args()

    run_predict(
        game_date=args.date,
        game_pk=args.game_pk,
        model_path=args.model_path,
        output_format=args.output,
    )
