import { createClient } from '@supabase/supabase-js'
import Link from 'next/link'
import PlayerProfileClient from './PlayerProfileClient'

export const dynamic = 'force-dynamic'

const supabaseUrl = process.env.NEXT_PUBLIC_SUPABASE_URL || ''
const supabaseAnonKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY || ''

const STAT_LABELS: Record<string, string> = {
  pitcher_strikeouts: 'Strikeouts',
  pitcher_walks: 'Walks (P)',
  batter_total_bases: 'Total Bases',
  batter_hits: 'Hits',
  batter_home_runs: 'Home Runs',
  batter_rbis: 'RBIs',
  batter_walks: 'Walks',
  batter_runs: 'Runs',
  batter_strikeouts: 'Batter Ks',
}

async function getPlayerData(mlbamId: string) {
  if (!supabaseUrl || !supabaseAnonKey) {
    return { player: null, projections: [], props: [], gameLog: [], rollingStats: [] }
  }
  const supabase = createClient(supabaseUrl, supabaseAnonKey)
  const mlbamInt = parseInt(mlbamId)

  // Fetch player info
  const { data: player } = await supabase
    .from('players')
    .select('*')
    .eq('mlbam_id', mlbamInt)
    .single()

  // Fetch recent projections (last 14 days, all stat types)
  const twoWeeksAgo = new Date(Date.now() - 14 * 86400000).toISOString().split('T')[0]
  const { data: projections } = await supabase
    .from('projections')
    .select('*')
    .eq('mlbam_id', mlbamInt)
    .gte('game_date', twoWeeksAgo)
    .order('game_date', { ascending: false })
    .limit(100)

  // Fetch today's props for this player (all markets)
  const today = new Date().toISOString().split('T')[0]
  const { data: props } = await supabase
    .from('props')
    .select('*')
    .eq('game_date', today)
    .ilike('player_name', `%${player?.full_name || ''}%`)
    .limit(50)

  // Fetch game log (picks with results for last 30 days)
  const thirtyDaysAgo = new Date(Date.now() - 30 * 86400000).toISOString().split('T')[0]
  const { data: gameLog } = await supabase
    .from('picks')
    .select('game_date, stat_type, line, projection, edge, direction, grade, result, actual_value')
    .eq('mlbam_id', mlbamInt)
    .gte('game_date', thirtyDaysAgo)
    .order('game_date', { ascending: false })
    .limit(100)

  // Fetch rolling advanced stats (last 30 days)
  const { data: rollingStats } = await supabase
    .from('player_rolling_stats')
    .select('*')
    .eq('player_id', mlbamInt)
    .gte('stat_date', thirtyDaysAgo)
    .order('stat_date', { ascending: true })
    .limit(30)

  return {
    player: player || null,
    projections: projections || [],
    props: props || [],
    gameLog: gameLog || [],
    rollingStats: rollingStats || [],
  }
}

export default async function PlayerDetailPage({
  params,
}: {
  params: { mlbam_id: string }
}) {
  const { player, projections, props, gameLog, rollingStats } = await getPlayerData(params.mlbam_id)

  if (!player) {
    return (
      <div className="text-center py-16">
        <h1 className="text-2xl font-bold text-white mb-2">Player Not Found</h1>
        <p className="text-slate-400 mb-4">No player found with ID {params.mlbam_id}</p>
        <Link href="/players" className="text-blue-400 hover:text-blue-300">
          Back to Players
        </Link>
      </div>
    )
  }

  return (
    <div>
      {/* Breadcrumb */}
      <div className="mb-6">
        <Link href="/players" className="text-sm text-slate-500 hover:text-slate-300 transition-colors">
          Players
        </Link>
        <span className="text-slate-600 mx-2">/</span>
        <span className="text-sm text-slate-300">{player.full_name}</span>
      </div>

      {/* Player Header */}
      <div className="bg-gray-800 border border-gray-700 rounded-lg p-6 mb-8">
        <div className="flex items-start justify-between">
          <div>
            <h1 className="text-3xl font-bold text-white mb-1">{player.full_name}</h1>
            <div className="flex items-center gap-3 text-slate-400">
              <span>{player.team}</span>
              <span className="text-slate-600">|</span>
              <span>{player.position}</span>
              {player.bats && (
                <>
                  <span className="text-slate-600">|</span>
                  <span>Bats: {player.bats}</span>
                </>
              )}
              {player.throws && (
                <>
                  <span className="text-slate-600">|</span>
                  <span>Throws: {player.throws}</span>
                </>
              )}
            </div>
          </div>
          <a
            href={`https://www.mlb.com/player/${player.mlbam_id}`}
            target="_blank"
            rel="noopener noreferrer"
            className="text-sm text-blue-400 hover:text-blue-300 border border-blue-800 px-3 py-1.5 rounded-lg"
          >
            MLB.com Profile
          </a>
        </div>
      </div>

      <PlayerProfileClient
        projections={projections}
        props={props}
        gameLog={gameLog}
        rollingStats={rollingStats}
        statLabels={STAT_LABELS}
        isPitcher={['SP', 'RP', 'P'].includes(player.position || '')}
      />

      {/* Model Version */}
      {projections.length > 0 && (
        <div className="text-xs text-slate-600 mt-4">
          Model: {projections[0]?.model_version || 'v2.1-glass-box'}
        </div>
      )}
    </div>
  )
}
