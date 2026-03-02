-- =============================================================================
-- Migration: 20260302_add_simulator_tables.sql
-- Description: Add tables required by the BaselineMLB Monte Carlo simulator.
--              Tables: sim_results, sim_prop_edges, lineups, weather
-- =============================================================================

-- Monte Carlo simulation results
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

-- Simulation-based prop edges
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

-- Confirmed lineups cache
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

-- Weather data cache
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

-- Indexes
CREATE INDEX IF NOT EXISTS sim_results_date_idx   ON sim_results(game_date);
CREATE INDEX IF NOT EXISTS sim_results_player_idx ON sim_results(player_id);
CREATE INDEX IF NOT EXISTS sim_edges_date_idx     ON sim_prop_edges(game_date);
CREATE INDEX IF NOT EXISTS lineups_date_idx       ON lineups(game_date);
CREATE INDEX IF NOT EXISTS weather_date_idx       ON weather(game_date);

-- Row Level Security
ALTER TABLE sim_results    ENABLE ROW LEVEL SECURITY;
ALTER TABLE sim_prop_edges ENABLE ROW LEVEL SECURITY;
ALTER TABLE lineups        ENABLE ROW LEVEL SECURITY;
ALTER TABLE weather        ENABLE ROW LEVEL SECURITY;

CREATE POLICY public_read_sim_results ON sim_results    FOR SELECT USING (TRUE);
CREATE POLICY public_read_sim_edges   ON sim_prop_edges FOR SELECT USING (TRUE);
CREATE POLICY public_read_lineups     ON lineups         FOR SELECT USING (TRUE);
CREATE POLICY public_read_weather     ON weather         FOR SELECT USING (TRUE);
