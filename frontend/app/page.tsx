import { createClient } from '@supabase/supabase-js'
import Link from 'next/link'
import HeroSignup from './HeroSignup'

export const dynamic = 'force-dynamic'

const supabaseUrl = process.env.NEXT_PUBLIC_SUPABASE_URL || ''
const supabaseAnonKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY || ''

// Opening Day 2026: March 26, 2026
const OPENING_DAY = new Date('2026-03-26T16:05:00-04:00')

function getDaysUntilOpeningDay(): number {
  const now = new Date()
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate())
  const target = new Date(2026, 2, 26) // March 26, 2026
  const diff = target.getTime() - today.getTime()
  return Math.max(0, Math.round(diff / (1000 * 60 * 60 * 24)))
}

async function getTodaysGames() {
  if (!supabaseUrl || !supabaseAnonKey) {
    return []
  }
  const supabase = createClient(supabaseUrl, supabaseAnonKey)
  const today = new Date().toISOString().split('T')[0]
  const { data, error } = await supabase
    .from('games')
    .select('*')
    .eq('game_date', today)
    .order('game_time', { ascending: true })
  if (error) {
    console.error('Error fetching games:', error)
    return []
  }
  return data || []
}

function GameCard({ game }: { game: any }) {
  const gameTime = game.game_time
    ? new Date(`2000-01-01T${game.game_time}`).toLocaleTimeString('en-US', {
        hour: 'numeric',
        minute: '2-digit',
        timeZone: 'America/New_York',
      }) + ' ET'
    : 'TBD'
  return (
    <div className="game-card">
      <div className="flex items-center justify-between mb-3">
        <span className="text-xs text-slate-400 uppercase tracking-wider">{game.venue || 'TBD'}</span>
        <span className="text-xs text-slate-400">{gameTime}</span>
      </div>
      <div className="flex items-center justify-between">
        <div className="flex-1">
          <div className="text-lg font-semibold text-white">{game.away_team}</div>
          <div className="text-sm text-slate-400 mt-0.5">Away</div>
        </div>
        <div className="px-4 text-center">
          <div className="text-slate-500 font-medium">@</div>
          {game.status === 'Final' && (
            <div className="text-xs text-baseline-green mt-1">Final</div>
          )}
          {game.status === 'In Progress' && (
            <div className="text-xs text-baseline-yellow mt-1 animate-pulse">Live</div>
          )}
        </div>
        <div className="flex-1 text-right">
          <div className="text-lg font-semibold text-white">{game.home_team}</div>
          <div className="text-sm text-slate-400 mt-0.5">Home</div>
        </div>
      </div>
      {(game.home_starter || game.away_starter) && (
        <div className="mt-3 pt-3 border-t border-gray-700 flex justify-between text-xs text-slate-400">
          <span>{game.away_starter || 'SP TBD'}</span>
          <span>vs</span>
          <span>{game.home_starter || 'SP TBD'}</span>
        </div>
      )}
    </div>
  )
}

