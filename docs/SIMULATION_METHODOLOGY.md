# BaselineMLB Monte Carlo Simulation Engine — Methodology

*Last updated: March 2, 2026*

---

## Executive Summary

BaselineMLB is an open-source, plate-appearance–level Monte Carlo simulator that runs 2,500 full-game simulations per matchup to produce probability distributions over individual player stats, then compares those distributions to sportsbook prop lines to identify edges. Unlike season-level projection systems (Steamer, ZiPS, PECOTA) that answer "what will this player do over 600 PA?", BaselineMLB answers "what is the probability this pitcher fans more than 6.5 batters *tonight at Coors Field* with Angel Hernandez behind the plate and a 12 mph wind blowing in?" Every projection is accompanied by a glass-box factor breakdown — park, umpire, catcher framing, weather, platoon — so bettors can understand exactly what is driving each number and make better-informed decisions.

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         DATA INGESTION LAYER                            │
│                                                                         │
│  Baseball Savant ──► StatcastFetcher ──┐                                │
│  MLB Stats API   ──► MLBApiClient  ────┼──► DataPrepPipeline            │
│  Supabase        ──► SupabaseReader ───┤         │                      │
│  OpenWeatherMap  ──► WeatherFetcher ───┘          │                     │
└────────────────────────────────────────────── GameData ─────────────────┘
                                                      │
                                                      ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                       MATCHUP PROBABILITY MODEL                         │
│                                                                         │
│   GameData ──► feature vector (33 cols) ──► MatchupModel                │
│                                                 │                       │
│                   ┌─────────────────────────────┴────────────────────┐  │
│                   │  LightGBM classifier (trained)                   │  │
│                   │  — 8 PA outcome classes                          │  │
│                   │  — falls back automatically if model missing     │  │
│                   └──────────────────┬───────────────────────────────┘  │
│                                      │  if not available                │
│                   ┌──────────────────▼───────────────────────────────┐  │
│                   │  OddsRatioModel (always active fallback)          │  │
│                   │  — generalised log5 formula                      │  │
│                   │  — 5 contextual adjustment layers                 │  │
│                   └──────────────────────────────────────────────────┘  │
│                                      │                                  │
│                       {strikeout, walk, hbp, single, double,            │
│                        triple, home_run, out} → probability vector      │
└──────────────────────────────────────┼──────────────────────────────────┘
                                       │
                                       ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                        GAME SIMULATION ENGINE                           │
│                                                                         │
│   GameData + PA probability vectors                                     │
│        │                                                                │
│        ▼  (× 2,500 Monte Carlo iterations, optionally parallelised)     │
│   GameSimulator.simulate_game()                                         │
│        │                                                                │
│        ├── PA loop: draw outcome → update GameState                     │
│        ├── Baserunner advancement (probabilistic for 1B/2B)             │
│        ├── Pitcher pull (pitch-count distribution)                      │
│        ├── Bullpen: team composite stats                                │
│        ├── Walk-off + Manfred rule (extra innings)                      │
│        └── Accumulate PlayerStats per simulation                        │
│                                                                         │
│   → SimulationResult  (full distribution for every player × stat)      │
└──────────────────────────────────────┬──────────────────────────────────┘
                                       │
                                       ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                           PROP ANALYSIS LAYER                           │
