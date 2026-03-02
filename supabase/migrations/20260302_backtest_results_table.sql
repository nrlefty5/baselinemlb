-- =============================================================================
-- Migration: 20260302_backtest_results_table.sql
-- Description: Ensure backtest_results table exists with proper schema,
--              indexes, RLS policies, and the Supabase RPC for the dashboard.
-- =============================================================================

-- Create backtest_results table if not already present
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

-- Indexes for common queries
CREATE INDEX IF NOT EXISTS idx_backtest_date      ON backtest_results(date);
CREATE INDEX IF NOT EXISTS idx_backtest_prop_type ON backtest_results(prop_type);
CREATE INDEX IF NOT EXISTS idx_backtest_date_type ON backtest_results(date, prop_type);

-- RLS
ALTER TABLE backtest_results ENABLE ROW LEVEL SECURITY;

-- Public read
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_policies WHERE tablename = 'backtest_results' AND policyname = 'public_read_backtest'
  ) THEN
    CREATE POLICY public_read_backtest ON backtest_results FOR SELECT USING (TRUE);
  END IF;
END $$;

-- Service-role write
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_policies WHERE tablename = 'backtest_results' AND policyname = 'service_write_backtest'
  ) THEN
    CREATE POLICY service_write_backtest ON backtest_results
      FOR ALL USING (auth.role() = 'service_role');
  END IF;
END $$;

-- ============================================================
-- RPC: get_backtest_summary()
-- Returns aggregated backtest metrics by prop type
-- ============================================================
CREATE OR REPLACE FUNCTION get_backtest_summary()
RETURNS TABLE (
  prop_type           TEXT,
  total_predictions   BIGINT,
  correct_predictions BIGINT,
  accuracy_pct        NUMERIC,
  avg_roi_pct         NUMERIC,
  avg_edge            NUMERIC,
  avg_tier_a_roi      NUMERIC,
  avg_tier_b_roi      NUMERIC,
  avg_tier_c_roi      NUMERIC,
  total_profit_loss   NUMERIC,
  days_tested         BIGINT,
  first_date          DATE,
  last_date           DATE
)
LANGUAGE sql STABLE AS $$
  SELECT
    br.prop_type,
    SUM(br.total_predictions)::BIGINT   AS total_predictions,
    SUM(br.correct_predictions)::BIGINT AS correct_predictions,
    ROUND(
      CASE WHEN SUM(br.total_predictions) > 0
        THEN SUM(br.correct_predictions)::NUMERIC / SUM(br.total_predictions) * 100
        ELSE 0
      END, 1
    ) AS accuracy_pct,
    ROUND(AVG(br.roi_pct), 1)          AS avg_roi_pct,
    ROUND(AVG(br.avg_edge), 4)         AS avg_edge,
    ROUND(AVG(br.tier_a_roi), 1)       AS avg_tier_a_roi,
    ROUND(AVG(br.tier_b_roi), 1)       AS avg_tier_b_roi,
    ROUND(AVG(br.tier_c_roi), 1)       AS avg_tier_c_roi,
    ROUND(SUM(br.profit_loss), 2)      AS total_profit_loss,
    COUNT(DISTINCT br.date)::BIGINT    AS days_tested,
    MIN(br.date)                       AS first_date,
    MAX(br.date)                       AS last_date
  FROM backtest_results br
  WHERE br.prop_type != 'ALL'
  GROUP BY br.prop_type
  ORDER BY SUM(br.total_predictions) DESC;
$$;
