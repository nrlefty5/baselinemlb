import { createClient } from '@supabase/supabase-js'

export const dynamic = 'force-dynamic'

export const metadata = {
  title: 'Park Factors — Daily Ballpark Effects on MLB Props',
  description:
    'See how every MLB ballpark affects strikeouts, home runs, and total bases. Daily weather-adjusted park factor data for prop betting.',
}

const supabaseUrl = process.env.NEXT_PUBLIC_SUPABASE_URL || ''
const supabaseAnonKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY || ''

// ── All 30 MLB parks with factors ──────────────────────────────────────
// K factor: + means more Ks (pitcher-friendly), - means fewer
// HR factor: + means more HRs (hitter-friendly), - means fewer
// TB factor: + means more total bases, - means fewer

interface ParkData {
  venue: string
  team: string
  k: number
  hr: number
  tb: number
  dome: boolean
}

const DOME_STADIUMS = new Set([
  'Tropicana Field', 'Minute Maid Park', 'Globe Life Field',
  'Chase Field', 'Rogers Centre', 'American Family Field',
  'loanDepot park', 'T-Mobile Park',
])

const PARK_K: Record<string, number> = {
  'Chase Field': 1, 'Truist Park': 2, 'Camden Yards': 0,
  'Fenway Park': -1, 'Wrigley Field': -3, 'Guaranteed Rate Field': 0,
  'Great American Ball Park': -2, 'Progressive Field': 1,
  'Coors Field': -8, 'Comerica Park': 2, 'Minute Maid Park': 2,
  'Kauffman Stadium': 0, 'Angel Stadium': 0, 'Dodger Stadium': 4,
  'loanDepot park': 1, 'American Family Field': -1,
  'Target Field': 0, 'Citi Field': 1, 'Yankee Stadium': 3,
  'Oakland Coliseum': 2, 'Citizens Bank Park': -2, 'PNC Park': 1,
  'Petco Park': 4, 'Oracle Park': 5, 'T-Mobile Park': 3,
  'Busch Stadium': 1, 'Tropicana Field': 1, 'Globe Life Field': 2,
  'Rogers Centre': 0, 'Nationals Park': 1,
}

const PARK_HR: Record<string, number> = {
  'Chase Field': 3, 'Truist Park': 0, 'Camden Yards': 2,
  'Fenway Park': 2, 'Wrigley Field': 3, 'Guaranteed Rate Field': 1,
  'Great American Ball Park': 5, 'Progressive Field': 0,
  'Coors Field': 10, 'Comerica Park': -2, 'Minute Maid Park': 3,
  'Kauffman Stadium': 0, 'Angel Stadium': 1, 'Dodger Stadium': -1,
  'loanDepot park': -1, 'American Family Field': 2,
  'Target Field': 1, 'Citi Field': -1, 'Yankee Stadium': 5,
  'Oakland Coliseum': -2, 'Citizens Bank Park': 3, 'PNC Park': -1,
  'Petco Park': -3, 'Oracle Park': -4, 'T-Mobile Park': 0,
  'Busch Stadium': 0, 'Tropicana Field': 0, 'Globe Life Field': 1,
  'Rogers Centre': 2, 'Nationals Park': 1,
}

const PARK_TB: Record<string, number> = {
  'Coors Field': 12, 'Great American Ball Park': 8, 'Yankee Stadium': 5,
  'Fenway Park': 4, 'Citizens Bank Park': 3, 'Chase Field': 2,
  'Globe Life Field': 2, 'Minute Maid Park': 1, 'Truist Park': 0,
  'Guaranteed Rate Field': 0, 'Angel Stadium': 0, 'Wrigley Field': -1,
  'PNC Park': -2, 'loanDepot park': -3, 'Oracle Park': -5,
  'T-Mobile Park': -5, 'Petco Park': -6, 'Dodger Stadium': -2,
  'Busch Stadium': -1, 'Camden Yards': 1, 'Progressive Field': 0,
  'Comerica Park': -1, 'Kauffman Stadium': 0, 'American Family Field': 1,
  'Target Field': 0, 'Citi Field': -2, 'Oakland Coliseum': -1,
  'Tropicana Field': 0, 'Rogers Centre': 1, 'Nationals Park': 0,
}

