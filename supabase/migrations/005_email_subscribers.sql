-- Migration: Create email_subscribers table for newsletter system
-- Run this in Supabase SQL editor

CREATE TABLE IF NOT EXISTS email_subscribers (
    id BIGSERIAL PRIMARY KEY,
    email TEXT UNIQUE NOT NULL,
    subscribed_at TIMESTAMPTZ DEFAULT NOW(),
    active BOOLEAN DEFAULT TRUE,
    source TEXT DEFAULT 'website'  -- 'website', 'manual', 'import'
);

-- Index for fast active subscriber lookups
CREATE INDEX IF NOT EXISTS idx_email_subscribers_active ON email_subscribers(active) WHERE active = TRUE;

-- RLS: Allow public inserts (for signup form) but restrict reads to service key
ALTER TABLE email_subscribers ENABLE ROW LEVEL SECURITY;

-- Allow anyone to insert (subscribe)
CREATE POLICY "Allow public subscribe" ON email_subscribers
    FOR INSERT
    WITH CHECK (true);

-- Only service role can read/update/delete
CREATE POLICY "Service role full access" ON email_subscribers
    FOR ALL
    USING (auth.role() = 'service_role');
