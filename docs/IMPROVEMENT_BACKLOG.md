# BaselineMLB — Improvement Backlog

> Generated: 2026-03-02 (Continuous Improvement Cycle #3)

## Component Grades (Phase 1 Audit — Cycle #3)

| Component | Cycle #2 Grade | Cycle #3 Grade | Delta | Notes |
|-----------|---------------|---------------|-------|-------|
| **Pipeline (pipeline/)** | B+ | **A-** | up | `fetch_statcast.py` refactored with lazy Supabase init. All 10 pipeline scripts compile cleanly. |
| **Scripts (scripts/)** | B- | **B** | up | Broken `scripts/fetch_statcast.py` reference removed. `grade_accuracy.py` compiles. Stubs in `backtest_simulator.py` are intentional fallbacks. |
| **Simulator (simulator/)** | B | **B+** | up | 4,421 lines, full compatibility layer, all 76 simulator tests pass. |
| **Simulation (simulation/)** | B+ | B+ | = | 8,636 lines. Still separate package from `simulator/` — consolidation deferred. |
| **Models (models/)** | B | B | = | Untrained (no Statcast parquet data yet). Architecture is solid. |
| **Frontend (frontend/)** | B+ | B+ | = | Next.js 14.1.0. Pages for simulator, accuracy, projections, players, best-bets. |
| **GitHub Actions** | B- | **A-** | up | Consolidated duplicate simulator workflows. Fixed broken Statcast reference in overnight pipeline. 7 workflows, all structurally sound. |
| **Supabase Schema** | A- | A- | = | 16 tables in master schema. RLS enabled on all. |
| **Documentation** | A- | A- | = | Full improvement log, backlog, architecture, methodology docs. |
| **Tests** | A | **A** | = | **244/244 passing (100%).** Zero regressions. |
| **Code Quality (Ruff)** | A | **A** | = | **0 lint errors** across all Python files (pipeline, scripts, lib, tests, simulation, simulator, models, analysis). |
| **Overall** | **B-** | **B+** | up | All critical CI/pipeline blockers resolved. |

---

## Ranked Improvements (Top 5)

### 1. CRITICAL: Consolidate `simulation/` and `simulator/` into one package
- **Impact**: HIGH — two separate packages (13,057 total lines) doing overlapping work creates confusion, maintenance burden, and import complexity.
- **Category**: Code organization / technical debt
- **Details**: `simulation/` (8,636 lines, 8 files) has its own game engine, model, config. `simulator/` (4,421 lines, 3 files) has the MC engine with compatibility layer. Tests import from both. Merging would simplify the dependency graph significantly.
- **Effort**: Large (needs careful cross-module dependency mapping)

### 2. HIGH: Train LightGBM model on Statcast data
- **Impact**: HIGH — the ML model architecture is fully built (`models/matchup_model.py`, `models/train_model.py`, `models/predict.py`) but untrained. The Statcast pipeline (`pipeline/fetch_statcast_historical.py`) can fetch training data, and `pipeline/build_training_dataset.py` can build the feature matrix. Opening Day is March 27.
- **Category**: Model accuracy improvement
- **Details**: Need to: (1) run `fetch_statcast_historical.py` to build `data/statcast_pa_features_2020_2025.parquet`, (2) run `build_training_dataset.py`, (3) run `train_model.py` to produce a trained artifact.
- **Effort**: Medium (infrastructure exists, needs data + compute)

### 3. MEDIUM: Wire accuracy dashboard to live Supabase data
- **Impact**: MEDIUM — the accuracy page (`frontend/app/accuracy/page.tsx`) and GitHub Pages dashboard (`dashboard/index.html`) still show hardcoded/static backtest data rather than live accuracy from Supabase.
- **Category**: User experience improvement
- **Details**: The `accuracy_summary` table exists in Supabase. The frontend needs to fetch from it instead of using embedded constants.
- **Effort**: Small-Medium

### 4. MEDIUM: Add integration test for `make simulate` pipeline
- **Impact**: MEDIUM — no end-to-end test validates the full pipeline with mocked APIs. Tests currently only cover unit-level simulator components.
- **Category**: Testing / reliability
- **Details**: Create a pytest fixture that mocks MLB Stats API + Supabase + Odds API responses and runs through the full simulate flow.
- **Effort**: Medium

### 5. LOW: Remove deprecated `analysis/projection_model.py`
- **Impact**: LOW — already marked deprecated, 229 lines with 6 stub functions returning 0.0. Superseded by `pipeline/generate_projections.py` v2.0. Keeping it creates false audit signals.
- **Category**: Cleanup
- **Details**: The file is marked `[DEPRECATED]` in its docstring but is still checked by lint and shows up in audits as having "stubs". Could be deleted or moved to an `archive/` directory.
- **Effort**: Small

---

## Additional Improvements (Queued)

6. Add proper error handling and retry logic to `pipeline/fetch_players.py` (crashes on import without env vars)
7. Integrate umpire/framing model into production projections (the logistic regression model in `analysis/umpire_framing_model.py` is disconnected from production)
8. Add email newsletter automation to GitHub Actions (pipeline/send_newsletter.py exists but is not wired)
9. Add Twitter auto-posting to GitHub Actions (pipeline/post_to_twitter.py exists but is not wired)
10. Expand backtest to full 2025 season (currently only July data validated)
