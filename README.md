# baselinemlb

> **MLB player prop analytics for mid-stakes bettors** — glass-box AI projections, umpire/framing composites, public accuracy dashboard

[![Data Pipeline](https://github.com/nrlefty5/baselinemlb/actions/workflows/pipelines.yml/badge.svg)](https://github.com/nrlefty5/baselinemlb/actions/workflows/pipelines.yml)

---

## What is this?

**baselinemlb** is an open-source MLB analytics engine that:

- Fetches daily game schedules, player stats, and prop lines automatically via GitHub Actions
- Pulls Statcast pitch data to compute **catcher framing scores** and **umpire accuracy** for each game
- Generates **glass-box prop projections** (no black-box models — every factor is visible and explained)
- Tracks historical prediction accuracy on a **public dashboard** at [baselinemlb.com](https://baselinemlb.com)
- Designed for **mid-stakes prop bettors** who want edge, not guesswork

---

## Key Features

| Feature | Details |
|---|---|
| **Automated pipelines** | GitHub Actions cron jobs run daily at 8 AM, 2 PM, and 2 AM ET |
| **Glass-box models** | All projection inputs are logged and publicly viewable |
| **Umpire composites** | Per-umpire called-strike accuracy, zone tendencies (L/R batter splits) |
| **Catcher framing** | Shadow-zone framing rate per catcher, updated nightly from Statcast |
| **Prop coverage** | K's, hits, total bases, RBIs, runs scored, home runs, pitcher outs |
| **Public accuracy dashboard** | Track our hit rate vs. the closing line over time |

---

## Repository Structure

```
baselinemlb/
├── .github/workflows/
│   └── pipelines.yml          # Daily cron: fetch games, players, props, statcast
├── scripts/
│   ├── fetch_games.py         # MLB Stats API → game schedule
│   ├── fetch_players.py       # Pitcher + batter season stats
│   ├── fetch_props.py         # The Odds API → prop lines (10 markets)
│   └── fetch_statcast.py      # Statcast → framing + umpire accuracy
├── pipeline/                  # Data transformation + scoring logic
├── supabase/                  # Database schema (8-table)
├── dashboard/                 # Public accuracy dashboard (HTML/JS)
├── data/                      # Local output: games/, players/, props/, statcast/
├── requirements.txt
├── .env.example
└── README.md
```

---

## Data Sources

- **[MLB Stats API](https://statsapi.mlb.com/api/v1/)** — free, official, no key required
- **[Statcast / pybaseball](https://github.com/jldbc/pybaseball)** — pitch-level data, catcher framing, umpire calls
- **[The Odds API](https://the-odds-api.com)** — prop lines across major US sportsbooks (API key required)

---

## Setup

### Local Development

```bash
git clone https://github.com/nrlefty5/baselinemlb.git
cd baselinemlb
pip install -r requirements.txt
cp .env.example .env
# Fill in your ODDS_API_KEY in .env
```

Run individual scripts:

```bash
python scripts/fetch_games.py
python scripts/fetch_players.py
python scripts/fetch_props.py      # Requires ODDS_API_KEY
python scripts/fetch_statcast.py   # Pulls yesterday's Statcast data
```

### GitHub Actions Secrets Required

| Secret | Description |
|---|---|
| `ODDS_API_KEY` | From [the-odds-api.com](https://the-odds-api.com) |
| `SUPABASE_URL` | Your Supabase project URL |
| `SUPABASE_SERVICE_KEY` | Supabase service role key |
| `SUPABASE_ANON_KEY` | Supabase anon (public) key — used by dashboard/js/stats.js |

---

## Prop Markets Tracked

- `pitcher_strikeouts` — our #1 focus
- `pitcher_outs`
- `pitcher_hits_allowed`
- `pitcher_walks`
- `pitcher_earned_runs`
- `batter_hits`
- `batter_total_bases`
- `batter_home_runs`
- `batter_rbis`
- `batter_runs_scored`

---

## Umpire + Framing Composites

Every game projection includes:

- **Umpire accuracy %** — correct called-pitch rate over trailing 30 games
- **Umpire zone bias** — called-strike rate above/below league average, L/R batter split
- **Catcher framing rate** — shadow-zone strike conversion over trailing 30 games
- **Net framing impact** — estimated extra K's per 9 innings from umpire + catcher combo

All of this is pulled nightly from Statcast via pybaseball and stored in `data/statcast/`.

---

## Public Accuracy Dashboard

Our prediction accuracy is tracked publicly at **[baselinemlb.com](https://baselinemlb.com)**. (live at **[nrlefty5.github.io/baselinemlb](https://nrlefty5.github.io/baselinemlb/)**).

Metrics shown:
- Overall hit rate (past 30 days, season)
- Hit rate by prop market
- Hit rate by bookmaker
- Closing line value (CLV) trend

---

## License


---

## Supabase Setup

### Running Migrations

All database schema changes are versioned in `supabase/migrations/`.

**To apply migrations to your Supabase project:**

```bash
# Install Supabase CLI (if not already installed)
brew install supabase/tap/supabase  # macOS
# or: npm install -g supabase

# Link to your project
supabase link --project-ref [YOUR_PROJECT_REF]

# Apply all pending migrations
supabase db push
```

### Required Tables

The following tables must exist for the pipeline to function:

| Table | Purpose | Migration File |
|-------|---------|----------------|
| `games` | MLB game schedule | `schema.sql` |
| `players` | Active MLB players (40-man rosters) | `schema.sql` |
| `props` | Prop lines from The Odds API | `schema.sql` |
| `projections` | Our K/TB projections | `schema.sql` |
| `statcast` | Pitch-level data from MLB | `schema.sql` |
| `picks` | Graded projection results | `schema.sql` |
| `accuracy_summary` | Aggregate hit rate stats | `schema.sql` |
| **`clv_tracking`** | Closing Line Value analysis | `20260225_create_clv_tracking.sql` |

### CLV Tracking Table Schema

```sql
CREATE TABLE clv_tracking (
  id BIGSERIAL PRIMARY KEY,
  game_date DATE NOT NULL,
  player_name TEXT NOT NULL,
  market TEXT NOT NULL,
  opening_price INTEGER,  -- American odds (e.g., -110, +150)
  closing_price INTEGER,
  opening_line NUMERIC,   -- Prop line (e.g., 6.5 Ks)
  closing_line NUMERIC,
  price_movement INTEGER, -- opening_price - closing_price
  clv_percent NUMERIC,    -- (price_movement / abs(closing_price)) * 100
  calculated_at TIMESTAMPTZ DEFAULT NOW(),
  UNIQUE(game_date, player_name, market)
);

CREATE INDEX idx_clv_game_date ON clv_tracking(game_date);
CREATE INDEX idx_clv_player ON clv_tracking(player_name);
```

### Verifying Migrations

To confirm all migrations have been applied:

```bash
# Check migration status
supabase migration list

# Or query directly in Supabase SQL Editor:
SELECT * FROM supabase_migrations.schema_migrations ORDER BY version;
```

You should see:
- `20260225_create_clv_tracking` with `inserted_at` timestamp

### Row-Level Security (RLS) for Dashboard

The public dashboard at [baselinemlb.com](https://baselinemlb.com) uses the Supabase **anon key** to fetch read-only data. Enable RLS policies:

```sql
-- Allow public read access to completed picks
ALTER TABLE picks ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Public read completed picks"
  ON picks FOR SELECT
  USING (result IS NOT NULL);  -- Only show graded picks

-- Allow public read access to CLV tracking
ALTER TABLE clv_tracking ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Public read CLV"
  ON clv_tracking FOR SELECT
  USING (true);

-- Allow public read access to accuracy summary
ALTER TABLE accuracy_summary ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Public read accuracy"
  ON accuracy_summary FOR SELECT
  USING (true);
```

**⚠️ Important:** Never expose your `SUPABASE_SERVICE_KEY` in client-side code. Only the `SUPABASE_ANON_KEY` should be used in `dashboard/js/stats.js`.
MIT — open source, use freely.


<!-- System validated and pipeline tested on 2026-02-26 -->
