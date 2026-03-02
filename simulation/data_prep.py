"""
data_prep.py — Data preparation module for the BaselineMLB Monte Carlo Simulator.

Fetches and prepares Statcast metrics, MLB schedule/lineup data, umpire/catcher
framing data from Supabase, and weather data from OpenWeatherMap. All fetchers
include graceful fallbacks, LRU caching, rate limiting, and structured logging.

Classes
-------
StatcastFetcher
    Downloads pitcher and batter Statcast leaderboard data from Baseball Savant,
    fetches recent game-log form from the MLB Stats API, and retrieves pitch
    count history.

MLBApiClient
    Wraps statsapi.mlb.com to pull today's schedule with probable pitchers,
    confirmed or projected lineups, team-level stats, platoon splits, and
    historical boxscores.

SupabaseReader
    Reads umpire framing scores, catcher framing scores, prop lines, and
    existing projections from a Supabase Postgres backend.

WeatherFetcher
    Calls the OpenWeatherMap current-weather or forecast endpoint to return
    temperature and wind information for an outdoor ballpark.

DataPrepPipeline
    Orchestrates all fetchers to produce a ``GameData`` object containing
    every feature needed by the Monte Carlo engine.

GameData
    Dataclass holding the fully-prepared game snapshot returned by the pipeline.
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from functools import lru_cache
from typing import Any

import numpy as np
import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from . import config

# ---------------------------------------------------------------------------
# Module-level logger (inherits root logger configured in config.py)
# ---------------------------------------------------------------------------
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Convenience aliases into the existing config (avoids repetition below)
# ---------------------------------------------------------------------------
_CFG = config.DEFAULT_CONFIG          # SimulationConfig instance
_LG = config.LEAGUE_AVG_RATES         # dict[str, float]  (outcome rates)

# Additional Statcast metric league averages not in LEAGUE_AVG_RATES.
# These are used as fallback defaults when a player row is missing.
_STATCAST_DEFAULTS: dict[str, float] = {
    # Pitcher metrics
    "k_rate": _LG["strikeout"],
    "bb_rate": _LG["walk"],
    "hr_rate": _LG["home_run"],
    "whiff_pct": 0.248,
    "csw_pct": 0.287,
    "zone_pct": 0.470,
    "swstr_pct": 0.112,
    "avg_velo": 93.5,
    "chase_rate": 0.295,
    "iz_contact_pct": 0.845,
    "gb_rate": 0.432,
    "fb_rate": 0.358,
    # Batter metrics
    "xba": 0.249,
    "xslg": 0.409,
    "barrel_pct": 0.080,
    "hard_hit_pct": 0.370,
    "contact_pct": 0.770,
    "pull_pct": 0.390,
    "avg_ev": 88.5,
    # Platoon factors (multiplicative on K rate)
    "platoon_same_hand_k": 1.05,
    "platoon_opp_hand_k": 0.95,
}

# API / rate-limit constants not in SimulationConfig
_MLB_API_BASE: str = "https://statsapi.mlb.com/api/v1"
_MLB_API_TIMEOUT: int = 15
_MLB_API_RATE_LIMIT: float = 0.3   # seconds between calls

_SAVANT_BASE: str = "https://baseballsavant.mlb.com"
_SAVANT_TIMEOUT: int = 30
_SAVANT_RATE_LIMIT: float = 1.5    # seconds between calls
_SAVANT_CACHE_TTL: int = 3600

_OPENWEATHER_BASE: str = "https://api.openweathermap.org/data/2.5"
_OPENWEATHER_TIMEOUT: int = 10

# Weather fallback defaults
_WEATHER_DEFAULTS: dict[str, Any] = {
    "temp_f": 72.0,
    "wind_speed_mph": 5.0,
    "wind_direction": "N",
    "wind_out": False,
}

# Ballpark GPS coordinates for weather lookups
_PARK_COORDS: dict[str, tuple[float, float]] = {
    "NYY": (40.8296, -73.9262),
    "NYM": (40.7571, -73.8458),
    "BOS": (42.3467, -71.0972),
    "TBR": (27.7683, -82.6534),
    "BAL": (39.2838, -76.6216),
    "TOR": (43.6414, -79.3894),
    "CHW": (41.8300, -87.6338),
    "CHC": (41.9484, -87.6553),
    "CLE": (41.4962, -81.6852),
    "DET": (42.3390, -83.0485),
    "KCR": (39.0517, -94.4803),
    "MIN": (44.9817, -93.2775),
    "HOU": (29.7573, -95.3555),
    "LAA": (33.8003, -117.8827),
    "OAK": (37.7516, -122.2005),
    "SEA": (47.5914, -122.3325),
    "TEX": (32.7513, -97.0832),
    "ATL": (33.8908, -84.4678),
    "MIA": (25.7781, -80.2197),
    "PHI": (39.9061, -75.1665),
    "WSN": (38.8730, -77.0074),
    "CIN": (39.0975, -84.5066),
    "MIL": (43.0280, -87.9712),
    "PIT": (40.4469, -80.0058),
    "STL": (38.6226, -90.1928),
    "ARI": (33.4453, -112.0667),
    "COL": (39.7559, -104.9942),
    "LAD": (34.0739, -118.2400),
    "SDP": (32.7076, -117.1570),
    "SFG": (37.7786, -122.3893),
}


# ---------------------------------------------------------------------------
# Shared HTTP session helper
# ---------------------------------------------------------------------------

def _build_session(retries: int = 3, backoff: float = 0.5) -> requests.Session:
    """Return a ``requests.Session`` with retry/back-off already wired up."""
    session = requests.Session()
    retry = Retry(
        total=retries,
        backoff_factor=backoff,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=["GET"],
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    session.headers.update({"User-Agent": "BaselineMLB/1.0 (+research)"})
    return session


# ===========================================================================
# GameData — structured output of the pipeline
# ===========================================================================

@dataclass
class PitcherData:
    """Holds all prepared stats for one starting pitcher."""

    mlbam_id: int
    name: str
    team: str
    hand: str  # "L" or "R"

    # Statcast season metrics
    k_rate: float = field(default_factory=lambda: _STATCAST_DEFAULTS["k_rate"])
    bb_rate: float = field(default_factory=lambda: _STATCAST_DEFAULTS["bb_rate"])
    hr_rate: float = field(default_factory=lambda: _STATCAST_DEFAULTS["hr_rate"])
    whiff_pct: float = field(default_factory=lambda: _STATCAST_DEFAULTS["whiff_pct"])
    csw_pct: float = field(default_factory=lambda: _STATCAST_DEFAULTS["csw_pct"])
    zone_pct: float = field(default_factory=lambda: _STATCAST_DEFAULTS["zone_pct"])
    swstr_pct: float = field(default_factory=lambda: _STATCAST_DEFAULTS["swstr_pct"])
    avg_velo: float = field(default_factory=lambda: _STATCAST_DEFAULTS["avg_velo"])
    chase_rate: float = field(default_factory=lambda: _STATCAST_DEFAULTS["chase_rate"])
    iz_contact_pct: float = field(default_factory=lambda: _STATCAST_DEFAULTS["iz_contact_pct"])
    gb_rate: float = field(default_factory=lambda: _STATCAST_DEFAULTS["gb_rate"])
    fb_rate: float = field(default_factory=lambda: _STATCAST_DEFAULTS["fb_rate"])

    # Recent form
    recent_k_rate: float = field(default_factory=lambda: _STATCAST_DEFAULTS["k_rate"])
    recent_bb_rate: float = field(default_factory=lambda: _STATCAST_DEFAULTS["bb_rate"])

    # Pitch count
    mean_pitch_count: float = field(default_factory=lambda: float(_CFG.PITCH_COUNT_MEAN))
    std_pitch_count: float = field(default_factory=lambda: float(_CFG.PITCH_COUNT_STD))

    # Days rest
    days_rest: int = 5


@dataclass
class BatterData:
    """Holds all prepared stats for one batter."""

    mlbam_id: int
    name: str
    team: str
    hand: str        # batting hand: "L" or "R"
    lineup_position: int = 5  # 1–9

    # Statcast season metrics
    k_rate: float = field(default_factory=lambda: _STATCAST_DEFAULTS["k_rate"])
    bb_rate: float = field(default_factory=lambda: _STATCAST_DEFAULTS["bb_rate"])
    hr_rate: float = field(default_factory=lambda: _STATCAST_DEFAULTS["hr_rate"])
    xba: float = field(default_factory=lambda: _STATCAST_DEFAULTS["xba"])
    xslg: float = field(default_factory=lambda: _STATCAST_DEFAULTS["xslg"])
    barrel_pct: float = field(default_factory=lambda: _STATCAST_DEFAULTS["barrel_pct"])
    hard_hit_pct: float = field(default_factory=lambda: _STATCAST_DEFAULTS["hard_hit_pct"])
    chase_rate: float = field(default_factory=lambda: _STATCAST_DEFAULTS["chase_rate"])
    whiff_pct: float = field(default_factory=lambda: _STATCAST_DEFAULTS["whiff_pct"])
    contact_pct: float = field(default_factory=lambda: _STATCAST_DEFAULTS["contact_pct"])
    pull_pct: float = field(default_factory=lambda: _STATCAST_DEFAULTS["pull_pct"])
    avg_ev: float = field(default_factory=lambda: _STATCAST_DEFAULTS["avg_ev"])

    # Recent form
    recent_ba: float = field(default_factory=lambda: _STATCAST_DEFAULTS["xba"])
    recent_k_rate: float = field(default_factory=lambda: _STATCAST_DEFAULTS["k_rate"])

    # Platoon splits (pre-computed vs. LHP / vs. RHP)
    ba_vs_lhp: float = 0.250
    ba_vs_rhp: float = 0.250


@dataclass
class UmpireData:
    """Umpire tendencies affecting strike zone."""

    name: str = "Unknown"
    composite_score: float = 0.0
    extra_strikes: float = 0.0
    strike_rate: float = 0.0
    k_factor: float = 1.0   # multiplicative; 1.0 = league average


@dataclass
class GameData:
    """Fully-prepared game snapshot ready for Monte Carlo simulation."""

    game_pk: int
    game_date: str
    home_team: str
    away_team: str
    venue: str = ""

    home_pitcher: PitcherData | None = None
    away_pitcher: PitcherData | None = None

    home_lineup: list[BatterData] = field(default_factory=list)
    away_lineup: list[BatterData] = field(default_factory=list)

    umpire: UmpireData = field(default_factory=UmpireData)

    home_catcher_framing: float = 0.0
    away_catcher_framing: float = 0.0

    temp_f: float = _WEATHER_DEFAULTS["temp_f"]           # type: ignore[assignment]
    wind_speed_mph: float = _WEATHER_DEFAULTS["wind_speed_mph"]  # type: ignore[assignment]
    wind_direction: str = _WEATHER_DEFAULTS["wind_direction"]    # type: ignore[assignment]
    wind_out: bool = False   # True if wind blowing toward outfield wall

    home_team_k_pct: float = field(default_factory=lambda: _LG["strikeout"])
    away_team_k_pct: float = field(default_factory=lambda: _LG["strikeout"])

    # Park factors dict (from config.PARK_FACTORS) for this venue
    park_factors: dict[str, float] = field(
        default_factory=lambda: dict(config.PARK_FACTORS["neutral"])
    )

    # raw schedule dict for downstream consumers
    raw_game: dict[str, Any] = field(default_factory=dict)


# ===========================================================================
# StatcastFetcher
# ===========================================================================

class StatcastFetcher:
    """
    Fetches Statcast metrics directly from Baseball Savant CSV leaderboards and
    the MLB Stats API game logs.

    All methods return ``dict`` with float values keyed by stat name, or fall
    back to ``_STATCAST_DEFAULTS`` entries on any error.

    Parameters
    ----------
    season : int, optional
        Default season year.  Defaults to the current calendar year.
    """

    # Savant leaderboard URL templates
    _PITCHER_STATS_URL = (
        "https://baseballsavant.mlb.com/leaderboard/statcast"
        "?type=pitcher&year={year}&min=25&csv=true"
    )
    _BATTER_STATS_URL = (
        "https://baseballsavant.mlb.com/leaderboard/statcast"
        "?type=batter&year={year}&min=100&csv=true"
    )
    _PITCHER_ARSENAL_URL = (
        "https://baseballsavant.mlb.com/leaderboard/pitch-arsenal-stats"
        "?type=pitcher&pitchType=&year={year}&team=&min=25&csv=true"
    )
    _PITCHER_EXPECTED_URL = (
        "https://baseballsavant.mlb.com/leaderboard/expected_statistics"
        "?type=pitcher&year={year}&min=25&csv=true"
    )
    _BATTER_EXPECTED_URL = (
        "https://baseballsavant.mlb.com/leaderboard/expected_statistics"
        "?type=batter&year={year}&min=100&csv=true"
    )

    def __init__(self, season: int | None = None) -> None:
        self._default_season: int = season or datetime.now().year
        self._session = _build_session()

    # ------------------------------------------------------------------
    # Public methods
    # ------------------------------------------------------------------

    def fetch_pitcher_stats(self, mlbam_id: int, season: int | None = None) -> dict[str, float]:
        """
        Fetch a pitcher's Statcast metrics from the Baseball Savant leaderboard.

        Parameters
        ----------
        mlbam_id : int
            Pitcher's MLBAM player ID.
        season : int, optional
            Season year; defaults to ``self._default_season``.

        Returns
        -------
        dict
            Keys: k_rate, bb_rate, hr_rate, whiff_pct, csw_pct, zone_pct,
            swstr_pct, avg_velo, chase_rate, iz_contact_pct, gb_rate, fb_rate.
            All values are floats in [0, 1] (or mph for avg_velo).
        """
        year = season or self._default_season
        fallback = self._pitcher_fallback()

        try:
            df_main = self._download_savant_csv(
                self._PITCHER_STATS_URL.format(year=year)
            )
            df_arsenal = self._download_savant_csv(
                self._PITCHER_ARSENAL_URL.format(year=year)
            )

            row_main = self._find_player_row(df_main, mlbam_id)
            row_arsenal = self._find_player_row(df_arsenal, mlbam_id)

            if row_main is None and row_arsenal is None:
                logger.warning(
                    "StatcastFetcher: no Savant data for pitcher %s season %s; "
                    "using league averages.", mlbam_id, year
                )
                return fallback

            result = dict(fallback)

            if row_main is not None:
                result.update(
                    {
                        "k_rate": self._safe_float(row_main, "k_percent", fallback["k_rate"] * 100) / 100,
                        "bb_rate": self._safe_float(row_main, "bb_percent", fallback["bb_rate"] * 100) / 100,
                        "whiff_pct": self._safe_float(row_main, "whiff_percent", fallback["whiff_pct"] * 100) / 100,
                        "swstr_pct": self._safe_float(row_main, "swinging_strike_percent", fallback["swstr_pct"] * 100) / 100,
                        "avg_velo": self._safe_float(row_main, "avg_best_speed", fallback["avg_velo"]),
                        "chase_rate": self._safe_float(row_main, "oz_swing_percent", fallback["chase_rate"] * 100) / 100,
                        "iz_contact_pct": self._safe_float(row_main, "z_contact_percent", fallback["iz_contact_pct"] * 100) / 100,
                        "gb_rate": self._safe_float(row_main, "groundballs_percent", fallback["gb_rate"] * 100) / 100,
                        "fb_rate": self._safe_float(row_main, "flyballs_percent", fallback["fb_rate"] * 100) / 100,
                        "zone_pct": self._safe_float(row_main, "z_percent", fallback["zone_pct"] * 100) / 100,
                        "csw_pct": self._safe_float(row_main, "csw_percent", fallback["csw_pct"] * 100) / 100,
                    }
                )

            # hr_rate from expected stats leaderboard
            try:
                df_exp = self._download_savant_csv(
                    self._PITCHER_EXPECTED_URL.format(year=year)
                )
                row_exp = self._find_player_row(df_exp, mlbam_id)
                if row_exp is not None:
                    pa = self._safe_float(row_exp, "pa", 1.0)
                    hr = self._safe_float(row_exp, "hr", 0.0)
                    if pa > 0:
                        result["hr_rate"] = hr / pa
            except Exception:
                pass  # keep fallback hr_rate

            time.sleep(_SAVANT_RATE_LIMIT)
            return result

        except Exception as exc:
            logger.error(
                "StatcastFetcher.fetch_pitcher_stats failed for %s: %s. "
                "Returning league averages.", mlbam_id, exc
            )
            return fallback

    def fetch_batter_stats(self, mlbam_id: int, season: int | None = None) -> dict[str, float]:
        """
        Fetch a batter's Statcast metrics from the Baseball Savant leaderboard.

        Parameters
        ----------
        mlbam_id : int
            Batter's MLBAM player ID.
        season : int, optional
            Season year; defaults to ``self._default_season``.

        Returns
        -------
        dict
            Keys: k_rate, bb_rate, hr_rate, xba, xslg, barrel_pct,
            hard_hit_pct, chase_rate, whiff_pct, contact_pct, pull_pct, avg_ev.
        """
        year = season or self._default_season
        fallback = self._batter_fallback()

        try:
            df_main = self._download_savant_csv(
                self._BATTER_STATS_URL.format(year=year)
            )
            df_exp = self._download_savant_csv(
                self._BATTER_EXPECTED_URL.format(year=year)
            )

            row_main = self._find_player_row(df_main, mlbam_id)
            row_exp = self._find_player_row(df_exp, mlbam_id)

            if row_main is None and row_exp is None:
                logger.warning(
                    "StatcastFetcher: no Savant data for batter %s season %s; "
                    "using league averages.", mlbam_id, year
                )
                return fallback

            result = dict(fallback)

            if row_main is not None:
                result.update(
                    {
                        "k_rate": self._safe_float(row_main, "k_percent", fallback["k_rate"] * 100) / 100,
                        "bb_rate": self._safe_float(row_main, "bb_percent", fallback["bb_rate"] * 100) / 100,
                        "barrel_pct": self._safe_float(row_main, "barrel_batted_rate", fallback["barrel_pct"] * 100) / 100,
                        "hard_hit_pct": self._safe_float(row_main, "hard_hit_percent", fallback["hard_hit_pct"] * 100) / 100,
                        "chase_rate": self._safe_float(row_main, "oz_swing_percent", fallback["chase_rate"] * 100) / 100,
                        "whiff_pct": self._safe_float(row_main, "whiff_percent", fallback["whiff_pct"] * 100) / 100,
                        "contact_pct": self._safe_float(row_main, "z_contact_percent", fallback["contact_pct"] * 100) / 100,
                        "pull_pct": self._safe_float(row_main, "pull_percent", fallback["pull_pct"] * 100) / 100,
                        "avg_ev": self._safe_float(row_main, "avg_best_speed", fallback["avg_ev"]),
                    }
                )

            if row_exp is not None:
                pa = self._safe_float(row_exp, "pa", 1.0)
                hr = self._safe_float(row_exp, "hr", 0.0)
                result.update(
                    {
                        "xba": self._safe_float(row_exp, "est_ba", fallback["xba"]),
                        "xslg": self._safe_float(row_exp, "est_slg", fallback["xslg"]),
                        "hr_rate": hr / pa if pa > 0 else fallback["hr_rate"],
                    }
                )

            time.sleep(_SAVANT_RATE_LIMIT)
            return result

        except Exception as exc:
            logger.error(
                "StatcastFetcher.fetch_batter_stats failed for %s: %s. "
                "Returning league averages.", mlbam_id, exc
            )
            return fallback

    def fetch_recent_form(
        self,
        mlbam_id: int,
        days: int = 14,
        player_type: str = "pitcher",
    ) -> dict[str, float]:
        """
        Compute recent performance metrics from the MLB Stats API game logs.

        Parameters
        ----------
        mlbam_id : int
            Player's MLBAM ID.
        days : int
            Lookback window in calendar days (default 14).
        player_type : str
            ``"pitcher"`` or ``"batter"`` (default ``"pitcher"``).

        Returns
        -------
        dict
            Pitcher: ``recent_k_rate``, ``recent_bb_rate``, ``recent_era``,
            ``recent_whip``, ``games_in_window``.
            Batter: ``recent_ba``, ``recent_k_rate``, ``recent_obp``,
            ``games_in_window``.
        """
        group = "pitching" if player_type == "pitcher" else "hitting"
        start_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
        end_date = datetime.now().strftime("%Y-%m-%d")

        url = (
            f"{_MLB_API_BASE}/people/{mlbam_id}/stats"
            f"?stats=gameLog&group={group}"
            f"&startDate={start_date}&endDate={end_date}&sportId=1"
        )

        try:
            data = self._mlb_api_get(url)
            stats_list = data.get("stats", [{}])[0].get("splits", [])
        except Exception as exc:
            logger.warning(
                "fetch_recent_form failed for %s (%s): %s", mlbam_id, player_type, exc
            )
            stats_list = []

        if not stats_list:
            if player_type == "pitcher":
                return {
                    "recent_k_rate": _STATCAST_DEFAULTS["k_rate"],
                    "recent_bb_rate": _STATCAST_DEFAULTS["bb_rate"],
                    "recent_era": 4.50,
                    "recent_whip": 1.30,
                    "games_in_window": 0,
                }
            else:
                return {
                    "recent_ba": _STATCAST_DEFAULTS["xba"],
                    "recent_k_rate": _STATCAST_DEFAULTS["k_rate"],
                    "recent_obp": 0.320,
                    "games_in_window": 0,
                }

        if player_type == "pitcher":
            totals: dict[str, float] = {"bf": 0, "so": 0, "bb": 0, "er": 0, "ip": 0.0, "h": 0}
            for split in stats_list:
                s = split.get("stat", {})
                totals["bf"] += float(s.get("battersFaced", 0) or 0)
                totals["so"] += float(s.get("strikeOuts", 0) or 0)
                totals["bb"] += float(s.get("baseOnBalls", 0) or 0)
                totals["er"] += float(s.get("earnedRuns", 0) or 0)
                totals["h"] += float(s.get("hits", 0) or 0)
                # IP stored as "X.Y" where .Y is thirds of an inning
                ip_raw = str(s.get("inningsPitched", "0.0"))
                try:
                    inn, thirds = ip_raw.split(".")
                    totals["ip"] += int(inn) + int(thirds) / 3
                except Exception:
                    totals["ip"] += float(ip_raw or 0)

            bf = max(totals["bf"], 1.0)
            ip = max(totals["ip"], 0.1)
            return {
                "recent_k_rate": totals["so"] / bf,
                "recent_bb_rate": totals["bb"] / bf,
                "recent_era": totals["er"] / ip * 9,
                "recent_whip": (totals["h"] + totals["bb"]) / ip,
                "games_in_window": len(stats_list),
            }
        else:
            totals = {"ab": 0, "h": 0, "so": 0, "bb": 0, "pa": 0}
            for split in stats_list:
                s = split.get("stat", {})
                totals["ab"] += float(s.get("atBats", 0) or 0)
                totals["h"] += float(s.get("hits", 0) or 0)
                totals["so"] += float(s.get("strikeOuts", 0) or 0)
                totals["bb"] += float(s.get("baseOnBalls", 0) or 0)
                totals["pa"] += float(s.get("plateAppearances", 0) or 0)

            ab = max(totals["ab"], 1.0)
            pa = max(totals["pa"], 1.0)
            return {
                "recent_ba": totals["h"] / ab,
                "recent_k_rate": totals["so"] / pa,
                "recent_obp": (totals["h"] + totals["bb"]) / pa,
                "games_in_window": len(stats_list),
            }

    def fetch_pitcher_pitch_count(
        self,
        mlbam_id: int,
        n_starts: int = 10,
    ) -> tuple[float, float]:
        """
        Return the mean and std of a pitcher's pitch count over their last
        ``n_starts`` starts.

        Parameters
        ----------
        mlbam_id : int
            Pitcher's MLBAM ID.
        n_starts : int
            Maximum number of recent starts to include (default 10).

        Returns
        -------
        tuple[float, float]
            ``(mean_pitch_count, std_pitch_count)``.  Falls back to
            ``(PITCH_COUNT_MEAN, PITCH_COUNT_STD)`` from ``DEFAULT_CONFIG``
            on error.
        """
        season = datetime.now().year
        url = (
            f"{_MLB_API_BASE}/people/{mlbam_id}/stats"
            f"?stats=gameLog&group=pitching&season={season}&sportId=1"
        )

        try:
            data = self._mlb_api_get(url)
            splits = data.get("stats", [{}])[0].get("splits", [])
        except Exception as exc:
            logger.warning(
                "fetch_pitcher_pitch_count failed for %s: %s; using config defaults.",
                mlbam_id, exc
            )
            return float(_CFG.PITCH_COUNT_MEAN), float(_CFG.PITCH_COUNT_STD)

        if not splits:
            return float(_CFG.PITCH_COUNT_MEAN), float(_CFG.PITCH_COUNT_STD)

        # Keep only games where pitcher started or pitched ≥ 3 innings
        starts = [
            s for s in splits
            if s.get("stat", {}).get("gamesStarted", 0) == 1
            or float(s.get("stat", {}).get("inningsPitched", "0") or 0) >= 3.0
        ]
        starts = starts[-n_starts:]

        pitch_counts: list[float] = []
        for split in starts:
            pc = float(split.get("stat", {}).get("numberOfPitches", 0) or 0)
            if pc > 0:
                pitch_counts.append(pc)

        if not pitch_counts:
            return float(_CFG.PITCH_COUNT_MEAN), float(_CFG.PITCH_COUNT_STD)

        mean_pc = float(np.mean(pitch_counts))
        std_pc = (
            float(np.std(pitch_counts, ddof=1))
            if len(pitch_counts) > 1
            else float(_CFG.PITCH_COUNT_STD)
        )
        return mean_pc, std_pc

    @lru_cache(maxsize=128)
    def _download_savant_csv(self, url: str) -> pd.DataFrame:
        """
        Download and parse a Baseball Savant CSV leaderboard.

        Results are cached via ``@lru_cache`` to avoid redundant downloads
        within the same process run.  The session itself handles HTTP-level
        retries.

        Parameters
        ----------
        url : str
            Full CSV endpoint URL.

        Returns
        -------
        pd.DataFrame
            Parsed DataFrame.  Returns an empty DataFrame on failure.
        """
        logger.debug("Downloading Savant CSV: %s", url)
        try:
            resp = self._session.get(url, timeout=_SAVANT_TIMEOUT)
            resp.raise_for_status()
            from io import StringIO

            df = pd.read_csv(StringIO(resp.text), low_memory=False)
            logger.debug(
                "Savant CSV downloaded: %d rows × %d cols from %s",
                len(df), len(df.columns), url,
            )
            return df
        except Exception as exc:
            logger.error("_download_savant_csv failed for %s: %s", url, exc)
            return pd.DataFrame()

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _mlb_api_get(self, url: str) -> dict[str, Any]:
        """Simple rate-limited GET against any MLB Stats API URL."""
        time.sleep(_MLB_API_RATE_LIMIT)
        resp = self._session.get(url, timeout=_MLB_API_TIMEOUT)
        resp.raise_for_status()
        return resp.json()  # type: ignore[return-value]

    @staticmethod
    def _find_player_row(df: pd.DataFrame, mlbam_id: int) -> pd.Series | None:
        """
        Locate a player row in a Savant leaderboard DataFrame.

        Tries common ID column names (``player_id``, ``batter``, ``pitcher``,
        ``xba_id``).  Returns ``None`` if not found or DataFrame is empty.
        """
        if df.empty:
            return None
        for col in ("player_id", "batter", "pitcher", "xba_id", "mlbam_id"):
            if col in df.columns:
                match = df[df[col].astype(str) == str(mlbam_id)]
                if not match.empty:
                    return match.iloc[0]
        return None

    @staticmethod
    def _safe_float(row: pd.Series, col: str, default: float) -> float:
        """Read a float from a Series column, returning ``default`` on any error."""
        try:
            val = row[col]
            if pd.isna(val):
                return default
            return float(val)
        except (KeyError, TypeError, ValueError):
            return default

    @staticmethod
    def _pitcher_fallback() -> dict[str, float]:
        return {
            "k_rate": _STATCAST_DEFAULTS["k_rate"],
            "bb_rate": _STATCAST_DEFAULTS["bb_rate"],
            "hr_rate": _STATCAST_DEFAULTS["hr_rate"],
            "whiff_pct": _STATCAST_DEFAULTS["whiff_pct"],
            "csw_pct": _STATCAST_DEFAULTS["csw_pct"],
            "zone_pct": _STATCAST_DEFAULTS["zone_pct"],
            "swstr_pct": _STATCAST_DEFAULTS["swstr_pct"],
            "avg_velo": _STATCAST_DEFAULTS["avg_velo"],
            "chase_rate": _STATCAST_DEFAULTS["chase_rate"],
            "iz_contact_pct": _STATCAST_DEFAULTS["iz_contact_pct"],
            "gb_rate": _STATCAST_DEFAULTS["gb_rate"],
            "fb_rate": _STATCAST_DEFAULTS["fb_rate"],
        }

    @staticmethod
    def _batter_fallback() -> dict[str, float]:
        return {
            "k_rate": _STATCAST_DEFAULTS["k_rate"],
            "bb_rate": _STATCAST_DEFAULTS["bb_rate"],
            "hr_rate": _STATCAST_DEFAULTS["hr_rate"],
            "xba": _STATCAST_DEFAULTS["xba"],
            "xslg": _STATCAST_DEFAULTS["xslg"],
            "barrel_pct": _STATCAST_DEFAULTS["barrel_pct"],
            "hard_hit_pct": _STATCAST_DEFAULTS["hard_hit_pct"],
            "chase_rate": _STATCAST_DEFAULTS["chase_rate"],
            "whiff_pct": _STATCAST_DEFAULTS["whiff_pct"],
            "contact_pct": _STATCAST_DEFAULTS["contact_pct"],
            "pull_pct": _STATCAST_DEFAULTS["pull_pct"],
            "avg_ev": _STATCAST_DEFAULTS["avg_ev"],
        }


# ===========================================================================
# MLBApiClient
# ===========================================================================

class MLBApiClient:
    """
    Client for the public MLB Stats API (``statsapi.mlb.com/api/v1/``).

    No API key is required.  All methods include rate limiting, retry logic,
    and structured logging.  Missing or unknown data returns ``None`` or an
    empty container rather than raising exceptions.
    """

    def __init__(self) -> None:
        self._session = _build_session()
        self._last_call: float = 0.0

    # ------------------------------------------------------------------
    # Public methods
    # ------------------------------------------------------------------

    def get_todays_games(self) -> list[dict[str, Any]]:
        """
        Fetch today's MLB schedule with probable pitchers.

        Returns
        -------
        list[dict]
            One dict per game with keys: ``game_pk``, ``game_date``,
            ``status``, ``home_team``, ``away_team``, ``home_team_id``,
            ``away_team_id``, ``home_probable_pitcher_id``,
            ``away_probable_pitcher_id``, ``venue_name``, ``venue_lat``,
            ``venue_lon``, ``game_time``.
        """
        today = date.today().strftime("%Y-%m-%d")
        return self.get_schedule(today)

    def get_schedule(self, game_date: str) -> list[dict[str, Any]]:
        """
        Fetch the MLB schedule for a specific date.

        Parameters
        ----------
        game_date : str
            ISO date string ``"YYYY-MM-DD"``.

        Returns
        -------
        list[dict]
            Same structure as :meth:`get_todays_games`.
        """
        try:
            data = self._api_get(
                "schedule",
                {
                    "sportId": 1,
                    "date": game_date,
                    "hydrate": (
                        "probablePitcher(note),linescore,team,"
                        "venue(location),flags,broadcasts(all)"
                    ),
                },
            )
        except Exception as exc:
            logger.error("get_schedule failed for %s: %s", game_date, exc)
            return []

        games: list[dict[str, Any]] = []
        for date_entry in data.get("dates", []):
            for g in date_entry.get("games", []):
                home = g.get("teams", {}).get("home", {})
                away = g.get("teams", {}).get("away", {})
                venue = g.get("venue", {})
                location = venue.get("location", {})

                def probable_id(team_dict: dict) -> int | None:
                    try:
                        return int(team_dict["probablePitcher"]["id"])
                    except (KeyError, TypeError):
                        return None

                games.append(
                    {
                        "game_pk": g.get("gamePk"),
                        "game_date": game_date,
                        "status": g.get("status", {}).get("abstractGameState", "Unknown"),
                        "home_team": home.get("team", {}).get("abbreviation", ""),
                        "away_team": away.get("team", {}).get("abbreviation", ""),
                        "home_team_id": home.get("team", {}).get("id"),
                        "away_team_id": away.get("team", {}).get("id"),
                        "home_probable_pitcher_id": probable_id(home),
                        "away_probable_pitcher_id": probable_id(away),
                        "venue_name": venue.get("name", ""),
                        "venue_lat": location.get("latitude"),
                        "venue_lon": location.get("longitude"),
                        "game_time": g.get("gameDate", ""),
                    }
                )
        return games

    def get_lineup(self, game_pk: int) -> dict[str, Any]:
        """
        Return confirmed lineups for a game.

        When the game hasn't started the MLB API boxscore endpoint still
        exposes the pre-game batting order if it has been submitted.  Falls
        back to an empty lineup list rather than raising.

        Parameters
        ----------
        game_pk : int
            The MLB game ID.

        Returns
        -------
        dict
            Keys ``home_lineup`` and ``away_lineup``, each a list of dicts
            with ``mlbam_id``, ``name``, ``batting_order``, ``position``,
            ``bat_side``.
        """
        empty: dict[str, Any] = {"home_lineup": [], "away_lineup": []}
        try:
            data = self._api_get(f"game/{game_pk}/boxscore", {})
        except Exception as exc:
            logger.warning("get_lineup: boxscore fetch failed for %s: %s", game_pk, exc)
            return empty

        def parse_side(side_data: dict) -> list[dict[str, Any]]:
            players = side_data.get("players", {})
            order: list[dict[str, Any]] = []
            for _key, player_info in players.items():
                bo = player_info.get("battingOrder")
                if bo is None:
                    continue
                try:
                    bo_int = int(str(bo).rstrip("0") or "0")
                except ValueError:
                    bo_int = 0
                person = player_info.get("person", {})
                bat_side = (
                    player_info.get("batSide", {}).get("code", "R")
                    if isinstance(player_info.get("batSide"), dict)
                    else str(player_info.get("batSide", "R"))
                )
                order.append(
                    {
                        "mlbam_id": person.get("id"),
                        "name": person.get("fullName", "Unknown"),
                        "batting_order": bo_int,
                        "position": player_info.get("position", {}).get("abbreviation", ""),
                        "bat_side": bat_side,
                    }
                )
            order.sort(key=lambda x: x["batting_order"])
            return order

        teams = data.get("teams", {})
        return {
            "home_lineup": parse_side(teams.get("home", {})),
            "away_lineup": parse_side(teams.get("away", {})),
        }

    def get_team_stats(self, team_id: int, season: int) -> dict[str, float]:
        """
        Fetch team-level aggregate hitting stats for the given season.

        Parameters
        ----------
        team_id : int
            MLB team ID.
        season : int
            Season year.

        Returns
        -------
        dict
            Keys: ``k_pct``, ``bb_pct``, ``avg``, ``obp``, ``slg``,
            ``ops``, ``pa``.
        """
        fallback: dict[str, float] = {
            "k_pct": _STATCAST_DEFAULTS["k_rate"],
            "bb_pct": _STATCAST_DEFAULTS["bb_rate"],
            "avg": 0.250,
            "obp": 0.320,
            "slg": 0.410,
            "ops": 0.730,
            "pa": 0,
        }
        try:
            data = self._api_get(
                f"teams/{team_id}/stats",
                {"stats": "season", "group": "hitting", "season": season, "sportId": 1},
            )
            splits = data.get("stats", [{}])[0].get("splits", [{}])
            if not splits:
                return fallback
            s = splits[0].get("stat", {})
            pa = float(s.get("plateAppearances", 1) or 1)
            return {
                "k_pct": float(s.get("strikeOuts", 0) or 0) / pa,
                "bb_pct": float(s.get("baseOnBalls", 0) or 0) / pa,
                "avg": float(s.get("avg", fallback["avg"]) or fallback["avg"]),
                "obp": float(s.get("obp", fallback["obp"]) or fallback["obp"]),
                "slg": float(s.get("slg", fallback["slg"]) or fallback["slg"]),
                "ops": float(s.get("ops", fallback["ops"]) or fallback["ops"]),
                "pa": pa,
            }
        except Exception as exc:
            logger.warning("get_team_stats failed for team %s season %s: %s", team_id, season, exc)
            return fallback

    def get_player_splits(self, mlbam_id: int, season: int) -> dict[str, Any]:
        """
        Fetch platoon splits (vs. LHP and vs. RHP) for a player.

        Parameters
        ----------
        mlbam_id : int
            Player's MLBAM ID.
        season : int
            Season year.

        Returns
        -------
        dict
            Keys ``vs_lhp`` and ``vs_rhp``, each a raw MLB API ``stat`` dict.
        """
        fallback: dict[str, Any] = {"vs_lhp": {}, "vs_rhp": {}}
        try:
            data = self._api_get(
                f"people/{mlbam_id}/stats",
                {
                    "stats": "statSplits",
                    "sitCodes": "vl,vr",
                    "group": "hitting",
                    "season": season,
                    "sportId": 1,
                },
            )
            splits = data.get("stats", [{}])[0].get("splits", [])
        except Exception as exc:
            logger.warning("get_player_splits failed for %s: %s", mlbam_id, exc)
            return fallback

        result: dict[str, Any] = {"vs_lhp": {}, "vs_rhp": {}}
        for split in splits:
            code = split.get("split", {}).get("code", "")
            stat = split.get("stat", {})
            if code == "vl":
                result["vs_lhp"] = stat
            elif code == "vr":
                result["vs_rhp"] = stat
        return result

    def get_boxscore(self, game_pk: int) -> dict[str, Any]:
        """
        Return the full boxscore for a game (useful for backtesting).

        Parameters
        ----------
        game_pk : int
            The MLB game ID.

        Returns
        -------
        dict
            Raw boxscore JSON from the MLB Stats API.  Empty dict on failure.
        """
        try:
            return self._api_get(f"game/{game_pk}/boxscore", {})
        except Exception as exc:
            logger.warning("get_boxscore failed for %s: %s", game_pk, exc)
            return {}

    def _api_get(self, endpoint: str, params: dict[str, Any]) -> dict[str, Any]:
        """
        GET against the MLB Stats API with rate limiting and retries.

        Parameters
        ----------
        endpoint : str
            Path relative to the MLB API base (e.g. ``"schedule"`` or
            ``"game/745528/boxscore"``).
        params : dict
            Query-string parameters.

        Returns
        -------
        dict
            Parsed JSON response.

        Raises
        ------
        requests.HTTPError
            Propagates HTTP errors after retries are exhausted.
        """
        elapsed = time.time() - self._last_call
        if elapsed < _MLB_API_RATE_LIMIT:
            time.sleep(_MLB_API_RATE_LIMIT - elapsed)

        url = f"{_MLB_API_BASE}/{endpoint}"
        try:
            resp = self._session.get(url, params=params, timeout=_MLB_API_TIMEOUT)
            resp.raise_for_status()
            self._last_call = time.time()
            return resp.json()  # type: ignore[return-value]
        except Exception:
            self._last_call = time.time()
            raise


# ===========================================================================
# SupabaseReader
# ===========================================================================

class SupabaseReader:
    """
    Reads auxiliary data (umpire framing, prop lines, projections) from a
    Supabase Postgres backend.

    Connection credentials are read from environment variables
    ``SUPABASE_URL`` and ``SUPABASE_KEY`` (also available as module-level
    constants ``config.SUPABASE_URL`` and ``config.SUPABASE_KEY``).

    When credentials are absent the reader operates in *offline mode* and
    returns sensible defaults without raising errors.

    Requires the ``supabase`` Python package (``pip install supabase``).
    Falls back gracefully if the package is not installed.
    """

    def __init__(self) -> None:
        self._url: str = os.environ.get("SUPABASE_URL", "") or config.SUPABASE_URL
        self._key: str = os.environ.get("SUPABASE_KEY", "") or config.SUPABASE_KEY
        self._client: Any = None

        if self._url and self._key:
            self._client = self._build_client()
        else:
            logger.info(
                "SupabaseReader: SUPABASE_URL / SUPABASE_KEY not set; "
                "all reads will return defaults."
            )

    def _build_client(self) -> Any:
        """Attempt to build a Supabase client; return None on ImportError."""
        try:
            from supabase import create_client  # type: ignore[import]

            client = create_client(self._url, self._key)
            logger.info("SupabaseReader: connected to %s", self._url)
            return client
        except ImportError:
            logger.warning(
                "SupabaseReader: 'supabase' package not installed. "
                "Run `pip install supabase` to enable database reads."
            )
            return None
        except Exception as exc:
            logger.error("SupabaseReader: failed to connect: %s", exc)
            return None

    # ------------------------------------------------------------------
    # Public methods
    # ------------------------------------------------------------------

    def get_umpire_data(self, umpire_name: str) -> dict[str, float]:
        """
        Fetch umpire tendencies from the ``umpire_framing`` table.

        Parameters
        ----------
        umpire_name : str
            Full umpire name as stored in the database.

        Returns
        -------
        dict
            Keys: ``composite_score``, ``extra_strikes``, ``strike_rate``,
            ``k_factor``.
        """
        default: dict[str, float] = {
            "composite_score": 0.0,
            "extra_strikes": 0.0,
            "strike_rate": 0.0,
            "k_factor": 1.0,
        }
        if self._client is None:
            return default
        try:
            resp = (
                self._client.table("umpire_framing")
                .select("composite_score,extra_strikes,strike_rate,k_factor")
                .eq("umpire_name", umpire_name)
                .limit(1)
                .execute()
            )
            rows = resp.data
            if not rows:
                logger.debug("SupabaseReader: no umpire data for '%s'", umpire_name)
                return default
            row = rows[0]
            return {
                "composite_score": float(row.get("composite_score", 0.0) or 0.0),
                "extra_strikes": float(row.get("extra_strikes", 0.0) or 0.0),
                "strike_rate": float(row.get("strike_rate", 0.0) or 0.0),
                "k_factor": float(row.get("k_factor", 1.0) or 1.0),
            }
        except Exception as exc:
            logger.warning("get_umpire_data failed for '%s': %s", umpire_name, exc)
            return default

    def get_catcher_framing(self, mlbam_id: int) -> dict[str, float]:
        """
        Fetch catcher framing score from the ``catcher_framing`` table.

        Parameters
        ----------
        mlbam_id : int
            Catcher's MLBAM player ID.

        Returns
        -------
        dict
            Keys: ``framing_score``, ``extra_strikes_per_game``.
        """
        default: dict[str, float] = {"framing_score": 0.0, "extra_strikes_per_game": 0.0}
        if self._client is None:
            return default
        try:
            resp = (
                self._client.table("catcher_framing")
                .select("framing_score,extra_strikes_per_game")
                .eq("mlbam_id", mlbam_id)
                .limit(1)
                .execute()
            )
            rows = resp.data
            if not rows:
                return default
            row = rows[0]
            return {
                "framing_score": float(row.get("framing_score", 0.0) or 0.0),
                "extra_strikes_per_game": float(
                    row.get("extra_strikes_per_game", 0.0) or 0.0
                ),
            }
        except Exception as exc:
            logger.warning("get_catcher_framing failed for %s: %s", mlbam_id, exc)
            return default

    def get_prop_lines(self, game_date: str) -> list[dict[str, Any]]:
        """
        Read current prop lines from the ``props`` table.

        Parameters
        ----------
        game_date : str
            ISO date string ``"YYYY-MM-DD"``.

        Returns
        -------
        list[dict]
            Each dict contains at minimum: ``player_id``, ``player_name``,
            ``prop_type``, ``line``, ``over_odds``, ``under_odds``,
            ``game_pk``, ``game_date``.
        """
        if self._client is None:
            return []
        try:
            resp = (
                self._client.table("props")
                .select("*")
                .eq("game_date", game_date)
                .execute()
            )
            return resp.data or []
        except Exception as exc:
            logger.warning("get_prop_lines failed for %s: %s", game_date, exc)
            return []

    def get_existing_projections(self, game_date: str) -> list[dict[str, Any]]:
        """
        Read existing projection rows (from a prior pipeline run).

        Parameters
        ----------
        game_date : str
            ISO date string ``"YYYY-MM-DD"``.

        Returns
        -------
        list[dict]
            Raw rows from the ``projections`` table.
        """
        if self._client is None:
            return []
        try:
            resp = (
                self._client.table("projections")
                .select("*")
                .eq("game_date", game_date)
                .execute()
            )
            return resp.data or []
        except Exception as exc:
            logger.warning("get_existing_projections failed for %s: %s", game_date, exc)
            return []


# ===========================================================================
# WeatherFetcher
# ===========================================================================

class WeatherFetcher:
    """
    Fetches game-time weather for outdoor ballparks using the OpenWeatherMap
    free-tier API.

    If ``OPENWEATHER_API_KEY`` is not set in the environment the fetcher
    returns ``_WEATHER_DEFAULTS`` silently, so the pipeline always has valid
    weather values.

    Outfield wind direction is determined by comparing the prevailing wind
    bearing to a simplified outfield bearing per park.  When park orientation
    is unknown a ±45° cone heuristic is used.
    """

    # Approximate bearing (degrees clockwise from North) of the outfield.
    # Wind blowing in this direction means it is blowing OUT toward the wall.
    _PARK_OUTFIELD_BEARING: dict[str, float] = {
        "NYY": 200.0,
        "NYM": 200.0,
        "BOS": 280.0,
        "CHC": 270.0,   # Wrigley wind-out historically NE → toward LF
        "COL": 220.0,
        "SFG": 270.0,
        "LAD": 290.0,
    }
    _DEFAULT_OUTFIELD_BEARING: float = 220.0   # generic SW bearing

    def __init__(self) -> None:
        self._api_key: str = os.environ.get("OPENWEATHER_API_KEY", "")
        self._session = _build_session(retries=2, backoff=1.0)

    def get_game_weather(
        self,
        lat: float,
        lon: float,
        game_time: str,
        team_abbr: str = "",
    ) -> dict[str, Any]:
        """
        Return weather conditions at a ballpark for a given game time.

        Parameters
        ----------
        lat : float
            Ballpark latitude.
        lon : float
            Ballpark longitude.
        game_time : str
            ISO 8601 datetime string, e.g. ``"2026-03-02T19:10:00Z"``.
        team_abbr : str, optional
            Home team abbreviation, used to look up park-specific outfield
            bearing when determining ``wind_out``.

        Returns
        -------
        dict
            Keys: ``temp_f`` (float), ``wind_speed_mph`` (float),
            ``wind_direction`` (str, 8-point cardinal), ``wind_out`` (bool).
        """
        if not self._api_key:
            logger.debug("WeatherFetcher: no API key; returning defaults.")
            return dict(_WEATHER_DEFAULTS)

        try:
            game_dt = datetime.fromisoformat(game_time.replace("Z", "+00:00"))
            forecast_data = self._fetch_forecast(lat, lon)
            entry = self._closest_forecast_entry(forecast_data, game_dt)

            if entry is None:
                entry = self._fetch_current(lat, lon)

            return self._parse_entry(entry, team_abbr)

        except Exception as exc:
            logger.warning(
                "WeatherFetcher.get_game_weather failed (lat=%.4f, lon=%.4f): %s; "
                "returning defaults.", lat, lon, exc
            )
            return dict(_WEATHER_DEFAULTS)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _fetch_forecast(self, lat: float, lon: float) -> dict[str, Any]:
        """Download a 5-day / 3-hour forecast from OpenWeatherMap."""
        resp = self._session.get(
            f"{_OPENWEATHER_BASE}/forecast",
            params={"lat": lat, "lon": lon, "units": "imperial", "appid": self._api_key},
            timeout=_OPENWEATHER_TIMEOUT,
        )
        resp.raise_for_status()
        return resp.json()  # type: ignore[return-value]

    def _fetch_current(self, lat: float, lon: float) -> dict[str, Any]:
        """Download current weather from OpenWeatherMap."""
        resp = self._session.get(
            f"{_OPENWEATHER_BASE}/weather",
            params={"lat": lat, "lon": lon, "units": "imperial", "appid": self._api_key},
            timeout=_OPENWEATHER_TIMEOUT,
        )
        resp.raise_for_status()
        return resp.json()  # type: ignore[return-value]

    @staticmethod
    def _closest_forecast_entry(
        forecast_data: dict[str, Any], game_dt: datetime
    ) -> dict[str, Any] | None:
        """Pick the forecast time slot closest to ``game_dt``."""
        entries = forecast_data.get("list", [])
        if not entries:
            return None
        game_ts = game_dt.timestamp()
        return min(entries, key=lambda e: abs(e.get("dt", 0) - game_ts))

    def _parse_entry(self, entry: dict[str, Any], team_abbr: str) -> dict[str, Any]:
        """Convert an OWM JSON entry into the canonical weather dict."""
        main = entry.get("main", {})
        wind = entry.get("wind", {})

        temp_f = float(main.get("temp", _WEATHER_DEFAULTS["temp_f"]))
        speed_mph = float(wind.get("speed", _WEATHER_DEFAULTS["wind_speed_mph"]))
        wind_deg = float(wind.get("deg", 180))
        direction_str = self._degrees_to_cardinal(wind_deg)

        park_bearing = self._PARK_OUTFIELD_BEARING.get(
            team_abbr, self._DEFAULT_OUTFIELD_BEARING
        )
        angle_diff = abs(((wind_deg - park_bearing + 180) % 360) - 180)
        wind_out = angle_diff <= 45

        return {
            "temp_f": round(temp_f, 1),
            "wind_speed_mph": round(speed_mph, 1),
            "wind_direction": direction_str,
            "wind_out": wind_out,
        }

    @staticmethod
    def _degrees_to_cardinal(degrees: float) -> str:
        """Convert a wind bearing (0–360°) to an 8-point cardinal string."""
        dirs = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]
        idx = int((degrees + 22.5) / 45) % 8
        return dirs[idx]


# ===========================================================================
# DataPrepPipeline
# ===========================================================================

class DataPrepPipeline:
    """
    Orchestrates all fetchers to build a fully-prepared :class:`GameData`
    object for the Monte Carlo engine.

    Parameters
    ----------
    season : int, optional
        Override the season year; defaults to the current calendar year.
    statcast : StatcastFetcher, optional
        Inject a custom ``StatcastFetcher`` (useful for testing / mocking).
    mlb_api : MLBApiClient, optional
        Inject a custom ``MLBApiClient``.
    supabase : SupabaseReader, optional
        Inject a custom ``SupabaseReader``.
    weather : WeatherFetcher, optional
        Inject a custom ``WeatherFetcher``.
    """

    def __init__(
        self,
        season: int | None = None,
        statcast: StatcastFetcher | None = None,
        mlb_api: MLBApiClient | None = None,
        supabase: SupabaseReader | None = None,
        weather: WeatherFetcher | None = None,
    ) -> None:
        self._season: int = season or datetime.now().year
        self._statcast: StatcastFetcher = statcast or StatcastFetcher(season=self._season)
        self._mlb_api: MLBApiClient = mlb_api or MLBApiClient()
        self._supabase: SupabaseReader = supabase or SupabaseReader()
        self._weather: WeatherFetcher = weather or WeatherFetcher()

    # ------------------------------------------------------------------
    # Public methods
    # ------------------------------------------------------------------

    def prepare_game_data(self, game: dict[str, Any]) -> GameData:
        """
        Orchestrate all fetchers and return a :class:`GameData` object ready
        for Monte Carlo simulation.

        Parameters
        ----------
        game : dict
            A game dict as returned by :meth:`MLBApiClient.get_todays_games`.
            Expected keys: ``game_pk``, ``game_date``, ``home_team``,
            ``away_team``, ``home_team_id``, ``away_team_id``,
            ``home_probable_pitcher_id``, ``away_probable_pitcher_id``,
            ``venue_name``, ``venue_lat``, ``venue_lon``, ``game_time``.

        Returns
        -------
        GameData
            Fully-populated game snapshot.  No field is ever ``None``; missing
            data is replaced with league averages or sensible defaults.
        """
        game_pk: int = int(game.get("game_pk") or 0)
        game_date: str = game.get("game_date", date.today().strftime("%Y-%m-%d"))
        home_team: str = game.get("home_team", "")
        away_team: str = game.get("away_team", "")

        logger.info(
            "DataPrepPipeline: preparing game %s — %s @ %s on %s",
            game_pk, away_team, home_team, game_date,
        )

        gd = GameData(
            game_pk=game_pk,
            game_date=game_date,
            home_team=home_team,
            away_team=away_team,
            venue=game.get("venue_name", ""),
            raw_game=game,
        )

        # ---- Park factors ---------------------------------------------------
        venue_name = game.get("venue_name", "")
        gd.park_factors = dict(
            config.PARK_FACTORS.get(venue_name, config.PARK_FACTORS["neutral"])
        )

        # ---- Pitchers -------------------------------------------------------
        home_pitcher_id: int | None = game.get("home_probable_pitcher_id")
        away_pitcher_id: int | None = game.get("away_probable_pitcher_id")

        if home_pitcher_id:
            gd.home_pitcher = self._build_pitcher_data(home_pitcher_id, home_team, game_date)
        if away_pitcher_id:
            gd.away_pitcher = self._build_pitcher_data(away_pitcher_id, away_team, game_date)

        # ---- Lineups --------------------------------------------------------
        lineup_data = self._mlb_api.get_lineup(game_pk)
        gd.home_lineup = self._build_lineup(
            lineup_data.get("home_lineup", []),
            home_team,
            vs_pitcher_hand=gd.away_pitcher.hand if gd.away_pitcher else "R",
        )
        gd.away_lineup = self._build_lineup(
            lineup_data.get("away_lineup", []),
            away_team,
            vs_pitcher_hand=gd.home_pitcher.hand if gd.home_pitcher else "R",
        )

        # ---- Team-level K% (for context) ------------------------------------
        home_team_id: int | None = game.get("home_team_id")
        away_team_id: int | None = game.get("away_team_id")
        if home_team_id:
            ts = self._mlb_api.get_team_stats(int(home_team_id), self._season)
            gd.home_team_k_pct = ts["k_pct"]
        if away_team_id:
            ts = self._mlb_api.get_team_stats(int(away_team_id), self._season)
            gd.away_team_k_pct = ts["k_pct"]

        # ---- Catcher framing ------------------------------------------------
        home_catcher_id = self._find_catcher_id(lineup_data.get("home_lineup", []))
        away_catcher_id = self._find_catcher_id(lineup_data.get("away_lineup", []))
        if home_catcher_id:
            gd.home_catcher_framing = self._supabase.get_catcher_framing(
                home_catcher_id
            ).get("framing_score", 0.0)
        if away_catcher_id:
            gd.away_catcher_framing = self._supabase.get_catcher_framing(
                away_catcher_id
            ).get("framing_score", 0.0)

        # ---- Umpire ---------------------------------------------------------
        # Umpire assignment is not in the pre-game schedule; defaults to neutral.
        umpire_data = self._supabase.get_umpire_data("Unknown")
        gd.umpire = UmpireData(
            name="Unknown",
            composite_score=umpire_data["composite_score"],
            extra_strikes=umpire_data["extra_strikes"],
            strike_rate=umpire_data["strike_rate"],
            k_factor=umpire_data["k_factor"],
        )

        # ---- Weather --------------------------------------------------------
        lat: float | None = game.get("venue_lat")
        lon: float | None = game.get("venue_lon")
        game_time: str = game.get("game_time", "")

        if lat is None or lon is None:
            coords = _PARK_COORDS.get(home_team)
            if coords:
                lat, lon = coords

        if lat is not None and lon is not None and game_time:
            wx = self._weather.get_game_weather(
                float(lat), float(lon), game_time, team_abbr=home_team
            )
        else:
            wx = dict(_WEATHER_DEFAULTS)

        gd.temp_f = float(wx["temp_f"])
        gd.wind_speed_mph = float(wx["wind_speed_mph"])
        gd.wind_direction = str(wx["wind_direction"])
        gd.wind_out = bool(wx["wind_out"])

        logger.info(
            "DataPrepPipeline: finished game %s — home_lineup=%d batters, "
            "away_lineup=%d batters, weather=%.1f°F wind=%.1f mph %s",
            game_pk,
            len(gd.home_lineup),
            len(gd.away_lineup),
            gd.temp_f,
            gd.wind_speed_mph,
            gd.wind_direction,
        )
        return gd

    def prepare_matchup_features(
        self,
        pitcher: dict[str, Any],
        batter: dict[str, Any],
        context: dict[str, Any],
    ) -> np.ndarray:
        """
        Build the numeric feature vector for one pitcher–batter matchup.

        The vector length and column order exactly match
        ``config.FEATURE_COLUMNS``, so it can be passed directly to the
        trained ML model (after scaling).

        Parameters
        ----------
        pitcher : dict
            Pitcher stats dict — keys matching :class:`PitcherData` fields or
            the raw dict returned by
            :meth:`StatcastFetcher.fetch_pitcher_stats` plus recent-form keys.
        batter : dict
            Batter stats dict — keys matching :class:`BatterData` fields.
        context : dict
            Contextual scalars corresponding to the non-player columns in
            ``config.FEATURE_COLUMNS``:
            ``umpire_k_factor``, ``catcher_framing_score``,
            ``park_hr_factor``, ``park_k_factor``, ``park_h_factor``,
            ``temp_f``, ``wind_speed_mph``, ``wind_out``,
            ``is_home``, ``game_total_line``.

        Returns
        -------
        np.ndarray
            Shape ``(len(config.FEATURE_COLUMNS),)`` float64 array.
        """
        sd = _STATCAST_DEFAULTS

        def g(d: dict, key: str, default: float) -> float:
            try:
                v = d.get(key, default)
                return float(v) if v is not None else default
            except (TypeError, ValueError):
                return default

        batter_hand = str(batter.get("hand", "R"))
        pitcher_hand = str(pitcher.get("hand", "R"))
        platoon_adv = self._compute_platoon_advantage(batter_hand, pitcher_hand)

        park_neutral = config.PARK_FACTORS["neutral"]

        vec: list[float] = [
            # --- Pitcher features (10 features) ---
            g(pitcher, "k_rate", sd["k_rate"]),
            g(pitcher, "bb_rate", sd["bb_rate"]),
            g(pitcher, "hr_rate", sd["hr_rate"]),
            g(pitcher, "whiff_pct", sd["whiff_pct"]),
            g(pitcher, "csw_pct", sd["csw_pct"]),
            g(pitcher, "zone_pct", sd["zone_pct"]),
            g(pitcher, "swstr_pct", sd["swstr_pct"]),
            g(pitcher, "avg_velo", sd["avg_velo"]),
            g(pitcher, "chase_rate", sd["chase_rate"]),
            g(pitcher, "iz_contact_pct", sd["iz_contact_pct"]),
            # --- Batter features (10 features) ---
            g(batter, "k_rate", sd["k_rate"]),
            g(batter, "bb_rate", sd["bb_rate"]),
            g(batter, "hr_rate", sd["hr_rate"]),
            g(batter, "xba", sd["xba"]),
            g(batter, "xslg", sd["xslg"]),
            g(batter, "barrel_pct", sd["barrel_pct"]),
            g(batter, "hard_hit_pct", sd["hard_hit_pct"]),
            g(batter, "chase_rate", sd["chase_rate"]),
            g(batter, "whiff_pct", sd["whiff_pct"]),
            g(batter, "contact_pct", sd["contact_pct"]),
            # --- Matchup context (5 features) ---
            platoon_adv,
            float(bool(context.get("is_home", False))),
            g(context, "park_hr_factor", float(park_neutral["hr"])),
            g(context, "park_k_factor", float(park_neutral["k"])),
            g(context, "park_h_factor", float(park_neutral["h"])),
            # --- Game-day context (2 features) ---
            g(context, "umpire_k_factor", 1.0),
            g(context, "catcher_framing_score", 0.0),
            # --- Recent form / market (3 features) ---
            g(pitcher, "recent_k_rate", sd["k_rate"]),
            g(batter, "recent_ba", sd["xba"]),
            g(context, "game_total_line", 8.5),
            # --- Weather (3 features) ---
            g(context, "temp_f", float(_WEATHER_DEFAULTS["temp_f"])),
            g(context, "wind_speed_mph", float(_WEATHER_DEFAULTS["wind_speed_mph"])),
            float(bool(context.get("wind_out", False))),
        ]

        n_expected = len(config.FEATURE_COLUMNS)
        n_built = len(vec)
        if n_built != n_expected:
            raise ValueError(
                f"Feature vector length {n_built} != "
                f"config.FEATURE_COLUMNS length {n_expected}. "
                "Ensure prepare_matchup_features and FEATURE_COLUMNS are in sync."
            )

        return np.array(vec, dtype=np.float64)

    def _regress_rate(
        self,
        observed_rate: float,
        sample_size: float,
        league_avg: float,
        regression_pa: int | None = None,
    ) -> float:
        """
        Regress an observed rate toward the league average based on sample size.

        Uses Bayesian / shrinkage formula:

            regressed = (observed * n + league_avg * regression_pa) /
                        (n + regression_pa)

        Parameters
        ----------
        observed_rate : float
            Raw observed rate (e.g. ``0.28`` for 28 % K rate).
        sample_size : float
            Plate appearances or batters faced in the observed sample.
        league_avg : float
            League-average rate for this stat.
        regression_pa : int, optional
            PA to add at the league-average rate.  Defaults to
            ``DEFAULT_CONFIG.REGRESSION_PA``.

        Returns
        -------
        float
            Regressed rate, always finite.
        """
        if regression_pa is None:
            regression_pa = _CFG.REGRESSION_PA
        if not np.isfinite(observed_rate):
            return league_avg
        n = max(sample_size, 0.0)
        return (observed_rate * n + league_avg * regression_pa) / (n + regression_pa)

    def _compute_platoon_advantage(
        self,
        batter_hand: str,
        pitcher_hand: str,
    ) -> float:
        """
        Return a multiplicative platoon-advantage factor for K-rate.

        Same hand (e.g. RHB vs. RHP) gives the pitcher a slight edge.
        Opposite-hand matchups slightly favour the batter.

        Parameters
        ----------
        batter_hand : str
            Batting hand: ``"L"`` or ``"R"``.
        pitcher_hand : str
            Throwing hand: ``"L"`` or ``"R"``.

        Returns
        -------
        float
            Factor > 1.0 → pitcher platoon advantage;
            < 1.0 → batter platoon advantage.
        """
        same = batter_hand.upper() == pitcher_hand.upper()
        return (
            _STATCAST_DEFAULTS["platoon_same_hand_k"]
            if same
            else _STATCAST_DEFAULTS["platoon_opp_hand_k"]
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _build_pitcher_data(
        self,
        mlbam_id: int,
        team: str,
        game_date: str,
    ) -> PitcherData:
        """Fetch all stats for one pitcher and return a :class:`PitcherData`."""
        logger.debug("Building pitcher data for mlbam_id=%s team=%s", mlbam_id, team)

        season_stats = self._statcast.fetch_pitcher_stats(mlbam_id, season=self._season)
        recent = self._statcast.fetch_recent_form(mlbam_id, days=_CFG.RECENT_DAYS, player_type="pitcher")
        mean_pc, std_pc = self._statcast.fetch_pitcher_pitch_count(mlbam_id, n_starts=10)
        name, hand = self._fetch_player_meta(mlbam_id)
        days_rest = self._compute_days_rest(mlbam_id, game_date)

        return PitcherData(
            mlbam_id=mlbam_id,
            name=name,
            team=team,
            hand=hand,
            k_rate=self._regress_rate(season_stats["k_rate"], 500, _STATCAST_DEFAULTS["k_rate"]),
            bb_rate=self._regress_rate(season_stats["bb_rate"], 500, _STATCAST_DEFAULTS["bb_rate"]),
            hr_rate=self._regress_rate(season_stats["hr_rate"], 500, _STATCAST_DEFAULTS["hr_rate"]),
            whiff_pct=season_stats["whiff_pct"],
            csw_pct=season_stats["csw_pct"],
            zone_pct=season_stats["zone_pct"],
            swstr_pct=season_stats["swstr_pct"],
            avg_velo=season_stats["avg_velo"],
            chase_rate=season_stats["chase_rate"],
            iz_contact_pct=season_stats["iz_contact_pct"],
            gb_rate=season_stats["gb_rate"],
            fb_rate=season_stats["fb_rate"],
            recent_k_rate=recent.get("recent_k_rate", _STATCAST_DEFAULTS["k_rate"]),
            recent_bb_rate=recent.get("recent_bb_rate", _STATCAST_DEFAULTS["bb_rate"]),
            mean_pitch_count=mean_pc,
            std_pitch_count=std_pc,
            days_rest=days_rest,
        )

    def _build_batter_data(
        self,
        player: dict[str, Any],
        team: str,
        vs_pitcher_hand: str = "R",
    ) -> BatterData:
        """Fetch all stats for one batter and return a :class:`BatterData`."""
        mlbam_id: int = int(player.get("mlbam_id") or 0)
        bat_side: str = str(player.get("bat_side", "R"))
        batting_order: int = int(player.get("batting_order") or 5)
        name: str = str(player.get("name", "Unknown"))

        logger.debug("Building batter data for mlbam_id=%s team=%s", mlbam_id, team)

        season_stats = self._statcast.fetch_batter_stats(mlbam_id, season=self._season)
        recent = self._statcast.fetch_recent_form(mlbam_id, days=_CFG.RECENT_DAYS, player_type="batter")
        splits = self._mlb_api.get_player_splits(mlbam_id, season=self._season)

        ba_vs_lhp = float(
            splits.get("vs_lhp", {}).get("avg", _STATCAST_DEFAULTS["xba"])
            or _STATCAST_DEFAULTS["xba"]
        )
        ba_vs_rhp = float(
            splits.get("vs_rhp", {}).get("avg", _STATCAST_DEFAULTS["xba"])
            or _STATCAST_DEFAULTS["xba"]
        )

        return BatterData(
            mlbam_id=mlbam_id,
            name=name,
            team=team,
            hand=bat_side,
            lineup_position=batting_order,
            k_rate=self._regress_rate(season_stats["k_rate"], 300, _STATCAST_DEFAULTS["k_rate"]),
            bb_rate=self._regress_rate(season_stats["bb_rate"], 300, _STATCAST_DEFAULTS["bb_rate"]),
            hr_rate=self._regress_rate(season_stats["hr_rate"], 300, _STATCAST_DEFAULTS["hr_rate"]),
            xba=season_stats["xba"],
            xslg=season_stats["xslg"],
            barrel_pct=season_stats["barrel_pct"],
            hard_hit_pct=season_stats["hard_hit_pct"],
            chase_rate=season_stats["chase_rate"],
            whiff_pct=season_stats["whiff_pct"],
            contact_pct=season_stats["contact_pct"],
            pull_pct=season_stats["pull_pct"],
            avg_ev=season_stats["avg_ev"],
            recent_ba=recent.get("recent_ba", _STATCAST_DEFAULTS["xba"]),
            recent_k_rate=recent.get("recent_k_rate", _STATCAST_DEFAULTS["k_rate"]),
            ba_vs_lhp=ba_vs_lhp,
            ba_vs_rhp=ba_vs_rhp,
        )

    def _build_lineup(
        self,
        lineup_raw: list[dict[str, Any]],
        team: str,
        vs_pitcher_hand: str = "R",
    ) -> list[BatterData]:
        """Build a full lineup as a list of :class:`BatterData` objects."""
        result: list[BatterData] = []
        for player in lineup_raw:
            try:
                bd = self._build_batter_data(player, team, vs_pitcher_hand)
                result.append(bd)
            except Exception as exc:
                logger.warning(
                    "Failed to build batter data for mlbam_id=%s team=%s: %s; skipping.",
                    player.get("mlbam_id"), team, exc,
                )
        return result

    @lru_cache(maxsize=512)
    def _fetch_player_meta(self, mlbam_id: int) -> tuple[str, str]:
        """
        Fetch a player's full name and throwing hand from the MLB API.

        Returns
        -------
        tuple[str, str]
            ``(full_name, pitch_hand)`` where pitch_hand is ``"L"`` or ``"R"``.
        """
        try:
            data = self._mlb_api._api_get(f"people/{mlbam_id}", {})
            person = data.get("people", [{}])[0]
            name = person.get("fullName", f"Player {mlbam_id}")
            hand = person.get("pitchHand", {}).get("code", "R")
            return str(name), str(hand)
        except Exception as exc:
            logger.warning("_fetch_player_meta failed for %s: %s", mlbam_id, exc)
            return f"Player {mlbam_id}", "R"

    def _compute_days_rest(self, mlbam_id: int, game_date: str) -> int:
        """
        Estimate a pitcher's days since last start from recent game logs.

        Returns 5 (typical rotation rest) when the information cannot be
        determined.
        """
        try:
            gd = datetime.strptime(game_date, "%Y-%m-%d")
            start_date = (gd - timedelta(days=45)).strftime("%Y-%m-%d")
            url = (
                f"{_MLB_API_BASE}/people/{mlbam_id}/stats"
                f"?stats=gameLog&group=pitching"
                f"&startDate={start_date}&endDate={game_date}&sportId=1"
            )
            data = self._mlb_api._api_get(url)
            splits = data.get("stats", [{}])[0].get("splits", [])
            starts = [
                s for s in splits
                if s.get("stat", {}).get("gamesStarted", 0) == 1
                or float(s.get("stat", {}).get("inningsPitched", "0") or 0) >= 3.0
            ]
            if not starts:
                return 5
            last_date_str = starts[-1].get("date", "")
            if not last_date_str:
                return 5
            last_date = datetime.strptime(last_date_str, "%Y-%m-%d")
            return max(1, (gd - last_date).days)
        except Exception:
            return 5

    @staticmethod
    def _find_catcher_id(lineup: list[dict[str, Any]]) -> int | None:
        """Extract the catcher's MLBAM ID from a lineup list."""
        for player in lineup:
            pos = str(player.get("position", "")).upper()
            if pos in ("C", "CA"):
                mid = player.get("mlbam_id")
                return int(mid) if mid is not None else None
        return None
