# BASELINE MLB — WEEK 1 ACTION PLAN

## February 25 – March 3, 2026

**Purpose:** Get every pipeline tested, post your first public content, and set up the frontend development environment. By the end of this week, Baseline MLB is a verified, functioning system with a public presence.

---

# 1. ENVIRONMENT SETUP CHECKLIST

Complete these steps before running any scripts. Estimated time: 20 minutes.

---

## Step 1: Clone the repository (if not already local)

```bash
git clone https://github.com/nrlefty5/baselinemlb.git
cd baselinemlb
```

If you already have it cloned, pull the latest:

```bash
cd baselinemlb
git pull origin main
```

---

## Step 2: Install Python dependencies

Make sure you're running Python 3.10 or higher:

```bash
python --version
# Should show Python 3.10.x or higher
```

Install all required packages:

```bash
pip install -r requirements.txt
```

If you see permission errors, use:

```bash
pip install -r requirements.txt --user
```

**Verify critical packages installed correctly:**

```bash
python -c "import requests; print('requests OK')"
python -c "import pandas; print('pandas OK')"
python -c "import pybaseball; print('pybaseball OK')"
python -c "import pyarrow; print('pyarrow OK')"
```

All four should print "OK". If any fail, install individually:

```bash
pip install requests pandas pybaseball pyarrow
```

---

## Step 3: Create your .env file

Copy the template:

```bash
cp .env.example .env
```

Open `.env` in any text editor and fill in these values:

```env
# Supabase — your production database
SUPABASE_URL=https://kjhglcfwuxfkpxbbtlrs.supabase.co
SUPABASE_ANON_KEY=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImtqaGdsY2Z3dXhma3B4YmJ0bHJzIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzIwNTgxNTgsImV4cCI6MjA4NzYzNDE1OH0.MCr87d5hGGdKnCLIQdAJELdlDodFI6CjtFoM7tKzsO4
SUPABASE_SERVICE_KEY=<GET THIS FROM SUPABASE DASHBOARD — see instructions below>

# The Odds API — prop lines and odds data
ODDS_API_KEY=fc90a2f6584d919654bd609185643c55

# OpenWeatherMap — game-time weather (sign up if you haven't)
WEATHER_API_KEY=<YOUR KEY — sign up at https://openweathermap.org/api>
```

**How to get your Supabase Service Key:**

1. Go to https://supabase.com/dashboard and log in
2. Select the "baselinemlb" project
3. Click **Settings** (gear icon) in the left sidebar
4. Click **API** under Configuration
5. Look for **Project API keys** section
6. Find the **service_role** key (labeled "secret" — this bypasses RLS)
7. Click "Reveal" and copy the full key
8. Paste it into your `.env` file as `SUPABASE_SERVICE_KEY`

**IMPORTANT:** The service key has full database access. Never commit it to GitHub. Your `.gitignore` should already exclude `.env` — verify this:

```bash
cat .gitignore | grep .env
# Should show: .env
```

---

## Step 4: Verify environment variables load correctly

Run this quick test:

```bash
python -c "
import os
from dotenv import load_dotenv
load_dotenv()
checks = {
    'SUPABASE_URL': os.getenv('SUPABASE_URL'),
    'SUPABASE_SERVICE_KEY': os.getenv('SUPABASE_SERVICE_KEY'),
    'ODDS_API_KEY': os.getenv('ODDS_API_KEY'),
}
for key, val in checks.items():
    status = 'SET' if val and len(val) > 5 else 'MISSING'
    print(f'  {key}: {status}')
"
```

Expected output:

```
  SUPABASE_URL: SET
  SUPABASE_SERVICE_KEY: SET
  ODDS_API_KEY: SET
```

If any show "MISSING", double-check your `.env` file. Common issues:
- Extra spaces around the `=` sign (there should be none)
- Missing quotes (values should NOT be wrapped in quotes in .env files)
- The `.env` file is in the wrong directory (must be in the repo root, same level as `requirements.txt`)

If `python-dotenv` isn't installed:

```bash
pip install python-dotenv
```

---

## Step 5: Verify Supabase connection

```bash
python -c "
import os, requests
from dotenv import load_dotenv
load_dotenv()
url = os.getenv('SUPABASE_URL')
key = os.getenv('SUPABASE_SERVICE_KEY')
resp = requests.get(
    f'{url}/rest/v1/games?limit=1',
    headers={'apikey': key, 'Authorization': f'Bearer {key}'}
)
print(f'Status: {resp.status_code}')
if resp.status_code == 200:
    data = resp.json()
    print(f'Games table accessible — {len(data)} rows returned')
    print('Supabase connection VERIFIED')
else:
    print(f'ERROR: {resp.text}')
"
```

**Expected output (if games table is empty):**

```
Status: 200
Games table accessible — 0 rows returned
Supabase connection VERIFIED
```

**Expected output (if games have been fetched):**

```
Status: 200
Games table accessible — 1 rows returned
Supabase connection VERIFIED
```