│                                                                         │
│   SimulationResult + PropLine (from The Odds API) → PropAnalyzer        │
│        │                                                                │
│        ├── P(over) / P(under) from simulated distribution               │
│        ├── No-vig implied probability from American odds                │
│        ├── Edge = P(sim) − P(implied)                                   │
│        ├── Kelly criterion bet sizing (quarter-Kelly, 5% cap)           │
│        └── Confidence tiering: HIGH / MEDIUM / LOW / PASS              │
│                                                                         │
│   → PropAnalysis (per player × prop line)                               │
│   → PropReporter: markdown table, JSON, Supabase rows, Twitter post     │
└─────────────────────────────────────────────────────────────────────────┘
```

### Component Inventory

| Module | Class(es) | Role |
|---|---|---|
| `config.py` | `SimulationConfig`, `PAOutcome`, `PARK_FACTORS`, `FEATURE_COLUMNS`, `LEAGUE_AVG_RATES` | Central configuration: all constants, park factors for 30 venues, 33-column feature list, 2024 league-average outcome rates |
| `data_prep.py` | `StatcastFetcher`, `MLBApiClient`, `SupabaseReader`, `WeatherFetcher`, `DataPrepPipeline` | Ingests data from four external sources; outputs a `GameData` object ready for simulation |
| `matchup_model.py` | `TrainedMatchupModel`, `OddsRatioModel`, `MatchupModel` | Predicts per-PA outcome probability vectors; `MatchupModel` is the public façade with automatic fallback |
| `game_engine.py` | `GameState`, `PlayerStats`, `SimulationResult`, `GameSimulator` | Runs the PA-by-PA Monte Carlo game loop; accumulates per-player stat distributions |
| `prop_analyzer.py` | `PropLine`, `PropAnalysis`, `PropAnalyzer`, `PropReporter` | Compares simulation output to sportsbook lines; sizes bets; formats output |
| `train_model.py` | `TrainingDataBuilder`, `ModelTrainer` | Builds the LightGBM training dataset from historical Statcast data; trains and persists the model |

---

## Matchup Probability Model

### Feature Engineering (33 Features)

The input vector fed to the matchup model is defined in `config.FEATURE_COLUMNS` — **order matters** as the scaler and model were fit on this exact column sequence.

#### Pitcher Statcast Features (10)

| Feature | Description | Why It Matters |
|---|---|---|
| `pitcher_k_rate` | Season K% (Ks per PA faced, regressed toward league average) | Direct measure of strikeout output; strongest single-season predictor |
| `pitcher_bb_rate` | Season BB% (walks per PA) | Walk rate; determines whether a PA ends without putting the ball in play |
| `pitcher_hr_rate` | Season HR rate (HRs allowed per PA) | Power-suppression ability; critical for total-bases props |
| `pitcher_whiff_pct` | Swinging-strike rate on pitches in the swing zone | Whiff% correlates r = 0.90 with K% year-over-year — the single strongest K predictor |
| `pitcher_csw_pct` | Called Strikes + Whiffs % | Combines whiffs with called strikes; r = 0.85 with K%; better than whiff% alone for BB prediction |
| `pitcher_zone_pct` | % of pitches thrown in the strike zone | Zone tendencies interplay with umpire K factors; high zone% → more contact, fewer walks |
| `pitcher_swstr_pct` | Swinging-strike rate (all pitches, not just swing-zone) | r = 0.88 with future K%; stronger than velocity for predicting swing-and-miss |
| `pitcher_avg_velo` | Average fastball velocity (mph) | Context feature; velocity alone r ≈ 0.11 with K%, but translates into whiff when combined with movement |
| `pitcher_chase_rate` | O-Swing% — opponent swing rate on pitches outside the zone | Pitchers with high chase rates generate more strikeouts without pitching in the zone |
| `pitcher_iz_contact_pct` | Z-Contact% — opponent contact rate on pitches inside the zone | Lower Z-Contact% → more strikeouts even when the pitch is hittable |

**Why Pitcher Statcast features matter:** Research confirms that traditional stats like ERA and WHIP are noisy, luck-influenced metrics. Statcast-derived rates like SwStr% and whiff% are considerably more stable season-to-season and better predict future performance, as demonstrated by the [Singlearity paper](https://www.baseballprospectus.com/news/article/59993/) and [RotoBallerRotobal K% correlation studies](https://www.rotoballer.com/exploring-k-correlation-pitchers-that-could-improve/1115959).

#### Batter Statcast Features (10)

| Feature | Description | Why It Matters |
|---|---|---|
| `batter_k_rate` | Batter K% (Ks per PA, regressed) | Directly opposes pitcher K rate in the log5 matchup calculation |
| `batter_bb_rate` | Batter BB% | Walk rate; batters with high BB% suppress pitcher K totals |
| `batter_hr_rate` | HR per PA (regressed) | Power; key for HR and total-bases props |
| `batter_xba` | Expected batting average (Statcast EV + launch angle model) | More stable year-to-year than actual BA (r=0.163 vs. 0.140); removes BABIP luck |
| `batter_xslg` | Expected slugging percentage | Best leading indicator of total-bases production; directly captures extra-base hit potential |
| `batter_barrel_pct` | Barrel rate (optimal EV + launch angle zone) | Best single predictor of sustained power and HR production; r² = 0.369 with HR/BBE |
| `batter_hard_hit_pct` | Hard-hit rate (95 mph+ exit velocity) | Drives BABIP and extra-base hit rates; noisy but informative |
| `batter_chase_rate` | Batter O-Swing% — how often the batter chases balls | High chase rate → more strikeouts, fewer walks |
| `batter_whiff_pct` | Batter whiff rate — misses per swing | High whiff rate → high K probability regardless of pitcher |
| `batter_contact_pct` | Overall contact rate on swings | Primary driver of hit production; low contact = high K |

**Why Batter Statcast features matter:** Traditional batting average is a poor input because it mixes luck (BABIP) with skill. Expected stats (xBA, xSLG) based on exit velocity and launch angle isolate the skill signal. [Academic research](https://lup.lub.lu.se/student-papers/record/9175631/file/9175632.pdf) confirms XGBoost models using launch-angle and EV features achieve F2 scores of 90%+ versus 77% for logistic regression with traditional inputs.

#### Matchup Context Features (5)

| Feature | Description | Why It Matters |
|---|---|---|
| `platoon_advantage` | Binary: 1 if batter has opposite-hand advantage | Platoon splits can represent 30–50 points of batting average; applied as a +5% hit boost / −3% K reduction |
| `is_home` | Binary: 1 if batter is the home team | Home/away splits are modest (~.008 OBP) but included for completeness |
| `park_hr_factor` | Park HR factor (from `config.PARK_FACTORS`) | Coors Field HR factor = 1.30; Petco Park = 0.85 — a 53% difference in HR probability |
| `park_k_factor` | Park strikeout factor | Ballparks vary ±8% in strikeout rates due to foul territory size and environmental factors |
| `park_h_factor` | Park hits/BABIP factor | Fenway Park (Green Monster) inflates doubles and BABIP substantially |

#### Game-Day Context Features (2)

| Feature | Description | Why It Matters |
|---|---|---|
| `umpire_k_factor` | Home plate umpire's historical K rate / league average | Some umpires run 10–20% higher K rates; [research](https://aibettingedge.com/using-in-zone-whiff-rate-to-predict-pitcher-strikeout-mlb-prop-bets/) shows umpire identity is a significant K% modifier |
| `catcher_framing_score` | Catcher framing z-score (0 = league average, stored in Supabase) | Elite framers (like José Treviño) add ~20 extra called strikes per season; modeled as +0.025 K probability per standard deviation above average |

#### Recent Form and Market Features (3)

| Feature | Description | Why It Matters |
|---|---|---|
| `pitcher_recent_k_rate` | Pitcher K% over the last 14 days | Captures current form; weighted 60% recent / 40% career in blended stats |
| `batter_recent_ba` | Batter batting average over the last 14 days | Recent slumps and hot streaks are real, particularly over 2-week windows |
| `game_total_line` | Sportsbook over/under total runs line | Market-implied run environment; serves as a Bayesian prior for overall game pace |

#### Weather Features (3)

| Feature | Description | Why It Matters |
|---|---|---|
| `temp_f` | Game-time temperature (°F, from OpenWeatherMap) | Ball carries further in warm air: approximately +0.3% HR probability per °F above 72°F baseline |
| `wind_speed_mph` | Wind speed in mph | Modulates the wind direction effect below |
| `wind_out` | Binary: 1 if wind is blowing toward the outfield wall | A strong wind blowing out (e.g., 15 mph out at Wrigley) adds up to +8% HR probability |

**Why weather matters:** The [BallparkPal Methods](https://www.ballparkpal.com/Methods.html) framework validates that temperature and wind direction measurably shift HR probabilities. A game at Coors Field on a warm day with wind blowing out can have nearly double the HR rate of a cold, wind-in night at Petco Park.

---

### Odds-Ratio Baseline Model

The `OddsRatioModel` implements the generalised log5 / odds-ratio formula described by [SABR — "Matchup Probabilities in Major League Baseball"](https://sabr.org/journal/article/matchup-probabilities-in-major-league-baseball/) (validated on 44,209 PAs from the 2012 season, p-values > 0.1) and extended by the [PLoS ONE Bayesian hierarchical log5 study](https://pmc.ncbi.nlm.nih.gov/articles/PMC6192592/).

#### The Formula

For each of the 8 PA outcome classes *i* ∈ {strikeout, walk, hbp, single, double, triple, home_run, out}:

**Step 1 — Bayesian regression toward league average** (handles small samples):

```
pitcher_rate_i = (pitcher_PA × raw_pitcher_rate_i + regression_PA_i × league_avg_i)
                 / (pitcher_PA + regression_PA_i)

