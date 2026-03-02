-- ============================================================
-- BaselineMLB — API Monetization Migration
-- 2026-03-02
-- ============================================================

-- ── Subscriptions ───────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS subscriptions (
  id                      BIGSERIAL PRIMARY KEY,
  email                   TEXT NOT NULL UNIQUE,
  stripe_customer_id      TEXT,
  stripe_subscription_id  TEXT,
  tier                    TEXT NOT NULL DEFAULT 'free' CHECK (tier IN ('free', 'pro', 'premium')),
  status                  TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'canceled', 'past_due')),
  current_period_start    TIMESTAMPTZ,
  current_period_end      TIMESTAMPTZ,
  created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_subscriptions_email ON subscriptions(email);
CREATE INDEX IF NOT EXISTS idx_subscriptions_status ON subscriptions(status);
CREATE INDEX IF NOT EXISTS idx_subscriptions_tier ON subscriptions(tier);

-- ── API Keys ─────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS api_keys (
  id                BIGSERIAL PRIMARY KEY,
  key_hash          TEXT NOT NULL UNIQUE,
  key_prefix        TEXT NOT NULL,
  email             TEXT NOT NULL REFERENCES subscriptions(email) ON DELETE CASCADE,
  tier              TEXT NOT NULL DEFAULT 'premium' CHECK (tier IN ('pro', 'premium')),
  name              TEXT NOT NULL DEFAULT 'Default Key',
  requests_today    INTEGER NOT NULL DEFAULT 0,
  last_request_at   TIMESTAMPTZ,
  active            BOOLEAN NOT NULL DEFAULT TRUE,
  created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_api_keys_hash ON api_keys(key_hash);
CREATE INDEX IF NOT EXISTS idx_api_keys_email ON api_keys(email);

-- ── Rate Limits ──────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS rate_limits (
  id             BIGSERIAL PRIMARY KEY,
  key_hash       TEXT NOT NULL,
  window_start   TIMESTAMPTZ NOT NULL,
  request_count  INTEGER NOT NULL DEFAULT 1,
  UNIQUE (key_hash, window_start)
);

CREATE INDEX IF NOT EXISTS idx_rate_limits_key_window ON rate_limits(key_hash, window_start);

-- Stored proc to atomically increment the counter
CREATE OR REPLACE FUNCTION increment_rate_limit(
  p_key_hash    TEXT,
  p_window_start TIMESTAMPTZ
) RETURNS VOID AS $$
BEGIN
  UPDATE rate_limits
     SET request_count = request_count + 1
   WHERE key_hash = p_key_hash
     AND window_start = p_window_start;
END;
$$ LANGUAGE plpgsql;

-- ── Newsletter Digests ───────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS newsletter_digests (
  id               BIGSERIAL PRIMARY KEY,
  game_date        DATE NOT NULL UNIQUE,
  subject          TEXT NOT NULL,
  edges_json       JSONB NOT NULL DEFAULT '[]',
  results_json     JSONB,
  sent_at          TIMESTAMPTZ,
  recipient_count  INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_newsletter_digests_date ON newsletter_digests(game_date DESC);

-- ── Alert Preferences ────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS alert_preferences (
  id          BIGSERIAL PRIMARY KEY,
  email       TEXT NOT NULL REFERENCES subscriptions(email) ON DELETE CASCADE,
  enabled     BOOLEAN NOT NULL DEFAULT TRUE,
  min_grade   TEXT DEFAULT 'C' CHECK (min_grade IN ('A', 'B', 'C')),
  min_edge    NUMERIC(5,4) DEFAULT 0.02,
  updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (email)
);

-- ── Row Level Security ───────────────────────────────────────────────
ALTER TABLE subscriptions ENABLE ROW LEVEL SECURITY;
ALTER TABLE api_keys ENABLE ROW LEVEL SECURITY;
ALTER TABLE rate_limits ENABLE ROW LEVEL SECURITY;
ALTER TABLE newsletter_digests ENABLE ROW LEVEL SECURITY;
ALTER TABLE alert_preferences ENABLE ROW LEVEL SECURITY;

-- newsletter_digests is public read
CREATE POLICY newsletter_digests_select
  ON newsletter_digests FOR SELECT
  USING (true);

-- subscriptions: users can read/update their own row
CREATE POLICY subscriptions_self
  ON subscriptions FOR ALL
  USING (auth.jwt() ->> 'email' = email);

-- api_keys: users can read/update their own keys
CREATE POLICY api_keys_self
  ON api_keys FOR ALL
  USING (auth.jwt() ->> 'email' = email);

-- alert_preferences: users can manage their own
CREATE POLICY alert_preferences_self
  ON alert_preferences FOR ALL
  USING (auth.jwt() ->> 'email' = email);
