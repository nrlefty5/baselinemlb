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

Our prediction accuracy is tracked publicly at **[baselinemlb.com](https://baselinemlb.com)**.

Metrics shown:
- Overall hit rate (past 30 days, season)
- Hit rate by prop market
- Hit rate by bookmaker
- Closing line value (CLV) trend

---

## License

MIT — open source, use freely.