batter_rate_i  = (batter_PA  × raw_batter_rate_i  + regression_PA_i × league_avg_i)
                 / (batter_PA  + regression_PA_i)
```

Regression PA counts are outcome-specific (e.g., HBP = 500 PA regression because it is so rare; strikeout = 200 PA; triple = 600 PA):

| Outcome | Regression PA | Rationale |
|---|---|---|
| strikeout | 200 | Common enough to stabilise quickly |
| walk | 200 | Similar frequency to strikeouts |
| hbp | 500 | Rare — regress heavily toward league mean |
| single | 150 | Most common hit type |
| double | 300 | Moderate rarity |
| triple | 600 | Extremely rare; heavy shrinkage |
| home_run | 300 | Moderate rarity |
| out | 100 | Most common PA result; fast stabilisation |

**Step 2 — Generalised log5 formula (Haechrel / SABR)**:

```
x'_i = (batter_rate_i / league_rate_i) / Σ_j (batter_rate_j / league_rate_j)

P(outcome_i) = (x'_i × pitcher_rate_i) / Σ_j (x'_j × pitcher_rate_j)
```

This is mathematically equivalent to the odds-ratio method for 2-outcome cases and generalises correctly to multi-outcome PA prediction. The property ΣP(outcome_i) = 1.0 is preserved by construction. An average batter facing an average pitcher yields P(outcome_i) = league_rate_i exactly.

#### Step-by-Step Example: Corbin Burnes vs. a Power-Hitting Lineup

*Scenario: Corbin Burnes (K% = 28%) faces a lineup with a collective 26% K rate, at a park with a 1.05 K factor (e.g., Citizens Bank Park), with umpire Angel Hernandez who historically runs an +8% K zone expansion, and an elite catcher framing score of +1.2 standard deviations above average.*

**Starting point — raw log5 K probability:**
- Pitcher K rate: 0.280; Batter K rate: 0.260; League avg K rate: 0.224
- x'_strikeout = (0.260 / 0.224) / Σ = modified batter K tendency
- P(K) ≈ 0.263 (raw log5 result for this matchup)

**Adjustment Layer 1 — Park Factor:**
```
P(K) × park_k_factor = 0.263 × 1.05 = 0.276
(then renormalise all 8 outcomes to sum to 1.0)
```

**Adjustment Layer 2 — Platoon (assume batter has no platoon advantage):**
- No adjustment; platoon is only applied when batter/pitcher hands differ.

**Adjustment Layer 3 — Umpire (+8% zone expansion):**
```
umpire_k_factor = 1.08
P(K) × 1.08 = 0.276 × 1.08 = 0.298
```

**Adjustment Layer 4 — Catcher Framing (+1.2 SD above average):**
```
framing_k_boost = 0.025 per SD → 0.025 × 1.2 = +0.030
P(K) += 0.030 → 0.328
```

**Adjustment Layer 5 — Weather (72°F, no wind effect on K):**
- Weather only adjusts HR probabilities; K is unaffected.

**Final normalisation:** All 8 outcome probabilities are clipped to [0.001, 0.999] and renormalised to sum to exactly 1.0.

**Result:** P(K) for this PA ≈ 0.315–0.330 (vs. 0.263 raw log5) — the umpire and framing layers account for a ~5 percentage point K rate boost above what pitcher and batter rates alone would predict.

#### Contextual Adjustment Summary

| Layer | Adjustment Type | Parameters |
|---|---|---|
| Park factors | Multiplicative on HR, 2B, 3B, 1B then renormalise | 6 factors per park: `hr`, `h`, `k`, `bb`, `2b`, `3b` |
| Platoon | +5% hit prob boost, −3% K reduction when batter has opposite-hand advantage | `_PLATOON_HIT_BOOST = 0.05`, `_PLATOON_K_REDUCTION = 0.03` |
| Umpire | Multiplicative on K and BB by `umpire_k_factor` / `umpire_bb_factor` | Sourced from Supabase umpire composite table |
| Catcher framing | +0.025 K prob per framing z-score SD | `_FRAMING_K_PER_SD = 0.025` |
| Weather | +0.3% HR per °F above 72°F; up to +8% HR for wind blowing out, −6% for wind in | `_WEATHER_TEMP_COEFFICIENT = 0.003`, `_WEATHER_WIND_OUT_BOOST = 0.08` |

---

### LightGBM Trained Model

#### Architecture

- **Algorithm:** LightGBM multi-class gradient-boosted tree classifier (`objective='multiclass'`)
- **Output classes:** 8 (`num_class=8`) — the same `MODEL_OUTCOMES` list as the odds-ratio model
- **Input features:** 33 columns from `config.FEATURE_COLUMNS`, in fixed order
- **Output:** Softmax probability distribution over 8 classes, clipped to [0.001, 0.999] and renormalised

#### Training Data

- **Source:** Baseball Savant Statcast PA-level data, downloaded via monthly chunked CSV queries
- **Seasons:** 2021–2025 (default; configurable via `TrainingDataBuilder`)
- **Scale:** ~1 million PA per season at standard participation thresholds (min 25 BF for pitchers, min 100 PA for batters)
- **Target construction:** Raw Statcast `events` column collapsed into 8 outcome groups via `config.OUTCOME_GROUPS` (e.g., `field_out`, `grounded_into_double_play`, `force_out`, `sac_fly` all map to `"out"`)

#### Anti-Lookahead Measures (Temporal Integrity)

This is critical for producing an unbiased model. Two key safeguards are implemented:

1. **Temporal train/test split:** The test set is always the most recent calendar period (not a random split). The model is evaluated strictly on games it could not have been trained on — a true out-of-sample test.

2. **Rolling stats with prior-game-only window:** For every PA in the training set, the features (pitcher K rate, batter xBA, etc.) are computed using only data from games *prior to that PA's game date*. The `TrainingDataBuilder` processes data in chronological order, maintaining running per-player stat accumulators. This is the most important protection — models trained without this invariant will dramatically overestimate their performance by leaking future information.

#### Hyperparameters (from `train_model.py`)

Defaults used in `ModelTrainer`:

```
objective       = multiclass
num_class       = 8
n_estimators    = 300
learning_rate   = 0.05
max_depth       = 6
num_leaves      = 63
min_child_samples = 50
subsample       = 0.8
colsample_bytree = 0.8
reg_alpha       = 0.1   (L1 regularisation)
reg_lambda      = 1.0   (L2 regularisation)
```

These are conservative defaults optimised to reduce overfitting given ~5M training rows and 33 features.

#### Training Procedure

1. `TrainingDataBuilder.build_training_data()` downloads Statcast CSVs for each season in monthly chunks (April–October), computes rolling features per-PA, maps events to outcome classes, and returns an `(X, y)` DataFrame
2. `ModelTrainer.train()` performs a temporal train/test split (default: last season held out), fits LightGBM, evaluates log-loss and Brier scores on the held-out set, saves the booster to `models/matchup_model.joblib`, and writes evaluation metrics to `models/training_metrics.json`
3. `ModelTrainer.evaluate_calibration()` computes reliability diagrams — checking that predicted probabilities of 30% actually result in strikeouts 30% of the time on held-out data

#### Expected Performance vs. Odds-Ratio Baseline

The Singlearity paper ([Baseball Prospectus](https://www.baseballprospectus.com/news/article/59993/)) established the benchmark hierarchy:

| Data Scenario | ML Model | Log5 | League Average |
|---|---|---|---|
| Extensive (≥502 PA/BF) | **Best** | 2nd | 3rd |
| Some data (150–502) | **Best** | ~League average | 2nd |
| Little data (<100 PA/BF) | **Best** | Worse than league average | 2nd |

The LightGBM model is expected to outperform the odds-ratio fallback in all scenarios once trained, especially for batters with limited historical samples where log5 degrades below league-average accuracy. However, this improvement requires adequate training data — see the Limitations section.

---

## Game Simulation Engine

### How a Single Game Simulation Works

The `GameSimulator.simulate_game()` method drives each of the 2,500 Monte Carlo iterations. Each iteration simulates a complete game from the first pitch through either 9 innings or a walk-off/extra-inning conclusion. The sequence within one iteration:

```
1. Initialise GameState:
      inning=1, half='top', outs=0, runners={1:None,2:None,3:None}
      score={'away':0, 'home':0}
      lineup pointers at batter 0 for each team