If you get a 401 error: your service key is wrong. Re-copy it from Supabase dashboard.
If you get a connection error: check that SUPABASE_URL is correct and has no trailing slash.

---

## Step 6: Verify GitHub Actions secrets

Your cron jobs run in GitHub Actions, which need the same environment variables. Verify they're configured:

1. Go to https://github.com/nrlefty5/baselinemlb
2. Click **Settings** tab
3. Click **Secrets and variables** → **Actions** in the left sidebar
4. Verify these secrets exist:
   - `SUPABASE_URL`
   - `SUPABASE_SERVICE_KEY` (or `SUPABASE_KEY`)
   - `ODDS_API_KEY`

If any are missing, click "New repository secret" and add them with the same values as your `.env` file.

---

## Step 7: Verify OpenWeatherMap API (optional today, needed for frontend)

If you've signed up:

```bash
python -c "
import os, requests
from dotenv import load_dotenv
load_dotenv()
key = os.getenv('WEATHER_API_KEY', '')
if not key:
    print('WEATHER_API_KEY not set yet — sign up at https://openweathermap.org/api')
else:
    # Test with Yankee Stadium coordinates
    resp = requests.get(
        f'https://api.openweathermap.org/data/2.5/forecast?lat=40.8296&lon=-73.9262&appid={key}&units=imperial'
    )
    print(f'Status: {resp.status_code}')
    if resp.status_code == 200:
        temp = resp.json()['list'][0]['main']['temp']
        print(f'Yankee Stadium forecast temp: {temp}°F')
        print('Weather API VERIFIED')
    else:
        print(f'ERROR: {resp.text}')
"
```

Not critical for Day 1 — but get this set up by Day 3.

---

# 2. TESTING PROTOCOL

## Test 1: Grade Accuracy Script (Historical Data)

This is the highest-priority test. Run it first.

### The command:

```bash
python scripts/grade_accuracy.py --date 2025-10-28
```

### What this does:

