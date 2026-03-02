import { createClient } from '@supabase/supabase-js'
import EmailSignup from './EmailSignup'
import Link from 'next/link'

export const dynamic = 'force-dynamic'

const supabaseUrl = process.env.NEXT_PUBLIC_SUPABASE_URL || ''
const supabaseAnonKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY || ''

// Opening Day 2026: March 26, 2026
const OPENING_DAY = new Date('2026-03-26T16:05:00-04:00')

function getDaysUntilOpeningDay(): number {
  const now = new Date()
  const diff = OPENING_DAY.getTime() - now.getTime()
  return Math.max(0, Math.ceil(diff / (1000 * 60 * 60 * 24)))
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

async function getSubscriberCount(): Promise<number> {
  if (!supabaseUrl || !supabaseAnonKey) return 0
  try {
    const supabase = createClient(supabaseUrl, supabaseAnonKey)
    const { count, error } = await supabase
      .from('email_subscribers')
      .select('*', { count: 'exact', head: true })
      .eq('active', true)
    if (error) return 0
    return count || 0
  } catch {
    return 0
  }
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

export default async function HomePage() {
  const [games, subscriberCount] = await Promise.all([
    getTodaysGames(),
    getSubscriberCount(),
  ])
  const daysUntil = getDaysUntilOpeningDay()
  const today = new Date().toLocaleDateString('en-US', {
    weekday: 'long',
    month: 'long',
    day: 'numeric',
    year: 'numeric',
    timeZone: 'America/New_York',
  })

  return (
    <div>
      {/* Opening Day Countdown Banner */}
      {daysUntil > 0 && (
        <div className="mb-8 p-4 bg-gradient-to-r from-green-900/40 to-gray-900/40 border border-green-700/50 rounded-xl flex items-center justify-between">
          <div>
            <div className="text-sm text-green-400 font-medium uppercase tracking-wider mb-0.5">Opening Day 2026</div>
            <div className="text-white text-sm">March 26 &mdash; Full model projections go live</div>
          </div>
          <div className="text-right">
            <div className="text-4xl font-bold text-white">{daysUntil}</div>
            <div className="text-xs text-slate-400 uppercase tracking-wider">days away</div>
          </div>
        </div>
      )}

      <div className="mb-8">
        <h1 className="text-3xl font-bold text-white mb-2">Today&apos;s Slate</h1>
        <p className="text-slate-400">{today}</p>
      </div>

      {games.length === 0 ? (
        <div>
          <div className="text-center py-12">
            <div className="text-4xl mb-4">&#x26BE;</div>
            <h2 className="text-xl font-semibold text-slate-300 mb-2">No games today</h2>
            <p className="text-slate-500 max-w-sm mx-auto">
              {!supabaseUrl
                ? 'Configure NEXT_PUBLIC_SUPABASE_URL and NEXT_PUBLIC_SUPABASE_ANON_KEY to load games.'
                : 'Pipelines run automatically starting Opening Day 2026. Check the Props and Projections pages for pre-season analysis.'}
            </p>
          </div>

          {/* Waitlist / Newsletter Signup */}
          <div className="max-w-md mx-auto mt-6">
            <EmailSignup />
            {subscriberCount > 0 && (
              <p className="text-center text-xs text-slate-500 mt-2">
                Join {subscriberCount.toLocaleString()}+ subscribers on the waitlist
              </p>
            )}
          </div>

          {/* Quick nav to other pages */}
          <div className="mt-10 grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
            <Link href="/best-bets" className="block p-4 bg-gray-800 border border-gray-700 rounded-xl hover:border-green-500 transition-colors">
              <div className="text-green-400 text-xl mb-2">&#x1F3AF;</div>
              <div className="font-semibold text-white">Best Bets</div>
              <div className="text-xs text-slate-400 mt-1">Top picks ranked by edge %</div>
            </Link>
            <Link href="/props" className="block p-4 bg-gray-800 border border-gray-700 rounded-xl hover:border-green-500 transition-colors">
              <div className="text-green-400 text-xl mb-2">&#x1F4CA;</div>
              <div className="font-semibold text-white">Props</div>
              <div className="text-xs text-slate-400 mt-1">Today&apos;s player prop lines with edge %</div>
            </Link>
            <Link href="/projections" className="block p-4 bg-gray-800 border border-gray-700 rounded-xl hover:border-green-500 transition-colors">
              <div className="text-green-400 text-xl mb-2">&#x1F9E0;</div>
              <div className="font-semibold text-white">Projections</div>
              <div className="text-xs text-slate-400 mt-1">Glass-box K projection model</div>
            </Link>
            <Link href="/calibration" className="block p-4 bg-gray-800 border border-gray-700 rounded-xl hover:border-green-500 transition-colors">
              <div className="text-green-400 text-xl mb-2">&#x1F4C8;</div>
              <div className="font-semibold text-white">Calibration</div>
              <div className="text-xs text-slate-400 mt-1">Model accuracy and calibration chart</div>
            </Link>
          </div>
        </div>
      ) : (
        <>
          <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
            {games.map((game: any) => (
              <GameCard key={game.game_pk} game={game} />
            ))}
          </div>

          {/* Waitlist / Newsletter Signup below games */}
          <div className="mt-12 max-w-md mx-auto">
            <EmailSignup />
            {subscriberCount > 0 && (
              <p className="text-center text-xs text-slate-500 mt-2">
                Join {subscriberCount.toLocaleString()}+ subscribers on the waitlist
              </p>
            )}
          </div>
        </>
      )}
    </div>
  )
}