2. For each half-inning until game_over():
   a. Determine batting team / fielding team
   b. Look up current pitcher (starter or bullpen composite)
   c. While outs < 3:
       i.  Identify current batter (from lineup_index, wraps at 9)
       ii. Build PA context (park, umpire, weather, framing, platoon)
       iii. Call MatchupModel.predict_pa_probs() → 8-outcome probability vector
       iv.  Draw outcome: numpy RNG choice weighted by probability vector
       v.   Apply outcome to GameState:
               strikeout / out → record_out() + check GDP
               walk / HBP → force_advance_on_walk(batter_id)
               single → advance_runners_probabilistic('single')
               double → advance_runners_probabilistic('double')
               triple → advance_runners(3)
               home_run → advance_runners(4) + batter scores
       vi.  Credit stats to PlayerStats (batter + pitcher sides)
       vii. Advance pitch count; check pitcher pull threshold
   d. switch_sides(): clear bases, reset outs, flip half-inning

3. Walk-off check: if home team takes the lead in the bottom of 9th+,
   end simulation immediately

4. Extra innings: if tied after 9, place Manfred runner on 2B for each
   half-inning (runner_id = -1; runs scored not credited to any batter)

5. Commit per-simulation totals to PlayerStats.finalise_simulation()
```

### Baserunner Advancement Probabilities

Singles and doubles use probabilistic advancement (reflecting the real-world uncertainty in baserunning decisions); home runs and triples use deterministic advancement.

| Situation | Probability | Source |
|---|---|---|
| Single: runner on 1B → scores | 30% | `SINGLE_R1_TO_3B = 0.30` (goes to 3B) |
| Single: runner on 1B → advances to 2B | 70% | Complement of above |
| Single: runner on 2B → scores | 65% | `SINGLE_R2_SCORE = 0.65` |
| Single: runner on 2B → holds at 3B | 35% | Complement |
| Single: runner on 3B → scores | 95% | `SINGLE_R3_SCORE = 0.95` |
| Double: runners on 2B and 3B → score | 100% | Deterministic |
| Double: runner on 1B → scores | 20% | `DOUBLE_R1_SCORE = 0.20` |
| Double: runner on 1B → advances to 3B | 80% | Complement |
| Triple: all runners score | 100% | Deterministic (`advance_runners(3)`) |
| Home run: all runners score | 100% | Deterministic (`advance_runners(4)`) |

Base collisions are handled: if a runner is pushed to an occupied base, they continue advancing until a free base is found, or score if they pass third.

### Grounded Into Double Play (GDP)

When the outcome is a ground-ball out (`"out"`) with a runner on first base and fewer than two outs, a double play is attempted with probability `DEFAULT_GDP_RATE = 0.12` (12%), consistent with the league-average GDP rate for those situations.

### Pitcher Pulling Mechanism

The starter's pitch count is drawn at the start of each simulation from a normal distribution:

```python
pitch_count_limit = Normal(μ=PITCH_COUNT_MEAN, σ=PITCH_COUNT_STD)
# config defaults: μ = 92, σ = 12
# (game_engine.py defaults: μ = 88, σ = 12 — slightly more conservative)
```

After each PA, the pitcher's pitch count is incremented by `AVG_PITCHES_PER_PA = 4.0`. When the running total exceeds the drawn limit, `is_starter_pulled[team] = True` and the bullpen takes over for the rest of the game.

Individual pitcher pitch-count distributions can be set from historical data via `PitcherData.mean_pitch_count` and `PitcherData.std_pitch_count` in the `GameData` object, overriding the defaults.

### Bullpen Handling

When a starter is pulled, the simulator transitions to a team-composite bullpen profile. The bullpen pitcher stats (K rate, BB rate, HR rate, etc.) are computed as the fielding team's aggregate relief statistics from `GameData`. This is a simplification — individual reliever matchups are not modelled (see Limitations).

### Walk-Off Logic and Extra Innings

- **Walk-off:** After the top of the 9th inning (or any extra inning), if the home team is trailing, the bottom half is played. If the home team takes the lead, the game ends immediately mid-inning. The `_walkoff_eligible` flag is set after the top half of inning 9 completes.
- **Extra innings — Manfred runner rule:** When the score is tied after 9 complete innings, each subsequent half-inning begins with a ghost runner placed on second base (`GameState.set_manfred_runner()`). The synthetic runner has `runner_id = -1` and any runs scored by this runner are credited to the team total but not to any individual batter's RBI or runs-scored stats.
- **Safety cap:** Games cannot exceed `MAX_INNINGS = 25`. If this cap is reached (essentially impossible in real play), the game is declared over.

### Number of Simulations and Why 2,500

The default `NUM_SIMULATIONS = 2500` balances statistical precision against computational cost:

- **Precision:** For a binary prop (over/under), the standard error of a proportion estimated from N simulations is √(p(1−p)/N). At N=2500 and p=0.50, SE ≈ 1.0%, which is sufficient for edge detection thresholds of 3–5%.
- **Runtime:** At approximately 70 PA per simulated game and ~50 μs per matchup model call, 2,500 simulations complete in under 60 seconds on a single CPU core. The `GameSimulator` supports parallel execution via `concurrent.futures` for further speedup.
- **Comparison:** BallparkPal uses 3,000 simulations per game. The [thorpe0/strikeout-simulation](https://github.com/thorpe0/strikeout-simulation) repo uses 100,000 iterations but with a much simpler Poisson model (not PA-level). The INFORMS Operations Research batting-order simulation used 200,000 game iterations. BaselineMLB's 2,500 PA-level simulations provide more realistic game-state modelling than a Poisson approximation while remaining tractable for daily use.

---

## Prop Analysis

### How Simulated Distributions Are Compared to Prop Lines

Each player's `PlayerStats` object accumulates a `Counter` distribution — a mapping of `{observed_value: number_of_simulations_with_that_value}` — for every tracked stat (strikeouts, hits, total_bases, home_runs, walks, RBIs, runs_scored, etc.).

For a prop line such as "Corbin Burnes Over 6.5 Ks":

```python
p_over = sum(count for value, count in distribution.items() if value > 6.5) / total_sims
```

This is read directly off the full integer distribution, not approximated by a smooth curve.

### American Odds → No-Vig Implied Probability

American odds include the sportsbook's vig (margin). BaselineMLB removes the vig before computing edge by normalising both sides:

```
Raw implied (over)  = |over_odds| / (|over_odds| + 100)   [if negative odds]
                    = 100 / (over_odds + 100)               [if positive odds]

