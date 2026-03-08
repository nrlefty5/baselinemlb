'use client'

import { useState, useMemo } from 'react'

interface PlayerProfileClientProps {
  projections: any[]
  props: any[]
  statLabels: Record<string, string>
}

function ConfidenceBadge({ score }: { score: number }) {
  const pct = Math.round(score * 100)
  let color: string
  let tier: string
  if (pct >= 85) {
    color = 'bg-emerald-900 text-emerald-200 border-emerald-600'
    tier = 'ELITE'
  } else if (pct >= 70) {
    color = 'bg-green-900 text-green-300 border-green-700'
    tier = 'HIGH'
  } else if (pct >= 55) {
    color = 'bg-blue-900 text-blue-300 border-blue-700'
    tier = 'MED'
  } else if (pct >= 40) {
    color = 'bg-yellow-900 text-yellow-300 border-yellow-700'
    tier = 'LOW'
  } else {
    color = 'bg-red-900/50 text-red-400 border-red-800'
    tier = 'V.LOW'
  }

  return (
    <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded border text-xs font-medium ${color}`}>
      {pct}% <span className="opacity-75">{tier}</span>
    </span>
  )
}

// Map prop market_key to our stat_type for matching
const MARKET_TO_STAT: Record<string, string> = {
  'pitcher_strikeouts': 'pitcher_strikeouts',
  'batter_total_bases': 'batter_total_bases',
  'batter_hits': 'batter_hits',
  'batter_home_runs': 'batter_home_runs',
  'batter_rbis': 'batter_rbis',
  'batter_walks': 'batter_walks',
  'batter_runs': 'batter_runs',
  'batter_strikeouts': 'batter_strikeouts',
  'pitcher_walks': 'pitcher_walks',
  // Common sportsbook market names
  'strikeouts': 'pitcher_strikeouts',
  'total_bases': 'batter_total_bases',
  'hits': 'batter_hits',
  'home_runs': 'batter_home_runs',
  'rbis': 'batter_rbis',
  'walks': 'batter_walks',
  'runs': 'batter_runs',
}

function PropEdgeCard({
  projection,
  prop,
  statLabel,
}: {
  projection: any
  prop: any | null
  statLabel: string
}) {
  const features = (() => {
    try {
      return typeof projection.features === 'string'
        ? JSON.parse(projection.features)
        : (projection.features || {})
    } catch { return {} }
  })()

  // Calculate edge if we have both projection and prop line
  let edge: number | null = null
  let direction: string | null = null
  if (prop && prop.line != null && projection.projection != null) {
    const diff = projection.projection - prop.line
    edge = prop.line > 0 ? (diff / prop.line) * 100 : null
    direction = diff > 0 ? 'OVER' : 'UNDER'
  }

  const confFactors = features.confidence_factors

  return (
    <div className="bg-gray-800 border border-gray-700 rounded-lg p-5 hover:border-gray-600 transition-colors">
      {/* Header */}
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <span className="text-sm font-semibold text-white">{statLabel}</span>
          {direction && (
            <span className={`text-xs font-bold px-2 py-0.5 rounded ${
              direction === 'OVER'
                ? 'text-green-400 bg-green-900/30'
                : 'text-red-400 bg-red-900/30'
            }`}>
              {direction}
            </span>
          )}
        </div>
        {projection.confidence != null && (
          <ConfidenceBadge score={projection.confidence} />
        )}
      </div>

      {/* Stats Row */}
      <div className="flex items-center gap-6">
        <div>
          <div className="text-2xl font-bold text-white">{projection.projection?.toFixed(1)}</div>
          <div className="text-xs text-slate-500">Projected</div>
        </div>
        {prop && prop.line != null && (
          <div>
            <div className="text-2xl font-bold text-slate-400">{prop.line}</div>
            <div className="text-xs text-slate-500">Line</div>
          </div>
        )}
        {edge != null && (
          <div>
            <div className={`text-2xl font-bold ${edge > 0 ? 'text-green-400' : 'text-red-400'}`}>
              {edge > 0 ? '+' : ''}{edge.toFixed(1)}%
            </div>
            <div className="text-xs text-slate-500">Edge</div>
          </div>
        )}
        {prop && (
          <div className="flex gap-4 text-xs text-slate-400">
            {prop.over_odds != null && (
              <span>O: <span className="text-slate-300">{prop.over_odds > 0 ? '+' : ''}{prop.over_odds}</span></span>
            )}
            {prop.under_odds != null && (
              <span>U: <span className="text-slate-300">{prop.under_odds > 0 ? '+' : ''}{prop.under_odds}</span></span>
            )}
          </div>
        )}
      </div>

      {/* Key Factors */}
      <div className="mt-3 pt-3 border-t border-gray-700 grid grid-cols-2 gap-1 text-xs">
        {features.blended_k9 != null && (
          <div><span className="text-slate-500">K/9:</span> <span className="text-slate-300">{features.blended_k9}</span></div>
        )}
        {features.opp_k_pct != null && (
          <div><span className="text-slate-500">Opp K%:</span> <span className="text-slate-300">{(features.opp_k_pct * 100).toFixed(1)}%</span></div>
        )}
        {features.umpire_name && (
          <div><span className="text-slate-500">Ump:</span> <span className="text-slate-300">{features.umpire_name}</span></div>
        )}
        {features.expected_innings != null && (
          <div><span className="text-slate-500">Exp IP:</span> <span className="text-slate-300">{features.expected_innings}</span></div>
        )}
        {features.park_adjustment && (
          <div><span className="text-slate-500">Park:</span> <span className="text-slate-300">{features.park_adjustment}</span></div>
        )}
        {features.platoon_matchup && features.platoon_matchup !== 'unknown' && (
          <div><span className="text-slate-500">Platoon:</span> <span className="text-slate-300">{features.platoon_matchup}</span></div>
        )}
        {features.career_tb_per_pa != null && (
          <div><span className="text-slate-500">TB/PA:</span> <span className="text-slate-300">{features.career_tb_per_pa}</span></div>
        )}
        {features.opponent && (
          <div><span className="text-slate-500">vs:</span> <span className="text-slate-300">{features.opponent}</span></div>
        )}
        {features.opponent_pitcher && (
          <div><span className="text-slate-500">vs:</span> <span className="text-slate-300">{features.opponent_pitcher}</span></div>
        )}
        {features.venue && (
          <div><span className="text-slate-500">Venue:</span> <span className="text-slate-300">{features.venue}</span></div>
        )}
      </div>

      {/* Confidence Factor Breakdown */}
      {confFactors && (
        <div className="mt-3 pt-3 border-t border-gray-700">
          <div className="text-xs text-slate-500 mb-1.5 font-medium uppercase tracking-wider">Confidence Breakdown</div>
          <div className="grid grid-cols-2 gap-1.5">
            {Object.entries(confFactors)
              .filter(([k]) => k !== 'overall')
              .map(([key, value]) => (
                <div key={key} className="flex items-center gap-2">
                  <span className="text-xs text-slate-500 w-28 truncate">
                    {key.replace(/_/g, ' ')}
                  </span>
                  <div className="flex-1 h-1.5 bg-gray-700 rounded-full overflow-hidden">
                    <div
                      className={`h-full rounded-full ${
                        (value as number) >= 0.7 ? 'bg-green-500' :
                        (value as number) >= 0.4 ? 'bg-blue-500' :
                        'bg-yellow-500'
                      }`}
                      style={{ width: `${Math.round((value as number) * 100)}%` }}
                    />
                  </div>
                  <span className="text-xs text-slate-400 w-8 text-right font-mono">
                    {((value as number) * 100).toFixed(0)}%
                  </span>
                </div>
              ))}
          </div>
        </div>
      )}
    </div>
  )
}

export default function PlayerProfileClient({
  projections,
  props,
  statLabels,
}: PlayerProfileClientProps) {
  // Get unique stat types from projections
  const statTypes = useMemo(() => {
    const types = new Set(projections.map((p: any) => p.stat_type))
    return Array.from(types).sort()
  }, [projections])

  const [selectedStat, setSelectedStat] = useState<string>('all')

  // Filter projections by selected stat type
  const filteredProjections = useMemo(() => {
    if (selectedStat === 'all') return projections
    return projections.filter((p: any) => p.stat_type === selectedStat)
  }, [projections, selectedStat])

  // Group today's projections by stat type for edge cards
  const today = new Date().toISOString().split('T')[0]
  const todayProjections = useMemo(() => {
    return projections.filter((p: any) => p.game_date === today)
  }, [projections, today])

  // Build prop lookup map
  const propMap = useMemo(() => {
    const map: Record<string, any> = {}
    for (const prop of props) {
      const statType = MARKET_TO_STAT[prop.market_key] || MARKET_TO_STAT[prop.stat_type] || prop.market_key
      map[statType] = prop
    }
    return map
  }, [props])

  // History projections (past, not today)
  const historyProjections = useMemo(() => {
    const past = filteredProjections.filter((p: any) => p.game_date !== today)
    return past
  }, [filteredProjections, today])

  return (
    <>
      {/* Stat Type Tabs */}
      {statTypes.length > 1 && (
        <div className="flex flex-wrap gap-2 mb-6">
          <button
            onClick={() => setSelectedStat('all')}
            className={`px-3 py-1.5 rounded-lg text-sm font-medium transition-colors ${
              selectedStat === 'all'
                ? 'bg-blue-600 text-white'
                : 'bg-gray-800 text-slate-400 hover:text-white border border-gray-700'
            }`}
          >
            All Stats
          </button>
          {statTypes.map(type => (
            <button
              key={type}
              onClick={() => setSelectedStat(type)}
              className={`px-3 py-1.5 rounded-lg text-sm font-medium transition-colors ${
                selectedStat === type
                  ? 'bg-blue-600 text-white'
                  : 'bg-gray-800 text-slate-400 hover:text-white border border-gray-700'
              }`}
            >
              {statLabels[type] || type}
            </button>
          ))}
        </div>
      )}

      {/* Today's Prop Edge Cards */}
      {todayProjections.length > 0 && (
        <section className="mb-8">
          <h2 className="text-xl font-semibold text-white mb-4 pb-2 border-b border-gray-700">
            Today's Projections & Edges
          </h2>
          <div className="grid gap-4 sm:grid-cols-2">
            {todayProjections
              .filter(p => selectedStat === 'all' || p.stat_type === selectedStat)
              .map((proj: any, i: number) => (
                <PropEdgeCard
                  key={`today-${proj.stat_type}-${i}`}
                  projection={proj}
                  prop={propMap[proj.stat_type] || null}
                  statLabel={statLabels[proj.stat_type] || proj.stat_type}
                />
              ))}
          </div>
        </section>
      )}

      {/* Today's Props Table (all markets, including ones without projections) */}
      {props.length > 0 && (
        <section className="mb-8">
          <h2 className="text-xl font-semibold text-white mb-4 pb-2 border-b border-gray-700">
            Today's Sportsbook Lines
          </h2>
          <div className="overflow-x-auto rounded-lg border border-gray-700">
            <table className="min-w-full">
              <thead>
                <tr className="bg-gray-800 text-left">
                  <th className="py-2 px-4 text-xs font-medium text-slate-400 uppercase">Market</th>
                  <th className="py-2 px-4 text-xs font-medium text-slate-400 uppercase text-center">Line</th>
                  <th className="py-2 px-4 text-xs font-medium text-slate-400 uppercase text-center">Over</th>
                  <th className="py-2 px-4 text-xs font-medium text-slate-400 uppercase text-center">Under</th>
                  <th className="py-2 px-4 text-xs font-medium text-slate-400 uppercase text-center">Our Proj</th>
                  <th className="py-2 px-4 text-xs font-medium text-slate-400 uppercase text-center">Edge</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-700">
                {props.map((prop: any, i: number) => {
                  const statType = MARKET_TO_STAT[prop.market_key] || MARKET_TO_STAT[prop.stat_type] || prop.market_key
                  const matchProj = todayProjections.find((p: any) => p.stat_type === statType)
                  let edge: number | null = prop.edge_pct ?? null
                  if (edge == null && matchProj && prop.line > 0) {
                    edge = ((matchProj.projection - prop.line) / prop.line) * 100
                  }

                  return (
                    <tr key={i} className="hover:bg-gray-800/50">
                      <td className="py-2 px-4 text-slate-300">
                        {statLabels[prop.market_key] || statLabels[statType] || prop.market_key}
                      </td>
                      <td className="py-2 px-4 text-center font-semibold text-white">{prop.line}</td>
                      <td className="py-2 px-4 text-center text-slate-300">
                        {prop.over_odds != null && `${prop.over_odds > 0 ? '+' : ''}${prop.over_odds}`}
                      </td>
                      <td className="py-2 px-4 text-center text-slate-300">
                        {prop.under_odds != null && `${prop.under_odds > 0 ? '+' : ''}${prop.under_odds}`}
                      </td>
                      <td className="py-2 px-4 text-center font-semibold text-white">
                        {matchProj ? matchProj.projection.toFixed(1) : '--'}
                      </td>
                      <td className="py-2 px-4 text-center">
                        {edge != null ? (
                          <span className={edge > 3 ? 'text-green-400 font-semibold' : edge < -3 ? 'text-red-400' : 'text-slate-400'}>
                            {edge > 0 ? '+' : ''}{edge.toFixed(1)}%
                          </span>
                        ) : '--'}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        </section>
      )}

      {/* Recent Projection History */}
      <section className="mb-8">
        <h2 className="text-xl font-semibold text-white mb-4 pb-2 border-b border-gray-700">
          Projection History
          <span className="ml-2 text-sm font-normal text-slate-400">Last 14 days</span>
        </h2>

        {historyProjections.length === 0 ? (
          <p className="text-slate-500 py-4">No historical projections found for this player.</p>
        ) : (
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {historyProjections.map((proj: any, i: number) => {
              let features: any = {}
              try {
                features = typeof proj.features === 'string' ? JSON.parse(proj.features) : (proj.features || {})
              } catch {}

              return (
                <div key={i} className="bg-gray-800 border border-gray-700 rounded-lg p-4">
                  <div className="flex items-center justify-between mb-2">
                    <span className="text-xs text-slate-500">{proj.game_date}</span>
                    {proj.confidence != null && <ConfidenceBadge score={proj.confidence} />}
                  </div>
                  <div className="text-sm text-slate-400 mb-1">
                    {statLabels[proj.stat_type] || proj.stat_type}
                  </div>
                  <div className="text-2xl font-bold text-white">
                    {proj.projection?.toFixed(1)}
                  </div>
                  {(features.venue || features.opponent || features.opponent_pitcher) && (
                    <div className="text-xs text-slate-500 mt-2">
                      {features.opponent && `vs ${features.opponent}`}
                      {features.opponent_pitcher && `vs ${features.opponent_pitcher}`}
                      {features.venue && ` @ ${features.venue}`}
                    </div>
                  )}
                  <div className="mt-2 grid grid-cols-2 gap-1 text-xs">
                    {features.blended_k9 != null && (
                      <div><span className="text-slate-500">K/9:</span> <span className="text-slate-300">{features.blended_k9}</span></div>
                    )}
                    {features.opp_k_pct != null && (
                      <div><span className="text-slate-500">Opp K%:</span> <span className="text-slate-300">{(features.opp_k_pct * 100).toFixed(1)}%</span></div>
                    )}
                    {features.umpire_name && (
                      <div><span className="text-slate-500">Ump:</span> <span className="text-slate-300">{features.umpire_name}</span></div>
                    )}
                    {features.platoon_matchup && features.platoon_matchup !== 'unknown' && (
                      <div><span className="text-slate-500">Platoon:</span> <span className="text-slate-300">{features.platoon_matchup}</span></div>
                    )}
                    {features.park_adjustment && (
                      <div><span className="text-slate-500">Park:</span> <span className="text-slate-300">{features.park_adjustment}</span></div>
                    )}
                    {features.career_tb_per_pa != null && (
                      <div><span className="text-slate-500">TB/PA:</span> <span className="text-slate-300">{features.career_tb_per_pa}</span></div>
                    )}
                  </div>
                </div>
              )
            })}
          </div>
        )}
      </section>
    </>
  )
}
