# BaselineMLB Betting Strategy Guide

*A comprehensive reference for profitable MLB player prop betting, built for the BaselineMLB projection system.*

---

## Table of Contents

1. [Bankroll Management](#1-bankroll-management)
2. [Closing Line Value (CLV) & Profitability](#2-closing-line-value-clv--profitability)
3. [Bet Sizing by Confidence Tier](#3-bet-sizing-by-confidence-tier)
4. [Best Sportsbooks for MLB Props](#4-best-sportsbooks-for-mlb-props)
5. [MLB Prop Strategy Playbook](#5-mlb-prop-strategy-playbook)
6. [Using the Edge Finder](#6-using-the-edge-finder)

---

## 1. Bankroll Management

### The Kelly Criterion

The Kelly Criterion, developed by Bell Labs scientist John Kelly Jr., is the gold standard for mathematically optimal bet sizing. It maximizes long-term geometric bankroll growth while minimizing ruin risk.

**Formula:**

```
f* = (bp - q) / b

Where:
  f* = fraction of bankroll to wager
  b  = net odds received (decimal odds - 1)
  p  = probability of winning
  q  = probability of losing (1 - p)
```

**Example:** A coin toss with 55% win probability at even money (+100):
- p = 0.55, q = 0.45, b = 1.0
- f* = (1 × 0.55 − 0.45) / 1 = **10% of bankroll**

Full Kelly produces mathematically optimal growth but carries extreme volatility. Research by [Harry Crane](https://harrycrane.substack.com/p/two-arguments-for-fractional-kelly) shows that with a 10% edge, there is a **46% probability of losing 50% of your bankroll** in the first 1,000 rounds using Full Kelly.

### Why Quarter Kelly (0.25x)

BaselineMLB's Edge Finder defaults to **Quarter Kelly (25%)** — the most widely recommended starting point for model-based bettors.

| Kelly Fraction | Probability of 50% Drawdown (1,000 bets) | Growth Rate vs. Full Kelly |
|---|---|---|
| 100% (Full) | 46% | 100% (maximum) |
| 50% (Half) | 11% | ~75% |
| **25% (Quarter)** | **0.8%** | **~50%** |
| 10% | <0.1% | ~19% |

Source: [Harry Crane — Two Arguments for Fractional Kelly](https://harrycrane.substack.com/p/two-arguments-for-fractional-kelly)

Quarter Kelly cuts growth rate to roughly half of full Kelly but reduces the probability of a devastating 50% drawdown from 46% to under 1%. This is the right trade-off for a projection model that has inherent uncertainty in its probability estimates.

**Progression:**
- Start at **Quarter Kelly** until you have 500+ tracked bets with a proven edge
- Progress to **Half Kelly** only with a long, validated record ([ScoutingStats](https://scoutingstats.ai/blog/kelly-calculator-guide))
- Use **Eighth Kelly (12.5%)** for high-variance props or uncertain edge estimates ([OddsIndex](https://oddsindex.com/guides/kelly-criterion-calculator))

### Fixed Unit Sizing

For bettors who prefer simplicity over Kelly optimization:

| Unit Size | Risk Level | Best For |
|---|---|---|
| 1% of bankroll | Very Conservative | Sharp bettors, high-volume players |
| 2% of bankroll | Conservative | Serious recreational bettors |
| 3% of bankroll | Moderate | Recreational bettors with proven edge |
| 4-5% of bankroll | Aggressive | Small bankrolls, entertainment focus |

Source: [Sports Insights](https://www.sportsinsights.com/how-to-bet-on-sports/bankroll-management/betting-unit-size/) — *"Professional bettors' betting unit sizes are normally in the 1% range."*

### Props Carry Higher Variance

Player props carry roughly **2x the standard deviation** of point spreads. For a 55% win prop at -110 over 100 bets ([Wizard of Odds](https://wizardofodds.com/article/variance-and-bankroll-management-for-player-props/)):
- Expected profit: $500
- Standard deviation: $950
- 95% confidence interval: **-$1,362 to +$2,362**

**Implications:**
- Use **smaller unit sizes (0.5-1%)** for props vs. the 2-3% you'd use for sides
- When betting 4+ simultaneous props, reduce each bet to half of your normal sizing to account for correlated variance
- Never exceed **5% of bankroll** on any single wager regardless of confidence

### Recommended Bankroll by Bettor Type

| Type | Starting Bankroll | Unit Size |
|---|---|---|
| Recreational | $200–$500 | $4–$15 per bet |
| Serious Hobbyist | $1,000–$5,000 | $10–$50 per bet |
| Semi-Professional | $5,000–$20,000 | $50–$200 per bet |
| Professional | $20,000+ | $200+ per bet |

Source: [Xclsv Media](https://xclsvmedia.com/sports-betting-bankroll-management-guide-2026-how-to-protect-and-grow-your-betting-funds/)

### Daily Limits

- Never wager more than **20% of bankroll** on a single day's card
- Recalculate unit size before each session based on current bankroll balance — this automatically reduces risk during losing streaks
- Consider increasing unit size only when up 25%+ from starting bankroll; decrease immediately if down 25%+

Source: [OddsIndex Bankroll Management Guide](https://oddsindex.com/guides/bankroll-management-guide)

---

## 2. Closing Line Value (CLV) & Profitability

### What Is CLV?

Closing Line Value measures whether the odds you bet are better or worse than the final line before game time. The closing line represents the market's most accurate probability estimate — it has absorbed all available information including sharp action, injury reports, weather updates, and lineup confirmations.

**Example:**
- You bet Aaron Nola Over 6.5 K at **-115**
- Line closes at **-135**
- You have **positive CLV** — you locked in better value than the final efficient price

### Why CLV Is the Best Predictor of Long-Term Profit

Consistently beating the closing line is the single strongest indicator that a bettor has a genuine edge. Sportsbooks use CLV as their primary metric to identify and limit sharp accounts.

**Data points:**

| CLV Beat Rate | Assessment |
|---|---|
| <50% | Negative expected value; losing long-term |
| 50-55% | Break-even range |
| 55-60% | Likely marginally profitable |
| 60-65% | Strong sharp bettor territory |
| 65-75% | Excellent — expect account limits |
| 75%+ | Elite; rapid account restrictions |

Source: [Boyd's Bets](https://www.boydsbets.com/closing-line-value/), [VSiN](https://vsin.com/how-to-bet/the-importance-of-closing-line-value/)

**RebelBetting data** on value bettors who beat the closing line >80% of the time:
- 100+ monthly bets: **79.7% of bettors are profitable**
- 500+ monthly bets: **90.0% of bettors are profitable**

Source: [RebelBetting](https://www.rebelbetting.com/faq/expected-value-and-variance)

### CLV Benchmarks for MLB

- **Main markets (sides, totals):** Use **Pinnacle's no-vig closing line** as the benchmark
- **Player props:** Use **FanDuel's closing line** — FanDuel operates as the sharpest reference book for MLB secondary markets per [Pikkit's weighted-market analysis](https://pikkit.com/blog/which-sportsbooks-are-sharp)

**Important nuance:** CLV is most reliable in highly liquid markets. MLB prop markets are less liquid, so line movement may reflect liability management rather than sharp action. A high CLV beat rate on props is still meaningful, but requires a larger sample size (500+ bets) to be statistically significant.

### How to Calculate CLV

**Win probability method (recommended for props):**
1. Convert your entry odds to implied probability (remove vig)
2. Convert closing odds to implied probability (remove vig)
3. CLV = Closing implied probability − Entry implied probability

**Example:**
- Bet at -120 (implied: 54.55%), closes at -170 (implied: 62.96%)
- CLV = 62.96% − 54.55% = **+8.41% win probability improvement**

Source: [SportsBettingDime](https://www.sportsbettingdime.com/guides/betting-101/closing-line-value/)

### Tracking CLV with BaselineMLB

The `scripts/track_clv.py` script in the BaselineMLB repo already tracks CLV. Combine it with the Edge Finder to:
1. Record the line at time of recommendation (`find_edges.py` output)
2. Record the closing line just before first pitch
3. Calculate CLV for every play
4. Track your CLV beat rate over time — aim for **60%+**

---

## 3. Bet Sizing by Confidence Tier

### Edge-to-Unit Mapping

BaselineMLB's Edge Finder assigns confidence tiers based on the projection edge (the gap between projected value and the prop line).

| Edge Size | Confidence Tier | Recommended Units | Kelly Equivalent |
|---|---|---|---|
| 0-5% | LOW | 0.5-1 unit | Eighth Kelly |
| 5-10% | LOW-MEDIUM | 1-2 units | Quarter Kelly |
| 10-20% | MEDIUM | 2-3 units | Quarter-Half Kelly |
| 20%+ | HIGH | 3-5 units | Half Kelly |

Source: [OddsIndex Kelly Guide](https://oddsindex.com/guides/kelly-criterion-calculator)

### Practical Framework

**Start with flat betting:**
- For your first 500 tracked bets, use flat 1-unit bets on every play the model recommends
- This establishes your baseline hit rate and ROI without the noise of variable sizing

**Graduate to tiered sizing:**
- After 500+ bets with a proven edge, move to **3 tiers maximum**: 1u, 1.5u, 2u
- This captures Kelly-like upside while maintaining psychological stability

Source: [LearnSportsBetting](https://www.learnsportsbetting.com/guides/bankroll-management.html)

**Advanced (Kelly-based) sizing:**
- Use the Edge Finder's Kelly output to size bets proportionally to edge magnitude
- Always apply at least Quarter Kelly fractional sizing
- Cap any single bet at 5% of bankroll regardless of Kelly recommendation

### When NOT to Bet

Even with a positive edge, skip the bet if:
- **Lineup not confirmed** for batter props
- **Edge < 3%** and you're early in your tracking (uncertain model calibration)
- **Correlated exposure** — you already have 3+ bets on the same game
- **Daily card exceeds 20% of bankroll** — reduce positions or skip lower-edge plays

---

## 4. Best Sportsbooks for MLB Props

### Sportsbook Comparison

| Book | Prop Vig | Prop Categories | Limits | Best For |
|---|---|---|---|---|
| **FanDuel** | ~5.5% | ~60 | $1K-$2.5K | Early props, Dinger Tuesday, MLB prop reference |
| **DraftKings** | ~6.5% | ~60 | $1K-$5K | Best interface, alt lines, SGPs |
| **BetMGM** | <6% | Extensive | Standard | First to post K props, stale line value |
| **Caesars** | <5% live | ~70 (most) | High-limit boosts | Live MLB props, in-play betting |
| **BetRivers** | ~5% (best) | ~40 | Standard | Lowest pregame vig |
| **Pinnacle** | 2-3% | Limited | $50K+ | CLV benchmark (offshore) |
| **Circa** | 3-4% | Limited | High | Sharp reference, Nevada only |

Sources: [BettingUSA](https://www.bettingusa.com/sports/mlb/), [Pikkit](https://pikkit.com/blog/which-sportsbooks-are-sharp)

### Book-Specific Strategy

**FanDuel:**
- Posts MLB props earliest — bet here for early-line value before market tightens
- The sharp reference for MLB prop CLV; other books often move toward FanDuel's prices
- **Dinger Tuesday** (50% profit boost on HR bets) provides reliable weekly value
- Will limit accounts that consistently beat their lines

**BetMGM:**
- Frequently the first book to release **strikeout props** specifically — creates an early-line window for K projections
- **Slower to adjust prices** than peers, creating short +EV windows when lines go stale
- Shop early in the day before BetMGM catches up to market consensus

Source: [RotoWire](https://www.rotowire.com/baseball/article/mlb-betting-strikeout-props-strategy-57185)

**BetRivers:**
- **Lowest pregame prop juice** at ~5% (vs. 6.5% at DraftKings)
- Best for pregame value without paying a premium on the vig
- Posts lines late; avoid for live betting (vig jumps to ~7%)

**Caesars:**
- **Best-in-class live/in-play props** with <5% vig on live moneylines
- Highest prop category count (~70); strong for obscure prop types
- Use for live betting opportunities when game situations shift

### Line Shopping is Non-Negotiable

The same pitcher's strikeout line can vary by a full strike between books (e.g., 5.5 at BetMGM vs. 6.5 at FanDuel). Always check at least 3 books before placing any prop bet. The line difference alone can turn a negative-edge play into a positive one.

### November 2025 Pitch-Level Limits

Following the Cleveland Guardians pitch-fixing scandal, MLB and sportsbooks implemented a **$200 maximum on pitch-level prop bets** and excluded pitch props from parlays. Standard player props (strikeouts, hits, HRs, total bases) are NOT affected.

Sources: [USA Today](https://www.usatoday.com/story/sports/mlb/columnist/bob-nightengale/2025/11/10/mlb-sportsbooks-agreement-prop-bets-scandal-guardians/87202467007/), [Covers](https://www.covers.com/industry/mlb-and-sportsbooks-collaborate-to-set-pitch-prop-wager-limit-nov-10-2025)

---

## 5. MLB Prop Strategy Playbook

### Pitcher Strikeouts — The BaselineMLB Sweet Spot

Strikeout props are the most analytically tractable prop type and the primary focus of the BaselineMLB projection model.

**Key metrics the model considers:**
- **K/9 & K%:** Baseline strikeout rate — elite pitchers: 28-35%+
- **SwStr% (Swinging Strike Rate):** Above 12% indicates strong K potential
- **CSW% (Called Strikes + Whiffs):** Elite pitchers exceed 30%
- **Park factors:** Pitcher-friendly parks affect K environment
- **Umpire zone:** Expanded-zone umpires favor K overs; tight zones favor unders
- **Opposing lineup K rate:** Teams with 25%+ K rate are prime OVER targets

Source: [ThisDayInBaseball](https://thisdayinbaseball.com/strikeout-props-betting-how-to-identify-elite-k-over-under-spots/)

**The moneyline/total correlation:** A pitcher favored at -200 with a game total of 7 has more K upside than a -120 favorite in a total of 9, even if the K lines are similar. Stronger favorites in lower-total games have more projected innings of dominance.

Source: [RotoWire](https://www.rotowire.com/baseball/article/mlb-betting-strikeout-props-strategy-57185)

### Batter Props

**Hits:**
- Driven by batting average, BABIP, and plate appearance count
- **Platoon splits** are heavily exploitable — books often price off overall averages while the actual matchup (L/R) can differ by 70+ points of BA
- Leadoff and #2 hitters get ~20-25% more plate appearances than #7-9 hitters

**Total Bases:**
- Best measured by SLG% and ISO (Isolated Power)
- Walks do NOT count as total bases — avoid players with high OBP but low SLG
- Exit velocity and barrel rate from Statcast are the strongest predictors

**Home Runs:**
- Highest-variance prop type (even elite hitters HR only once per 12-15 PA)
- Only play when multiple factors converge: hitter-friendly park + favorable wind + warm temperature + platoon advantage + fly-ball pitcher
- Price usually +400 to +1,000 — treat as speculative / 0.5u plays

Sources: [Props Optimizer](https://www.propsoptimizer.com/guides/mlb-player-props-strategy), [BettorEdge](https://www.bettoredge.com/post/mlb-player-prop-betting-how-to-pick-winners-for-hits-hrs-and-more)

### Park Factors

| Park | Factor | Effect |
|---|---|---|
| Coors Field (COL) | 1.15-1.30 | Major offense boost; impacts all batter props |
| Great American (CIN) | ~1.10 | Hitter-friendly; good for HR props |
| Yankee Stadium (NYY) | ~1.08 | Short RF porch favors LHB HR props |
| Oracle Park (SF) | ~0.90 | Marine layer suppresses HRs |
| Petco Park (SD) | ~0.90 | Large outfield; pitcher-friendly |

Source: [Outlier](https://help.outlier.bet/en/articles/12313109-how-much-does-weather-the-ballpark-itself-impact-mlb-betting/)

### Weather Impact

| Factor | Threshold | Effect |
|---|---|---|
| Wind blowing OUT | 10+ mph significant | Increases HR/TB probability |
| Wind blowing IN | 10+ mph significant | Suppresses HRs; favors unders |
| Temperature 85°F+ | Especially outdoors | Ball travels further; favors overs |
| Temperature <50°F | April/late Sept games | "Dead ball" effect; suppresses offense |

**Strategy:** Monitor weather through game day. If wind direction shifts after lines are posted, HR/TB overs become significantly more valuable before books adjust.

Source: [Outlier](https://help.outlier.bet/en/articles/12313109-how-much-does-weather-the-ballpark-itself-impact-mlb-betting/)

### Lineup Confirmation — The Golden Rule

- **Pitcher props (K, outs):** Safe to bet early — starting pitcher is confirmed the night before
- **Batter props (hits, HR, TB):** ALWAYS wait for official lineup confirmation (3-4 hours before first pitch)
- A batter dropped from #2 to #7 in the order, or scratched entirely, can invalidate the entire prop thesis

Source: [BettorEdge](https://www.bettoredge.com/post/mlb-player-prop-betting-how-to-pick-winners-for-hits-hrs-and-more)

### Steam Moves & Reverse Line Movement

**Steam moves** — rapid synchronized line shifts at sharp books — indicate sharp money entering the market. For MLB props, only trust steam on high-volume markets (primarily pitcher K totals on nationally televised games).

**Reverse Line Movement (RLM)** — when lines move opposite to public bet percentages — signals sharp money on the minority side. NFL data shows a +15.5% ROI on RLM plays with 20%+ discrepancies between ticket count and dollar volume.

Source: [Fantasy Life](https://www.fantasylife.com/articles/betting/what-is-reverse-line-movement), [Action Network](https://www.actionnetwork.com/education/reverse-line-movement)

For MLB props, RLM is less reliable in thin markets. Only act on it when you can confirm the line movement aligns with your model's projection.

---

## 6. Using the Edge Finder

### Daily Workflow

```bash
# 1. Run the projection pipeline (generates today's projections)
python pipeline/generate_projections.py

# 2. Fetch today's prop lines
python pipeline/fetch_props.py

# 3. Find edges with default settings (Quarter Kelly, $1000 bankroll)
python scripts/find_edges.py

# 4. Custom bankroll and Kelly fraction
python scripts/find_edges.py --bankroll 5000 --kelly-fraction 0.25

# 5. Filter for only strong edges (10%+)
python scripts/find_edges.py --min-edge 10

# 6. Verbose output showing all edges
python scripts/find_edges.py -v

# 7. Specific date
python scripts/find_edges.py --date 2026-04-15
```

### Output Files

The Edge Finder generates three output formats in the `output/` directory:

| File | Format | Use Case |
|---|---|---|
| `edges_YYYY-MM-DD.json` | JSON | Programmatic consumption, dashboards, API |
| `edges_YYYY-MM-DD.md` | Markdown | Twitter/X posting, blog embeds |
| `edges_YYYY-MM-DD_twitter.txt` | Plain text | Direct Twitter thread copy-paste |
| `edges_YYYY-MM-DD.txt` | Plain text | Terminal review, logging |

### Interpreting the Output

Each play includes:
- **Edge %** — How much the projection exceeds/undercuts the line as a percentage. Higher = stronger edge.
- **Confidence Tier** — LOW / LOW-MEDIUM / MEDIUM / HIGH based on edge magnitude.
- **Kelly %** — The exact bankroll fraction to wager (already adjusted for Quarter Kelly).
- **Wager** — Dollar amount based on your bankroll and Kelly sizing.
- **Recommended Units** — Unit-based alternative to Kelly sizing.

### Historical Edge Performance

The tool queries the `picks` table to show hit rates segmented by edge magnitude:
- **Edge ≥10%:** Expected hit rate when your model has a 10%+ projection edge
- **Edge ≥20%:** Performance on the highest-conviction plays
- Track these over time — improving hit rates at higher edge thresholds confirms model calibration

### Integration with CLV Tracking

1. Run `find_edges.py` to identify plays
2. Place bets on recommended plays
3. Run `scripts/track_clv.py` to record closing lines
4. Compare entry lines vs. closing lines to compute CLV
5. Over 500+ bets, a CLV beat rate of 60%+ confirms your model has a real edge

---

## Quick Reference

| Topic | Guideline |
|---|---|
| Unit size (professional) | 1% of bankroll |
| Unit size (recreational) | 2-3% of bankroll |
| Maximum single bet | 5% of bankroll |
| Kelly fraction (starting) | Quarter Kelly (25%) |
| Kelly fraction (proven model) | Half Kelly (50%) |
| CLV beat rate for profitability | 55-60%+ |
| CLV benchmark (MLB main markets) | Pinnacle closing line |
| CLV benchmark (MLB props) | FanDuel closing line |
| Minimum sample to judge edge | 500+ bets |
| Prop variance vs. spreads | ~2x higher standard deviation |
| Lineup confirmation rule | Always wait for batter props |
| Best MLB prop book (most markets) | FanDuel / DraftKings |
| Best MLB prop book (lowest vig) | BetRivers (pregame) / Caesars (live) |
| Sharp MLB prop reference | FanDuel |

---

*Built for the [BaselineMLB](https://github.com/nrlefty5/baselinemlb) project.*

*Sources: [Harry Crane](https://harrycrane.substack.com/p/two-arguments-for-fractional-kelly), [Sports Insights](https://www.sportsinsights.com/how-to-bet-on-sports/bankroll-management/betting-unit-size/), [OddsIndex](https://oddsindex.com/guides/bankroll-management-guide), [VSiN](https://vsin.com/how-to-bet/the-importance-of-closing-line-value/), [Boyd's Bets](https://www.boydsbets.com/closing-line-value/), [OddsJam](https://oddsjam.com/betting-education/closing-line-value), [RebelBetting](https://www.rebelbetting.com/faq/expected-value-and-variance), [Pikkit](https://pikkit.com/blog/which-sportsbooks-are-sharp), [BettingUSA](https://www.bettingusa.com/sports/mlb/), [RotoWire](https://www.rotowire.com/baseball/article/mlb-betting-strikeout-props-strategy-57185), [Props Optimizer](https://www.propsoptimizer.com/guides/mlb-player-props-strategy), [Outlier](https://help.outlier.bet/en/articles/12313109-how-much-does-weather-the-ballpark-itself-impact-mlb-betting/), [BettorEdge](https://www.bettoredge.com/post/mlb-player-prop-betting-how-to-pick-winners-for-hits-hrs-and-more), [Wizard of Odds](https://wizardofodds.com/article/variance-and-bankroll-management-for-player-props/)*