Raw implied (under) = same formula applied to under_odds

No-vig implied (over)  = raw_implied_over  / (raw_implied_over + raw_implied_under)
No-vig implied (under) = raw_implied_under / (raw_implied_over + raw_implied_under)
```

Example: Over −115 / Under −105
- Raw over: 115/215 = 53.49%
- Raw under: 105/205 = 51.22%
- Total raw: 104.71% (the 4.71% is the vig)
- No-vig over: 53.49% / 104.71% = **51.08%**
- No-vig under: 51.22% / 104.71% = **48.92%**

### Edge Calculation

```
edge_over  = p_over  − no_vig_implied_over
edge_under = p_under − no_vig_implied_under
```

A positive edge means the simulator assigns a higher probability to the outcome than the sportsbook's no-vig line implies. The minimum edge threshold to flag a bet is `EV_THRESHOLD = 0.03` (3%).

### Kelly Criterion Bet Sizing

The Kelly formula maximises long-run bankroll growth given an edge and odds:

```
f* = (b × p − q) / b

where:
  b = decimal_odds − 1   (profit per unit wagered)
  p = simulated P(outcome)
  q = 1 − p

Decimal odds conversion:
  negative American: 1 + (100 / |odds|)   e.g. -115 → 1.8696
  positive American: 1 + (odds / 100)      e.g. +130 → 2.30