/* ── Sample Pick Card (static mock for hero) ── */
function SamplePickCard() {
  return (
    <div className="bg-slate-900 border border-slate-700 rounded-2xl overflow-hidden max-w-sm w-full">
      {/* Header */}
      <div className="px-5 py-3 border-b border-slate-700 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className="text-xs px-2 py-0.5 rounded bg-green-900 text-green-300 font-bold">HIGH</span>
          <span className="text-xs text-slate-500">Today 7:10 PM ET</span>
        </div>
        <span className="text-xs text-green-400 font-mono font-bold">+9.2% edge</span>
      </div>

      {/* Main */}
      <div className="px-5 py-4">
        <div className="flex items-center justify-between mb-3">
          <div>
            <div className="text-white font-semibold">Corbin Burnes</div>
            <div className="text-xs text-slate-500">BAL vs NYY &middot; Yankee Stadium</div>
          </div>
          <div className="text-right">
            <div className="text-white font-bold text-lg">O 6.5 Ks</div>
            <div className="text-xs text-slate-500">-115 DraftKings</div>
          </div>
        </div>

        {/* Factor breakdown */}
        <div className="mt-3 pt-3 border-t border-slate-800 space-y-1.5">
          <div className="text-xs text-slate-500 uppercase tracking-wider mb-2">Factor Breakdown</div>
          <div className="flex justify-between text-xs">
            <span className="text-slate-400">Base matchup K rate</span>
            <span className="text-slate-300">26.3%</span>
          </div>
          <div className="flex justify-between text-xs">
            <span className="text-slate-400">Park K factor</span>
            <span className="text-blue-400">+1.4pp</span>
          </div>
          <div className="flex justify-between text-xs">
            <span className="text-slate-400">Umpire tendency</span>
            <span className="text-blue-400">+2.2pp</span>
          </div>
          <div className="flex justify-between text-xs">
            <span className="text-slate-400">Catcher framing</span>
            <span className="text-blue-400">+3.0pp</span>
          </div>
        </div>

        {/* Sim stats */}
        <div className="mt-3 pt-3 border-t border-slate-800 flex gap-4">
          <div>
            <div className="text-xs text-slate-500">Sim mean</div>
            <div className="text-sm font-semibold text-white">6.8 Ks</div>
          </div>
          <div>
            <div className="text-xs text-slate-500">P(Over)</div>
            <div className="text-sm font-semibold text-green-400">60.7%</div>
          </div>
          <div>
            <div className="text-xs text-slate-500">Book implied</div>
            <div className="text-sm font-semibold text-slate-300">54.3%</div>
          </div>
          <div>
            <div className="text-xs text-slate-500">Kelly</div>
            <div className="text-sm font-semibold text-slate-300">2.4%</div>
          </div>
        </div>
      </div>

      {/* Footer */}
      <div className="px-5 py-3 bg-slate-800/50 border-t border-slate-700 text-center">
        <span className="text-xs text-slate-500">Sample pick &middot; Not real-time data</span>
      </div>
    </div>
  )
}