1. Calls MLB Stats API for games on October 28, 2025 (World Series Game 3, if applicable)
2. Fetches box scores for all completed games that day
3. Extracts actual pitcher strikeout totals
4. Attempts to load projections from Supabase for that date (there won't be any)
5. Since no projections exist, it exits cleanly

### What SUCCESS looks like:

```
2026-02-25 10:00:00 [INFO] === Grading projections for 2025-10-28 ===
2026-02-25 10:00:01 [INFO] Found 1 completed games on 2025-10-28
2026-02-25 10:00:02 [INFO] Fetched actuals for 8 pitcher appearances
2026-02-25 10:00:03 [INFO] Loaded 0 projections for 2025-10-28
2026-02-25 10:00:03 [INFO] No projections found for this date. Exiting.
```

Key things to verify:
- "Found X completed games" — confirms MLB Stats API is working
- "Fetched actuals for X pitcher appearances" — confirms box score parsing works
- "Loaded 0 projections" — expected (you had no projections stored for that date)
- No Python errors or stack traces

### What FAILURE looks like and how to fix it:

**Error: `EnvironmentError: Missing env vars: SUPABASE_SERVICE_KEY`**
- Fix: Your `.env` file is missing the service key, or the script can't find `.env`
- Run from the repo root directory: `cd baselinemlb && python scripts/grade_accuracy.py --date 2025-10-28`
- Verify `.env` is in the same directory you're running from

**Error: `requests.exceptions.ConnectionError`**
- Fix: Network issue. Check internet connection. Try again.

**Error: `401 Unauthorized` from Supabase**
- Fix: Your SUPABASE_SERVICE_KEY is incorrect. Re-copy from Supabase dashboard.

**Error: `KeyError: 'dates'` or similar JSON parsing error**
- Fix: The MLB Stats API response format may differ for postseason games. Try a regular season date instead:
  ```bash
  python scripts/grade_accuracy.py --date 2025-09-15
  ```

**Error: `ModuleNotFoundError: No module named 'requests'`**
- Fix: Dependencies not installed. Run `pip install -r requirements.txt`

### Test 1B: Backfill test

Once the single-date test passes, try backfilling a week:

```bash
python scripts/grade_accuracy.py --backfill 3
```

This grades the last 3 days. Since it's February (offseason), it should find 0 completed games for each date and exit cleanly for each:

```
2026-02-25 10:00:00 [INFO] === Grading projections for 2026-02-22 ===
2026-02-25 10:00:01 [INFO] Found 0 completed games on 2026-02-22
2026-02-25 10:00:01 [INFO] No completed games found. Exiting.
2026-02-25 10:00:01 [INFO] === Grading projections for 2026-02-23 ===
...
```

---

## Test 2: Props Pipeline (Spring Training)

```bash
python scripts/fetch_props.py
```

### What SUCCESS looks like:

```
[INFO] Season: preseason — using sport key: baseball_mlb_preseason
[INFO] Fetching props for market: pitcher_strikeouts
[INFO] x-requests-remaining: 497
[INFO] Upserted 24 rows into props
...
```

### What to watch for:
- The `x-requests-remaining` header — you have 500/month on free tier. Each market fetch costs 1 credit. With 8 markets, each run costs 8 credits. That's ~62 runs per month, or about 2 per day. Budget accordingly.
- If spring training prop markets are thin (few or no lines available), that's normal — not all books offer spring training props. Regular season will have full coverage.

---

## Test 3: Games Pipeline

```bash
python scripts/fetch_games.py
```

Should fetch today's spring training schedule (if any games today) or upcoming games.

---

## Test 4: Statcast Pipeline

```bash
python scripts/fetch_statcast.py
```

Note: Spring training Statcast data availability varies. If you get empty results, that's expected — Statcast coverage for spring training games is inconsistent. Regular season data will be comprehensive.

---

## Test 5: Full Pipeline Chain

Run everything in order to verify the complete flow:

```bash
echo "=== Step 1: Games ===" && python scripts/fetch_games.py
echo "=== Step 2: Players ===" && python scripts/fetch_players.py
echo "=== Step 3: Props ===" && python scripts/fetch_props.py
echo "=== Step 4: Statcast ===" && python scripts/fetch_statcast.py
echo "=== Step 5: Projections ===" && python analysis/projection_model.py
echo "=== DONE ==="
```

If any step fails, the error will show which script broke. Fix that script before moving to the next.

---

## Test 6: Verify Data in Supabase

After running the pipelines, check that data actually landed:

1. Go to https://supabase.com/dashboard
2. Select baselinemlb project
3. Click **Table Editor** in the left sidebar
4. Check each table:
   - `games` — should have rows if spring training games exist
   - `players` — should have pitcher/batter records
   - `props` — should have prop lines (if available for spring training)
   - `statcast_pitches` — may be empty (spring training Statcast is sparse)
   - `projections` — should have records if projection model ran
   - `picks` — empty until grading runs against real projections
   - `accuracy_summary` — empty until grading runs

---

# 3. FIRST TWITTER POST STRATEGY

## Brand Positioning to Establish

Your first tweets should communicate three things:
1. This is an MLB analytics product (not a tout/picks account)
2. Transparency is the core value (glass-box, show your work)
3. It's coming soon (summer 2026 launch — build anticipation)

## Option A: The Manifesto (best for establishing brand identity)

```
⚾ Introducing Baseline MLB.

Most betting tools tell you WHAT to bet.
We show you WHY.

Every projection. Every factor. No black boxes.

Pitcher Statcast + umpire zones + catcher framing +
park factors + weather — all visible, all auditable.

Building in public. Launching summer 2026.

baselinemlb.com
```

## Option B: The Problem Statement (best for resonating with bettors)

```
Tired of spending 45 minutes every morning checking:
- Baseball Savant for pitcher stats
- Weather.com for wind direction
- UmpScorecards for the HP umpire
- 3 different odds sites for the best line

Building a tool that puts it all on one screen — and
shows you exactly why each projection says what it does.

Baseline MLB. Launching summer 2026. ⚾
```

## Option C: The Transparency Pledge (best for differentiation)

```
Here's what Baseline MLB will do that no other tool does:

Every projection we publish will show the exact factors
that drive it — pitcher K rate, umpire zone tendency,
catcher framing impact, park factor, weather adjustment.

Every pick will be graded publicly.
Every miss will be logged.
No hiding. No black boxes.

Coming summer 2026.
```

## Option D: The Data Teaser (best for getting engagement)

```
Did you know that the home plate umpire assignment can
swing a pitcher's strikeout projection by 8-12%?

Or that catcher framing at the shadow zone is worth
an extra 0.3 strikeouts per game for elite framers?

We're building a tool that accounts for ALL of this
— and shows you every factor behind every number.

Baseline MLB. Summer 2026. ⚾
```

## Option E: Short and Direct (best if you want to keep it simple)

```
⚾ Baseline MLB

MLB prop analytics with full transparency.
Every factor visible. Every result graded publicly.

Launching summer 2026.

baselinemlb.com
```

## Posting Strategy for the First Tweet:

1. **Post Option A or B** (the two strongest standalone options)
2. **Pin it** to your profile immediately
3. **Bio should read:** "MLB prop analytics. Every factor visible. Every result graded. Launching summer 2026. Built by @[your personal handle]"
4. **Profile image:** Use a clean baseball-themed graphic or the Baseline MLB wordmark (you can create a simple one on Canva in 10 minutes — dark background, white text, baseball accent)
5. **Header image:** Dark gradient with "Baseline MLB — Every factor. No secrets." text overlay
6. **Follow 50-100 accounts:** BallparkPal, MLB betting analysts, Statcast-related accounts, sports betting media. This seeds your timeline and makes your account look active.

## Follow-Up Tweets (Days 2-7):

**Day 2:** Share a specific data insight

```
Spring training note: [Pitcher X] has thrown 47 pitches
across 2 appearances. Whiff rate on his slider: 42%.

Last year's season average: 31%.

Small sample — but the kind of thing we'll be tracking
daily once Baseline MLB launches. The early signals
are the edge.
```

**Day 3:** Explain a feature

```
One thing we're building into Baseline MLB that nobody
else does: umpire + catcher framing composites.

The HP umpire's zone tendencies + the catcher's framing
ability = a "K environment score" for every game.

Some games are played in a 15% larger strike zone.
That matters for K props.
```

**Day 4:** Engage with existing content
- Quote-tweet a BallparkPal park factor post and add umpire context
- Reply to MLB betting tweets with Statcast-backed analysis
- Don't promote Baseline MLB in every interaction — just be helpful and data-driven

**Day 5-7:** Post your first manual prop breakdown using Template A from the launch playbook (if spring training games are available with prop lines)

---

# 4. WEEK 1 DAILY CHECKLIST

---

## DAY 1 — Tuesday Feb 25 (Today)

### Morning Block (1-2 hours)

- [ ] Complete Environment Setup (Section 1 above — Steps 1-6)
- [ ] Run Test 1: `python scripts/grade_accuracy.py --date 2025-10-28`
- [ ] Run Test 1B: `python scripts/grade_accuracy.py --backfill 3`
- [ ] Run Test 2: `python scripts/fetch_props.py`
- [ ] Run Test 3: `python scripts/fetch_games.py`
- [ ] Verify data landed in Supabase Table Editor
- [ ] Screenshot all successful test outputs (for your records)
- [ ] Fix any errors encountered (refer to Troubleshooting Guide below)

### Afternoon Block (30-45 minutes)

- [ ] Set up @baselinemlb Twitter profile:
  - [ ] Profile photo (baseball-themed, or simple wordmark from Canva)
  - [ ] Header image (dark gradient + tagline)
  - [ ] Bio: "MLB prop analytics. Every factor visible. Every result graded. Launching summer 2026."
  - [ ] Website link: baselinemlb.com
  - [ ] Location: (optional — your city or leave blank)
- [ ] Follow 50-100 relevant accounts:
  - @BallparkPal, @baseaborant, @FanGraphs, @PitcherList
  - MLB betting accounts: @RotoBaller, @RotoGrinders, @ActionNetworkHQ
  - Individual MLB analysts and bettors you already follow
- [ ] Post your first tweet (use Option A, B, or C from above)
- [ ] Pin the tweet to your profile

### Evening (10 minutes)

- [ ] Check for any engagement on your first tweet
- [ ] Like and reply to anyone who interacts
- [ ] Confirm GitHub Actions ran (check Actions tab — any scheduled runs today?)

---

## DAY 2 — Wednesday Feb 26

### Morning (30 minutes)

- [ ] Check GitHub Actions — did the 8 AM cron job run? (It may not fire until tomorrow depending on when you set up secrets)
- [ ] Review Supabase tables — any new data from overnight?
- [ ] If props pipeline ran automatically, check how many credits were used
- [ ] Post Day 2 tweet (data insight — see follow-up tweet examples above)

### Afternoon (45 minutes)

- [ ] Manual prop analysis practice:
  1. Go to MLB.com and check today's spring training schedule
  2. Pick one game with known starting pitchers
  3. Go to Baseball Savant → search the starting pitcher
  4. Note: K%, Whiff rate, Chase rate, Hard Hit% (last season or spring)
  5. Check if any sportsbook has spring training K props (DraftKings and FanDuel sometimes do)
  6. Write up a quick analysis in your notes — this is practice for the daily Twitter posts
- [ ] Create your Google Sheet results tracker:
  - Columns: Date | Game | Prop Type | Player | Line | Lean | Odds | Result | W/L | Units +/- | Notes
  - Share link with yourself across devices so you can update from phone

### Evening (10 minutes)

- [ ] Engage with 5-10 MLB betting tweets (reply with thoughtful analysis, no self-promotion)

---

## DAY 3 — Thursday Feb 27

### Morning (30 minutes)

- [ ] Check GitHub Actions runs from overnight and 8 AM
- [ ] Verify Supabase data freshness
- [ ] Post Day 3 tweet (explain the umpire + framing feature — see example above)
- [ ] Sign up for OpenWeatherMap API if you haven't (https://openweathermap.org/api)
  - Free tier: 1,000 calls/day
  - Add key to `.env` and GitHub Secrets

### Afternoon (45 minutes)

- [ ] Manual prop analysis — do a full Template A breakdown:
  1. Find a spring training game with a notable pitcher
  2. Pull all the data (Statcast, weather, umpire if assigned)
  3. Write the full breakdown using Template A format
  4. Post it on Twitter as your first "real" analytical content
- [ ] Start thinking about the `stadium_data.json` file:
  - You need lat/long for all 30 spring training venues AND regular season venues
  - Spring training sites: Grapefruit League (Florida) + Cactus League (Arizona)
  - This is a manual research task — start a spreadsheet

### Evening (15 minutes)

- [ ] Check engagement on your analytical tweet — what got likes/replies?
- [ ] Log any spring training projection in your Google Sheet (even if informal)

---

## DAY 4 — Friday Feb 28

### Morning (30 minutes)

- [ ] Routine pipeline check (GitHub Actions, Supabase data)
- [ ] Post tweet (engagement day — quote-tweet an interesting MLB take with data)

### Afternoon (1-2 hours) — START FRONTEND SETUP

- [ ] Sign up for Vercel (https://vercel.com) — use "Continue with GitHub"
- [ ] Create a new Next.js project locally:
  ```bash
  npx create-next-app@latest baselinemlb-web --typescript --tailwind --app --src-dir --use-npm
  cd baselinemlb-web
  ```
- [ ] When prompted:
  - Would you like to use TypeScript? → **Yes**
  - Would you like to use ESLint? → **Yes**
  - Would you like to use Tailwind CSS? → **Yes**
  - Would you like to use `src/` directory? → **Yes**
  - Would you like to use App Router? → **Yes**
  - Would you like to customize the default import alias? → **No**
- [ ] Install Supabase client:
  ```bash
  npm install @supabase/supabase-js
  ```
- [ ] Create environment file:
  ```bash
  echo "NEXT_PUBLIC_SUPABASE_URL=https://kjhglcfwuxfkpxbbtlrs.supabase.co" > .env.local
  echo "NEXT_PUBLIC_SUPABASE_ANON_KEY=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImtqaGdsY2Z3dXhma3B4YmJ0bHJzIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzIwNTgxNTgsImV4cCI6MjA4NzYzNDE1OH0.MCr87d5hGGdKnCLIQdAJELdlDodFI6CjtFoM7tKzsO4" >> .env.local
  ```
- [ ] Create Supabase client file (`src/lib/supabase.ts`):
  ```typescript
  import { createClient } from '@supabase/supabase-js'

  const supabaseUrl = process.env.NEXT_PUBLIC_SUPABASE_URL!
  const supabaseAnonKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!

  export const supabase = createClient(supabaseUrl, supabaseAnonKey)
  ```
- [ ] Run locally to verify it works:
  ```bash
  npm run dev
  ```
  Open http://localhost:3000 — you should see the default Next.js welcome page
- [ ] Create a new GitHub repository for the frontend:
  ```bash
  git init
  git add .
  git commit -m "feat: initialize Next.js project with Supabase client"
  git remote add origin https://github.com/nrlefty5/baselinemlb-web.git
  git push -u origin main
  ```
  (Or add it as a `/web` directory in the existing repo — your choice)
- [ ] Connect to Vercel:
  1. Go to https://vercel.com/dashboard
  2. Click "Add New Project"
  3. Import your `baselinemlb-web` repo from GitHub
  4. Add environment variables: `NEXT_PUBLIC_SUPABASE_URL` and `NEXT_PUBLIC_SUPABASE_ANON_KEY`
  5. Click Deploy
  6. Vercel gives you a URL like `baselinemlb-web.vercel.app` — verify it loads

### Evening (10 minutes)

- [ ] Verify Vercel deployment is live
- [ ] Check Twitter engagement
- [ ] Post a Friday tweet: "Weekend slate preview" energy for spring training

---

## DAY 5 — Saturday Mar 1

### Morning (20 minutes)

- [ ] Pipeline check
- [ ] Post a spring training prop breakdown (Template A or B)
- [ ] Check if spring training games have Statcast data available yet

### Afternoon (1-2 hours) — FIRST REAL FRONTEND CODE

- [ ] Replace the default Next.js homepage with a dark-themed layout:
  - Set up the dark color palette from the frontend spec (background: #0a0a0f)
  - Add the navigation bar: BASELINE MLB | Today's Slate | Props | Accuracy | About
  - Use Tailwind classes: `bg-[#0a0a0f] text-[#e4e4e7]`
- [ ] Create a basic page that fetches from Supabase and displays results:
  ```typescript
  // src/app/page.tsx — simplified first version
  import { supabase } from '@/lib/supabase'

  export default async function Home() {
    const today = new Date().toISOString().split('T')[0]
    const { data: games } = await supabase
      .from('games')
      .select('*')
      .eq('game_date', today)
      .order('game_time', { ascending: true })

    return (
      <main className="min-h-screen bg-[#0a0a0f] text-[#e4e4e7] p-6">
        <h1 className="text-2xl font-bold mb-6">Baseline MLB — Today's Slate</h1>
        {games && games.length > 0 ? (
          games.map((game) => (
            <div key={game.game_pk} className="bg-[#141418] border border-[#2a2a30] rounded-lg p-4 mb-4">
              <p className="text-lg">{game.away_team} @ {game.home_team}</p>
              <p className="text-sm text-[#8b8b94]">{game.venue_name} — {game.game_time}</p>
            </div>
          ))
        ) : (
          <p className="text-[#8b8b94]">No games scheduled today or data not yet loaded.</p>
        )}
      </main>
    )
  }
  ```
- [ ] Commit and push — Vercel auto-deploys
- [ ] Check your Vercel URL — you should see either today's games or "No games scheduled"

### Evening (15 minutes)

- [ ] Post results for any spring training prop calls you made
- [ ] Log results in Google Sheet

---

## DAY 6 — Sunday Mar 2

### Morning (20 minutes)

- [ ] Pipeline check
- [ ] Post a weekly preview: "What I'm watching for in spring training this week"

### Afternoon (1-2 hours) — UI MOCKUP / DESIGN

- [ ] Open Figma (free) or just sketch on paper: what should a game card look like?
  - Reference the wireframe in the frontend architecture spec (Section: PAGE 1)
  - Key elements: time, matchup, pitcher stats, weather, umpire, odds, lean
- [ ] If you prefer to design in code:
  - Build a static mockup game card component with hardcoded data
  - Focus on the visual layout, not the data fetching
  - Get the card looking good with the dark theme palette
- [ ] Push any updates to GitHub → Vercel auto-deploys

### Evening (15 minutes)

- [ ] Review the week: what worked, what didn't, what broke
- [ ] Plan content for next week (WBC starts March 5!)

---

## DAY 7 — Monday Mar 3

### Morning (30 minutes)

- [ ] Full pipeline health check:
  - [ ] GitHub Actions: all 3 cron jobs ran this weekend? Any failures?
  - [ ] Supabase: data in tables growing? Any empty tables that should have data?
  - [ ] Odds API: check credits remaining (`x-requests-remaining` in pipeline logs)
- [ ] Post Monday tweet (lead into WBC week starting Wednesday)

### Afternoon (1 hour)

- [ ] Connect baselinemlb.com to Vercel:
  1. In Vercel dashboard: Settings → Domains → Add "baselinemlb.com"
  2. Vercel will give you DNS instructions (typically an A record or CNAME)
  3. In Namecheap:
     - Go to Domain List → baselinemlb.com → Manage
     - Click "Advanced DNS"
     - Add the records Vercel specifies (usually):
       - A Record: @ → 76.76.21.21
       - CNAME Record: www → cname.vercel-dns.com
     - Delete any existing parking page records
  4. Wait 10-30 minutes for DNS propagation
  5. Visit baselinemlb.com — should show your Next.js app
  6. Vercel auto-provisions SSL (HTTPS)
- [ ] Verify baselinemlb.com loads with HTTPS
- [ ] Screenshot it — this is a milestone

### Evening (15 minutes)

- [ ] Confirm domain is working
- [ ] Update your Twitter bio link if needed
- [ ] Prep for WBC content this week

---

# 5. TROUBLESHOOTING GUIDE

## Environment & Setup Issues

### "ModuleNotFoundError: No module named 'X'"

**Cause:** Python package not installed.

**Fix:**
```bash
pip install -r requirements.txt
# Or install the specific package:
pip install requests pandas pybaseball
```

If you have multiple Python versions:
```bash
python3 -m pip install -r requirements.txt
```

---

### ".env file not loading / environment variables are None"

**Cause:** Script can't find the `.env` file, or `python-dotenv` isn't installed.

**Fix:**
```bash
pip install python-dotenv
```

Make sure you're running scripts from the repo root directory:
```bash
cd baselinemlb
python scripts/grade_accuracy.py --date 2025-10-28
```

If your scripts don't use `load_dotenv()`, you may need to export variables manually:
```bash
export SUPABASE_URL=https://kjhglcfwuxfkpxbbtlrs.supabase.co
export SUPABASE_SERVICE_KEY=your_key_here
export ODDS_API_KEY=fc90a2f6584d919654bd609185643c55
python scripts/grade_accuracy.py --date 2025-10-28
```

---

### "EnvironmentError: Missing env vars: SUPABASE_SERVICE_KEY"

**Cause:** The script's validation check caught a missing variable.

**Fix:** Open `.env` and verify `SUPABASE_SERVICE_KEY` is set. The key should be a long JWT string starting with `eyJ...`. Get it from Supabase Dashboard → Settings → API → service_role key → Reveal.

---

## API Issues

### Supabase: "401 Unauthorized" or "Invalid API key"

**Cause:** Wrong API key or using anon key where service key is needed.

**Fix:**
- For pipeline scripts (writing data): use `SUPABASE_SERVICE_KEY` (the service_role key)
- For frontend (reading data): use `SUPABASE_ANON_KEY` (the anon key)
- Re-copy the correct key from Supabase Dashboard → Settings → API

---

### Supabase: "42501: permission denied for table X"

**Cause:** RLS (Row Level Security) is blocking the request. You're using the anon key for a write operation, or the RLS policy doesn't allow this action.

**Fix:**
- Pipeline scripts must use the service key (bypasses RLS)
- If you need the anon key to write, add an RLS policy for inserts

---

### Supabase: "23505: duplicate key value violates unique constraint"

**Cause:** Trying to insert a row that already exists.

**Fix:** This should be handled by the upsert logic (`on_conflict`). If it's not:
- Check that your `Prefer` header includes `resolution=merge-duplicates`
- Verify the unique constraint matches the conflict columns in your upsert

---

### Odds API: "401 Unauthorized"

**Cause:** Invalid API key.

**Fix:** Verify `ODDS_API_KEY` matches the key shown in your The Odds API dashboard at https://the-odds-api.com/account/

---

### Odds API: "429 Too Many Requests" or "Insufficient credits"

**Cause:** You've exceeded your monthly credit limit (500 on free tier).

**Fix:**
- Check remaining credits: the pipeline logs `x-requests-remaining` after each call
- Each market fetch costs 1 credit. 8 markets × 2 runs/day = 16 credits/day
- 500 credits ÷ 16 credits/day = 31 days — just barely enough for one month
- If you're running out: reduce to 1 run/day, or upgrade to the $30/month tier
- You can also reduce markets — drop the least-used ones temporarily

---

### MLB Stats API: "404 Not Found" or empty response

**Cause:** No games on that date, or the date format is wrong.

**Fix:**
- Verify date format is YYYY-MM-DD (e.g., 2025-10-28, not 10-28-2025)
- Some dates genuinely have no games (offseason, All-Star break)
- Try a known active date: `--date 2025-09-15` (guaranteed regular season)

---

### pybaseball: "HTTPError" or slow/hanging requests

**Cause:** Baseball Savant rate limiting or temporary outage.

**Fix:**
- pybaseball pulls from Baseball Savant which has unofficial rate limits
- Wait 30 seconds and retry
- If persistent: Baseball Savant may be down (check status on their site)
- Add `cache_type='memory'` to pybaseball calls to avoid redundant fetches:
  ```python
  from pybaseball import cache
  cache.enable()
  ```

---

## Frontend Issues

### Next.js: "Module not found: Can't resolve '@supabase/supabase-js'"

**Fix:**
```bash
cd baselinemlb-web
npm install @supabase/supabase-js
```

---

### Vercel: "Build failed"

**Fix:**
1. Check the Vercel deployment logs (Dashboard → Deployments → click the failed one)
2. Most common cause: TypeScript errors. Fix the error shown in the log.
3. Test locally first: `npm run build` should complete without errors before pushing.

---

### Vercel: "Environment variable not found"

**Fix:**
1. Go to Vercel Dashboard → Your Project → Settings → Environment Variables
2. Add `NEXT_PUBLIC_SUPABASE_URL` and `NEXT_PUBLIC_SUPABASE_ANON_KEY`
3. IMPORTANT: Variables must start with `NEXT_PUBLIC_` to be accessible in client-side code
4. Redeploy after adding variables (Settings → Deployments → Redeploy)

---

### DNS: "baselinemlb.com not resolving"

**Fix:**
1. DNS changes can take 10 minutes to 48 hours (usually 10-30 minutes)
2. Check propagation: https://dnschecker.org/#A/baselinemlb.com
3. Verify the records in Namecheap match what Vercel specified
4. Common mistake: leaving the old Namecheap parking page records active — delete those

---

## GitHub Actions Issues

### "Cron job didn't run"

**Fix:**
1. GitHub Actions cron uses UTC time, not ET. Verify your schedule accounts for the offset.
   - 8:00 AM ET = 13:00 UTC (during EST) or 12:00 UTC (during EDT)
2. GitHub doesn't guarantee exact cron timing — jobs can be delayed up to 15 minutes
3. Check the Actions tab for run history
4. If the workflow has never run: push a commit to trigger the first run, or manually trigger via "Run workflow" button

---

### "GitHub Actions failing with missing secrets"

**Fix:**
1. Go to repo Settings → Secrets and variables → Actions
2. Verify all required secrets are present (names must match exactly what the workflow references)
3. Secret values are hidden after creation — if unsure, delete and re-create

---

# END OF WEEK 1 CHECKLIST

By end of day Sunday Mar 2, you should have:

- [ ] All pipeline scripts tested and verified working# Week 1 Action Plan - BaselineMLB
*Generated: January 2025*
*Status: IN PROGRESS*

## 🎯 Sprint Goal
Establish core data infrastructure and initial player analytics capability

---

## 📋 Task Breakdown

### Phase 1: Data Pipeline Foundation (Days 1-3)
**Priority: CRITICAL**

#### Task 1.1: Supabase Schema Setup
- [ ] Create `players` table with core fields (player_id, name, team, position)
- [ ] Create `games` table (game_id, date, home_team, away_team, venue)
- [ ] Create `player_stats` table (player_id, game_id, stat_type, value)
- [ ] Set up RLS policies for public read access
- [ ] Create database indexes for performance
**Owner:** Data Team | **Est:** 4 hours

#### Task 1.2: MLB Stats API Integration
- [ ] Set up MLB Stats API client in `/pipeline/fetch_players.py`
- [ ] Implement player roster fetching (all 30 teams)
- [ ] Create data transformation layer (API → Supabase schema)
- [ ] Add error handling and retry logic
- [ ] Test with 3 teams before full deployment
**Owner:** Data Team | **Est:** 6 hours

#### Task 1.3: Daily Stats Pipeline
- [ ] Create `/pipeline/fetch_daily_stats.py`
- [ ] Fetch yesterday's game results
- [ ] Extract player performance metrics (AB, H, HR, RBI, etc.)
- [ ] Load into Supabase with upsert logic
- [ ] Add logging for monitoring
**Owner:** Data Team | **Est:** 6 hours

---

### Phase 2: Analytics Engine (Days 3-5)
**Priority: HIGH**

#### Task 2.1: Projection Model v0.1
- [ ] Create `/analysis/projection_model.py`
- [ ] Implement simple weighted average algorithm:
  - Last 7 games: 40% weight
  - Last 30 games: 35% weight
  - Season average: 25% weight
- [ ] Calculate projections for batting average, HRs, RBIs
- [ ] Store projections in `player_projections` table
**Owner:** Analytics Team | **Est:** 8 hours

#### Task 2.2: Glass-Box Transparency Layer
- [ ] Design explanation format (JSON structure)
- [ ] Add calculation breakdown to projection output:
  ```json
  {
    "projection": 0.285,
    "explanation": {
      "last_7_games": {"avg": 0.310, "weight": 0.40},
      "last_30_games": {"avg": 0.275, "weight": 0.35},
      "season": {"avg": 0.268, "weight": 0.25}
    }
  }
  ```
- [ ] Test with 10 sample players
**Owner:** Analytics Team | **Est:** 4 hours

---

### Phase 3: Dashboard MVP (Days 5-7)
**Priority: MEDIUM**

#### Task 3.1: Dashboard Structure
- [ ] Create `/dashboard/index.html` with basic layout
- [ ] Add navigation: Home | Players | About
- [ ] Implement responsive design (mobile-first)
- [ ] Set up static asset hosting on GitHub Pages
**Owner:** Frontend Team | **Est:** 4 hours

#### Task 3.2: Player Leaderboard
- [ ] Create player table with sortable columns:
  - Name, Team, Position
  - Batting Avg, HRs, RBIs (actual)
  - Projected stats (next 7 days)
- [ ] Add search/filter functionality
- [ ] Connect to Supabase API
- [ ] Display loading states
**Owner:** Frontend Team | **Est:** 6 hours

#### Task 3.3: Glass-Box Visualization
- [ ] Create explanation card component
- [ ] Show projection breakdown on player click
- [ ] Add visual weight indicators (e.g., bar charts)
- [ ] Include "Why this projection?" tooltip
**Owner:** Frontend Team | **Est:** 5 hours

---

## 🔄 Daily Standup Format
**Time:** 9:00 AM (async in Slack)
**Template:**
```
✅ Completed yesterday:
🚧 Working on today:
🚨 Blockers:
```

---

## 📊 Success Metrics
- [ ] All 30 MLB team rosters loaded into Supabase (target: 750+ players)
- [ ] Daily stats pipeline runs successfully for 3 consecutive days
- [ ] Projection model generates predictions for 100+ players
- [ ] Dashboard loads player data in <2 seconds
- [ ] At least 1 glass-box explanation is fully functional

---

## 🚧 Known Risks & Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| MLB API rate limits | HIGH | Implement caching, stagger requests |
| Supabase free tier limits | MEDIUM | Monitor usage, plan upgrade path |
| Data quality issues | HIGH | Add validation layer, manual spot checks |
| GitHub Pages deployment | LOW | Test locally first, use Actions for CI/CD |

---

## 📝 Notes from Roadmap Review
- Focus on **simplicity over sophistication** in Week 1
- Prioritize **data accuracy** over prediction accuracy
- Build **transparency into every component** from the start
- Keep dashboard **dead simple** - complexity comes later

---

## 🎉 Week 1 Definition of Done
1. Data pipeline runs automatically (cron job or GitHub Action)
2. Dashboard displays real player data (not mock data)
3. At least one projection is explainable to a non-technical user
4. All code is committed to GitHub with clear documentation
5. README is updated with setup instructions

---

**Next Week Preview:** Umpire/framing analysis, ballpark adjustments, mobile optimization
- [ ] Data flowing into Supabase tables (at least games and props)
- [ ] Grade accuracy script tested with historical date
- [ ] GitHub Actions confirmed running on schedule
- [ ] @baselinemlb Twitter account live with first 3-5 tweets posted
- [ ] 20-50 accounts followed, some engagement happening
- [ ] Google Sheet results tracker created
- [ ] Next.js project initialized and deployed to Vercel
- [ ] Basic dark-themed homepage fetching from Supabase
- [ ] OpenWeatherMap API key obtained
- [ ] Game card mockup designed (code or sketch)

By end of day Monday Mar 3:

- [ ] baselinemlb.com pointing to your Vercel deployment
- [ ] SSL working (https://baselinemlb.com loads)
- [ ] Ready for WBC content week (starts March 5)

---

**If you complete everything on this list, you enter WBC week with a functioning data pipeline, a live website (even if basic), a growing Twitter presence, and validated infrastructure. That puts you ahead of 99% of people who say "I'm going to build something."**