```

**Quarter-Kelly safety factor:** The raw Kelly fraction is multiplied by `KELLY_FRACTION = 0.25`. Full-Kelly is theoretically optimal only with perfect probability estimates; in practice, model error and limited sample sizes mean full-Kelly leads to excessive variance. Quarter-Kelly sacrifices ~25% of expected growth rate but dramatically reduces drawdown risk.

**Hard cap:** Even after the quarter-Kelly adjustment, no single bet may exceed `MAX_KELLY_BET = 0.05` (5% of bankroll). This prevents catastrophic exposure on any single game.

### Confidence Tiering

| Tier | Criteria | Interpretation |
|---|---|---|
| **HIGH** | Edge ≥ 8% AND simulation count ≥ 100 | Strong edge with adequate sample; highest conviction plays |
| **MEDIUM** | Edge ≥ 5% | Moderate edge; worth consideration |
| **LOW** | Edge ≥ 3% (the EV_THRESHOLD) | Marginal edge; bet small or wait for confirmation |
| **PASS** | Edge < 3% | No detectable edge; do not bet |

---

## Glass-Box Transparency (Key Differentiator)

Unlike proprietary systems (BallparkPal, THE BAT X) that output a single number with no explanation, BaselineMLB exposes every factor that contributed to each projection through the `MatchupModel.explain_prediction()` method and the `factors` field on every `PropAnalysis`.

### How It Works

The `explain_prediction()` method returns a structured dict containing:

1. **Base log5 probability** — what the odds-ratio formula produces from raw pitcher/batter rates before any adjustments
2. **Per-layer adjustment breakdown** — the multiplier and absolute probability change from each of the five contextual layers (park, platoon, umpire, catcher framing, weather)
3. **Data quality confidence** — derived from sample sizes via `_confidence_from_sample()`, a harmonic mean of pitcher and batter PA quality scores
4. **Feature vector** — the actual 33-value input vector used, visible for inspection

This data is stored in `SimulationResult.game_info['explain_data']` and surfaced in `PropAnalysis.factors`.

### Example Output

For the `PropReporter.format_markdown()` HIGH-confidence plays section:

```
### Corbin Burnes O6.5 Ks — edge=+9.2%

Factors: 
  base_log5_k=0.263 
  | park_k_factor=+1.05 (+1.4pp) 
  | umpire_k_factor=+1.08 (+2.2pp) 
  | catcher_framing=+1.2SD (+3.0pp) 
  | weather=no adjustment 
  | platoon=no advantage
  | data_confidence=0.84 (pitcher 420 BF, batter avg 340 PA)