const VENUE_TEAMS: Record<string, string> = {
  'Chase Field': 'ARI', 'Truist Park': 'ATL', 'Camden Yards': 'BAL',
  'Fenway Park': 'BOS', 'Wrigley Field': 'CHC', 'Guaranteed Rate Field': 'CWS',
  'Great American Ball Park': 'CIN', 'Progressive Field': 'CLE',
  'Coors Field': 'COL', 'Comerica Park': 'DET', 'Minute Maid Park': 'HOU',
  'Kauffman Stadium': 'KC', 'Angel Stadium': 'LAA', 'Dodger Stadium': 'LAD',
  'loanDepot park': 'MIA', 'American Family Field': 'MIL',
  'Target Field': 'MIN', 'Citi Field': 'NYM', 'Yankee Stadium': 'NYY',
  'Oakland Coliseum': 'OAK', 'Citizens Bank Park': 'PHI', 'PNC Park': 'PIT',
  'Petco Park': 'SD', 'Oracle Park': 'SF', 'T-Mobile Park': 'SEA',
  'Busch Stadium': 'STL', 'Tropicana Field': 'TB', 'Globe Life Field': 'TEX',
  'Rogers Centre': 'TOR', 'Nationals Park': 'WSH',
}

const ALL_PARKS: ParkData[] = Object.keys(PARK_K)
  .map(venue => ({
    venue,
    team: VENUE_TEAMS[venue] || '??',
    k: PARK_K[venue] ?? 0,
    hr: PARK_HR[venue] ?? 0,
    tb: PARK_TB[venue] ?? 0,
    dome: DOME_STADIUMS.has(venue),
  }))
  .sort((a, b) => a.venue.localeCompare(b.venue))

// ── Data fetching ──────────────────────────────────────────────────────

interface GameWithWeather {
  game_pk: number
  venue: string
  away_team: string
  home_team: string
  game_time: string
  temperature_f: number | null
  wind_speed_mph: number | null
  wind_direction: string | null
  humidity_pct: number | null
  k_rate_multiplier: number | null
}

async function getTodaysGamesWithWeather(): Promise<GameWithWeather[]> {
  if (!supabaseUrl || !supabaseAnonKey) return []
  const supabase = createClient(supabaseUrl, supabaseAnonKey)
  const today = new Date().toISOString().split('T')[0]

  const { data: games } = await supabase
    .from('games')
    .select('game_pk, venue, away_team, home_team, game_time')
    .eq('game_date', today)
    .order('game_time', { ascending: true })

  if (!games || games.length === 0) return []

  const gamePks = games.map((g: any) => g.game_pk)
  const { data: weather } = await supabase
    .from('weather')
    .select('game_pk, temperature_f, wind_speed_mph, wind_direction, humidity_pct, k_rate_multiplier')
    .in('game_pk', gamePks)

  const weatherMap: Record<number, any> = {}
  weather?.forEach((w: any) => { weatherMap[w.game_pk] = w })

  return games.map((g: any) => {
    const w = weatherMap[g.game_pk]
    return {
      ...g,
      temperature_f: w?.temperature_f ?? null,
      wind_speed_mph: w?.wind_speed_mph ?? null,
      wind_direction: w?.wind_direction ?? null,
      humidity_pct: w?.humidity_pct ?? null,
      k_rate_multiplier: w?.k_rate_multiplier ?? null,
    }
  })
}

// ── UI helpers ─────────────────────────────────────────────────────────

function factorColor(value: number, type: 'k' | 'hr' | 'tb'): string {
  // For K: positive = pitcher-friendly (green for K props), negative = hitter-friendly (red for K props)
  // For HR/TB: positive = hitter-friendly (green), negative = pitcher-friendly (red)
  const isKType = type === 'k'
  const abs = Math.abs(value)

  if (value === 0) return 'text-slate-500'

  if (isKType) {
    // K: positive is good for K overs
    if (value >= 4) return 'text-emerald-400 font-semibold'
    if (value >= 2) return 'text-emerald-500'
    if (value > 0) return 'text-emerald-600'
    if (value <= -4) return 'text-red-400 font-semibold'
    if (value <= -2) return 'text-red-500'
    return 'text-red-600'
  } else {
    // HR/TB: positive is good for batter overs
    if (value >= 6) return 'text-emerald-400 font-semibold'
    if (value >= 3) return 'text-emerald-500'
    if (value > 0) return 'text-emerald-600'
    if (value <= -4) return 'text-red-400 font-semibold'
    if (value <= -2) return 'text-red-500'
    return 'text-red-600'
  }
}

