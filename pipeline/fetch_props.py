import os
import requests
from datetime import date
from supabase import create_client, Client
# from dotenv import load_dotenv  # DISABLED - GitHub Actions provides env vars

# load_dotenv()

# ── Clients ────────────────────────────────────────────────────────────────────
ODDS_API_KEY = os.getenv("ODDS_API_KEY")
SUPABASE_URL = os.getenv("SUPABASE_URL", "").strip()
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_KEY", "").strip()

# Fail fast with a clear error instead of cryptic HTTP 400
if not SUPABASE_URL.startswith("https://") or not SUPABASE_URL.endswith(".supabase.co"):
    raise RuntimeError(f"Invalid SUPABASE_URL (length={len(SUPABASE_URL)}, repr={repr(SUPABASE_URL[:30])})")  

if not all([ODDS_API_KEY, SUPABASE_URL, SUPABASE_KEY]):
    raise EnvironmentError("Missing required env vars. Check your .env file.")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# ── Config ───────────────────────────────────────────────────────────────────
REGIONS = "us"
MARKETS = (
    "batter_hits,batter_home_runs,batter_rbis,"
    "batter_strikeouts,pitcher_strikeouts,pitcher_hits_allowed,"
    "batter_total_bases,batter_walks"
)
ODDS_FMT = "american"
BASE_URL = "https://api.the-odds-api.com/v4"


# MLB regular season: late March – early October
# Spring training: mid-Feb – late March
def get_sport_key() -> str:
    """Return the correct Odds API sport key based on calendar date."""
    today = date.today()
    month, day = today.month, today.day

    # Spring training window: Feb 15 – Mar 27
    if (month == 2 and day >= 15) or (month == 3 and day <= 27):
        return "baseball_mlb_preseason"

    # Regular season + playoffs: Mar 28 – Nov 15
    if (month == 3 and day >= 28) or (4 <= month <= 10) or (month == 11 and day <= 15):
        return "baseball_mlb"

    # Off-season — nothing to fetch
    return None


def fetch_events(sport: str) -> list[dict]:
    """Return today's MLB event IDs from The Odds API."""
    url = f"{BASE_URL}/sports/{sport}/events"
    r = requests.get(url, params={"apiKey": ODDS_API_KEY, "dateFormat": "iso"})
    r.raise_for_status()

    remaining = r.headers.get("x-requests-remaining", "?")
    print(f" [API] requests remaining this month: {remaining}")

    return r.json()


def fetch_player_props(sport: str, event_id: str) -> dict:
    """Fetch all player prop markets for a single event."""
    url = f"{BASE_URL}/sports/{sport}/events/{event_id}/odds"
    r = requests.get(
        url,
        params={
            "apiKey": ODDS_API_KEY,
            "regions": REGIONS,
            "markets": MARKETS,
            "oddsFormat": ODDS_FMT,
        },
    )
    r.raise_for_status()
    return r.json()


def parse_props(event_data: dict) -> list[dict]:
    """Flatten bookmaker/market/outcome structure into prop rows."""
    rows = []

    event_id = event_data.get("id")
    home_team = event_data.get("home_team")
    away_team = event_data.get("away_team")
    commence = event_data.get("commence_time")
    game_date = str(date.today())

    for bm in event_data.get("bookmakers", []):
        book = bm["key"]
        for market in bm.get("markets", []):
            market_key = market["key"]
            for outcome in market.get("outcomes", []):
                rows.append(
                    {
                        "external_id": f"{event_id}_{book}_{market_key}_{outcome.get('description', '')}_{outcome['name']}",
                        "source": book,
                        "player_name": outcome.get("description") or "",
                        "stat_type": market_key,
                        "line": outcome.get("point"),
                        "over_odds": outcome["price"] if outcome["name"] == "Over" else None,
                        "under_odds": outcome["price"] if outcome["name"] == "Under" else None,
                        "game_date": game_date,
                        # metadata (not schema columns — stored for reference)
                        "_home_team": home_team,
                        "_away_team": away_team,
                        "_commence": commence,
                        "_event_id": event_id,
                    }
                )

    return rows


def clean_row(row: dict) -> dict:
    """Remove internal metadata keys before upserting."""
    return {k: v for k, v in row.items() if not k.startswith("_")}


def upsert_props(rows: list[dict]) -> None:
    """Insert prop rows into Supabase, skip duplicates via external_id."""
    if not rows:
        print(" No prop rows to upsert.")
        return

    clean = [clean_row(r) for r in rows]
    # Filter out rows with no line (some bookmakers omit point for certain markets)
    clean = [r for r in clean if r.get("line") is not None]

    for i in range(0, len(clean), 500):
        batch = clean[i : i + 500]
        supabase.table("props").upsert(batch, on_conflict="external_id").execute()
    print(f" Upserted {len(clean)} prop rows.")


def main():
    sport = get_sport_key()

    if sport is None:
        print(f"Off-season ({date.today()}). No MLB events to fetch.")
        return

    print(f"Fetching MLB props [{sport}] for {date.today()} ...")
    events = fetch_events(sport)
    print(f" Found {len(events)} games.")

    if not events:
        print(" No events today. Done.")
        return

    all_rows = []
    for event in events:
        try:
            data = fetch_player_props(sport, event["id"])
            rows = parse_props(data)
            all_rows.extend(rows)
            print(f" {event['home_team']} vs {event['away_team']}: {len(rows)} prop rows")
        except Exception as e:
            print(f" ERROR on {event.get('home_team','?')} vs {event.get('away_team','?')}: {e}")

    upsert_props(all_rows)
    print("Done.")


if __name__ == "__main__":
    main()
