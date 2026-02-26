import { createClient } from '@supabase/supabase-js'

const supabaseUrl = process.env.NEXT_PUBLIC_SUPABASE_URL || ''
const supabaseAnonKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY || ''

async function getPlayers(search?: string, position?: string) {
  if (!supabaseUrl || !supabaseAnonKey) {
    return []
  }
  const supabase = createClient(supabaseUrl, supabaseAnonKey)
  let query = supabase
    .from('players')
    .select('*')
    .order('full_name', { ascending: true })
    .limit(100)

  if (position && position !== 'ALL') {
    query = query.eq('position', position)
  }

  const { data, error } = await query
  if (error) {
    console.error('Error fetching players:', error)
    return []
  }
  return data || []
}

const POSITIONS = ['ALL', 'SP', 'RP', 'C', '1B', '2B', '3B', 'SS', 'LF', 'CF', 'RF', 'DH']

function PlayerCard({ player }: { player: any }) {
  return (
    <div className="bg-gray-800 border border-gray-700 rounded-lg p-4 hover:border-green-500 transition-colors">
      <div className="flex items-start justify-between mb-3">
        <div>
          <div className="text-lg font-semibold text-white">{player.full_name}</div>
          <div className="text-sm text-slate-400 mt-0.5">
            {player.team_name || player.team_id} &bull; {player.position}
          </div>
        </div>
        <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-gray-700 text-slate-300">
          #{player.jersey_number || '--'}
        </span>
      </div>
      {(player.b_hand || player.p_hand) && (
        <div className="mt-2 pt-2 border-t border-gray-700 grid grid-cols-2 gap-2 text-xs text-slate-400">
          {player.b_hand && (
            <span>Bats: <span className="text-slate-300">{player.b_hand}</span></span>
          )}
          {player.p_hand && (
            <span>Throws: <span className="text-slate-300">{player.p_hand}</span></span>
          )}
        </div>
      )}
      {player.age && (
        <div className="mt-1 text-xs text-slate-500">Age: {player.age}</div>
      )}
    </div>
  )
}

export default async function PlayersPage() {
  const players = await getPlayers()

  const pitchers = players.filter((p: any) => ['SP', 'RP', 'P'].includes(p.position))
  const batters = players.filter((p: any) => !['SP', 'RP', 'P'].includes(p.position))

  return (
    <div>
      <div className="mb-8">
        <h1 className="text-3xl font-bold text-white mb-2">Player Tracker</h1>
        <p className="text-slate-400">
          40-man roster data updated daily. {players.length} players tracked.
        </p>
      </div>

      {players.length === 0 ? (
        <div className="text-center py-16">
          <div className="text-4xl mb-4">⚾</div>
          <h2 className="text-xl font-semibold text-slate-300 mb-2">No player data yet</h2>
          <p className="text-slate-500">
            {!supabaseUrl
              ? 'Configure NEXT_PUBLIC_SUPABASE_URL to load players.'
              : 'Roster data loads automatically each morning before Opening Day 2026.'}
          </p>
        </div>
      ) : (
        <div className="space-y-10">
          {pitchers.length > 0 && (
            <section>
              <h2 className="text-xl font-semibold text-white mb-4 pb-2 border-b border-gray-700">
                Pitchers
                <span className="ml-2 text-sm font-normal text-slate-400">({pitchers.length})</span>
              </h2>
              <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
                {pitchers.map((player: any) => (
                  <PlayerCard key={player.player_id} player={player} />
                ))}
              </div>
            </section>
          )}

          {batters.length > 0 && (
            <section>
              <h2 className="text-xl font-semibold text-white mb-4 pb-2 border-b border-gray-700">
                Position Players
                <span className="ml-2 text-sm font-normal text-slate-400">({batters.length})</span>
              </h2>
              <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
                {batters.map((player: any) => (
                  <PlayerCard key={player.player_id} player={player} />
                ))}
              </div>
            </section>
          )}
        </div>
      )}
    </div>
  )
}