function FactorBar({ value, max }: { value: number; max: number }) {
  const pct = Math.min(Math.abs(value) / max * 100, 100)
  const isPositive = value > 0
  const barColor = isPositive ? 'bg-emerald-500' : 'bg-red-500'

  if (value === 0) {
    return <div className="w-full h-2 bg-slate-800 rounded-full" />
  }

  return (
    <div className="w-full h-2 bg-slate-800 rounded-full overflow-hidden relative">
      <div
        className={`absolute top-0 h-full rounded-full ${barColor}`}
        style={{
          width: `${pct}%`,
          ...(isPositive ? { left: '50%' } : { right: '50%' }),
        }}
      />
      <div className="absolute top-0 left-1/2 w-px h-full bg-slate-600" />
    </div>
  )
}

function weatherImpactLabel(temp: number | null, wind: number | null, windDir: string | null): string | null {
  const effects: string[] = []
  if (temp != null) {
    if (temp >= 85) effects.push('Hot — boosts HR/TB')
    else if (temp <= 45) effects.push('Cold — suppresses offense')
  }
  if (wind != null && windDir) {
    const dir = windDir.toLowerCase()
    if (wind >= 12) {
      if (dir.includes('out') || dir.includes('lf') || dir.includes('rf') || dir.includes('cf')) {
        effects.push(`Wind out ${wind}mph — boosts HR`)
      } else if (dir.includes('in')) {
        effects.push(`Wind in ${wind}mph — suppresses HR`)
      }
    }
  }
  return effects.length > 0 ? effects.join(' · ') : null
}

// ── Page ───────────────────────────────────────────────────────────────

