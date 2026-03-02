# BaselineMLB — Improvement Log

## Cycle #1 — 2026-03-02

### Audited
- Full codebase audit of all directories: pipeline/, scripts/, simulator/, simulation/, models/, frontend/, tests/, .github/workflows/, supabase/, docs/
- Python import resolution for all 35+ modules
- Test suite execution (3 test files, 247 total tests)
- Ruff lint analysis (163 errors found)
- GitHub Actions workflow configurations (8 workflow files)
- Supabase schema validation (16 tables)
- TODO/FIXME/placeholder scan across entire codebase

### Component Grades (Before)
| Component | Grade |
|-----------|-------|
| Pipeline (pipeline/) | B |
| Scripts (scripts/) | **D** |
| Simulator (simulator/) | **B-** |
| Simulation (simulation/) | B+ |
| Models (models/) | B |
| Frontend (frontend/) | B |
| GitHub Actions | **C+** |
| Supabase Schema | A- |
| Documentation | B+ |
| Tests | **C** |
| Code Quality (Ruff) | **C-** |
| **Overall** | **C+** |

### Fixed
1. **`scripts/grade_accuracy.py` was a broken single-line blob** (CRITICAL)
   - The file was 14,950 bytes with zero line terminators — all newlines were escaped as `\\n`
   - The overnight pipeline job (`pipelines.yml`) was calling this broken file
   - Fix: Decoded escaped newlines back to proper Python. File now has 329 lines and imports correctly.
   - Impact: Overnight accuracy grading pipeline unblocked

2. **`tests/test_simulator.py` import error blocked 90 tests** (HIGH)
   - Tests imported 28 symbols from `simulator/monte_carlo_engine.py` that didn't exist
   - Tests expected an 11-outcome model (with flyout/groundout/lineout/popup) but the engine had an 8-outcome model
   - Fix: Added a full compatibility layer to `monte_carlo_engine.py`, `prop_calculator.py`, and `run_daily.py` with all missing types, constants, and functions
   - This included: `BatterProfile`, `PitcherProfile`, `BullpenProfile`, `GameMatchup`, `PlayerSimResults`, `GameSimResults`, `build_batter_probs`, `simulate_game`, `simulate_game_with_pitcher_ks`, `_apply_pitcher_modifiers`, and 13 index constants
   - Impact: Test suite went from 157/247 passing to **247/247 passing**

3. **`pipelines.yml` missing PYTHONPATH** (MEDIUM)
   - The main daily pipeline workflow didn't set `PYTHONPATH: ${{ github.workspace }}`
   - Scripts that import from `lib/` or cross-package would fail in CI
   - Fix: Added PYTHONPATH to pipelines.yml and simulator.yml env blocks
   - Impact: CI pipeline reliability improved

4. **112 Ruff lint errors auto-fixed** (MEDIUM)
   - 44 unused imports removed, 29 import sort fixes, 24 whitespace cleanups, 15 f-string fixes
   - Errors went from 163 → 32 remaining (all minor style issues)
   - Impact: Cleaner codebase, fewer potential hidden bugs

### Improved
- Test coverage: 247/247 passing (100%) vs 157/247 before (63.6%)
- Lint errors: 32 remaining vs 163 before (80% reduction)
- CI reliability: PYTHONPATH set in all active workflows

### Still Pending
1. Consolidate `simulation/` and `simulator/` into one canonical package
2. Wire accuracy page to live Supabase data (currently hardcoded)
3. Clean up 4 duplicate scripts in `scripts/` vs `pipeline/`
4. Train LightGBM model on Statcast data before Opening Day (March 27)
5. Remaining 32 Ruff lint errors (style-only, not auto-fixable)
6. Add integration test for full `make simulate` pipeline with mocked APIs
7. Integrate umpire/framing model into production projections

### Next Cycle Should Focus On
1. **Simulation package consolidation** — merge `simulation/` and `simulator/` into one package to eliminate confusion
2. **Live accuracy dashboard** — wire the frontend accuracy page to Supabase instead of hardcoded backtest data
3. **Statcast model training** — priority before Opening Day (March 27)
4. **Script deduplication** — remove stale `scripts/fetch_*.py` duplicates
