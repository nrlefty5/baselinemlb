import { createClient } from '@supabase/supabase-js'
export const dynamic = 'force-dynamic'

const supabaseUrl = process.env.NEXT_PUBLIC_SUPABASE_URL || ''
const supabaseAnonKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY || ''

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

export default async function HomePage() {
  const games = await getTodaysGames()
  const today = new Date().toLocaleDateString('en-US', {
    weekday: 'long',
    month: 'long',
    day: 'numeric',
    year: 'numeric',
    timeZone: 'America/New_York',
  })

  return (
    <div>
      <div className="mb-8">
        <h1 className="text-3xl font-bold text-white mb-2">Today\'s Slate</h1>
        <p className="text-slate-400">{today}</p>
      </div>

      {games.length === 0 ? (
        <div className="text-center py-16">
          <div className="text-4xl mb-4">⚾</div>
          <h2 className="text-xl font-semibold text-slate-300 mb-2">No games today</h2>
          <p className="text-slate-500">
            {!supabaseUrl
              ? 'Configure NEXT_PUBLIC_SUPABASE_URL and NEXT_PUBLIC_SUPABASE_ANON_KEY to load games.'
              : 'Check back during the regular season. Pipelines run automatically starting Opening Day 2026.'}
          </p>
          <div className="mt-8 p-4 bg-gray-900 rounded-lg border border-gray-700 max-w-md mx-auto">
            <p className="text-sm text-slate-400">Tracking begins Opening Day 2026.</p>
            <p className="text-sm text-slate-400 mt-1">Follow <a href="https://twitter.com/baselinemlb" className="text-blue-400 hover:text-blue-300">@baselinemlb</a> for daily analysis.</p>
          </div>
        </div>
      ) : (
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
          {games.map((game: any) => (
            <GameCard key={game.game_pk} game={game} />
          ))}
        </div>
      )}
    </div>
  )
}
