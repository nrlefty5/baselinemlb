-- Create CLV (Closing Line Value) tracking table
-- Tracks opening vs closing prop prices to measure bet timing value

CREATE TABLE IF NOT EXISTS clv_tracking (
    id SERIAL PRIMARY KEY,
    game_date DATE NOT NULL,
    player_name TEXT NOT NULL,
    market TEXT NOT NULL,
    opening_price DECIMAL,
    closing_price DECIMAL,
    opening_line DECIMAL,
    closing_line DECIMAL,
    price_movement DECIMAL,
    clv_percent DECIMAL,
    calculated_at TIMESTAMP DEFAULT NOW(),
    created_at TIMESTAMP DEFAULT NOW(),
    
    -- Composite unique constraint to prevent duplicates
    UNIQUE(game_date, player_name, market)
);

-- Add indexes for common queries
CREATE INDEX idx_clv_game_date ON clv_tracking(game_date);
CREATE INDEX idx_clv_player_name ON clv_tracking(player_name);
CREATE INDEX idx_clv_market ON clv_tracking(market);
CREATE INDEX idx_clv_percent ON clv_tracking(clv_percent);

-- Enable Row Level Security
ALTER TABLE clv_tracking ENABLE ROW LEVEL SECURITY;

-- Create policy to allow all operations for authenticated users
CREATE POLICY "Allow all operations for authenticated users" 
    ON clv_tracking
    FOR ALL 
    TO authenticated
    USING (true)
    WITH CHECK (true);

-- Create policy to allow read for anonymous users
CREATE POLICY "Allow read for anonymous users" 
    ON clv_tracking
    FOR SELECT 
    TO anon
    USING (true);
