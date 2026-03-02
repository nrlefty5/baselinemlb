-- =============================================================================
-- Migration: 20260302_accuracy_summary_add_clv.sql
-- Description: Add avg_clv column to accuracy_summary table to support
--              CLV (Closing Line Value) tracking on the accuracy dashboard.
-- =============================================================================

ALTER TABLE accuracy_summary
  ADD COLUMN IF NOT EXISTS avg_clv NUMERIC(6,3) DEFAULT NULL;

COMMENT ON COLUMN accuracy_summary.avg_clv IS 'Average closing line value for picks in this stat_type/period';
