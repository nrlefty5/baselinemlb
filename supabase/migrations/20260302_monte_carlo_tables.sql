-- ============================================================
-- Monte Carlo Simulation Tables
-- Migration: 2026-03-02
-- ============================================================

-- 1. SIMULATION RESULTS (per-player, per-game summary)
CREATE TABLE IF NOT EXISTS simulation_results (
    id              BIGSERIAL PRIMARY KEY,
    game_date       DATE NOT NULL,
    game_pk         INT REFERENCES games(game_pk),
    mlbam_id        INT REFERENCES players(mlbam_id),
    player_name     TEXT NOT NULL,
    stat_type       TEXT NOT NULL,
    -- Simulation params
    n_simulations   INT NOT NULL DEFAULT 3000,
    model_version   TEXT,
    -- Distribution summary
    sim_mean        NUMERIC(6,2),
    sim_median      NUMERIC(6,2),
    sim_std         NUMERIC(6,3),
    sim_p10         NUMERIC(6,2),
    sim_p25         NUMERIC(6,2),
    sim_p75         NUMERIC(6,2),
    sim_p90         NUMERIC(6,2),
    -- Prop edge analysis
    prop_line       NUMERIC(5,1),
    p_over          NUMERIC(5,4),
    p_under         NUMERIC(5,4),
    edge_pct        NUMERIC(6,3),
    kelly_fraction  NUMERIC(6,4),
    kelly_stake     NUMERIC(8,2),
    confidence_tier TEXT CHECK (confidence_tier IN ('A', 'B', 'C')),
    direction       TEXT CHECK (direction IN ('OVER', 'UNDER')),
    -- Feature contributions (SHAP-like)
    feature_contributions JSONB,
    -- Full distribution buckets for histogram
    distribution_buckets  JSONB,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (game_date, mlbam_id, stat_type)
);

CREATE INDEX IF NOT EXISTS sim_results_date_idx ON simulation_results(game_date);
CREATE INDEX IF NOT EXISTS sim_results_game_idx ON simulation_results(game_pk);
CREATE INDEX IF NOT EXISTS sim_results_tier_idx ON simulation_results(confidence_tier);

-- 2. BACKTEST RESULTS (historical simulation accuracy tracking)
CREATE TABLE IF NOT EXISTS simulation_backtest (
    id              BIGSERIAL PRIMARY KEY,
    game_date       DATE NOT NULL,
    stat_type       TEXT NOT NULL,
    -- Calibration data
    predicted_prob  NUMERIC(5,4),
    actual_rate     NUMERIC(5,4),
    sample_size     INT,
    -- P/L tracking
    total_bets      INT DEFAULT 0,
    wins            INT DEFAULT 0,
    losses          INT DEFAULT 0,
    pushes          INT DEFAULT 0,
    profit_loss     NUMERIC(10,2) DEFAULT 0,
    roi_pct         NUMERIC(6,3),
    -- By confidence tier
    tier            TEXT CHECK (tier IN ('A', 'B', 'C', 'ALL')),
    -- Cumulative
    cumulative_pl   NUMERIC(10,2),
    cumulative_roi  NUMERIC(6,3),
    bankroll        NUMERIC(10,2),
    model_version   TEXT,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (game_date, stat_type, tier)
);

CREATE INDEX IF NOT EXISTS sim_bt_date_idx ON simulation_backtest(game_date);
CREATE INDEX IF NOT EXISTS sim_bt_tier_idx ON simulation_backtest(tier);

-- RLS policies
ALTER TABLE simulation_results ENABLE ROW LEVEL SECURITY;
ALTER TABLE simulation_backtest ENABLE ROW LEVEL SECURITY;

CREATE POLICY public_read_sim_results ON simulation_results
    FOR SELECT USING (true);

CREATE POLICY public_read_sim_backtest ON simulation_backtest
    FOR SELECT USING (true);
