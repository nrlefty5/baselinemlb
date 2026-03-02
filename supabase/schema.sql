-- ============================================================
-- Baseline MLB — Master Schema
-- ============================================================

-- 1. PLAYERS
CREATE TABLE IF NOT EXISTS players (
  id            BIGSERIAL PRIMARY KEY,
  mlbam_id      INT UNIQUE NOT NULL,
  full_name     TEXT NOT NULL,
  team          TEXT,
  position      TEXT,
  bats          CHAR(1),
  throws        CHAR(1),
  active        BOOLEAN DEFAULT TRUE,
  updated_at    TIMESTAMPTZ DEFAULT NOW()
);

-- 2. GAMES
CREATE TABLE IF NOT EXISTS games (
  id                        BIGSERIAL PRIMARY KEY,
  game_pk                   INT UNIQUE NOT NULL,
  game_date                 DATE NOT NULL,
  game_time                 TEXT,
  home_team                 TEXT NOT NULL,
  away_team                 TEXT NOT NULL,
  venue                     TEXT,
  status                    TEXT,
  home_score                INT,
  away_score                INT,
  home_probable_pitcher_id  INT,
  home_probable_pitcher     TEXT,
  away_probable_pitcher_id  INT,
  away_probable_pitcher     TEXT,
  created_at                TIMESTAMPTZ DEFAULT NOW()
);

-- 3. PROPS (from The Odds API)
CREATE TABLE IF NOT EXISTS props (
  id              BIGSERIAL PRIMARY KEY,
  external_id     TEXT UNIQUE,
  source          TEXT NOT NULL,
  game_pk         INT REFERENCES games(game_pk),
  mlbam_id        INT REFERENCES players(mlbam_id),
  player_name     TEXT NOT NULL,
  stat_type       TEXT NOT NULL,
  line            NUMERIC(5,1) NOT NULL,
  over_odds       INT,
  under_odds      INT,
  fetched_at      TIMESTAMPTZ DEFAULT NOW(),
  game_date       DATE
);

CREATE INDEX IF NOT EXISTS props_game_date_idx ON props(game_date);
CREATE INDEX IF NOT EXISTS props_mlbam_idx     ON props(mlbam_id);
CREATE INDEX IF NOT EXISTS props_stat_idx      ON props(stat_type);

