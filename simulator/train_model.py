"""
train_model.py -- BaselineMLB Monte Carlo Simulator
====================================================
Training pipeline that builds the LightGBM matchup model from historical
Statcast data.

Classes
-------
TrainingDataBuilder
    Downloads PA-level Statcast data season-by-season and month-by-month,
    computes rolling pitcher/batter stats with zero lookahead bias, and
    produces the (X, y) training dataset aligned to FEATURE_COLUMNS.

ModelTrainer
    Wraps the LightGBM multi-class classifier, performs a temporal
    train/test split, evaluates calibration and Brier scores, and
    persists the trained model + metrics.

CLI
---
python -m simulation.train_model --help
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import sys
import time
from datetime import date
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import joblib
import numpy as np
import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# tqdm is optional but strongly encouraged
try:
    from tqdm import tqdm  # type: ignore
    _TQDM_AVAILABLE = True
except ImportError:
    _TQDM_AVAILABLE = False

    class tqdm:  # type: ignore[no-redef]
        """Minimal tqdm shim so the rest of the code works without the package."""
        def __init__(self, iterable=None, **kwargs):
            self._it = iterable

        def __iter__(self):
            return iter(self._it)

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def set_postfix(self, **kwargs):
            pass

        def update(self, n=1):
            pass

        def close(self):
            pass

# LightGBM -- required for training
try:
    import lightgbm as lgb  # type: ignore
    _LGBM_AVAILABLE = True
except ImportError:
    lgb = None  # type: ignore
    _LGBM_AVAILABLE = False

# sklearn helpers
try:
    from sklearn.metrics import (  # type: ignore
        brier_score_loss,
        classification_report,
        log_loss,
    )
    from sklearn.preprocessing import LabelEncoder  # type: ignore
    _SKLEARN_AVAILABLE = True
except ImportError:
    _SKLEARN_AVAILABLE = False

from simulator.config import (
    FEATURE_COLUMNS,
    LEAGUE_AVG_RATES,
    MODEL_OUTCOMES,
    OUTCOME_GROUPS,
    PARK_FACTORS,
    SimulationConfig,
    configure_logging,
)

# ---------------------------------------------------------------------------
# Module logger
# ---------------------------------------------------------------------------
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Statcast CSV base URL -- monthly chunks
_SAVANT_CSV_URL = (
    "https://baseballsavant.mlb.com/statcast_search/csv"
    "?all=true&hfGT=R%7C&hfSea={season}%7C"
    "&player_type=pitcher&type=details"
    "&game_date_gt={start}&game_date_lt={end}"
)

# Default seasons to train on
_DEFAULT_SEASONS: List[int] = [2021, 2022, 2023, 2024, 2025]

# Rolling stat defaults (fall back to league averages for small samples)
_REGRESSION_PA: int = 200  # minimum PA before trusting individual stats

# Statcast column name for batter/pitcher identifiers
_PITCHER_ID_COL = "pitcher"
_BATTER_ID_COL = "batter"
_DATE_COL = "game_date"
_EVENT_COL = "events"
_TEAM_HOME_COL = "home_team"
_INNING_TOPBOT_COL = "inning_topbot"
_STAND_COL = "stand"          # batter handedness
_P_THROWS_COL = "p_throws"    # pitcher handedness
_VENUE_COL = "venue_name"

# Pitch-level metrics used for rolling computations
_SWINGING_STRIKE_TYPE = "swinging_strike"
_ZONE_IN_TYPES = {"called_strike", "swinging_strike", "foul", "hit_into_play"}

# HTTP session settings
_REQUEST_TIMEOUT: int = 60
_MAX_RETRIES: int = 3
_BACKOFF_FACTOR: float = 2.0

# Default temperature when not available
_DEFAULT_TEMP_F: float = 72.0

# Reverse lookup: Statcast event string -> MODEL_OUTCOMES key
_EVENT_TO_OUTCOME: Dict[str, str] = {}
for _outcome, _events in OUTCOME_GROUPS.items():
    for _event in _events:
        _EVENT_TO_OUTCOME[_event] = _outcome

# ===========================================================================
#  Helper: build a requests Session with retry logic
# ===========================================================================


def _build_session() -> requests.Session:
    """Return a requests.Session with exponential back-off retries."""
    session = requests.Session()
    retry = Retry(
        total=_MAX_RETRIES,
        backoff_factor=_BACKOFF_FACTOR,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET"],
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


# ===========================================================================
#  Helper: month-chunk generator
# ===========================================================================


def _monthly_chunks(season: int) -> List[Tuple[str, str]]:
    """
    Return (start_date, end_date) pairs covering each calendar month of a
    regular MLB season (roughly April - October).

    Returns
    -------
    list of (start: str, end: str) in 'YYYY-MM-DD' format.
    """
    months = [
        (4, 1, 4, 30),
        (5, 1, 5, 31),
        (6, 1, 6, 30),
        (7, 1, 7, 31),
        (8, 1, 8, 31),
        (9, 1, 9, 30),
        (10, 1, 10, 15),  # post-season cutoff
    ]
    chunks = []
    today = date.today()
    for m_start, d_start, m_end, d_end in months:
        start = date(season, m_start, d_start)
        try:
            end = date(season, m_end, d_end)
        except ValueError:
            # Handle months that don't have that many days
            import calendar
            last_day = calendar.monthrange(season, m_end)[1]
            end = date(season, m_end, last_day)
        if start > today:
            break  # don't request future data
        if end > today:
            end = today
        chunks.append((str(start), str(end)))
    return chunks


# ===========================================================================
#  TrainingDataBuilder
# ===========================================================================


class TrainingDataBuilder:
    """
    Builds the (X, y) training dataset from historical Statcast data.

    Downloads PA-level Statcast CSVs season-by-season in monthly chunks
    (staying under the ~40K row per-query limit), then constructs feature
    vectors with zero lookahead bias -- rolling stats are computed from all
    games *prior* to each PA's game date only.

    Parameters
    ----------
    seasons : list[int] | None
        Calendar years to include.  Defaults to 2021-2025.
    cache_dir : str | Path | None
        Directory in which to cache downloaded CSVs.  Creates the directory
        if it does not exist.  ``None`` disables caching.
    sample_frac : float
        Fraction of PAs to retain (random sample, for rapid prototyping).
    """

    def __init__(
        self,
        seasons: Optional[List[int]] = None,
        cache_dir: Optional[str | Path] = "data/statcast_cache",
        sample_frac: float = 1.0,
    ) -> None:
        self.seasons: List[int] = seasons if seasons is not None else list(_DEFAULT_SEASONS)
        self.cache_dir: Optional[Path] = Path(cache_dir) if cache_dir else None
        self.sample_frac: float = float(sample_frac)
        self._session: requests.Session = _build_session()

        if self.cache_dir is not None:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            logger.info("Statcast CSV cache directory: %s", self.cache_dir)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def build_training_data(self) -> Tuple[pd.DataFrame, pd.Series]:
        """
        Download Statcast data for all seasons and build the training dataset.

        Returns
        -------
        X : pd.DataFrame
            Feature matrix with columns matching ``FEATURE_COLUMNS``.
        y : pd.Series
            Target labels (strings from ``MODEL_OUTCOMES``).
        """
        all_rows: List[pd.DataFrame] = []

        for season in self.seasons:
            logger.info("Processing season %d ...", season)
            season_df = self._load_season(season)
            if season_df is None or season_df.empty:
                logger.warning("No data for season %d -- skipping.", season)
                continue

            logger.info(
                "Season %d: %d pitch rows loaded. Building PA features ...",
                season,
                len(season_df),
            )
            season_rows = self._build_season_features(season_df, season)
            if season_rows:
                all_rows.extend(season_rows)
                logger.info(
                    "Season %d: %d PA feature rows built.", season, len(season_rows)
                )

        if not all_rows:
            raise RuntimeError(
                "No training rows were built. Check network access and season list."
            )

        full_df = pd.DataFrame(all_rows)

        # Sample fraction for rapid prototyping
        if self.sample_frac < 1.0:
            full_df = full_df.sample(
                frac=self.sample_frac, random_state=42
            ).reset_index(drop=True)
            logger.info(
                "Applied sample_frac=%.2f -> %d rows retained.",
                self.sample_frac,
                len(full_df),
            )

        logger.info("Total training rows: %d", len(full_df))

        # Ensure all feature columns are present; fill missing with 0
        for col in FEATURE_COLUMNS:
            if col not in full_df.columns:
                logger.warning("Feature column '%s' missing -- filling with 0.", col)
                full_df[col] = 0.0

        X = full_df[FEATURE_COLUMNS].astype(np.float32)
        y = full_df["outcome"].astype(str)

        # Drop rows where outcome is not a valid MODEL_OUTCOME
        valid_mask = y.isin(MODEL_OUTCOMES)
        if not valid_mask.all():
            dropped = (~valid_mask).sum()
            logger.warning("Dropping %d rows with unmapped outcomes.", dropped)
            X = X[valid_mask].reset_index(drop=True)
            y = y[valid_mask].reset_index(drop=True)

        return X, y

    # ------------------------------------------------------------------
    # Season loading (download + cache)
    # ------------------------------------------------------------------

    def _load_season(self, season: int) -> Optional[pd.DataFrame]:
        """
        Load all pitch-level Statcast data for a season, using disk cache
        when available.  Downloads month-by-month to stay under the 40K row
        query limit.
        """
        chunks = _monthly_chunks(season)
        if not chunks:
            logger.warning("No monthly chunks generated for season %d.", season)
            return None

        frames: List[pd.DataFrame] = []
        for start, end in tqdm(chunks, desc=f"Season {season} downloads", leave=False):
            df_chunk = self._load_chunk(season, start, end)
            if df_chunk is not None and not df_chunk.empty:
                frames.append(df_chunk)

        if not frames:
            return None

        combined = pd.concat(frames, ignore_index=True)

        # Ensure game_date is parsed
        if _DATE_COL in combined.columns:
            combined[_DATE_COL] = pd.to_datetime(combined[_DATE_COL], errors="coerce")

        # De-duplicate (same pitch can appear in overlapping date ranges)
        combined = combined.drop_duplicates().reset_index(drop=True)
        return combined

    def _load_chunk(
        self, season: int, start: str, end: str
    ) -> Optional[pd.DataFrame]:
        """
        Load a single monthly chunk, returning a DataFrame.
        Checks the cache first; downloads and caches if not found.
        """
        cache_path = self._chunk_cache_path(season, start, end)
        if cache_path is not None and cache_path.is_file():
            logger.debug("Cache hit: %s", cache_path)
            try:
                return pd.read_csv(cache_path, low_memory=False)
            except Exception as exc:
                logger.warning("Failed to read cache file %s: %s", cache_path, exc)

        url = _SAVANT_CSV_URL.format(season=season, start=start, end=end)
        logger.debug("Downloading: %s", url)

        for attempt in range(1, _MAX_RETRIES + 1):
            try:
                response = self._session.get(url, timeout=_REQUEST_TIMEOUT)
                response.raise_for_status()

                if not response.content or len(response.content) < 100:
                    logger.debug(
                        "Empty response for %s - %s (season %d).", start, end, season
                    )
                    return None

                from io import StringIO

                df = pd.read_csv(StringIO(response.text), low_memory=False)

                if df.empty:
                    return None

                # Cache successful download
                if cache_path is not None:
                    try:
                        df.to_csv(cache_path, index=False)
                        logger.debug("Cached to %s", cache_path)
                    except Exception as exc:
                        logger.warning("Failed to cache chunk: %s", exc)

                return df

            except Exception as exc:
                wait = _BACKOFF_FACTOR ** attempt
                logger.warning(
                    "Download failed (attempt %d/%d) for %s-%s season %d: %s. "
                    "Retrying in %.1fs ...",
                    attempt,
                    _MAX_RETRIES,
                    start,
                    end,
                    season,
                    exc,
                    wait,
                )
                time.sleep(wait)

        logger.error(
            "All %d download attempts failed for %s-%s season %d.",
            _MAX_RETRIES,
            start,
            end,
            season,
        )
        return None

    def _chunk_cache_path(
        self, season: int, start: str, end: str
    ) -> Optional[Path]:
        """Return deterministic cache file path for a chunk, or None if caching disabled."""
        if self.cache_dir is None:
            return None
        key = f"{season}_{start}_{end}"
        safe = hashlib.md5(key.encode()).hexdigest()[:12]
        return self.cache_dir / f"statcast_{season}_{start}_{end}_{safe}.csv"

    # ------------------------------------------------------------------
    # Feature building
    # ------------------------------------------------------------------

    def _build_season_features(
        self, season_df: pd.DataFrame, season: int
    ) -> List[dict]:
        """
        Iterate through every PA in a season (rows with non-null 'events')
        and build a feature-row dict for each.

        Anti-leak guarantee: rolling stats are computed using only prior-game
        data.  Same-game data is excluded.
        """
        if _EVENT_COL not in season_df.columns:
            logger.warning("'events' column missing from season data.")
            return []

        # Filter to PA-terminating rows only (events != NaN)
        pa_df = season_df[season_df[_EVENT_COL].notna()].copy()
        pa_df = pa_df.reset_index(drop=True)

        if pa_df.empty:
            return []

        # Ensure date column
        if _DATE_COL not in pa_df.columns:
            logger.warning("'game_date' column missing -- skipping season.")
            return []

        pa_df[_DATE_COL] = pd.to_datetime(pa_df[_DATE_COL], errors="coerce")
        pa_df = pa_df.dropna(subset=[_DATE_COL])
        pa_df = pa_df.sort_values(_DATE_COL).reset_index(drop=True)

        # Pre-compute per-pitcher and per-batter rolling lookup tables
        pitcher_stats_cache: Dict[str, Dict[str, dict]] = {}  # pitcher_id -> {date -> stats}
        batter_stats_cache: Dict[str, Dict[str, dict]] = {}

        # Build the caches in one pass through the full pitch data (for whiff%)
        pitcher_stats_cache = self._precompute_rolling_pitcher_stats(season_df)
        batter_stats_cache = self._precompute_rolling_batter_stats(season_df)

        rows: List[dict] = []
        disabled = not _TQDM_AVAILABLE
        pa_iter = tqdm(
            pa_df.itertuples(index=False),
            total=len(pa_df),
            desc=f"Season {season} PAs",
            disable=disabled,
            leave=False,
        )

        for row in pa_iter:
            try:
                outcome = self._map_event_to_outcome(getattr(row, _EVENT_COL, None))
                if outcome is None:
                    continue

                game_date = getattr(row, _DATE_COL, None)
                if pd.isna(game_date):
                    continue

                pitcher_id = str(getattr(row, _PITCHER_ID_COL, ""))
                batter_id = str(getattr(row, _BATTER_ID_COL, ""))

                # Rolling stats -- prior games only
                p_stats = self._get_cached_stats(
                    pitcher_stats_cache, pitcher_id, game_date, "pitcher"
                )
                b_stats = self._get_cached_stats(
                    batter_stats_cache, batter_id, game_date, "batter"
                )

                # Context features
                stand = str(getattr(row, _STAND_COL, "R"))
                p_throws = str(getattr(row, _P_THROWS_COL, "R"))
                platoon = 1.0 if (stand == "S" or stand != p_throws) else 0.0

                inning_topbot = str(getattr(row, _INNING_TOPBOT_COL, "Top"))
                is_home = 1.0 if inning_topbot == "Bot" else 0.0

                # Park factors
                venue = str(getattr(row, _VENUE_COL, "neutral"))
                pf = PARK_FACTORS.get(venue, PARK_FACTORS["neutral"])

                feature_row: dict = {
                    # Pitcher features
                    "pitcher_k_rate": p_stats.get("k_rate", LEAGUE_AVG_RATES["strikeout"]),
                    "pitcher_bb_rate": p_stats.get("bb_rate", LEAGUE_AVG_RATES["walk"]),
                    "pitcher_hr_rate": p_stats.get("hr_rate", LEAGUE_AVG_RATES["home_run"]),
                    "pitcher_whiff_pct": p_stats.get("whiff_pct", 0.248),
                    "pitcher_csw_pct": p_stats.get("csw_pct", 0.287),
                    "pitcher_zone_pct": p_stats.get("zone_pct", 0.470),
                    "pitcher_swstr_pct": p_stats.get("swstr_pct", 0.112),
                    "pitcher_avg_velo": p_stats.get("avg_velo", 93.5),
                    "pitcher_chase_rate": p_stats.get("chase_rate", 0.295),
                    "pitcher_iz_contact_pct": p_stats.get("iz_contact_pct", 0.845),
                    # Batter features
                    "batter_k_rate": b_stats.get("k_rate", LEAGUE_AVG_RATES["strikeout"]),
                    "batter_bb_rate": b_stats.get("bb_rate", LEAGUE_AVG_RATES["walk"]),
                    "batter_hr_rate": b_stats.get("hr_rate", LEAGUE_AVG_RATES["home_run"]),
                    "batter_xba": b_stats.get("xba", 0.249),
                    "batter_xslg": b_stats.get("xslg", 0.409),
                    "batter_barrel_pct": b_stats.get("barrel_pct", 0.080),
                    "batter_hard_hit_pct": b_stats.get("hard_hit_pct", 0.370),
                    "batter_chase_rate": b_stats.get("chase_rate", 0.295),
                    "batter_whiff_pct": b_stats.get("whiff_pct", 0.248),
                    "batter_contact_pct": b_stats.get("contact_pct", 0.770),
                    # Matchup context
                    "platoon_advantage": platoon,
                    "is_home": is_home,
                    "park_hr_factor": pf.get("hr", 1.0),
                    "park_k_factor": pf.get("k", 1.0),
                    "park_h_factor": pf.get("h", 1.0),
                    # Game-day context (neutral for historical training)
                    "umpire_k_factor": 1.0,
                    "catcher_framing_score": 0.0,
                    # Recent form
                    "pitcher_recent_k_rate": p_stats.get(
                        "recent_k_rate", p_stats.get("k_rate", LEAGUE_AVG_RATES["strikeout"])
                    ),
                    "batter_recent_ba": b_stats.get("recent_ba", b_stats.get("ba", 0.249)),
                    # Market / game total -- not available in training
                    "game_total_line": 0.0,
                    # Weather -- not available in training
                    "temp_f": _DEFAULT_TEMP_F,
                    "wind_speed_mph": 0.0,
                    "wind_out": 0.0,
                    # Target
                    "outcome": outcome,
                    # Metadata for temporal split
                    "game_date": game_date,
                }
                rows.append(feature_row)

            except Exception as exc:
                logger.debug("Skipping PA row due to error: %s", exc)
                continue

        return rows

    # ------------------------------------------------------------------
    # Rolling stat pre-computation
    # ------------------------------------------------------------------

    def _precompute_rolling_pitcher_stats(
        self, season_df: pd.DataFrame
    ) -> Dict[str, Dict[str, dict]]:
        """
        For each pitcher, pre-compute a dict keyed by unique game dates,
        where the value is the rolling stats computed from all *prior* games.

        Returns
        -------
        dict: pitcher_id (str) -> dict: date (pd.Timestamp) -> stats (dict)
        """
        cache: Dict[str, Dict] = {}

        if _PITCHER_ID_COL not in season_df.columns:
            return cache

        # Ensure dates are parsed
        df = season_df.copy()
        df[_DATE_COL] = pd.to_datetime(df.get(_DATE_COL, pd.NaT), errors="coerce")
        df = df.dropna(subset=[_DATE_COL])

        for pitcher_id, grp in df.groupby(_PITCHER_ID_COL):
            pitcher_id = str(pitcher_id)
            grp = grp.sort_values(_DATE_COL)
            unique_dates = sorted(grp[_DATE_COL].unique())
            cache[pitcher_id] = {}
            for game_date in unique_dates:
                prior = grp[grp[_DATE_COL] < game_date]
                stats = self._compute_rolling_pitcher_stats(
                    pitcher_id, game_date, prior
                )
                cache[pitcher_id][game_date] = stats

        return cache

    def _precompute_rolling_batter_stats(
        self, season_df: pd.DataFrame
    ) -> Dict[str, Dict[str, dict]]:
        """
        Same as _precompute_rolling_pitcher_stats but for batters.
        """
        cache: Dict[str, Dict] = {}

        if _BATTER_ID_COL not in season_df.columns:
            return cache

        df = season_df.copy()
        df[_DATE_COL] = pd.to_datetime(df.get(_DATE_COL, pd.NaT), errors="coerce")
        df = df.dropna(subset=[_DATE_COL])

        for batter_id, grp in df.groupby(_BATTER_ID_COL):
            batter_id = str(batter_id)
            grp = grp.sort_values(_DATE_COL)
            unique_dates = sorted(grp[_DATE_COL].unique())
            cache[batter_id] = {}
            for game_date in unique_dates:
                prior = grp[grp[_DATE_COL] < game_date]
                stats = self._compute_rolling_batter_stats(
                    batter_id, game_date, prior
                )
                cache[batter_id][game_date] = stats

        return cache

    def _get_cached_stats(
        self,
        cache: Dict[str, Dict],
        player_id: str,
        game_date: pd.Timestamp,
        role: str,
    ) -> dict:
        """
        Retrieve pre-computed rolling stats for player on game_date.
        Falls back to league-average defaults if the player/date is missing.
        """
        player_cache = cache.get(player_id, {})
        if not player_cache:
            return self._default_stats(role)

        # Find the most recent date strictly before game_date
        prior_dates = [d for d in player_cache if d < game_date]
        if not prior_dates:
            return self._default_stats(role)

        closest = max(prior_dates)
        return player_cache.get(closest, self._default_stats(role))

    def _default_stats(self, role: str) -> dict:
        """Return league-average default stats for a pitcher or batter."""
        if role == "pitcher":
            return {
                "k_rate": LEAGUE_AVG_RATES["strikeout"],
                "bb_rate": LEAGUE_AVG_RATES["walk"],
                "hr_rate": LEAGUE_AVG_RATES["home_run"],
                "whiff_pct": 0.248,
                "csw_pct": 0.287,
                "zone_pct": 0.470,
                "swstr_pct": 0.112,
                "avg_velo": 93.5,
                "chase_rate": 0.295,
                "iz_contact_pct": 0.845,
                "recent_k_rate": LEAGUE_AVG_RATES["strikeout"],
            }
        return {
            "k_rate": LEAGUE_AVG_RATES["strikeout"],
            "bb_rate": LEAGUE_AVG_RATES["walk"],
            "hr_rate": LEAGUE_AVG_RATES["home_run"],
            "xba": 0.249,
            "xslg": 0.409,
            "barrel_pct": 0.080,
            "hard_hit_pct": 0.370,
            "chase_rate": 0.295,
            "whiff_pct": 0.248,
            "contact_pct": 0.770,
            "ba": 0.249,
            "recent_ba": 0.249,
        }

    def _compute_rolling_pitcher_stats(
        self,
        pitcher_id: str,  # noqa: ARG002  (kept for API symmetry)
        game_date: pd.Timestamp,  # noqa: ARG002
        prior_data: pd.DataFrame,
    ) -> dict:
        """
        Compute a pitcher's rolling stats from all prior-game pitch data.

        Uses only rows in ``prior_data`` (which must already be filtered to
        games before ``game_date``).

        Returns
        -------
        dict with keys: k_rate, bb_rate, hr_rate, whiff_pct, csw_pct,
                        zone_pct, swstr_pct, avg_velo, chase_rate,
                        iz_contact_pct, recent_k_rate, sample_pa
        """
        lg = LEAGUE_AVG_RATES
        defaults = self._default_stats("pitcher")

        if prior_data.empty:
            return defaults

        # PA-level events
        pa_rows = prior_data[prior_data[_EVENT_COL].notna()]
        n_pa = len(pa_rows)

        if n_pa == 0:
            return defaults

        def _rate(event_list: List[str]) -> float:
            count = pa_rows[_EVENT_COL].isin(event_list).sum()
            raw = count / n_pa
            # Bayesian shrinkage toward league average
            # Use the first matching outcome key for the regression PA
            reg_pa = _REGRESSION_PA
            outcome_key = _map_event_key(event_list)
            lg_avg = lg.get(outcome_key, raw)
            return (raw * n_pa + lg_avg * reg_pa) / (n_pa + reg_pa)

        k_events = OUTCOME_GROUPS.get("strikeout", ["strikeout"])
        bb_events = OUTCOME_GROUPS.get("walk", ["walk"])
        hr_events = OUTCOME_GROUPS.get("home_run", ["home_run"])

        k_rate = _rate(k_events)
        bb_rate = _rate(bb_events)
        hr_rate = _rate(hr_events)

        # Pitch-level metrics from all pitches
        n_pitches = len(prior_data)

        whiff_pct = defaults["whiff_pct"]
        csw_pct = defaults["csw_pct"]
        zone_pct = defaults["zone_pct"]
        swstr_pct = defaults["swstr_pct"]
        avg_velo = defaults["avg_velo"]
        chase_rate = defaults["chase_rate"]
        iz_contact_pct = defaults["iz_contact_pct"]

        if n_pitches > 0:
            # Whiff %: swinging strikes / total pitches
            if "description" in prior_data.columns:
                swinging = prior_data["description"].isin(
                    {"swinging_strike", "swinging_strike_blocked", "foul_tip"}
                ).sum()
                whiff_pct = float(swinging / n_pitches) if n_pitches > 0 else defaults["whiff_pct"]
                swstr_pct = whiff_pct

                # CSW: called_strike + swinging_strike
                called_strike = prior_data["description"].isin({"called_strike"}).sum()
                csw_count = swinging + called_strike
                csw_pct = float(csw_count / n_pitches) if n_pitches > 0 else defaults["csw_pct"]

                # Zone %
                if "zone" in prior_data.columns:
                    in_zone = prior_data["zone"].between(1, 9, inclusive="both").sum()
                    zone_pct = float(in_zone / n_pitches)

                # Chase rate: swinging_strike on pitches outside zone
                if "zone" in prior_data.columns:
                    outside = prior_data[~prior_data["zone"].between(1, 9, inclusive="both")]
                    if len(outside) > 0:
                        chases = outside["description"].isin(
                            {"swinging_strike", "swinging_strike_blocked", "foul", "foul_tip"}
                        ).sum()
                        chase_rate = float(chases / len(outside))

                # In-zone contact %
                if "zone" in prior_data.columns:
                    in_zone_pitches = prior_data[prior_data["zone"].between(1, 9, inclusive="both")]
                    if len(in_zone_pitches) > 0:
                        iz_contact = in_zone_pitches["description"].isin(
                            {"hit_into_play", "foul", "foul_tip"}
                        ).sum()
                        iz_contact_pct = float(iz_contact / len(in_zone_pitches))

            # Average velocity
            for velo_col in ("release_speed", "start_speed", "effective_speed"):
                if velo_col in prior_data.columns:
                    velo_vals = pd.to_numeric(prior_data[velo_col], errors="coerce").dropna()
                    if len(velo_vals) > 0:
                        avg_velo = float(velo_vals.mean())
                    break

        # Recent K rate (last 14 calendar days before game_date -- within prior)
        recent_k_rate = k_rate
        if _DATE_COL in prior_data.columns:
            cutoff = game_date - pd.Timedelta(days=14)
            recent_pa = pa_rows[pa_rows[_DATE_COL] >= cutoff]
            if len(recent_pa) >= 10:
                recent_k_count = recent_pa[_EVENT_COL].isin(k_events).sum()
                recent_k_rate = float(recent_k_count / len(recent_pa))

        return {
            "k_rate": k_rate,
            "bb_rate": bb_rate,
            "hr_rate": hr_rate,
            "whiff_pct": whiff_pct,
            "csw_pct": csw_pct,
            "zone_pct": zone_pct,
            "swstr_pct": swstr_pct,
            "avg_velo": avg_velo,
            "chase_rate": chase_rate,
            "iz_contact_pct": iz_contact_pct,
            "recent_k_rate": recent_k_rate,
            "sample_pa": n_pa,
        }

    def _compute_rolling_batter_stats(
        self,
        batter_id: str,  # noqa: ARG002
        game_date: pd.Timestamp,  # noqa: ARG002
        prior_data: pd.DataFrame,
    ) -> dict:
        """
        Compute a batter's rolling stats from all prior-game plate appearance data.

        Returns
        -------
        dict with keys: k_rate, bb_rate, hr_rate, xba, xslg, barrel_pct,
                        hard_hit_pct, chase_rate, whiff_pct, contact_pct,
                        ba, recent_ba, sample_pa
        """
        lg = LEAGUE_AVG_RATES
        defaults = self._default_stats("batter")

        if prior_data.empty:
            return defaults

        pa_rows = prior_data[prior_data[_EVENT_COL].notna()]
        n_pa = len(pa_rows)

        if n_pa == 0:
            return defaults

        def _rate(event_list: List[str], outcome_key: str) -> float:
            count = pa_rows[_EVENT_COL].isin(event_list).sum()
            raw = count / n_pa
            lg_avg = lg.get(outcome_key, raw)
            return (raw * n_pa + lg_avg * _REGRESSION_PA) / (n_pa + _REGRESSION_PA)

        k_rate = _rate(OUTCOME_GROUPS.get("strikeout", ["strikeout"]), "strikeout")
        bb_rate = _rate(OUTCOME_GROUPS.get("walk", ["walk"]), "walk")
        hr_rate = _rate(OUTCOME_GROUPS.get("home_run", ["home_run"]), "home_run")

        # Batting average (hits / (PA - BB - HBP - SF - SB))
        hit_events = (
            OUTCOME_GROUPS.get("single", [])
            + OUTCOME_GROUPS.get("double", [])
            + OUTCOME_GROUPS.get("triple", [])
            + OUTCOME_GROUPS.get("home_run", [])
        )
        n_hits = pa_rows[_EVENT_COL].isin(hit_events).sum()
        ba = float(n_hits / n_pa) if n_pa > 0 else 0.249

        # Statcast metrics (from leaderboard columns if present)
        xba = defaults["xba"]
        xslg = defaults["xslg"]
        barrel_pct = defaults["barrel_pct"]
        hard_hit_pct = defaults["hard_hit_pct"]

        for col_name, default_key in [
            ("estimated_ba_using_speedangle", "xba"),
            ("estimated_slg_using_speedangle", "xslg"),
        ]:
            if col_name in prior_data.columns:
                vals = pd.to_numeric(pa_rows.get(col_name, pd.Series()), errors="coerce").dropna()
                if len(vals) > 0:
                    if default_key == "xba":
                        xba = float(vals.mean())
                    elif default_key == "xslg":
                        xslg = float(vals.mean())

        if "barrel" in prior_data.columns:
            barrel_vals = pd.to_numeric(pa_rows.get("barrel", pd.Series()), errors="coerce").fillna(0)
            if len(barrel_vals) > 0:
                barrel_pct = float(barrel_vals.mean())

        if "launch_speed" in prior_data.columns:
            ls = pd.to_numeric(pa_rows.get("launch_speed", pd.Series()), errors="coerce").dropna()
            if len(ls) > 0:
                hard_hit_pct = float((ls >= 95.0).mean())

        # Pitch-level metrics for batters
        n_pitches = len(prior_data)
        chase_rate = defaults["chase_rate"]
        whiff_pct = defaults["whiff_pct"]
        contact_pct = defaults["contact_pct"]

        if n_pitches > 0 and "description" in prior_data.columns:
            swinging = prior_data["description"].isin(
                {"swinging_strike", "swinging_strike_blocked", "foul_tip"}
            ).sum()
            whiff_pct = float(swinging / n_pitches)

            swings = prior_data["description"].isin(
                {"swinging_strike", "swinging_strike_blocked", "foul_tip",
                 "hit_into_play", "foul"}
            ).sum()
            contact = prior_data["description"].isin({"hit_into_play", "foul"}).sum()
            contact_pct = float(contact / swings) if swings > 0 else defaults["contact_pct"]

            if "zone" in prior_data.columns:
                outside = prior_data[~prior_data["zone"].between(1, 9, inclusive="both")]
                if len(outside) > 0:
                    chases = outside["description"].isin(
                        {"swinging_strike", "swinging_strike_blocked", "foul", "foul_tip"}
                    ).sum()
                    chase_rate = float(chases / len(outside))

        # Recent batting average (last 14 days)
        recent_ba = ba
        if _DATE_COL in prior_data.columns:
            cutoff = game_date - pd.Timedelta(days=14)
            recent_pa = pa_rows[pa_rows[_DATE_COL] >= cutoff]
            if len(recent_pa) >= 5:
                r_hits = recent_pa[_EVENT_COL].isin(hit_events).sum()
                recent_ba = float(r_hits / len(recent_pa))

        return {
            "k_rate": k_rate,
            "bb_rate": bb_rate,
            "hr_rate": hr_rate,
            "xba": xba,
            "xslg": xslg,
            "barrel_pct": barrel_pct,
            "hard_hit_pct": hard_hit_pct,
            "chase_rate": chase_rate,
            "whiff_pct": whiff_pct,
            "contact_pct": contact_pct,
            "ba": ba,
            "recent_ba": recent_ba,
            "sample_pa": n_pa,
        }

    # ------------------------------------------------------------------
    # Outcome mapping
    # ------------------------------------------------------------------

    def _map_event_to_outcome(self, event: Optional[str]) -> Optional[str]:
        """
        Map a Statcast ``events`` field value to one of the 8 ``MODEL_OUTCOMES``.

        Parameters
        ----------
        event : str | None
            Raw Statcast event string (e.g. ``'single'``, ``'field_out'``).

        Returns
        -------
        str | None
            One of ``MODEL_OUTCOMES``, or ``None`` if the event is not mapped.
        """
        if not event or not isinstance(event, str):
            return None
        event_lower = event.strip().lower()
        return _EVENT_TO_OUTCOME.get(event_lower, None)


# ===========================================================================
#  Helper (module-level)
# ===========================================================================


def _map_event_key(event_list: List[str]) -> str:
    """
    Given a list of Statcast event strings, return the MODEL_OUTCOME key
    that contains them (for regression toward league average).
    """
    if not event_list:
        return "out"
    for outcome, events in OUTCOME_GROUPS.items():
        if event_list[0] in events:
            return outcome
    return "out"


# ===========================================================================
#  ModelTrainer
# ===========================================================================


class ModelTrainer:
    """
    Trains, evaluates, and persists the LightGBM matchup model.

    Parameters
    ----------
    config : SimulationConfig
        Simulator configuration (provides MODEL_PATH, SCALER_PATH, etc.).
    output_dir : str | Path | None
        Override for the directory to save artefacts.  Defaults to the
        parent directory of ``config.MODEL_PATH``.
    """

    def __init__(
        self,
        config: SimulationConfig,
        output_dir: Optional[str | Path] = None,
    ) -> None:
        self.config = config
        self._model: Optional["lgb.Booster"] = None
        self._label_encoder: Optional["LabelEncoder"] = None
        self._feature_names: List[str] = list(FEATURE_COLUMNS)

        # Resolve output directory
        model_path = Path(config.MODEL_PATH)
        if output_dir is not None:
            self._output_dir = Path(output_dir)
        else:
            self._output_dir = model_path.parent

        self._output_dir.mkdir(parents=True, exist_ok=True)
        self._model_path = self._output_dir / model_path.name
        self._scaler_path = self._output_dir / Path(config.SCALER_PATH).name
        self._metrics_path = self._output_dir / "training_metrics.json"

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def train(self, X: pd.DataFrame, y: pd.Series) -> None:
        """
        Train the LightGBM multi-class classifier.

        Parameters
        ----------
        X : pd.DataFrame
            Feature matrix (columns == FEATURE_COLUMNS).
        y : pd.Series
            Outcome labels (strings from MODEL_OUTCOMES).
        """
        if not _LGBM_AVAILABLE:
            raise ImportError(
                "lightgbm is required for training.  "
                "Install with: pip install lightgbm"
            )
        if not _SKLEARN_AVAILABLE:
            raise ImportError(
                "scikit-learn is required for training.  "
                "Install with: pip install scikit-learn"
            )

        logger.info("Starting model training ...")

        # ---------------------------------------------------------------
        # 1. Label encoding
        # ---------------------------------------------------------------
        self._label_encoder = LabelEncoder()
        self._label_encoder.fit(MODEL_OUTCOMES)  # fit on canonical order
        y_enc = self._label_encoder.transform(y)

        logger.info("Class distribution:\n%s", y.value_counts().to_string())

        # ---------------------------------------------------------------
        # 2. Temporal train / test split (80 / 20 by game_date)
        # ---------------------------------------------------------------
        if "game_date" in X.columns:
            game_dates = pd.to_datetime(X["game_date"], errors="coerce")
            split_quantile = game_dates.quantile(0.80)
            train_mask = game_dates <= split_quantile
            test_mask = ~train_mask
            X_train = X[train_mask][FEATURE_COLUMNS].astype(np.float32)
            X_test = X[test_mask][FEATURE_COLUMNS].astype(np.float32)
            y_train = y_enc[train_mask.values]
            y_test = y_enc[test_mask.values]
            y_test_str = y[test_mask].reset_index(drop=True)
        else:
            # Fallback: sequential split
            split_idx = int(len(X) * 0.80)
            X_train = X.iloc[:split_idx][FEATURE_COLUMNS].astype(np.float32)
            X_test = X.iloc[split_idx:][FEATURE_COLUMNS].astype(np.float32)
            y_train = y_enc[:split_idx]
            y_test = y_enc[split_idx:]
            y_test_str = y.iloc[split_idx:].reset_index(drop=True)

        logger.info(
            "Temporal split -> train: %d rows | test: %d rows",
            len(X_train),
            len(X_test),
        )

        # ---------------------------------------------------------------
        # 3. LightGBM dataset
        # ---------------------------------------------------------------
        lgb_train = lgb.Dataset(
            X_train,
            label=y_train,
            feature_name=FEATURE_COLUMNS,
            free_raw_data=False,
        )
        lgb_eval = lgb.Dataset(
            X_test,
            label=y_test,
            feature_name=FEATURE_COLUMNS,
            reference=lgb_train,
            free_raw_data=False,
        )

        # ---------------------------------------------------------------
        # 4. Training parameters
        # ---------------------------------------------------------------
        params = {
            "objective": "multiclass",
            "num_class": 8,
            "metric": "multi_logloss",
            "learning_rate": 0.05,
            "num_leaves": 63,
            "max_depth": 7,
            "min_child_samples": 100,
            "subsample": 0.8,
            "colsample_bytree": 0.8,
            "reg_alpha": 0.1,
            "reg_lambda": 1.0,
            "verbose": -1,
            "num_threads": -1,
        }

        callbacks = [
            lgb.early_stopping(stopping_rounds=50, verbose=True),
            lgb.log_evaluation(period=50),
        ]

        logger.info("Training LightGBM with params:\n%s", json.dumps(params, indent=2))

        self._model = lgb.train(
            params,
            lgb_train,
            num_boost_round=500,
            valid_sets=[lgb_train, lgb_eval],
            valid_names=["train", "eval"],
            callbacks=callbacks,
        )

        best_iter = self._model.best_iteration
        logger.info("Training complete. Best iteration: %d", best_iter)

        # ---------------------------------------------------------------
        # 5. Save model (native LightGBM .txt format) + metadata
        # ---------------------------------------------------------------
        self._model.save_model(str(self._model_path))
        logger.info("Model saved to %s", self._model_path)

        # Save label encoder via joblib (no scaler needed for tree models,
        # but we persist it for the pipeline interface)
        joblib.dump(self._label_encoder, str(self._scaler_path))
        logger.info("Label encoder saved to %s", self._scaler_path)

        # ---------------------------------------------------------------
        # 6. Evaluate
        # ---------------------------------------------------------------
        metrics = self.evaluate(X_test, y_test_str)
        self._save_metrics(metrics)

        # Feature importance
        fi_df = self.get_feature_importance()
        if not fi_df.empty:
            logger.info("Top 10 features by gain:\n%s", fi_df.head(10).to_string(index=False))

    def evaluate(self, X_test: pd.DataFrame, y_test: pd.Series) -> dict:
        """
        Evaluate the trained model on the hold-out test set.

        Computes multi-class log loss, per-class Brier scores, calibration
        summary, and sklearn classification report.

        Parameters
        ----------
        X_test : pd.DataFrame
            Feature matrix (columns must match FEATURE_COLUMNS).
        y_test : pd.Series
            True outcome labels (strings from MODEL_OUTCOMES).

        Returns
        -------
        dict
            Metrics dictionary suitable for JSON serialisation.
        """
        if self._model is None:
            raise RuntimeError("No trained model available.  Call train() first.")
        if not _SKLEARN_AVAILABLE:
            raise ImportError("scikit-learn is required for evaluation.")

        # Ensure correct feature subset
        if isinstance(X_test, pd.DataFrame) and "game_date" in X_test.columns:
            X_eval = X_test[FEATURE_COLUMNS].astype(np.float32)
        elif isinstance(X_test, pd.DataFrame):
            X_eval = X_test.reindex(columns=FEATURE_COLUMNS, fill_value=0.0).astype(np.float32)
        else:
            X_eval = np.asarray(X_test, dtype=np.float32)

        logger.info("Evaluating model on %d test samples ...", len(X_eval))

        # Predict probabilities -- shape: (n_samples, n_classes)
        raw_probs: np.ndarray = self._model.predict(X_eval)

        # Map string labels to integer indices
        le = self._label_encoder
        if le is None:
            le = LabelEncoder()
            le.fit(MODEL_OUTCOMES)

        # Re-index probabilities to canonical MODEL_OUTCOMES order
        class_order = list(le.classes_)
        ordered_probs = np.zeros((len(raw_probs), len(MODEL_OUTCOMES)), dtype=np.float64)
        for i, outcome in enumerate(MODEL_OUTCOMES):
            if outcome in class_order:
                src_idx = class_order.index(outcome)
                ordered_probs[:, i] = raw_probs[:, src_idx]

        # Predicted labels
        pred_idx = np.argmax(ordered_probs, axis=1)
        pred_labels = [MODEL_OUTCOMES[i] for i in pred_idx]

        # One-hot encode true labels
        y_test_arr = np.array(y_test.tolist())
        y_onehot = np.zeros_like(ordered_probs)
        for i, lbl in enumerate(y_test_arr):
            if lbl in MODEL_OUTCOMES:
                y_onehot[i, MODEL_OUTCOMES.index(lbl)] = 1.0

        # Multi-class log loss
        ll = float(log_loss(y_test_arr, ordered_probs, labels=MODEL_OUTCOMES))
        logger.info("Multi-class log loss: %.5f", ll)

        # Per-class Brier scores
        brier_scores: dict = {}
        for i, outcome in enumerate(MODEL_OUTCOMES):
            brier_scores[outcome] = float(
                brier_score_loss(y_onehot[:, i], ordered_probs[:, i])
            )

        # Calibration: for each outcome, compare predicted prob vs actual freq
        # in 10 decile bins
        calibration: dict = {}
        for i, outcome in enumerate(MODEL_OUTCOMES):
            probs_i = ordered_probs[:, i]
            actual_i = y_onehot[:, i]
            try:
                bins = np.percentile(probs_i, np.linspace(0, 100, 11))
                bins = np.unique(bins)
                bin_means_pred = []
                bin_means_actual = []
                for lo, hi in zip(bins[:-1], bins[1:]):
                    mask = (probs_i >= lo) & (probs_i < hi)
                    if mask.sum() > 0:
                        bin_means_pred.append(float(probs_i[mask].mean()))
                        bin_means_actual.append(float(actual_i[mask].mean()))
                calibration[outcome] = {
                    "predicted": bin_means_pred,
                    "actual": bin_means_actual,
                }
            except Exception:
                calibration[outcome] = {}

        # Classification report
        report = classification_report(
            y_test_arr, pred_labels, labels=MODEL_OUTCOMES, output_dict=True, zero_division=0
        )
        print("\n=== Classification Report ===")
        print(
            classification_report(
                y_test_arr, pred_labels, labels=MODEL_OUTCOMES, zero_division=0
            )
        )

        metrics = {
            "n_test_samples": int(len(y_test)),
            "multi_class_log_loss": ll,
            "brier_scores": brier_scores,
            "calibration": calibration,
            "classification_report": report,
        }

        logger.info("Brier scores per outcome: %s", brier_scores)
        return metrics

    def get_feature_importance(self) -> pd.DataFrame:
        """
        Return a DataFrame of feature importances sorted by gain (descending).

        Returns
        -------
        pd.DataFrame
            Columns: ``feature``, ``importance_gain``, ``importance_split``
        """
        if self._model is None:
            logger.warning("No trained model available for feature importance.")
            return pd.DataFrame(columns=["feature", "importance_gain", "importance_split"])

        gain_vals: np.ndarray = self._model.feature_importance(importance_type="gain")
        split_vals: np.ndarray = self._model.feature_importance(importance_type="split")
        names: List[str] = self._model.feature_name()

        df = pd.DataFrame(
            {
                "feature": names,
                "importance_gain": gain_vals.astype(float),
                "importance_split": split_vals.astype(float),
            }
        ).sort_values("importance_gain", ascending=False).reset_index(drop=True)

        return df

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _save_metrics(self, metrics: dict) -> None:
        """Persist evaluation metrics as JSON."""
        try:
            with open(self._metrics_path, "w", encoding="utf-8") as fh:
                json.dump(metrics, fh, indent=2, default=_json_serialisable)
            logger.info("Metrics saved to %s", self._metrics_path)
        except Exception as exc:
            logger.warning("Could not save metrics: %s", exc)


# ===========================================================================
#  JSON serialisation helper
# ===========================================================================


def _json_serialisable(obj):
    """Fallback JSON serialiser for numpy scalars and pandas types."""
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        return float(obj)
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    if isinstance(obj, pd.Timestamp):
        return str(obj)
    return str(obj)


# ===========================================================================
#  Command-line interface
# ===========================================================================


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="train_model",
        description="Build and train the BaselineMLB LightGBM matchup model.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--seasons",
        nargs="+",
        type=int,
        default=_DEFAULT_SEASONS,
        metavar="YEAR",
        help="Seasons to include in training (e.g. 2021 2022 2023 2024 2025).",
    )
    parser.add_argument(
        "--output-dir",
        default="models/",
        metavar="DIR",
        help="Directory in which to save the trained model and metrics.",
    )
    parser.add_argument(
        "--cache-dir",
        default="data/statcast_cache",
        metavar="DIR",
        help="Directory for caching downloaded Statcast CSVs.",
    )
    parser.add_argument(
        "--evaluate-only",
        action="store_true",
        default=False,
        help="Skip training; load the existing model and evaluate it.",
    )
    parser.add_argument(
        "--sample-frac",
        type=float,
        default=1.0,
        metavar="FRAC",
        help=(
            "Fraction of training PAs to use (0 < FRAC <= 1). "
            "Values < 1 enable rapid smoke-testing."
        ),
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging verbosity.",
    )
    parser.add_argument(
        "--log-file",
        default=None,
        metavar="FILE",
        help="Optional path to write log output to a file.",
    )
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    """
    Entry point for the training pipeline.

    Returns 0 on success, 1 on failure.
    """
    parser = _build_arg_parser()
    args = parser.parse_args(argv)

    # Configure logging
    log_level = getattr(logging, args.log_level.upper(), logging.INFO)
    configure_logging(level=log_level, log_file=args.log_file)

    logger.info("BaselineMLB -- Training Pipeline")
    logger.info("Seasons: %s", args.seasons)
    logger.info("Output dir: %s", args.output_dir)
    logger.info("Cache dir: %s", args.cache_dir)
    logger.info("Sample fraction: %.2f", args.sample_frac)

    if not _LGBM_AVAILABLE:
        logger.error(
            "lightgbm is not installed. Install with: pip install lightgbm"
        )
        return 1

    if not _SKLEARN_AVAILABLE:
        logger.error(
            "scikit-learn is not installed. Install with: pip install scikit-learn"
        )
        return 1

    cfg = SimulationConfig(
        MODEL_PATH=str(Path(args.output_dir) / "matchup_model.txt"),
        SCALER_PATH=str(Path(args.output_dir) / "feature_scaler.joblib"),
    )

    trainer = ModelTrainer(config=cfg, output_dir=args.output_dir)

    # ------------------------------------------------------------------
    # Evaluate-only mode: load existing model and evaluate on cached data
    # ------------------------------------------------------------------
    if args.evaluate_only:
        model_path = Path(args.output_dir) / "matchup_model.txt"
        if not model_path.is_file():
            logger.error("No model found at %s. Run without --evaluate-only first.", model_path)
            return 1

        logger.info("Evaluate-only mode: loading model from %s", model_path)
        try:
            trainer._model = lgb.Booster(model_file=str(model_path))
        except Exception as exc:
            logger.error("Failed to load model: %s", exc)
            return 1

        scaler_path = Path(args.output_dir) / "feature_scaler.joblib"
        if scaler_path.is_file():
            try:
                trainer._label_encoder = joblib.load(str(scaler_path))
            except Exception as exc:
                logger.warning("Could not load label encoder: %s", exc)

        logger.info("Building evaluation dataset ...")
        builder = TrainingDataBuilder(
            seasons=args.seasons,
            cache_dir=args.cache_dir,
            sample_frac=min(args.sample_frac, 0.2),  # use a small fraction for eval-only
        )
        try:
            X, y = builder.build_training_data()
        except Exception as exc:
            logger.error("Failed to build evaluation data: %s", exc)
            return 1

        metrics = trainer.evaluate(X, y)
        trainer._save_metrics(metrics)
        logger.info("Evaluation complete.")
        return 0

    # ------------------------------------------------------------------
    # Full training pipeline
    # ------------------------------------------------------------------

    # 1. Build training data
    logger.info("Step 1/3 -- Building training dataset ...")
    builder = TrainingDataBuilder(
        seasons=args.seasons,
        cache_dir=args.cache_dir,
        sample_frac=args.sample_frac,
    )

    try:
        X, y = builder.build_training_data()
    except Exception as exc:
        logger.error("Failed to build training data: %s", exc)
        return 1

    logger.info("Dataset shape: %s | Target classes: %s", X.shape, sorted(y.unique()))

    # 2. Train model
    logger.info("Step 2/3 -- Training LightGBM model ...")
    try:
        trainer.train(X, y)
    except Exception as exc:
        logger.error("Training failed: %s", exc, exc_info=True)
        return 1

    # 3. Feature importance report
    logger.info("Step 3/3 -- Saving feature importance report ...")
    fi_df = trainer.get_feature_importance()
    fi_path = Path(args.output_dir) / "feature_importance.csv"
    try:
        fi_df.to_csv(fi_path, index=False)
        logger.info("Feature importance saved to %s", fi_path)
    except Exception as exc:
        logger.warning("Could not save feature importance: %s", exc)

    logger.info("Training pipeline complete. Model artefacts in: %s", args.output_dir)
    return 0


if __name__ == "__main__":
    sys.exit(main())
