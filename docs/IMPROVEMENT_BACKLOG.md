# BaselineMLB — Improvement Backlog

> Generated: 2026-03-02 (Continuous Improvement Cycle #4)

## Component Grades (Phase 1 Audit — Cycle #4)

| Component | Cycle #3 Grade | Cycle #4 Grade | Delta | Notes |
|-----------|---------------|---------------|-------|-------|
| **Pipeline (pipeline/)** | A- | A- | = | All 10 pipeline scripts compile cleanly with lazy Supabase init. |
| **Scripts (scripts/)** | B | B | = | `backtest_simulator.py` and `integration_test.py` have intentional stub fallbacks. |
| **Simulator (simulator/)** | B+ | B+ | = | 4,421 lines, full compatibility layer, 76 simulator tests pass. |
| **Simulation (simulation/)** | B+ | **B** | ↓ | 8,636 lines. Unused outside its own tests. Pure tech debt — no production code imports from it. |
| **Models (models/)** | B | B | = | Untrained (no Statcast parquet data yet). Architecture is solid. |
| **Frontend (frontend/)** | B+ | B+ | = | Next.js 14.1.0. Pages for simulator, accuracy, projections, players, best-bets. |
| **GitHub Actions** | A- | **B** | ↓ | `morning_data_refresh.yml` references deleted `scripts/fetch_statcast.py` (CRITICAL). Overlaps with `pipelines.yml`. Deprecated `static.yml` still present. |
| **Supabase Schema** | A- | **B+** | ↓ | 6 migration files with duplicate CREATE TABLE statements (3x `simulation_results`, 3x `email_subscribers`, etc.). Needs consolidation. |
| **Documentation** | A- | A- | = | Full improvement log, backlog, architecture, methodology docs. |
| **Tests** | A | **A** | = | **244/244 passing (100%).** Zero regressions. |
| **Code Quality (Ruff)** | A | **A-** | ↓ | 4 E402 errors in `test_simulation.py` (deliberate — sys.path insertion before imports). |
| **Overall** | **B+** | **B+** | = | No regressions, but lingering tech debt from Cycles #1-3 needs resolution. |

---

## Ranked Improvements (Top 5)

### 1. CRITICAL: Fix `morning_data_refresh.yml` broken script reference
- **Impact**: CRITICAL — workflow runs daily at 7 AM ET and crashes because `scripts/fetch_statcast.py` was deleted in Cycle #2. The Cycle #3 fix only patched `pipelines.yml` but missed this separate workflow.
- **Category**: Fix broken (production failure)
- **Details**: Line 52 references `python scripts/fetch_statcast.py`. Must change to `python pipeline/fetch_statcast.py`. Also evaluate whether this entire workflow is redundant with `pipelines.yml` which runs 1 hour later and does the same work.
- **Effort**: Small

### 2. HIGH: Consolidate duplicate workflows (`morning_data_refresh.yml` + `pipelines.yml`)
- **Impact**: HIGH — two workflows do overlapping work (both fetch statcast + props) at nearly the same time (11:00 UTC and 12:00 UTC). `morning_data_refresh.yml` also has inline Python for rolling stats that doesn't exist as a standalone script.
- **Category**: Fix broken / code organization
- **Details**: Merge the unique value from `morning_data_refresh.yml` (rolling stats computation, park factor refresh) into `pipelines.yml`, then remove the duplicate workflow. Also remove deprecated `static.yml`.
- **Effort**: Medium

### 3. HIGH: Consolidate `simulation/` and `simulator/` into one package
- **Impact**: HIGH — 13,057 total lines across two packages doing overlapping simulation work. `simulation/` is NOT imported by any production code — only its own test file uses it. The `simulator/` package is the canonical one used by pipelines, backtest, and integration test.
- **Category**: Technical debt (carried since Cycle #1)
- **Details**: Make `simulation/` re-export from `simulator/` so tests still pass, or migrate `test_simulation.py` to import from `simulator/` directly and delete `simulation/`.
- **Effort**: Large (1,427-line test file to migrate)

### 4. MEDIUM: Consolidate Supabase migration files
- **Impact**: MEDIUM — 6 migration files with duplicate CREATE TABLE definitions cause confusion about what the actual schema is. Tables like `simulation_results`, `email_subscribers`, `model_artifacts` are defined 2-3 times across different files.
- **Category**: Code organization
- **Details**: Consolidate into a clean single migration file or a properly numbered sequential set. Ensure `supabase/schema.sql` is the single source of truth.
- **Effort**: Medium

### 5. MEDIUM: Remove deprecated files and clean project structure
- **Impact**: MEDIUM — `analysis/projection_model.py` (deprecated stubs), `dashboard/` (replaced by Vercel), `static.yml` (disabled workflow) are dead code that creates noise in audits.
- **Category**: Cleanup
- **Details**: Delete `analysis/projection_model.py`, `dashboard/` directory, and `.github/workflows/static.yml`. Archive to a single `DEPRECATED.md` note if desired.
- **Effort**: Small

---

## Additional Improvements (Queued)

6. Fix E402 lint errors in `test_simulation.py` (move sys.path manipulation into conftest.py)
7. Train LightGBM model on Statcast data before Opening Day (March 27)
8. Wire accuracy dashboard to live Supabase data
9. Add integration test for full `make simulate` pipeline with mocked APIs
10. Wire newsletter + Twitter automation into GitHub Actions