Simulated mean: 6.8 Ks | P(over 6.5) = 56.3% | Book implied = 47.1% | Edge = +9.2%
```

### Why This Matters

Transparency builds trust in two ways:

1. **Sanity checking:** If the model says "bet over 6.5 Ks" and the explanation shows the umpire K factor as 0.82 (umpire squeezes the zone), but you *know* tonight's umpire is Angel Hernandez (generous zone), something went wrong with the data feed and you should not place the bet. Glass-box outputs let users catch data errors before they become expensive mistakes.

2. **Learning feedback loop:** When a bet loses, the factor breakdown allows post-game attribution analysis — "we gave +8% for umpire K factor but the starter was pulled in the 4th inning before the umpire's tendencies could matter." This drives systematic model improvement over time.

---

## BaselineMLB vs. Competitors

### vs. BallparkPal

[BallparkPal](https://www.ballparkpal.com/Methods.html) is the closest structural analogue to BaselineMLB — it also runs PA-level Monte Carlo simulations.

| Feature | BallparkPal | BaselineMLB |
|---|---|---|
| Simulations per game | 3,000 | 2,500 |
| PA-level resolution | Yes | Yes |
| ML model | Proprietary (100+ features) | LightGBM (33 features) + odds-ratio fallback |
| Umpire integration | No (uses umpire data for other tools) | Yes — PA-level K adjustment |
| Catcher framing | Unknown | Yes — PA-level K adjustment |
| Glass-box explanations | No | Yes — every factor visible |
| Weather integration | Yes (CPW model) | Yes |
| Park factors | Yes (4 per park) | Yes (6 per park: HR, H, K, BB, 2B, 3B) |
| Free / Open source | No ($30+/month) | Yes |
| Trained model available | Yes | Pending (odds-ratio fallback currently active) |

**Assessment:** BallparkPal has the advantage of a trained proprietary model with substantially more features. BaselineMLB's advantages are cost (free), transparency (glass-box explanations), and deeper park factor granularity (6 dimensions vs. 4). The gap will narrow once BaselineMLB's LightGBM model is trained on 5 seasons of Statcast data.

### vs. Steamer / ZiPS / PECOTA

These are **season-level projection systems**, not game simulators. They answer fundamentally different questions:

- **Steamer/ZiPS/PECOTA:** "What will Mike Trout do over ~500 plate appearances in 2026?" — useful for fantasy drafts and season-long analysis
- **BaselineMLB:** "What is the probability Mike Trout records 2+ hits *tonight* vs. Cole at Globe Life Field with wind blowing out?" — useful for daily props

Season-level systems project stable expected performance but cannot incorporate game-specific context: tonight's umpire, current weather, bullpen availability, or recent form over the past 14 days. [PECOTA 2025](https://www.baseballprospectus.com/news/article/96300/) uses a sophisticated aging curve and comparable player methodology, but its output is a point-estimate for the season, not a probability distribution for a single night.

BaselineMLB fills a different niche: game-specific, prop-optimised, with daily context adjustments.

### vs. THE BAT X

[THE BAT X](https://www.fantasypros.com/2026/02/most-accurate-fantasy-baseball-projections-2025-results/) is the top-ranked original projection system per FantasyPros accuracy rankings for 2025 results. It incorporates Statcast data alongside park, weather, umpire, and defensive context — making it the most contextually aware season-level system available.

Key difference: **THE BAT X outputs point estimates; BaselineMLB outputs P(over) for any line.**

- THE BAT X says "Corbin Burnes projects for 220 strikeouts this season" — which implies roughly 5.5 per start but provides no probability distribution around that estimate
- BaselineMLB says "P(Burnes records ≥ 7 Ks tonight) = 41%" — directly actionable for prop betting

The approaches are complementary: BaselineMLB's recent-form and game-specific features could be improved by incorporating THE BAT X's longer-horizon stable projections as a prior.

### vs. Singlearity (Baseball Prospectus)

[Singlearity](https://www.baseballprospectus.com/news/article/59993/) is a neural network PA outcome predictor published by Baseball Prospectus. Direct comparison:

| Dimension | Singlearity | BaselineMLB |
|---|---|---|
| Model architecture | 2-layer neural network | LightGBM + odds-ratio fallback |
| Input features | 79 (includes head-to-head history, game state, fielder IDs) | 33 (Statcast metrics, context, weather) |
| PA outcome classes | 21 (fine-grained Statcast events) | 8 (grouped for prop-relevant resolution) |
| Training data | 1.66M PAs, 2011–2019 | Target: ~5M PAs, 2021–2025 |
| Game-level simulation | Not designed for it | Core use case |
| Umpire integration | No | Yes |
| Catcher framing | No | Yes |
| Weather | Partial (temperature) | Full (temp + wind direction + speed) |
| Prop betting output | Not designed for it | Core use case (P(over) for any line) |
| Open source / free | Academic paper only | Yes |

Singlearity is the gold standard for PA outcome prediction accuracy but is not designed for game-level simulation or prop betting. BaselineMLB trades some outcome resolution (8 classes vs. 21) and feature depth (33 vs. 79) for prop-bet-specific output, game simulation, and daily operational use.

---

## Data Sources

| Source | Access | What We Use |
|---|---|---|
| **[MLB Stats API](https://statsapi.mlb.com/api/v1/)** | Free, no API key required | Daily schedules with probable pitchers, confirmed lineups, team-level stats, platoon splits, historical boxscores |
| **[Baseball Savant / Statcast](https://baseballsavant.mlb.com/)** | Free, no API key required | Pitch-level data for training; leaderboard CSVs for pitcher/batter Statcast season stats (whiff%, xBA, barrel%, etc.); expected stats; arsenal stats |
| **[The Odds API](https://the-odds-api.com/)** | Existing BaselineMLB integration | Prop lines (over/under odds) for all major sportsbooks |
| **[Supabase](https://supabase.com/)** | Existing BaselineMLB tables | Umpire framing composites (`umpire_k_factor`), catcher framing z-scores, historical projections |
| **[OpenWeatherMap](https://openweathermap.org/)** | Free tier (1,000 calls/day) | Game-time temperature (°F), wind speed (mph), wind direction for outdoor ballparks |

Data prep rate limits and caching:
- Baseball Savant: 1.5 seconds between requests (`_SAVANT_RATE_LIMIT`); leaderboard data cached for 1 hour (`_SAVANT_CACHE_TTL = 3600`)
- MLB Stats API: 0.3 seconds between requests (`_MLB_API_RATE_LIMIT`)
- Total pipeline time for a single game's data: **5–10 minutes** (dominated by Savant rate limiting on pitcher and batter lookups)

---

## Limitations & Honest Assessment

1. **Model has not been trained yet.** The odds-ratio fallback is the active prediction mechanism. The LightGBM model in `matchup_model.py` loads gracefully and falls back to `OddsRatioModel` when no saved model file is present at `models/matchup_model.joblib`. Training requires downloading and processing ~5M PAs from Baseball Savant, which takes several hours and significant storage.

2. **33 features vs. BallparkPal's 100+ proprietary features.** BaselineMLB's feature set is deliberately parsimonious — focusing on the highest-signal Statcast metrics — but it will underperform a well-tuned high-feature model on raw accuracy, particularly for outcome classes with more subtle predictors (ground-ball double play rates, sac fly tendencies, etc.).

3. **No stolen base or error modeling.** Stolen base attempts and caught stealings are omitted from the simulation. In 2024, successful steals occurred in roughly 2–3% of base-running situations — small on average but non-trivial in specific matchup contexts (e.g., fast leadoff hitter vs. slow-throwing catcher). Errors are similarly excluded; they affect roughly 1–2% of at-bats.

4. **Bullpen is a team composite, not individual relievers.** When the starter is pulled, the model uses the fielding team's aggregate relief stats. High-leverage situations that bring in an elite closer (e.g., Edwin Díaz vs. a typical middle reliever) are not distinguished. This particularly affects pitcher strikeout totals, where the bullpen can account for 6+ outs after the starter exits.

5. **Lineup batting order is taken as given but can change mid-game.** The simulator holds lineup positions fixed throughout the game. In reality, double switches, pinch hitters, and late-game defensive substitutions alter batting order. This is a minor source of error but impossible to predict pre-game.

6. **Umpire and catcher framing training data gap.** During model training, these factors are only available when umpire assignments have been announced and catcher data loaded from Supabase. PAs in the training set that lack umpire/catcher data will default to neutral values (`umpire_k_factor = 1.0`, `catcher_framing_score = 0.0`), meaning the model partially learns to ignore these features. This can be corrected by backfilling historical umpire assignments into the training data.

7. **Rate limiting on Baseball Savant means data preparation takes 5–10 minutes per game.** For daily use across 15 games, the full data prep pipeline requires 1.5–2.5 hours of wall-clock time if run sequentially. Parallelisation per game reduces this but increases the risk of HTTP 429 (rate limit exceeded) responses.

8. **Calibration has not been validated on real prop line data.** The model has not yet been run against a backtest of historical prop lines to verify that its P(over) estimates are well-calibrated (i.e., that a 60% simulation P(over) actually wins ~60% of the time). Calibration validation is essential before treating the output as reliable EV calculations.

9. **The model is only as good as its inputs — early-season small samples will be noisy.** In April (the first 2–3 weeks of the season), pitchers have 30–80 batters faced in the current season. At these sample sizes, the Bayesian regression toward league average dominates, and individual player projections converge toward the mean. Model output should be treated with extra skepticism until ~400+ BF/PA have accumulated for key players.

---

## Future Improvements

1. **Train the LightGBM model on 5 seasons of Statcast data** (target: before 2026 Opening Day). This is the single highest-impact improvement. The training pipeline in `train_model.py` is complete; it needs to be run, evaluated, and the resulting model file committed.

2. **Individual reliever matchup modeling** instead of team composites. Retrieve reliever usage patterns from the MLB Stats API (most managers have consistent high-leverage reliever assignments) and apply individual reliever stats when the starter exits.

3. **Stolen base and caught stealing probability.** Add base-stealing attempts based on runner speed score (available from Statcast) and catcher arm strength metrics. Most critical for leadoff-heavy lineups with fast runners.

4. **Integrate bat speed and swing metrics** from Baseball Savant bat tracking data (available since 2024). Bat speed and squared-up rate are new leading indicators of contact quality not yet incorporated into the feature set.

5. **Auto-calibration:** Track predicted P(over) vs. actual hit rate across all props in a rolling window and apply a Platt scaling or isotonic regression calibration correction to adjust for systematic over/under-confidence.

6. **Expand to more prop types:** Pitcher outs recorded (`outs_recorded` is already tracked in `PlayerStats`), batter walks, runs + RBIs combined, and first-5-innings lines (truncate simulation at inning 5.5).

7. **Live in-game simulation updates.** The `GameState` architecture supports mid-game initialisation — start a simulation with the current game state (score, runners, inning, pitch count) to update P(over) in real time as the game progresses.

8. **Upgrade to a neural network** (Singlearity-style) once 5+ seasons of training data with umpire and framing annotations are available. The Singlearity architecture (2 hidden layers × 80 nodes, 79 inputs, 21 outputs) is the documented gold standard and a natural evolution of the current LightGBM model.

---

## How to Train and Run

### Training the LightGBM Model

```bash
# Train on 2021–2025 Statcast data
python -m simulation.train_model \
    --seasons 2021 2022 2023 2024 2025 \
    --cache-dir data/statcast_cache \
    --output-dir models/