export default async function HomePage() {
  const games = await getTodaysGames()
  const daysUntil = getDaysUntilOpeningDay()
  const isPreSeason = daysUntil > 0

  return (
    <div>
      {/* ════════════════════════════════════════════════
          HERO SECTION
          ════════════════════════════════════════════════ */}
      <section className="relative overflow-hidden">
        {/* Subtle gradient background */}
        <div className="absolute inset-0 bg-gradient-to-b from-green-950/20 via-slate-950 to-slate-950" />
        <div className="absolute top-0 left-1/2 -translate-x-1/2 w-[800px] h-[400px] bg-green-500/5 rounded-full blur-3xl" />

        <div className="relative max-w-6xl mx-auto px-4 pt-16 pb-20">
          <div className="grid lg:grid-cols-2 gap-12 items-center">
            {/* Left: Value prop */}
            <div>
              {isPreSeason && (
                <div className="inline-flex items-center gap-2 px-3 py-1.5 bg-green-900/30 border border-green-700/50 rounded-full text-xs text-green-400 font-medium mb-6">
                  <span className="w-1.5 h-1.5 bg-green-400 rounded-full animate-pulse" />
                  Opening Day in {daysUntil} days &mdash; March 26, 2026
                </div>
              )}

              <h1 className="text-4xl sm:text-5xl font-bold text-white leading-tight tracking-tight mb-6">
                MLB prop edges you can{' '}
                <span className="text-green-400">actually verify</span>
              </h1>

              <p className="text-slate-400 text-lg leading-relaxed mb-8 max-w-lg">
                2,500 Monte Carlo simulations per game. 33 Statcast features.
                Glass-box factor breakdowns on every pick. See exactly why we like
                each bet &mdash; not just that we do.
              </p>

              {/* CTA */}
              <HeroSignup />
            </div>

            {/* Right: Sample pick card */}
            <div className="flex justify-center lg:justify-end">
              <SamplePickCard />
            </div>
          </div>
        </div>
      </section>

      {/* ════════════════════════════════════════════════
          SOCIAL PROOF / STATS BAR
          ════════════════════════════════════════════════ */}
      <section className="border-y border-slate-800 bg-slate-900/50">
        <div className="max-w-6xl mx-auto px-4 py-10">
          <div className="text-center mb-6">
            <div className="text-xs text-slate-500 uppercase tracking-wider mb-1">
              Backtested on 12,847 graded props &middot; 2024 season
            </div>
          </div>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-6">
            {[
              { value: '+8.7%', label: 'Backtest ROI', sub: 'at 4% edge threshold' },
              { value: '3.1%', label: 'Calibration Error', sub: 'ECE across all bins' },
              { value: '2,500', label: 'Simulations', sub: 'per game, PA-level' },
              { value: '6', label: 'Prop Types', sub: 'K, H, TB, RBI, BB, R' },
            ].map((stat) => (
              <div key={stat.label} className="text-center">
                <div className="text-2xl sm:text-3xl font-bold text-green-400">
                  {stat.value}
                </div>
                <div className="text-sm text-slate-300 font-medium mt-1">
                  {stat.label}
                </div>
                <div className="text-xs text-slate-500 mt-0.5">{stat.sub}</div>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ════════════════════════════════════════════════
          HOW IT WORKS
          ════════════════════════════════════════════════ */}
      <section className="max-w-6xl mx-auto px-4 py-20">
        <div className="text-center mb-12">
          <h2 className="text-2xl font-bold text-white mb-3">
            How FullCountProps Works
          </h2>
          <p className="text-slate-400 max-w-lg mx-auto">
            Three layers of analysis, updated twice daily during the season.
          </p>
        </div>

        <div className="grid sm:grid-cols-3 gap-6">
          {[
            {
              step: '01',
              title: 'Matchup Model',
              desc: 'A LightGBM model takes 33 Statcast features for every pitcher-batter matchup and predicts the probability of 8 PA outcomes.',
              color: 'text-green-400',
            },
            {
              step: '02',
              title: 'Monte Carlo Simulation',
              desc: 'Each game is simulated 2,500 times, plate appearance by plate appearance, with real lineups, park factors, umpire data, and weather.',
              color: 'text-blue-400',
            },
            {
              step: '03',
              title: 'Edge Detection',
              desc: 'Simulated probability distributions are compared to sportsbook lines (vig-removed) to surface props where we see 3%+ mathematical edge.',
              color: 'text-purple-400',
            },
          ].map((item) => (
            <div
              key={item.step}
              className="bg-slate-900/60 border border-slate-800 rounded-xl p-6"
            >
              <div className={`${item.color} font-mono text-sm font-bold mb-3`}>
                {item.step}
              </div>
              <h3 className="text-lg font-semibold text-white mb-2">
                {item.title}
              </h3>
              <p className="text-sm text-slate-400 leading-relaxed">
                {item.desc}
              </p>
            </div>
          ))}
        </div>

        <div className="text-center mt-8">
          <Link
            href="/methodology"
            className="text-sm text-green-400 hover:text-green-300 font-medium transition-colors"
          >
            Read the full methodology &rarr;
          </Link>
        </div>
      </section>

      {/* ════════════════════════════════════════════════
          DIFFERENTIATORS
          ════════════════════════════════════════════════ */}
      <section className="max-w-6xl mx-auto px-4 pb-20">
        <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-6">
          {[
            {
              icon: '🔍',
              title: 'Glass-Box Transparency',
              desc: 'Every pick shows exactly what drove the projection: park factor, umpire, catcher framing, weather, platoon. No black boxes.',
            },
            {
              icon: '⚾',
              title: 'PA-Level Simulation',
              desc: 'Not a simple formula. We simulate every plate appearance of every game with full game state: innings, outs, runners, pitch count.',
            },
            {
              icon: '📊',
              title: 'Publicly Graded',
              desc: 'Every projection is graded against actual results nightly. We never hide bad nights. Full accuracy data is always available.',
            },
            {
              icon: '🧪',
              title: 'Open Source',
              desc: 'The entire codebase is on GitHub. Audit the model, verify the methodology, or run your own simulations.',
            },
            {
              icon: '🎯',
              title: 'Umpire + Framing',
              desc: 'We integrate home plate umpire K-rate tendencies and catcher pitch framing at the PA level — most competitors don\'t.',
            },
            {
              icon: '🌡️',
              title: 'Real-Time Weather',
              desc: 'Temperature, wind speed, and wind direction are fetched 75 minutes before first pitch and applied to HR probability.',
            },
          ].map((feature) => (
            <div
              key={feature.title}
              className="p-5 bg-slate-900/40 border border-slate-800 rounded-xl"
            >
              <div className="text-2xl mb-3">{feature.icon}</div>
              <h3 className="font-semibold text-white mb-1">{feature.title}</h3>
              <p className="text-sm text-slate-400 leading-relaxed">
                {feature.desc}
              </p>
            </div>
          ))}
        </div>
      </section>

      {/* ════════════════════════════════════════════════
          TODAY'S GAMES (if any)
          ════════════════════════════════════════════════ */}
      {games.length > 0 && (
        <section className="max-w-6xl mx-auto px-4 pb-20">
          <h2 className="text-2xl font-bold text-white mb-6">
            Today&apos;s Slate
          </h2>
          <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
            {games.map((game: any) => (
              <GameCard key={game.game_pk} game={game} />
            ))}
          </div>
        </section>
      )}

      {/* ════════════════════════════════════════════════
          QUICK NAV
          ════════════════════════════════════════════════ */}
      <section className="max-w-6xl mx-auto px-4 pb-20">
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
          <Link
            href="/props"
            className="block p-5 bg-slate-900/60 border border-slate-800 rounded-xl hover:border-green-500/50 transition-colors"
          >
            <div className="text-green-400 text-xl mb-2">&#128202;</div>
            <div className="font-semibold text-white">Props</div>
            <div className="text-xs text-slate-400 mt-1">
              Today&apos;s player prop lines with edge %
            </div>
          </Link>
          <Link
            href="/projections"
            className="block p-5 bg-slate-900/60 border border-slate-800 rounded-xl hover:border-green-500/50 transition-colors"
          >
            <div className="text-green-400 text-xl mb-2">&#129504;</div>
            <div className="font-semibold text-white">Projections</div>
            <div className="text-xs text-slate-400 mt-1">
              Glass-box projection model outputs
            </div>
          </Link>
          <Link
            href="/players"
            className="block p-5 bg-slate-900/60 border border-slate-800 rounded-xl hover:border-green-500/50 transition-colors"
          >
            <div className="text-green-400 text-xl mb-2">&#128100;</div>
            <div className="font-semibold text-white">Players</div>
            <div className="text-xs text-slate-400 mt-1">
              Search 2,000+ MLB roster entries
            </div>
          </Link>
        </div>
      </section>

      {/* ════════════════════════════════════════════════
          BOTTOM CTA
          ════════════════════════════════════════════════ */}
      <section className="max-w-6xl mx-auto px-4 pb-20">
        <div className="text-center p-10 bg-gradient-to-b from-green-950/20 to-slate-900/60 border border-slate-800 rounded-2xl">
          <h2 className="text-2xl font-bold text-white mb-3">
            Ready to find your edge?
          </h2>
          <p className="text-slate-400 mb-6 max-w-md mx-auto">
            Join the waitlist for free daily prop picks, or upgrade to Pro for
            the full slate with SHAP explanations.
          </p>
          <div className="flex items-center justify-center gap-4 flex-wrap">
            <Link
              href="/subscribe"
              className="px-6 py-3 bg-green-600 hover:bg-green-500 text-white font-semibold rounded-xl transition-colors"
            >
              View Plans
            </Link>
            <Link
              href="/methodology"
              className="px-6 py-3 bg-slate-700 hover:bg-slate-600 text-white font-medium rounded-xl transition-colors"
            >
              Read Methodology
            </Link>
          </div>
        </div>
      </section>
    </div>
  )
}
