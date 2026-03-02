# BaselineMLB — System Architecture

> **Version:** 2.0 (Monte Carlo Engine)
> **Last Updated:** March 2026
> **Maintainer:** BaselineMLB Core Team

---

## Table of Contents

1. [Project Overview](#1-project-overview)
2. [System Data Flow](#2-system-data-flow)
3. [Component Descriptions](#3-component-descriptions)
4. [Dependency Map](#4-dependency-map)
5. [Database Schema](#5-database-schema)
6. [Cron Schedule](#6-cron-schedule)
7. [How to Run Locally](#7-how-to-run-locally)
8. [Environment Variables](#8-environment-variables)
9. [Package Consolidation: simulation/ vs simulator/](#9-package-consolidation-simulation-vs-simulator)

---

## 1. Project Overview

**BaselineMLB** is a production-grade MLB player prop analytics platform built around a plate-appearance-level Monte Carlo simulation engine. The system ingests real-time game, player, and Statcast pitch data, trains an XGBoost matchup model on ~6 million historical plate appearances, and simulates each game 3,000 times to generate probability distributions over every meaningful player outcome (strikeouts, hits, total bases, RBIs, walks, etc.).

The simulation output is cross-referenced against live sportsbook lines from The Odds API to identify edges — situations where the model's estimated probability of a prop outcome meaningfully exceeds the no-vig implied probability embedded in the market. Edges are ranked using a fractional Kelly criterion for stake sizing and surfaced to users via a Next.js frontend deployed on Vercel.

### Design Philosophy

| Principle | Implementation |
|-----------|----------------|
| **Glass-box transparency** | Full methodology exposed in docs; no black-box outputs |
| **Plate-appearance granularity** | Each PA simulated individually, not regressed at the game level |
| **Real game state** | Inning, outs, baserunners, and score tracked across all 3,000 simulations |
| **Honest uncertainty** | Confidence scores via bootstrap resampling; limitations clearly documented |
| **Automated pipeline** | Four GitHub Actions cron jobs cover full daily data lifecycle |
| **Open source** | MIT license; all code, schema, and methodology public |

---

## 2. System Data Flow

The diagram below traces data from external APIs through the processing pipeline, into the database, through the simulation engine, and finally to the user-facing frontend.

```
 External APIs → Supabase → XGBoost Model → Monte Carlo Engine → Prop Calculator → Frontend
```

For the full ASCII diagram, see the repository source of this file.

---

## 3. Component Descriptions

### `pipeline/` — Data Ingestion Layer

The pipeline directory contains all scripts responsible for pulling external data and persisting it to Supabase. Each script is designed to be idempotent — running a script twice on the same day produces the same database state as running it once.

| Script | Purpose | Source API |
|--------|---------|------------|
| `fetch_games.py` | Pulls today's schedule: game IDs, teams, venues, start times, weather station coordinates | MLB Stats API |
| `fetch_players.py` | Fetches confirmed lineups, starting pitchers, roster updates | MLB Stats API |
| `fetch_props.py` | Downloads current player prop lines and odds for all active markets | The Odds API |
| `fetch_weather.py` | Retrieves current weather for each game venue (temp, wind speed/direction, humidity, precipitation) | OpenWeatherMap API |
| `fetch_statcast_historical.py` | Backfills pitch-level Statcast data for model training; runs nightly for the previous day's games | pybaseball / Baseball Savant |
| `grade_props.py` | After games conclude, fetches final box scores and grades each outstanding prop as WIN/LOSS/PUSH | MLB Stats API |

**Key design decisions:**
- All pipeline scripts log run metadata (start time, row count, errors) to a `pipeline_runs` audit table
- Partial failures are caught and surfaced without halting subsequent pipeline stages
- Statcast backfill is rate-limited to avoid Baseball Savant blocks

---

### `models/` — XGBoost Matchup Model

The models directory contains training infrastructure for the plate-appearance outcome classifier that powers the Monte Carlo engine.

| File | Purpose |
|------|---------|
| `build_training_dataset.py` | Queries `statcast_pitches`, engineers 24 features, encodes labels, outputs `data/training_set.parquet` |
| `train_model.py` | Trains XGBoost multiclass classifier on the parquet dataset; exports model artifact to `data/xgboost_model.json` |
| `evaluate_model.py` | Computes log-loss, calibration curves, and per-class AUC; outputs evaluation report |
| `feature_registry.py` | Single source of truth for all 24 feature definitions; shared with inference code at runtime |

**Training cadence:** The model is retrained at the start of each new season (late February) and optionally mid-season (July All-Star break) when sample size is sufficient.

---

### `simulator/` — Monte Carlo Engine (CANONICAL)

The simulator is the core intellectual contribution of BaselineMLB v2.0. It orchestrates the plate-appearance model into full game simulations.

| File | Purpose |
|------|---------|
| `monte_carlo_engine.py` | Main simulation loop: 3,000 iterations per game, full nine-inning game state tracking |
| `game_state.py` | Dataclass representing inning, outs, baserunner positions, and score |
| `pitcher_fatigue.py` | Applies K-rate decay after 25 batters faced; models fatigue curve empirically |
| `runner_advancement.py` | Advances runners on all PA outcome types (1B/2B/3B/HR/FC/wild pitch/etc.) |
| `park_factors.py` | Lookup table of per-stadium park factor multipliers for all 30 MLB venues |
| `weather_adjustments.py` | Applies temperature, wind, and humidity modifiers to HR, fly ball, and K rates |
| `umpire_tendencies.py` | Encodes individual umpire strike-zone tendencies affecting K and BB rates |
| `catcher_framing.py` | Adjusts called-strike probability based on catcher framing metrics |
| `prop_calculator.py` | Post-simulation: converts simulation distributions to prop probabilities and Kelly stakes |
| `find_edges.py` | Compares model probabilities to sportsbook implied probabilities; ranks edges by strength |

---

### `simulation/` — Legacy Package (DEPRECATED)

> **Deprecated.** This package is a compatibility wrapper around `simulator/`. Do not use it in new code.

The `simulation/` directory contains the original v1.0 Monte Carlo implementation (8,636 lines across 7 modules). Its `__init__.py` now emits a `DeprecationWarning` on import and re-exports constants from `simulator/`. The submodule files are preserved so that `tests/test_simulation.py` (168 tests) continues to pass without modification.

See [Section 9](#9-package-consolidation-simulation-vs-simulator) for the full consolidation notes and migration path.

---

### `scripts/` — Utilities, Backtesting & Grading

Standalone utility scripts for analysis, validation, and one-off operations.

| Script | Purpose |
|--------|--------|
| `backtest.py` | Runs the full simulation pipeline against historical dates; generates P&L and calibration statistics |
| `calibration_check.py` | Computes reliability diagrams and ECE (Expected Calibration Error) scores |
| `generate_projections.py` | Lightweight wrapper to run projections for a specific date or player; used for on-demand analysis |
| `compare_models.py` | Side-by-side comparison of v1.0 (career K/9) vs v2.0 (Monte Carlo) projection accuracy |
| `export_results.py` | Exports simulation results to CSV for offline analysis |
| `seed_park_factors.py` | One-time seed of park factor data from FanGraphs |
| `seed_umpire_data.py` | One-time seed of umpire tendency data from Umpire Scorecards |

---

### `frontend/` — Next.js on Vercel

The React/Next.js application that surfaces prop picks and methodology to end users.

```
frontend/
├── app/
│   ├── page.tsx                  # Today's props dashboard
│   ├── props/[id]/page.tsx       # Individual prop deep-dive
│   ├── players/[id]/page.tsx     # Player profile + projections
│   ├── methodology/page.tsx      # Methodology transparency page
│   └── results/page.tsx          # Historical grading and ROI
├── components/
│   ├── PropCard.tsx              # Edge card with Kelly stake
│   ├── SimDistribution.tsx       # Histogram of simulation outcomes
│   ├── EdgeLeaderboard.tsx       # Ranked list of today's edges
│   └── CalibrationChart.tsx      # Model calibration visualization
├── lib/
│   └── supabaseClient.ts         # Supabase JS client for frontend
└── public/
```

**Deployment:** Automatically deployed to Vercel on every push to `main`. Preview deployments on all pull requests.

---

### `lib/` — Shared Supabase Helpers

Python utilities shared across pipeline, model, and simulator modules.

| File | Purpose |
|------|---------|
| `supabase_client.py` | Initializes authenticated Supabase client; used by all pipeline and simulator scripts |
| `db_helpers.py` | Common query patterns: upsert games, fetch lineups, write simulation results |
| `logging_helpers.py` | Structured logging to `pipeline_runs` audit table |

---

### `supabase/` — Schema & Migrations

All database definitions managed as versioned SQL migrations.

```
supabase/
├── migrations/
│   ├── 001_initial_schema.sql
│   ├── 002_add_statcast_pitches.sql
│   ├── 003_add_sim_results.sql
│   ├── 004_add_graded_props.sql
│   ├── 005_add_weather_snapshots.sql
│   ├── 006_add_umpire_data.sql
│   └── 007_add_model_artifacts.sql
└── seed/
    ├── park_factors.sql
    └── umpire_tendencies.sql
```

---

### `.github/workflows/` — CI/CD

GitHub Actions workflows drive the daily data pipeline and CI checks.

| Workflow | Trigger | Purpose |
|----------|---------|--------|
| `morning_pipeline.yml` | Cron 8:00 AM ET | Fetch games + players |
| `midday_pipeline.yml` | Cron 10:30 AM ET | Fetch props + run projections + run simulations |
| `afternoon_pipeline.yml` | Cron 4:30 PM ET | Afternoon prop refresh |
| `overnight_pipeline.yml` | Cron 2:00 AM ET | Statcast backfill + prop grading |
| `ci.yml` | Push / PR | Lint, test, type-check |

---

### `docs/` — Documentation

| File | Contents |
|------|---------|
| `ARCHITECTURE.md` | This document — full system architecture |
| `MONTE_CARLO_METHODOLOGY.md` | Glass-box explanation of the simulation methodology |
| `DATABASE_SCHEMA.md` | Full table-by-table schema reference |
| `API_REFERENCE.md` | Internal API endpoint documentation |
| `CONTRIBUTING.md` | Contribution guidelines |

---

### `data/` — Training Datasets & Model Artifacts

```
data/
├── training_set.parquet          # Feature matrix for XGBoost training (~6M rows)
├── xgboost_model.json            # Serialized trained XGBoost model
├── feature_importance.csv        # Feature importance scores from last training run
├── calibration_report.json       # Latest calibration evaluation output
└── backtest_results/
    ├── 2023_backtest.csv
    ├── 2024_backtest.csv
    └── 2025_backtest.csv
```

> **Note:** The `data/` directory is excluded from version control via `.gitignore`. Model artifacts and datasets are stored in Supabase Storage and downloaded by pipeline scripts at runtime.

---

## 4. Dependency Map

The following diagram shows which modules import from which. Arrows indicate the direction of dependency (A → B means A imports from B).

```
External APIs
    │
    ▼
pipeline/* ─────────────────────────────────────────────────────────────┐
    │                                                                         │
    │ writes to                                                               │ uses
    ▼                                                                         ▼
supabase/                                                       lib/supabase_client.py
    │                                                           lib/db_helpers.py
    │ reads from                                                lib/logging_helpers.py
    ▼
models/build_training_dataset.py
    │
    ▼
models/train_model.py ──────────────────────────────────────────────┐
    │                                                                         │
    │ produces model artifact (data/xgboost_model.json)                      │
    ▼                                                                         │
simulator/monte_carlo_engine.py ──────────────────────────────────────┘
    │
    ▼
simulator/prop_calculator.py
    │
    ▼
simulator/find_edges.py
    │
    ▼
supabase/ (writes edges + projections)
    │
    ▼
frontend/ (reads via Supabase JS client)
```

**Cross-cutting concerns:**
- `lib/supabase_client.py` is imported by all pipeline, model, and simulator scripts
- `models/feature_registry.py` is imported by both `build_training_dataset.py` (training) and `monte_carlo_engine.py` (inference) to guarantee feature consistency
- `simulator/park_factors.py` is imported by both the Monte Carlo engine (runtime adjustments) and `scripts/seed_park_factors.py` (data seeding)

---

## 5. Database Schema

BaselineMLB uses Supabase (PostgreSQL) with 20 core tables.

### Table Overview

| Table | Rows (est.) | Primary Use | Updated |
|-------|------------|------------|--------|
| `games` | ~2,400/season | Game schedule, venues, start times | Morning pipeline |
| `players` | ~1,500 active | Roster data, confirmed lineup slots | Morning pipeline |
| `statcast_pitches` | ~700K/season | Pitch-level Statcast data for model training | Overnight |
| `props` | ~8K/game day | Live sportsbook lines from The Odds API | Midday + afternoon |
| `projections` | ~300/game day | PA outcome probability distributions per player | Midday |
| `sim_results` | ~300/game day | Full simulation output (all 3,000 runs summarized) | Midday |
| `graded_props` | ~8K/game day | Final prop outcomes (WIN/LOSS/PUSH) | Overnight |
| `park_factors` | 30 static | Per-stadium HR/fly ball/strikeout factors | Seeded once |
| `weather_snapshots` | ~50/game day | Game-time weather conditions per venue | Midday + afternoon |
| `umpire_data` | ~100 active | Home plate umpire K/BB tendency scores | Weekly refresh |
| `model_artifacts` | ~1/season | Serialized XGBoost model + metadata | Seasonal |

---

## 6. Cron Schedule

All cron jobs run as GitHub Actions workflows. Times are Eastern Time.

| Time (ET) | Workflow | Scripts Run |
|-----------|----------|------------|
| **8:00 AM** | Morning | `fetch_games.py`, `fetch_players.py` |
| **10:30 AM** | Midday | `fetch_props.py`, `fetch_weather.py`, `generate_projections.py`, `monte_carlo_engine.py`, `prop_calculator.py`, `find_edges.py` |
| **4:30 PM** | Afternoon | `fetch_props.py`, `fetch_weather.py`, `monte_carlo_engine.py`, `prop_calculator.py`, `find_edges.py` |
| **2:00 AM** | Overnight | `fetch_statcast_historical.py`, `grade_props.py`, `calibration_check.py` |

**Notes:**
- The midday simulation run (10:30 AM) is the primary publication window. Edges are live on the frontend by ~11:15 AM ET on game days.
- The 4:30 PM refresh captures late line movement and updated weather conditions.
- The 2:00 AM overnight job backfills the previous day's Statcast data and grades all props that settled.
- All workflows send failure alerts to Slack if any step exits non-zero.

---

## 7. How to Run Locally

### Prerequisites

- Python 3.11+
- Node.js 20+
- Git
- A Supabase project (free tier is sufficient for development)
- API keys: MLB Stats (free), The Odds API, OpenWeatherMap

### Clone and Install

```bash
# Clone the repository
git clone https://github.com/your-org/baselinemlb.git
cd baselinemlb

# Create and activate a Python virtual environment
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate

# Install Python dependencies
pip install -r requirements.txt

# Install frontend dependencies
cd frontend
npm install
cd ..
```

### Set Environment Variables

Copy the example environment file and fill in your credentials:

```bash
cp .env.example .env
```

Edit `.env` with your API keys and Supabase connection details (see [Environment Variables](#8-environment-variables) below).

### Run the Database Migrations

```bash
# Using the Supabase CLI
supabase db push

# Or manually run migrations in order
psql $DATABASE_URL < supabase/migrations/001_initial_schema.sql
# ... repeat for each migration file
```

### Run the Pipeline Manually

```bash
# Step 1: Fetch today's games and lineups
python pipeline/fetch_games.py
python pipeline/fetch_players.py

# Step 2: Fetch props and weather
python pipeline/fetch_props.py
python pipeline/fetch_weather.py

# Step 3: Build training dataset (first time only; takes ~20 min)
python models/build_training_dataset.py

# Step 4: Train the model (first time only; takes ~10 min on a modern laptop)
python models/train_model.py

# Step 5: Run projections
python scripts/generate_projections.py --date today

# Step 6: Run simulations (runs 3,000 sims per game; ~2-3 min per game)
python simulator/monte_carlo_engine.py --date today

# Step 7: Calculate prop edges
python simulator/prop_calculator.py --date today
python simulator/find_edges.py --date today
```

### Start the Frontend Dev Server

```bash
cd frontend
cp .env.example .env.local   # Add your Supabase URL and anon key
npm run dev
# Opens at http://localhost:3000
```

---

## 8. Environment Variables

All environment variables are stored in `.env` at the project root. GitHub Actions secrets mirror these variables for the CI/CD pipeline.

```bash
# Supabase
SUPABASE_URL=https://your-project-id.supabase.co
SUPABASE_SERVICE_ROLE_KEY=your-service-role-key   # Pipeline (server-side only)
SUPABASE_ANON_KEY=your-anon-key                   # Frontend (public, safe to expose)
DATABASE_URL=postgresql://postgres:[password]@db.your-project-id.supabase.co:5432/postgres

# The Odds API
ODDS_API_KEY=your-odds-api-key

# OpenWeatherMap
OPENWEATHER_API_KEY=your-openweather-api-key

# MLB Stats API (no key required; included for rate-limit headers)
MLB_STATS_API_BASE=https://statsapi.mlb.com/api/v1

# Model Configuration
MODEL_VERSION=2.0
N_SIMULATIONS=3000
MIN_EDGE_THRESHOLD=0.04            # Minimum edge % to surface a pick (default: 4%)
KELLY_FRACTION=0.25                # Fractional Kelly (default: quarter Kelly)

# Notifications
SLACK_WEBHOOK_URL=https://hooks.slack.com/services/...   # Pipeline failure alerts

# Frontend (Next.js — prefix with NEXT_PUBLIC_ for client-side exposure)
NEXT_PUBLIC_SUPABASE_URL=https://your-project-id.supabase.co
NEXT_PUBLIC_SUPABASE_ANON_KEY=your-anon-key
```

> **Security note:** Never commit `.env` to version control. The `SUPABASE_SERVICE_ROLE_KEY` bypasses row-level security and should only be used in server-side pipeline scripts, never in frontend code.

---

## 9. Package Consolidation: `simulation/` vs `simulator/`

> **Last Updated:** March 2026

### Summary

The repository contains two simulation packages with overlapping responsibilities:

| Package | Lines | Status | Used By |
|---------|-------|--------|---------|
| `simulator/` | 4,421 | **Production** (canonical) | `make simulate`, GitHub Actions, pipeline scripts, frontend |
| `simulation/` | 8,636 | **Legacy** (deprecated) | `tests/test_simulation.py` (168 tests) only |

### Why Both Packages Exist

`simulation/` is the original Monte Carlo implementation from the v1.0 era. `simulator/` is the rewritten production engine introduced in v2.0. The legacy package was retained because `tests/test_simulation.py` (168 tests) validates the original implementation, and removing it would eliminate that test coverage.

### Current State (as of March 2026)

`simulation/__init__.py` has been converted into a **thin compatibility wrapper**:

- It emits a `DeprecationWarning` on import: `"The 'simulation' package is deprecated ... Use 'simulator' instead."`
- It re-exports `VERSION` and `DEFAULT_N_SIMS` from `simulator/` for backward compatibility
- The individual submodule files (`simulation/config.py`, `simulation/game_engine.py`, `simulation/matchup_model.py`, `simulation/prop_analyzer.py`, etc.) remain in place so that all imports in `tests/test_simulation.py` continue to resolve without modification

### Migration Path

To fully retire the `simulation/` package:

1. Update `tests/test_simulation.py` to import from `simulator/` directly
2. Verify all 168 tests pass against the `simulator/` implementations
3. Delete `simulation/` directory

**For all new development, use `simulator/` exclusively.**

---

*For questions about the architecture, open a GitHub Discussion or file an issue with the `architecture` label.*