# Quick validation run (10% sample, single season)
python -m simulation.train_model \
    --seasons 2024 \
    --sample-frac 0.1 \
    --output-dir models/test/

# Training produces:
#   models/matchup_model.joblib   (LightGBM booster)
#   models/feature_scaler.joblib  (StandardScaler)
#   models/training_metrics.json  (log-loss, Brier scores, calibration)
```

### Running Daily Simulations

```python
from simulation.config import SimulationConfig
from simulation.data_prep import DataPrepPipeline
from simulation.game_engine import GameSimulator
from simulation.matchup_model import MatchupModel
from simulation.prop_analyzer import PropAnalyzer, PropReporter

# 1. Load config and model
cfg = SimulationConfig(NUM_SIMULATIONS=2500)
model = MatchupModel(model_path="models/matchup_model.joblib")
simulator = GameSimulator(config=cfg, matchup_model=model)
analyzer = PropAnalyzer(config=cfg)
reporter = PropReporter()

# 2. Fetch today's game data
pipeline = DataPrepPipeline()
game_data = pipeline.prepare_game(game_pk=<game_pk>, game_date="2026-04-03")

# 3. Simulate and analyze
sim_result = simulator.simulate_game(game_data)

# 4. Fetch prop lines (via existing Odds API integration) and analyze
analyses = analyzer.analyze_game(sim_result, prop_lines)

# 5. Output
print(reporter.format_markdown(analyses, sim_result.game_info))
```

### Environment Variables Required

```bash
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_KEY=your-anon-key
OPENWEATHER_API_KEY=your-key   # optional; defaults used if absent
ODDS_API_KEY=your-key           # for prop line fetching
```

---

## References

- [BallparkPal Methods](https://www.ballparkpal.com/Methods.html) — PA-level Monte Carlo simulation methodology, park factor construction, and weather (CPW) model
- [Baseball Prospectus — Singlearity-PA](https://www.baseballprospectus.com/news/article/59993/) — Neural network PA outcome prediction; 79-feature, 21-class architecture; benchmark vs. log5
- [SABR — Matchup Probabilities in Major League Baseball](https://sabr.org/journal/article/matchup-probabilities-in-major-league-baseball/) — Generalised log5 / Haechrel formula; validation on 44,209 PAs
- [PLoS ONE — Bayesian Hierarchical Log5](https://pmc.ncbi.nlm.nih.gov/articles/PMC6192592/) — Bayesian extension of log5 with shrinkage toward league averages; superiority over standard log5 with small samples
- [thorpe0/strikeout-simulation](https://github.com/thorpe0/strikeout-simulation) — Open-source K prop model using XGBoost + Poisson Monte Carlo; 7 features; architectural reference
- [FantasyPros — Most Accurate Baseball Projections 2025 Results](https://www.fantasypros.com/2026/02/most-accurate-fantasy-baseball-projections-2025-results/) — THE BAT X ranked #1 original projection system; basis for competitor comparison
- [Baseball Prospectus — PECOTA 2025 Introduction](https://www.baseballprospectus.com/news/article/96300/) — Season-level projection methodology using aging curves and comparable players
- [MLB Data Warehouse — Projection Wars: Which System Is Best?](https://www.mlbdatawarehouse.com/p/projection-wars-which-system-is-best) — Cross-system accuracy comparison across Steamer, ZiPS, PECOTA, THE BAT X, and others
