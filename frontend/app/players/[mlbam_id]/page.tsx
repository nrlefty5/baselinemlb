import { createClient } from '@supabase/supabase-js'
import Link from 'next/link'

export const dynamic = 'force-dynamic'

const supabaseUrl = process.env.NEXT_PUBLIC_SUPABASE_URL || ''
const supabaseAnonKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY || ''

async function getPlayerData(mlbamId: string) {
  if (!supabaseUrl || !supabaseAnonKey) {
    return { player: null, projections: [], props: [] }
  }
  const supabase = createClient(supabaseUrl, supabaseAnonKey)

  // Fetch player info
  const { data: player } = await supabase
    .from('players')
    .select('*')
    .eq('mlbam_id', parseInt(mlbamId))
    .single()

  // Fetch recent projections (last 7 days)
  const weekAgo = new Date(Date.now() - 7 * 86400000).toISOString().split('T')[0]
  const { data: projections } = await supabase
    .from('projections')
    .select('*')
    .eq('mlbam_id', parseInt(mlbamId))
    .gte('game_date', weekAgo)
    .order('game_date', { ascending: false })
    .limit(20)

  // Fetch today's props for this player
  const today = new Date().toISOString().split('T')[0]
  const { data: props } = await supabase
    .from('props')
    .select('*')
    .eq('game_date', today)
    .ilike('player_name', `%${player?.full_name || ''}%`)
    .limit(20)

  return {
    player: player || null,
    projections: projections || [],
    props: props || [],
  }
}

function ConfidenceBadge({ score }: { score: number }) {
  const pct = Math.round(score * 100)
  const color =
    pct >= 70 ? 'bg-green-900 text-green-300 border-green-700' :
    pct >= 55 ? 'bg-blue-900 text-blue-300 border-blue-700' :
    'bg-gray-700 text-slate-400 border-gray-600'

  return (
    <span className={`inline-flex items-center px-2 py-0.5 rounded border text-xs font-medium ${color}`}>
      {pct}%
    </span>
  )
}

export default async function PlayerDetailPage({
  params,
}: {
  params: { mlbam_id: string }
}) {
  const { player, projections, props } = await getPlayerData(params.mlbam_id)

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

      {/* Today's Props */}
      {props.length > 0 && (
        <section className="mb-8">
          <h2 className="text-xl font-semibold text-white mb-4 pb-2 border-b border-gray-700">
            Today's Props
          </h2>
          <div className="overflow-x-auto rounded-lg border border-gray-700">
            <table className="min-w-full">
              <thead>
                <tr className="bg-gray-800 text-left">
                  <th className="py-2 px-4 text-xs font-medium text-slate-400 uppercase">Market</th>
                  <th className="py-2 px-4 text-xs font-medium text-slate-400 uppercase text-center">Line</th>
                  <th className="py-2 px-4 text-xs font-medium text-slate-400 uppercase text-center">Over</th>
                  <th className="py-2 px-4 text-xs font-medium text-slate-400 uppercase text-center">Under</th>
                  <th className="py-2 px-4 text-xs font-medium text-slate-400 uppercase text-center">Edge</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-700">
                {props.map((prop: any, i: number) => (
                  <tr key={i} className="hover:bg-gray-750">
                    <td className="py-2 px-4 text-slate-300">{prop.market_key}</td>
                    <td className="py-2 px-4 text-center font-semibold text-white">{prop.line}</td>
                    <td className="py-2 px-4 text-center text-slate-300">
                      {prop.over_odds && `${prop.over_odds > 0 ? '+' : ''}${prop.over_odds}`}
                    </td>
                    <td className="py-2 px-4 text-center text-slate-300">
                      {prop.under_odds && `${prop.under_odds > 0 ? '+' : ''}${prop.under_odds}`}
                    </td>
                    <td className="py-2 px-4 text-center">
                      {prop.edge_pct != null ? (
                        <span className={prop.edge_pct > 0 ? 'text-green-400' : prop.edge_pct < -3 ? 'text-red-400' : 'text-slate-400'}>
                          {prop.edge_pct > 0 ? '+' : ''}{prop.edge_pct?.toFixed(1)}%
                        </span>
                      ) : '--'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}

      {/* Recent Projections */}
      <section className="mb-8">
        <h2 className="text-xl font-semibold text-white mb-4 pb-2 border-b border-gray-700">
          Recent Projections
          <span className="ml-2 text-sm font-normal text-slate-400">Last 7 days</span>
        </h2>

        {projections.length === 0 ? (
          <p className="text-slate-500 py-4">No projections found for this player in the last 7 days.</p>
        ) : (
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {projections.map((proj: any, i: number) => {
              let features: any = {}
              try {
                features = typeof proj.features === 'string' ? JSON.parse(proj.features) : (proj.features || {})
              } catch {}

              return (
                <div key={i} className="bg-gray-800 border border-gray-700 rounded-lg p-4">
                  <div className="flex items-center justify-between mb-2">
                    <span className="text-xs text-slate-500">{proj.game_date}</span>
                    {proj.confidence && <ConfidenceBadge score={proj.confidence} />}
                  </div>
                  <div className="text-sm text-slate-400 mb-1">
                    {proj.stat_type === 'pitcher_strikeouts' ? 'Strikeouts' : 'Total Bases'}
                  </div>
                  <div className="text-2xl font-bold text-white">
                    {proj.projection?.toFixed(1)}
                  </div>
                  {features.venue && (
                    <div className="text-xs text-slate-500 mt-2">
                      vs {features.opponent} @ {features.venue}
                    </div>
                  )}
                  {/* Show v2.0 model factors if available */}
                  <div className="mt-2 grid grid-cols-2 gap-1 text-xs">
                    {features.blended_k9 && (
                      <div><span className="text-slate-500">K/9:</span> <span className="text-slate-300">{features.blended_k9}</span></div>
                    )}
                    {features.umpire_name && (
                      <div><span className="text-slate-500">Ump:</span> <span className="text-slate-300">{features.umpire_name}</span></div>
                    )}
                    {features.opp_k_pct && (
                      <div><span className="text-slate-500">Opp K%:</span> <span className="text-slate-300">{(features.opp_k_pct * 100).toFixed(1)}%</span></div>
                    )}
                    {features.platoon_matchup && features.platoon_matchup !== 'unknown' && (
                      <div><span className="text-slate-500">Platoon:</span> <span className="text-slate-300">{features.platoon_matchup}</span></div>
                    )}
                  </div>
                </div>
              )
            })}
          </div>
        )}
      </section>

      {/* Model Version */}
      {projections.length > 0 && (
        <div className="text-xs text-slate-600 mt-4">
          Model: {projections[0]?.model_version || 'v2.0-glass-box'}
        </div>
      )}
    </div>
  )
}
