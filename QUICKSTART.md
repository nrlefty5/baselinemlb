# 🚀 BaselineMLB Quick Start Guide

Get your MLB analytics platform running in 10 minutes.

---

## 📚 Prerequisites

- Python 3.9+
- Git
- A Supabase account (free tier)
- The Odds API key (optional, free tier available)

---

## Step 1: Clone the Repository

```bash
git clone https://github.com/nrlefty5/baselinemlb.git
cd baselinemlb
```

---

## Step 2: Set Up Supabase

### Create a Supabase Project
1. Go to [supabase.com](https://supabase.com)
2. Click "New Project"
3. Name it `baselinemlb` (or your preference)
4. Save your **Project URL** and **API keys**

### Create Database Tables
1. In Supabase dashboard, go to **SQL Editor**
2. Copy the contents of `supabase/schema.sql`
3. Paste and click "Run"
4. Verify 8 tables were created:
   - players
   - games  
   - props
   - statcast_pitches
   - umpire_framing
   - projections
   - picks
   - accuracy_summary

---

## Step 3: Configure Environment Variables

```bash
# Copy the example file
cp .env.example .env

# Edit .env with your favorite editor
nano .env  # or vim, code, etc.
```

**Required values:**
```bash
SUPABASE_URL=https://klhglcfwuxfkpxbbtlrs.supabase.co
SUPABASE_ANON_KEY=your_anon_key_here
SUPABASE_SERVICE_KEY=your_service_role_key_here
```

**Optional (for prop data):**
```bash
ODDS_API_KEY=your_odds_api_key_here
```

> 💡 **Where to find keys:**  
> Supabase Dashboard → Settings → API  
> - Project URL = SUPABASE_URL
> - `anon` `public` key = SUPABASE_ANON_KEY
> - `service_role` key = SUPABASE_SERVICE_KEY

---

## Step 4: Install Dependencies

```bash
pip install -r requirements.txt
```

This installs:
- `supabase` - Database client
- `requests` - HTTP library
- `pandas` - Data manipulation
- `pybaseball` - Baseball statistics
- `python-dotenv` - Environment variables

---

## Step 5: Run the Test Suite

```bash
python scripts/run_pipeline_test.py
```

**This will test:**
1. ✅ Environment variables configured
2. ✅ Supabase connection working
3. ✅ Player data pipeline
4. ✅ Games data pipeline
5. ✅ Props data pipeline (if API key provided)
6. ✅ Projection model
7. ✅ Dashboard files present

**Expected output:**
```
╔════════════════════════════════════════════════════════╗
║   BASELINEMLB - WEEK 1 PIPELINE TEST SUITE            ║
╚════════════════════════════════════════════════════════╝

✅ Environment Check: PASS
✅ Fetch Players Pipeline: PASS
✅ Fetch Games Pipeline: PASS
...

🎉 SUCCESS! All Week 1 pipelines are operational.
```

---

## Step 6: Run Individual Pipelines

Once tests pass, run pipelines individually:

### Fetch Player Rosters
```bash
python pipeline/fetch_players.py
```
*Loads 750+ MLB players from all 30 teams*

### Fetch Today's Games
```bash
python pipeline/fetch_games.py
```
*Loads MLB schedule and game data*

### Fetch Player Props (optional)
```bash
python pipeline/fetch_props.py
```
*Requires ODDS_API_KEY*

### Generate Projections
```bash
python analysis/projection_model.py
```
*Creates glass-box projections for today's players*

---

## Step 7: View Your Dashboard

### Option A: Local Preview
```bash
cd dashboard
python -m http.server 8000
```
Open: http://localhost:8000

### Option B: Deploy to GitHub Pages
1. Go to your GitHub repo → **Settings** → **Pages**
2. Source: **GitHub Actions**
3. Go to **Actions** tab
4. Run "Deploy Dashboard" workflow
5. Dashboard will be live at: `https://[username].github.io/baselinemlb`

---

## Step 8: Automate Daily Updates

GitHub Actions are pre-configured to run daily.

### Enable GitHub Actions
1. Go to repo **Settings** → **Secrets and variables** → **Actions**
2. Add repository secrets:
   - `SUPABASE_URL`
   - `SUPABASE_SERVICE_KEY`
   - `ODDS_API_KEY` (optional)

### Verify Workflows
Go to **Actions** tab and check:
- ✅ **Data Pipeline** (runs daily at 6 AM UTC)
- ✅ **Deploy Dashboard** (runs on push to main)

---

## 🐞 Troubleshooting

### Error: "Missing SUPABASE_URL"
**Solution:** Make sure `.env` file exists and contains valid credentials.

### Error: "Connection refused"
**Solution:** Check Supabase project is active and URL is correct.

### Error: "No module named 'supabase'"
**Solution:** Run `pip install -r requirements.txt`

### Players table is empty
**Solution:** Run `python pipeline/fetch_players.py` to populate data.

### Props fetch fails
**Solution:** Verify ODDS_API_KEY is valid. Free tier has 500 requests/month.

---

## 📋 Next Steps

1. 📊 Monitor pipeline runs in GitHub Actions
2. 🔍 Explore data in Supabase dashboard
3. 📈 Watch accuracy metrics accumulate
4. ⚙️ Customize projection model in `analysis/projection_model.py`
5. 🎨 Enhance dashboard in `dashboard/index.html`

---

## 📚 Additional Resources

- **Full Documentation:** [README.md](README.md)
- **Week 1 Tasks:** [week-1-action-plan.md](week-1-action-plan.md)
- **Progress Tracking:** [WEEK1_PROGRESS.md](WEEK1_PROGRESS.md)
- **Architecture:** [frontend-architecture-spec.md](frontend-architecture-spec.md)

---

## ❓ Need Help?

- Check existing files for examples
- Review test output for specific errors
- Verify Supabase tables were created correctly
- Ensure all environment variables are set

---

**Time to first projection:** ~10 minutes ⏱️  
**Happy analyzing! ⚾📊**
