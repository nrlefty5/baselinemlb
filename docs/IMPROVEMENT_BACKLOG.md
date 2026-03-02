# BaselineMLB — Improvement Backlog

> Generated: 2026-03-02 (Continuous Improvement Cycle #1)

## Component Grades (Phase 1 Audit)

| Component | Grade | Notes |
|-----------|-------|-------|
| **Pipeline (pipeline/)** | B | Core scripts work with proper env vars. `generate_projections.py` and `generate_batter_projections.py` have solid math. Missing `PYTHONPATH` in pipelines.yml may cause import issues. |
| **Scripts (scripts/)** | D | `grade_accuracy.py` is **BROKEN** — file has no line terminators (single escaped-string blob, 14,950 bytes, 0 newlines). 4 duplicate scripts overlap with pipeline/. |
| **Simulator (simulator/)** | B- | Engine works. `test_simulator.py` fails to collect — imports `N_OUTCOMES`, `K_IDX`, `BB_IDX`, etc. that don't exist in `monte_carlo_engine.py`. 90 tests blocked. |
| **Simulation (simulation/)** | B+ | 130 tests pass. Comprehensive game engine, matchup model, prop analyzer. Separate from simulator/ with unclear relationship. |
| **Models (models/)** | B | Well-structured LightGBM pipeline. Untrained (no training data parquet yet). Correct architecture. |
| **Frontend (frontend/)** | B | Next.js 14 + Supabase. Dark theme, responsive. Accuracy page uses hardcoded backtest data. |
| **GitHub Actions** | C+ | 8 workflow files. `pipelines.yml` missing `PYTHONPATH` env var. CI runs tests but test_simulator.py breaks collection. Overnight job calls broken `grade_accuracy.py`. |
| **Supabase Schema** | A- | Comprehensive 16-table schema with RLS, indexes, proper constraints. Well-organized. |
| **Documentation** | B+ | 6 methodology docs, README, architecture spec. No improvement log or changelog. |
| **Tests** | C | 27 projection tests pass, 130 simulation tests pass. But 90 simulator tests blocked by import error. Total: 157/247 passing. |
| **Code Quality (Ruff)** | C- | 163 lint errors: 44 unused imports, 29 unsorted imports, 24 whitespace issues, 21 syntax issues, 15 f-string issues. |

**Overall Grade: C+** — Strong foundation with critical breakages preventing end-to-end operation.

---

## Ranked Improvements (Top 5)

### 1. 🔴 FIX: `scripts/grade_accuracy.py` is a broken single-line blob
- **Impact**: CRITICAL — overnight pipeline job fails silently, no accuracy grading happens
- **Category**: Fixing broken code
- **Details**: File is 14,950 bytes with zero line terminators. All `\n` are escaped as `\\n`. The `backtest_weekly.yml` workflow imports `run_grading` from this file — it will crash.
- **Fix**: Rewrite the file with proper newlines from the escaped content

### 2. 🔴 FIX: `tests/test_simulator.py` import error blocks 90 tests
- **Impact**: HIGH — CI test suite broken, can't validate simulator changes
- **Category**: Fixing broken code
- **Details**: Test imports `N_OUTCOMES`, `K_IDX`, `BB_IDX`, `SINGLE_IDX`, `DOUBLE_IDX`, `TRIPLE_IDX`, `HR_IDX`, `FLYOUT_IDX`, `GROUNDOUT_IDX`, `HIT_INDICES`, `OUT_INDICES`, `MLB_AVG_PROBS` plus several functions that don't exist in `simulator/monte_carlo_engine.py`
- **Fix**: Add the missing constants/exports to `monte_carlo_engine.py`

### 3. 🟡 FIX: `pipelines.yml` missing PYTHONPATH causes import resolution issues
- **Impact**: MEDIUM — pipeline jobs may fail when scripts import from `lib/` or cross-package
- **Category**: Fixing broken code
- **Details**: The `ci.yml` correctly sets `PYTHONPATH: ${{ github.workspace }}` but `pipelines.yml` does not. Scripts like `grade_accuracy.py` that import from `lib/` will fail.
- **Fix**: Add `PYTHONPATH: ${{ github.workspace }}` to pipelines.yml env block

### 4. 🟡 IMPROVE: Fix 163 Ruff lint errors across codebase
- **Impact**: MEDIUM — code quality, maintainability, potential hidden bugs from unused imports
- **Category**: Code quality
- **Details**: 111 auto-fixable errors (unused imports, unsorted imports, whitespace). 52 need manual review.
- **Fix**: Run `ruff check --fix` for auto-fixable, manually address remaining

### 5. 🟢 IMPROVE: Clean up duplicate scripts/ vs pipeline/ files
- **Impact**: LOW-MEDIUM — confusion about which version is authoritative
- **Category**: Code organization
- **Details**: `fetch_games.py`, `fetch_players.py`, `fetch_props.py`, `fetch_statcast.py` exist in both `scripts/` and `pipeline/`. Workflows use `pipeline/` versions. `scripts/` copies are stale.
- **Fix**: Remove or clearly deprecate the scripts/ duplicates

---

## Additional Improvements (Queued)

6. Consolidate `simulation/` and `simulator/` directories into one canonical package
7. Wire accuracy page to live Supabase data instead of hardcoded backtest values
8. Add PYTHONPATH to all GitHub Actions workflows consistently
9. Train LightGBM model on available Statcast data before Opening Day
10. Add integration test that validates full `make simulate` pipeline with mocked APIs