export default async function ParkFactorsPage() {
  const todaysGames = await getTodaysGamesWithWeather()

  const today = new Date().toLocaleDateString('en-US', {
    weekday: 'long',
    month: 'long',
    day: 'numeric',
    timeZone: 'America/New_York',
  })

  // Find the parks in play today
  const todaysVenues = new Set(todaysGames.map(g => g.venue))

  // Pre-compute max values for bar scaling
  const maxK = Math.max(...ALL_PARKS.map(p => Math.abs(p.k)))
  const maxHR = Math.max(...ALL_PARKS.map(p => Math.abs(p.hr)))
  const maxTB = Math.max(...ALL_PARKS.map(p => Math.abs(p.tb)))

  return (
    <div className="max-w-6xl mx-auto px-4 py-10">
      {/* Header */}
      <div className="mb-8">
        <h1 className="text-3xl font-bold text-white mb-2">Park Factors</h1>
        <p className="text-slate-400">
          {today} &bull; How each MLB ballpark affects K, HR, and TB outcomes.
          {todaysGames.length > 0 && (
            <span className="ml-1">&bull; {todaysGames.length} games today</span>
          )}
        </p>
      </div>

      {/* Legend */}
      <div className="flex flex-wrap gap-4 mb-8 text-xs text-slate-400">
        <div className="flex items-center gap-2">
          <span className="inline-block w-3 h-3 rounded bg-emerald-500" />
          <span>Boosts stat (+ factor)</span>
        </div>
        <div className="flex items-center gap-2">
          <span className="inline-block w-3 h-3 rounded bg-red-500" />
          <span>Suppresses stat (- factor)</span>
        </div>
        <div className="flex items-center gap-2">
          <span className="inline-block w-3 h-3 rounded bg-slate-600" />
          <span>Neutral (0)</span>
        </div>
        <div className="flex items-center gap-2">
          <span className="text-yellow-500">★</span>
          <span>In play today</span>
        </div>
        <div className="flex items-center gap-2">
          <span className="text-blue-400">⌂</span>
          <span>Dome / retractable roof</span>
        </div>
      </div>

      {/* Today's Games Section */}
      {todaysGames.length > 0 && (
        <section className="mb-12">
          <h2 className="text-xl font-semibold text-white mb-4 pb-2 border-b border-emerald-800">
            Today&apos;s Games — Park Effects
            <span className="ml-2 text-sm font-normal text-emerald-500">{todaysGames.length} games</span>
          </h2>
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {todaysGames.map(game => {
              const k = PARK_K[game.venue] ?? 0
              const hr = PARK_HR[game.venue] ?? 0
              const tb = PARK_TB[game.venue] ?? 0
              const isDome = DOME_STADIUMS.has(game.venue)
              const impact = weatherImpactLabel(game.temperature_f, game.wind_speed_mph, game.wind_direction)

              return (
                <div
                  key={game.game_pk}
                  className="bg-gray-800 border border-gray-700 rounded-lg p-4 hover:border-gray-500 transition-colors"
                >
                  <div className="flex items-center justify-between mb-2">
                    <div className="font-semibold text-white text-sm">
                      {game.away_team} @ {game.home_team}
                    </div>
                    <div className="text-xs text-slate-500">
                      {new Date(game.game_time).toLocaleTimeString('en-US', {
                        hour: 'numeric',
                        minute: '2-digit',
                        timeZone: 'America/New_York',
                      })} ET
                    </div>
                  </div>

                  <div className="text-xs text-slate-400 mb-3">
                    {game.venue}
                    {isDome && <span className="text-blue-400 ml-1">⌂</span>}
                  </div>

                  {/* Factor chips */}
                  <div className="flex gap-2 mb-3">
                    <span className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-medium border ${
                      k > 0 ? 'bg-emerald-900/50 border-emerald-700 text-emerald-300' :
                      k < 0 ? 'bg-red-900/50 border-red-700 text-red-300' :
                      'bg-slate-800 border-slate-700 text-slate-400'
                    }`}>
                      K {k > 0 ? '+' : ''}{k}%
                    </span>
                    <span className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-medium border ${
                      hr > 0 ? 'bg-emerald-900/50 border-emerald-700 text-emerald-300' :
                      hr < 0 ? 'bg-red-900/50 border-red-700 text-red-300' :
                      'bg-slate-800 border-slate-700 text-slate-400'
                    }`}>
                      HR {hr > 0 ? '+' : ''}{hr}%
                    </span>
                    <span className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-medium border ${
                      tb > 0 ? 'bg-emerald-900/50 border-emerald-700 text-emerald-300' :
                      tb < 0 ? 'bg-red-900/50 border-red-700 text-red-300' :
                      'bg-slate-800 border-slate-700 text-slate-400'
                    }`}>
                      TB {tb > 0 ? '+' : ''}{tb}%
                    </span>
                  </div>

                  {/* Weather */}
                  {(game.temperature_f != null || game.wind_speed_mph != null) && (
                    <div className="text-xs text-slate-500 border-t border-gray-700 pt-2 mt-2">
                      <div className="flex gap-3">
                        {game.temperature_f != null && <span>{game.temperature_f}°F</span>}
                        {game.wind_speed_mph != null && (
                          <span>{game.wind_speed_mph}mph {game.wind_direction || ''}</span>
                        )}
                        {game.humidity_pct != null && <span>{game.humidity_pct}% humidity</span>}
                      </div>
                      {impact && (
                        <div className="mt-1 text-yellow-500/80 font-medium">{impact}</div>
                      )}
                      {game.k_rate_multiplier != null && game.k_rate_multiplier !== 1.0 && (
                        <div className="mt-1">
                          <span className="text-slate-600">Weather K adj:</span>
                          <span className={`ml-1 ${game.k_rate_multiplier > 1 ? 'text-emerald-500' : 'text-red-500'}`}>
                            {game.k_rate_multiplier > 1 ? '+' : ''}{((game.k_rate_multiplier - 1) * 100).toFixed(1)}%
                          </span>
                        </div>
                      )}
                    </div>
                  )}
                </div>
              )
            })}
          </div>
        </section>
      )}

      {/* Full Reference Table */}
      <section>
        <h2 className="text-xl font-semibold text-white mb-4 pb-2 border-b border-gray-700">
          All 30 MLB Ballparks
          <span className="ml-2 text-sm font-normal text-slate-400">Season baseline factors</span>
        </h2>

        {/* Column headers explanation */}
        <div className="grid grid-cols-3 gap-4 mb-4 text-xs text-slate-500">
          <div className="text-center">
            <span className="font-medium text-slate-400">K Factor</span>
            <div>+ = more strikeouts</div>
          </div>
          <div className="text-center">
            <span className="font-medium text-slate-400">HR Factor</span>
            <div>+ = more home runs</div>
          </div>
          <div className="text-center">
            <span className="font-medium text-slate-400">TB Factor</span>
            <div>+ = more total bases</div>
          </div>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-gray-700 text-slate-400 text-xs">
                <th className="text-left py-3 pr-4 font-medium">Venue</th>
                <th className="text-center py-3 px-2 font-medium">Team</th>
                <th className="text-center py-3 px-2 font-medium w-16">K%</th>
                <th className="py-3 px-2 w-24"><span className="sr-only">K bar</span></th>
                <th className="text-center py-3 px-2 font-medium w-16">HR%</th>
                <th className="py-3 px-2 w-24"><span className="sr-only">HR bar</span></th>
                <th className="text-center py-3 px-2 font-medium w-16">TB%</th>
                <th className="py-3 px-2 w-24"><span className="sr-only">TB bar</span></th>
              </tr>
            </thead>
            <tbody>
              {ALL_PARKS.map(park => {
                const inPlay = todaysVenues.has(park.venue)
                return (
                  <tr
                    key={park.venue}
                    className={`border-b border-gray-800 ${
                      inPlay ? 'bg-emerald-950/20' : 'hover:bg-gray-800/50'
                    } transition-colors`}
                  >
                    <td className="py-2.5 pr-4">
                      <div className="flex items-center gap-1.5">
                        {inPlay && <span className="text-yellow-500 text-xs">★</span>}
                        <span className={inPlay ? 'text-white font-medium' : 'text-slate-300'}>
                          {park.venue}
                        </span>
                        {park.dome && <span className="text-blue-400 text-xs">⌂</span>}
                      </div>
                    </td>
                    <td className="text-center py-2.5 px-2 text-slate-500 font-mono text-xs">
                      {park.team}
                    </td>
                    <td className={`text-center py-2.5 px-2 font-mono ${factorColor(park.k, 'k')}`}>
                      {park.k > 0 ? '+' : ''}{park.k}
                    </td>
                    <td className="py-2.5 px-2">
                      <FactorBar value={park.k} max={maxK} />
                    </td>
                    <td className={`text-center py-2.5 px-2 font-mono ${factorColor(park.hr, 'hr')}`}>
                      {park.hr > 0 ? '+' : ''}{park.hr}
                    </td>
                    <td className="py-2.5 px-2">
                      <FactorBar value={park.hr} max={maxHR} />
                    </td>
                    <td className={`text-center py-2.5 px-2 font-mono ${factorColor(park.tb, 'tb')}`}>
                      {park.tb > 0 ? '+' : ''}{park.tb}
                    </td>
                    <td className="py-2.5 px-2">
                      <FactorBar value={park.tb} max={maxTB} />
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      </section>

      {/* Methodology note */}
      <section className="mt-12 p-6 bg-gray-900 rounded-lg border border-gray-700">
        <h3 className="text-sm font-semibold text-slate-300 uppercase tracking-wider mb-3">
          How Park Factors Work
        </h3>
        <div className="text-sm text-slate-400 space-y-2">
          <p>
            Park factors represent the percentage adjustment each ballpark applies to a given stat
            relative to a neutral venue. A <span className="text-emerald-400">+5% K factor</span> means
            pitchers throw ~5% more strikeouts at that park, while a <span className="text-red-400">-8% K factor</span> (Coors Field)
            means significantly fewer Ks.
          </p>
          <p>
            These factors are baked into every FullCountProps projection. Our model adjusts pitcher K/9, batter TB/PA,
            and HR rates using these park-specific multipliers before running Monte Carlo simulations.
          </p>
          <p>
            Weather conditions (temperature, wind speed/direction, humidity) create additional daily adjustments
            on top of the baseline park factors. Hot weather and wind blowing out boost offense; cold temps and
            wind blowing in suppress it.
          </p>
        </div>
      </section>
    </div>
  )
}