-- 4. STATCAST (pitch-level)
CREATE TABLE IF NOT EXISTS statcast_pitches (
  id              BIGSERIAL PRIMARY KEY,
  game_pk         INT,
  game_date       DATE,
  pitcher_id      INT,
  batter_id       INT,
  inning          INT,
  pitch_type      TEXT,
  release_speed   NUMERIC(5,2),
  pfx_x           NUMERIC(6,3),
  pfx_z           NUMERIC(6,3),
  plate_x         NUMERIC(6,3),
  plate_z         NUMERIC(6,3),
  description     TEXT,
  zone            INT,
  estimated_ba    NUMERIC(5,3),
  estimated_woba  NUMERIC(5,3),
  launch_speed    NUMERIC(5,2),
  launch_angle    NUMERIC(5,2),
  hit_distance    INT,
  events          TEXT,
  fetched_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS statcast_pitcher_date_idx ON statcast_pitches(pitcher_id, game_date);
CREATE INDEX IF NOT EXISTS statcast_batter_date_idx  ON statcast_pitches(batter_id, game_date);

-- 5. UMPIRE FRAMING COMPOSITE
CREATE TABLE IF NOT EXISTS umpire_framing (
  id                  BIGSERIAL PRIMARY KEY,
  game_pk             INT REFERENCES games(game_pk),
  game_date           DATE NOT NULL,
  umpire_id           INT,
  umpire_name         TEXT,
  catcher_id          INT REFERENCES players(mlbam_id),
  catcher_name        TEXT,
  total_pitches       INT,
  called_strikes      INT,
  extra_strikes       NUMERIC(5,2),
  framing_runs        NUMERIC(6,3),
  strike_rate         NUMERIC(5,4),
  composite_score     NUMERIC(6,3),
  computed_at         TIMESTAMPTZ DEFAULT NOW(),
  UNIQUE (game_pk, umpire_id, catcher_id)
);

CREATE INDEX IF NOT EXISTS framing_date_idx ON umpire_framing(game_date);
CREATE INDEX IF NOT EXISTS framing_ump_idx  ON umpire_framing(umpire_id);

-- 6. PROJECTIONS (model output)
CREATE TABLE IF NOT EXISTS projections (
  id              BIGSERIAL PRIMARY KEY,
  game_date       DATE NOT NULL,
  game_pk         INT,
  mlbam_id        INT REFERENCES players(mlbam_id),
  player_name     TEXT NOT NULL,
  stat_type       TEXT NOT NULL,
  projection      NUMERIC(6,2) NOT NULL,
  confidence      NUMERIC(4,3),
  model_version   TEXT,
  features        JSONB,
  created_at      TIMESTAMPTZ DEFAULT NOW(),
  UNIQUE (game_date, mlbam_id, stat_type)
);

CREATE INDEX IF NOT EXISTS proj_date_player_idx ON projections(game_date, mlbam_id);
CREATE INDEX IF NOT EXISTS proj_stat_idx        ON projections(stat_type);

-- 7. PICKS (model vs line)
CREATE TABLE IF NOT EXISTS picks (
  id              BIGSERIAL PRIMARY KEY,
  game_date       DATE NOT NULL,
  game_pk         INT,
  prop_id         BIGINT REFERENCES props(id),
  projection_id   BIGINT REFERENCES projections(id),
  mlbam_id        INT,
  player_name     TEXT NOT NULL,
  stat_type       TEXT NOT NULL,
  line            NUMERIC(5,1),
  projection      NUMERIC(6,2),
  edge            NUMERIC(6,3),
  direction       TEXT,
  grade           TEXT,
  published       BOOLEAN DEFAULT FALSE,
  result          TEXT,
  actual_value    NUMERIC(6,2),
  created_at      TIMESTAMPTZ DEFAULT NOW(),
  UNIQUE (game_date, mlbam_id, stat_type)
);

CREATE INDEX IF NOT EXISTS picks_date_idx      ON picks(game_date);
CREATE INDEX IF NOT EXISTS picks_player_idx    ON picks(mlbam_id);
CREATE INDEX IF NOT EXISTS picks_published_idx ON picks(published);

-- 8. ACCURACY DASHBOARD (materialized summary)
CREATE TABLE IF NOT EXISTS accuracy_summary (
  id              BIGSERIAL PRIMARY KEY,
  period          TEXT NOT NULL,
  stat_type       TEXT,
  total_picks     INT DEFAULT 0,
  hits            INT DEFAULT 0,
  misses          INT DEFAULT 0,
  pushes          INT DEFAULT 0,
  hit_rate        NUMERIC(5,4),
  avg_edge        NUMERIC(6,3),
  avg_clv         NUMERIC(6,3) DEFAULT NULL,
  updated_at      TIMESTAMPTZ DEFAULT NOW(),
  UNIQUE (period, stat_type)
);

-- 9. CLV TRACKING
CREATE TABLE IF NOT EXISTS clv_tracking (
  id              BIGSERIAL PRIMARY KEY,
  game_date       DATE NOT NULL,
  player_name     TEXT NOT NULL,
  market          TEXT NOT NULL,
  opening_price   INTEGER,
  closing_price   INTEGER,
  opening_line    NUMERIC,
  closing_line    NUMERIC,
  price_movement  INTEGER,
  clv_percent     NUMERIC,
  calculated_at   TIMESTAMPTZ DEFAULT NOW(),
  UNIQUE (game_date, player_name, market)
);

CREATE INDEX IF NOT EXISTS idx_clv_game_date ON clv_tracking(game_date);
CREATE INDEX IF NOT EXISTS idx_clv_player    ON clv_tracking(player_name);

-- 10. EMAIL SUBSCRIBERS
CREATE TABLE IF NOT EXISTS email_subscribers (
  id              BIGSERIAL PRIMARY KEY,
  email           TEXT NOT NULL UNIQUE,
  source          TEXT DEFAULT 'website',
  subscribed_at   TIMESTAMPTZ DEFAULT NOW(),
  unsubscribed    BOOLEAN DEFAULT FALSE
);

-- 11. PITCHER OVERRIDES
CREATE TABLE IF NOT EXISTS pitcher_overrides (
  id              BIGSERIAL PRIMARY KEY,
  game_pk         INT NOT NULL REFERENCES games(game_pk),
  game_date       DATE NOT NULL,
  side            TEXT NOT NULL CHECK (side IN ('home', 'away')),
  pitcher_id      INT NOT NULL,
  pitcher_name    TEXT,
  created_at      TIMESTAMPTZ DEFAULT NOW(),
  UNIQUE (game_pk, side)
);

CREATE INDEX IF NOT EXISTS overrides_date_idx ON pitcher_overrides(game_date);

-- ============================================================
-- 12. SIMULATION RESULTS (Monte Carlo)
-- ============================================================
CREATE TABLE IF NOT EXISTS simulation_results (
  id                BIGSERIAL PRIMARY KEY,
  game_id           INT NOT NULL,
  simulation_date   DATE NOT NULL,
  player_id         INT NOT NULL,
  player_name       TEXT NOT NULL,
  team              TEXT,
  prop_type         TEXT NOT NULL
                      CHECK (prop_type IN ('K','H','TB','HR','R','RBI','BB')),
  sportsbook_line   NUMERIC(5,1) NOT NULL,
  simulated_mean    NUMERIC(8,4) NOT NULL,
  simulated_median  NUMERIC(8,4) NOT NULL,
  p_over            NUMERIC(6,5) NOT NULL,
  p_under           NUMERIC(6,5) NOT NULL,
  edge_pct          NUMERIC(7,4),
  kelly_stake       NUMERIC(6,4),
  confidence_tier   TEXT CHECK (confidence_tier IN ('A','B','C','D')),
  distribution_json JSONB,
  created_at        TIMESTAMPTZ DEFAULT NOW(),
  UNIQUE (simulation_date, game_id, player_id, prop_type)
);

CREATE INDEX IF NOT EXISTS idx_sim_results_date        ON simulation_results(simulation_date);
CREATE INDEX IF NOT EXISTS idx_sim_results_player      ON simulation_results(player_id);
CREATE INDEX IF NOT EXISTS idx_sim_results_game        ON simulation_results(game_id);
CREATE INDEX IF NOT EXISTS idx_sim_results_date_player ON simulation_results(simulation_date, player_id);
CREATE INDEX IF NOT EXISTS idx_sim_results_date_tier   ON simulation_results(simulation_date, confidence_tier);
CREATE INDEX IF NOT EXISTS idx_sim_results_prop_type   ON simulation_results(prop_type);

-- ============================================================
-- 13. SIMULATION EXPLANATIONS (SHAP values)
-- ============================================================
CREATE TABLE IF NOT EXISTS simulation_explanations (
  id                  BIGSERIAL PRIMARY KEY,
  result_id           BIGINT NOT NULL
                        REFERENCES simulation_results(id)
                        ON DELETE CASCADE,
  feature_name        TEXT NOT NULL,
  shap_value          NUMERIC(10,6) NOT NULL,
  direction           TEXT NOT NULL
                        CHECK (direction IN ('positive','negative')),
  human_readable_text TEXT,
  UNIQUE (result_id, feature_name)
);

CREATE INDEX IF NOT EXISTS idx_sim_explanations_result ON simulation_explanations(result_id);

-- ============================================================
-- 14. BACKTEST RESULTS
-- ============================================================
CREATE TABLE IF NOT EXISTS backtest_results (
  id                  BIGSERIAL PRIMARY KEY,
  date                DATE NOT NULL,
  prop_type           TEXT NOT NULL
                        CHECK (prop_type IN ('K','H','TB','HR','R','RBI','BB','ALL')),
  total_predictions   INT NOT NULL DEFAULT 0,
  correct_predictions INT NOT NULL DEFAULT 0,
  accuracy_pct        NUMERIC(6,3),
  profit_loss         NUMERIC(10,2),
  roi_pct             NUMERIC(7,3),
  avg_edge            NUMERIC(7,4),
  tier_a_roi          NUMERIC(7,3),
  tier_b_roi          NUMERIC(7,3),
  tier_c_roi          NUMERIC(7,3),
  created_at          TIMESTAMPTZ DEFAULT NOW(),
  UNIQUE (date, prop_type)
);

CREATE INDEX IF NOT EXISTS idx_backtest_date      ON backtest_results(date);
CREATE INDEX IF NOT EXISTS idx_backtest_prop_type ON backtest_results(prop_type);

-- ============================================================
-- 15. MODEL ARTIFACTS
-- ============================================================
CREATE TABLE IF NOT EXISTS model_artifacts (
  id                      BIGSERIAL PRIMARY KEY,
  model_version           TEXT NOT NULL UNIQUE,
  trained_date            DATE NOT NULL,
  training_samples        INT,
  log_loss                NUMERIC(8,6),
  accuracy_vs_baseline    NUMERIC(7,4),
  feature_importance_json JSONB,
  model_path              TEXT,
  is_active               BOOLEAN DEFAULT FALSE,
  created_at              TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_model_active ON model_artifacts(is_active) WHERE is_active = TRUE;

-- ============================================================
-- 16. PLAYER ROLLING STATS (14-day windows)
-- ============================================================
CREATE TABLE IF NOT EXISTS player_rolling_stats (
  id              BIGSERIAL PRIMARY KEY,
  player_id       INT NOT NULL,
  stat_date       DATE NOT NULL,
  k_rate_14d      NUMERIC(6,4),
  bb_rate_14d     NUMERIC(6,4),
  xba_14d         NUMERIC(6,4),
  xslg_14d        NUMERIC(6,4),
  barrel_rate_14d NUMERIC(6,4),
  chase_rate_14d  NUMERIC(6,4),
  whiff_rate_14d  NUMERIC(6,4),
  exit_velo_14d   NUMERIC(6,2),
  hard_hit_14d    NUMERIC(6,4),
  swstr_14d       NUMERIC(6,4),
  csw_14d         NUMERIC(6,4),
  zone_14d        NUMERIC(6,4),
  created_at      TIMESTAMPTZ DEFAULT NOW(),
  UNIQUE (player_id, stat_date)
);

CREATE INDEX IF NOT EXISTS idx_rolling_stats_player      ON player_rolling_stats(player_id);
CREATE INDEX IF NOT EXISTS idx_rolling_stats_date        ON player_rolling_stats(stat_date);
CREATE INDEX IF NOT EXISTS idx_rolling_stats_player_date ON player_rolling_stats(player_id, stat_date);

-- ============================================================
-- 17. SIMULATION RESULTS (run_daily.py output)
-- ============================================================
CREATE TABLE IF NOT EXISTS sim_results (
  id                BIGSERIAL PRIMARY KEY,
  game_date         DATE        NOT NULL,
  game_pk           INT         REFERENCES games(game_pk),
  player_id         INT,
  player_name       TEXT        NOT NULL,
  stat_type         TEXT        NOT NULL,
  sim_mean          NUMERIC(6,2),
  sim_median        NUMERIC(6,2),
  sim_std           NUMERIC(6,3),
  sim_p10           NUMERIC(6,2),
  sim_p25           NUMERIC(6,2),
  sim_p75           NUMERIC(6,2),
  sim_p90           NUMERIC(6,2),
  n_simulations     INT         DEFAULT 3000,
  model_version     TEXT,
  created_at        TIMESTAMPTZ DEFAULT NOW(),
  UNIQUE (game_date, game_pk, player_id, stat_type)
);

CREATE INDEX IF NOT EXISTS sim_results_date_idx   ON sim_results(game_date);
CREATE INDEX IF NOT EXISTS sim_results_player_idx ON sim_results(player_id);

-- ============================================================
-- 18. SIMULATION PROP EDGES
-- ============================================================
CREATE TABLE IF NOT EXISTS sim_prop_edges (
  id                  BIGSERIAL PRIMARY KEY,
  game_date           DATE        NOT NULL,
  game_pk             INT,
  player_id           INT,
  player_name         TEXT        NOT NULL,
  stat_type           TEXT        NOT NULL,
  prop_line           NUMERIC(5,1),
  over_prob           NUMERIC(5,4),
  under_prob          NUMERIC(5,4),
  book_implied_over   NUMERIC(5,4),
  book_implied_under  NUMERIC(5,4),
  edge_pct            NUMERIC(6,3),
  direction           TEXT,
  kelly_fraction      NUMERIC(6,4),
  confidence          NUMERIC(4,3),
  explanation         JSONB,
  created_at          TIMESTAMPTZ DEFAULT NOW(),
  UNIQUE (game_date, player_id, stat_type)
);

CREATE INDEX IF NOT EXISTS sim_edges_date_idx ON sim_prop_edges(game_date);

-- ============================================================
-- 19. LINEUPS (confirmed daily lineups cache)
-- ============================================================
CREATE TABLE IF NOT EXISTS lineups (
  id                    BIGSERIAL PRIMARY KEY,
  game_date             DATE        NOT NULL,
  game_pk               INT         REFERENCES games(game_pk),
  team_id               INT,
  team_abbreviation     TEXT,
  side                  TEXT        CHECK (side IN ('home', 'away')),
  batting_order         JSONB,
  probable_pitcher_id   INT,
  confirmed             BOOLEAN     DEFAULT FALSE,
  created_at            TIMESTAMPTZ DEFAULT NOW(),
  UNIQUE (game_pk, side)
);

CREATE INDEX IF NOT EXISTS lineups_date_idx ON lineups(game_date);

-- ============================================================
-- 20. WEATHER (game-day conditions cache)
-- ============================================================
CREATE TABLE IF NOT EXISTS weather (
  id                      BIGSERIAL PRIMARY KEY,
  game_date               DATE        NOT NULL,
  game_pk                 INT         REFERENCES games(game_pk),
  venue                   TEXT,
  temperature_f           NUMERIC(5,1),
  wind_speed_mph          NUMERIC(5,1),
  wind_direction          TEXT,
  humidity_pct            NUMERIC(5,1),
  precipitation_chance    NUMERIC(5,2),
  k_rate_multiplier       NUMERIC(5,4) DEFAULT 1.0,
  created_at              TIMESTAMPTZ DEFAULT NOW(),
  UNIQUE (game_pk)
);

CREATE INDEX IF NOT EXISTS weather_date_idx ON weather(game_date);

-- ============================================================
-- ROW LEVEL SECURITY
-- ============================================================

-- Existing tables
ALTER TABLE players          ENABLE ROW LEVEL SECURITY;
ALTER TABLE games            ENABLE ROW LEVEL SECURITY;
ALTER TABLE props            ENABLE ROW LEVEL SECURITY;
ALTER TABLE statcast_pitches ENABLE ROW LEVEL SECURITY;
ALTER TABLE umpire_framing   ENABLE ROW LEVEL SECURITY;
ALTER TABLE projections      ENABLE ROW LEVEL SECURITY;
ALTER TABLE picks            ENABLE ROW LEVEL SECURITY;
ALTER TABLE accuracy_summary ENABLE ROW LEVEL SECURITY;
ALTER TABLE clv_tracking     ENABLE ROW LEVEL SECURITY;
ALTER TABLE email_subscribers ENABLE ROW LEVEL SECURITY;
ALTER TABLE pitcher_overrides ENABLE ROW LEVEL SECURITY;

-- New tables
ALTER TABLE simulation_results      ENABLE ROW LEVEL SECURITY;
ALTER TABLE simulation_explanations ENABLE ROW LEVEL SECURITY;
ALTER TABLE backtest_results        ENABLE ROW LEVEL SECURITY;
ALTER TABLE model_artifacts         ENABLE ROW LEVEL SECURITY;
ALTER TABLE player_rolling_stats    ENABLE ROW LEVEL SECURITY;

-- Public read policies (existing)
CREATE POLICY public_read_picks ON picks
  FOR SELECT USING (published = TRUE);
CREATE POLICY public_read_accuracy ON accuracy_summary
  FOR SELECT USING (TRUE);
CREATE POLICY public_read_projections ON projections
  FOR SELECT USING (TRUE);
CREATE POLICY public_read_players ON players
  FOR SELECT USING (TRUE);
CREATE POLICY public_read_games ON games
  FOR SELECT USING (TRUE);
CREATE POLICY public_read_props ON props
  FOR SELECT USING (TRUE);
CREATE POLICY public_read_clv ON clv_tracking
  FOR SELECT USING (TRUE);

-- Public read policies (new simulation tables)
CREATE POLICY public_read_simulation_results ON simulation_results
  FOR SELECT USING (TRUE);
CREATE POLICY public_read_simulation_explanations ON simulation_explanations
  FOR SELECT USING (TRUE);
CREATE POLICY public_read_backtest_results ON backtest_results
  FOR SELECT USING (TRUE);
CREATE POLICY public_read_model_artifacts ON model_artifacts
  FOR SELECT USING (TRUE);
CREATE POLICY public_read_player_rolling_stats ON player_rolling_stats
  FOR SELECT USING (TRUE);

-- New simulator tables
ALTER TABLE sim_results    ENABLE ROW LEVEL SECURITY;
ALTER TABLE sim_prop_edges ENABLE ROW LEVEL SECURITY;
ALTER TABLE lineups        ENABLE ROW LEVEL SECURITY;
ALTER TABLE weather        ENABLE ROW LEVEL SECURITY;

CREATE POLICY public_read_sim_results ON sim_results    FOR SELECT USING (TRUE);
CREATE POLICY public_read_sim_edges   ON sim_prop_edges FOR SELECT USING (TRUE);
CREATE POLICY public_read_lineups     ON lineups         FOR SELECT USING (TRUE);
CREATE POLICY public_read_weather     ON weather         FOR SELECT USING (TRUE);

-- Service-role write policies (all tables)
CREATE POLICY service_write_simulation_results ON simulation_results
  FOR ALL TO service_role USING (TRUE) WITH CHECK (TRUE);
CREATE POLICY service_write_simulation_explanations ON simulation_explanations
  FOR ALL TO service_role USING (TRUE) WITH CHECK (TRUE);
CREATE POLICY service_write_backtest_results ON backtest_results
  FOR ALL TO service_role USING (TRUE) WITH CHECK (TRUE);
CREATE POLICY service_write_model_artifacts ON model_artifacts
  FOR ALL TO service_role USING (TRUE) WITH CHECK (TRUE);
CREATE POLICY service_write_player_rolling_stats ON player_rolling_stats
  FOR ALL TO service_role USING (TRUE) WITH CHECK (TRUE);
CREATE POLICY service_write_sim_results ON sim_results
  FOR ALL TO service_role USING (TRUE) WITH CHECK (TRUE);
CREATE POLICY service_write_sim_prop_edges ON sim_prop_edges
  FOR ALL TO service_role USING (TRUE) WITH CHECK (TRUE);
CREATE POLICY service_write_lineups ON lineups
  FOR ALL TO service_role USING (TRUE) WITH CHECK (TRUE);
CREATE POLICY service_write_weather ON weather
  FOR ALL TO service_role USING (TRUE) WITH CHECK (TRUE);
