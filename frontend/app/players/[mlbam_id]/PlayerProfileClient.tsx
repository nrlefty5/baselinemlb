'use client'

import { useState, useMemo } from 'react'

interface PlayerProfileClientProps {
  projections: any[]
  props: any[]
  gameLog: any[]
  rollingStats: any[]
  statLabels: Record<string, string>
  isPitcher: boolean
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
  'strikeouts': 'pitcher_strikeouts',
  'total_bases': 'batter_total_bases',
  'hits': 'batter_hits',
  'home_runs': 'batter_home_runs',
  'rbis': 'batter_rbis',
  'walks': 'batter_walks',
  'runs': 'batter_runs',
}

// SVG Sparkline component
function Sparkline({ values, color = 'text-blue-400', height = 32 }: { values: number[]; color?: string; height?: number }) {
  if (values.length < 2) return null
  const min = Math.min(...values)
  const max = Math.max(...values)
  const range = max - min || 1
  const width = 120
  const points = values.map((v, i) => {
    const x = (i / (values.length - 1)) * width
    const y = height - ((v - min) / range) * (height - 4) - 2
    return `${x},${y}`
  }).join(' ')

  return (
    <svg width={width} height={height} className={`inline-block ${color}`}>
      <polyline
        points={points}
        fill="none"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      {/* Dot on the last point */}
      {values.length > 0 && (() => {
        const lastX = width
        const lastY = height - ((values[values.length - 1] - min) / range) * (height - 4) - 2
        return <circle cx={lastX} cy={lastY} r="2.5" fill="currentColor" />
      })()}
    </svg>
  )
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
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <span className="text-sm font-semibold text-white">{statLabel}</span>
          {direction && (
            <span className={`text-xs font-bold px-2 py-0.5 rounded ${
              direction === 'OVER' ? 'text-green-400 bg-green-900/30' : 'text-red-400 bg-red-900/30'
            }`}>
              {direction}
            </span>
          )}
        </div>
        {projection.confidence != null && <ConfidenceBadge score={projection.confidence} />}
      </div>

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
        {features.blended_k9 != null && <div><span className="text-slate-500">K/9:</span> <span className="text-slate-300">{features.blended_k9}</span></div>}
        {features.opp_k_pct != null && <div><span className="text-slate-500">Opp K%:</span> <span className="text-slate-300">{(features.opp_k_pct * 100).toFixed(1)}%</span></div>}
        {features.umpire_name && <div><span className="text-slate-500">Ump:</span> <span className="text-slate-300">{features.umpire_name}</span></div>}
        {features.expected_innings != null && <div><span className="text-slate-500">Exp IP:</span> <span className="text-slate-300">{features.expected_innings}</span></div>}
        {features.park_adjustment && <div><span className="text-slate-500">Park:</span> <span className="text-slate-300">{features.park_adjustment}</span></div>}
        {features.platoon_matchup && features.platoon_matchup !== 'unknown' && <div><span className="text-slate-500">Platoon:</span> <span className="text-slate-300">{features.platoon_matchup}</span></div>}
        {features.career_tb_per_pa != null && <div><span className="text-slate-500">TB/PA:</span> <span className="text-slate-300">{features.career_tb_per_pa}</span></div>}
        {features.opponent && <div><span className="text-slate-500">vs:</span> <span className="text-slate-300">{features.opponent}</span></div>}
        {features.opponent_pitcher && <div><span className="text-slate-500">vs:</span> <span className="text-slate-300">{features.opponent_pitcher}</span></div>}
        {features.venue && <div><span className="text-slate-500">Venue:</span> <span className="text-slate-300">{features.venue}</span></div>}
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
                  <span className="text-xs text-slate-500 w-28 truncate">{key.replace(/_/g, ' ')}</span>
                  <div className="flex-1 h-1.5 bg-gray-700 rounded-full overflow-hidden">
                    <div
                      className={`h-full rounded-full ${(value as number) >= 0.7 ? 'bg-green-500' : (value as number) >= 0.4 ? 'bg-blue-500' : 'bg-yellow-500'}`}
                      style={{ width: `${Math.round((value as number) * 100)}%` }}
                    />
                  </div>
                  <span className="text-xs text-slate-400 w-8 text-right font-mono">{((value as number) * 100).toFixed(0)}%</span>
                </div>
              ))}
          </div>
        </div>
      )}
    </div>
  )
}

type Tab = 'projections' | 'game-log' | 'trends'

export default function PlayerProfileClient({
  projections,
  props,
  gameLog,
  rollingStats,
  statLabels,
  isPitcher,
}: PlayerProfileClientProps) {
  const [activeTab, setActiveTab] = useState<Tab>('projections')
  const [selectedStat, setSelectedStat] = useState<string>('all')

  const statTypes = useMemo(() => {
    const types = new Set(projections.map((p: any) => p.stat_type))
    return Array.from(types).sort()
  }, [projections])

  const today = new Date().toISOString().split('T')[0]

  const todayProjections = useMemo(() => {
    return projections.filter((p: any) => p.game_date === today)
  }, [projections, today])

  const propMap = useMemo(() => {
    const map: Record<string, any> = {}
    for (const prop of props) {
      const statType = MARKET_TO_STAT[prop.market_key] || MARKET_TO_STAT[prop.stat_type] || prop.market_key
      map[statType] = prop
    }
    return map
  }, [props])

  const filteredProjections = useMemo(() => {
    const past = projections.filter((p: any) => p.game_date !== today)
    if (selectedStat === 'all') return past
    return past.filter((p: any) => p.stat_type === selectedStat)
  }, [projections, selectedStat, today])

  // Game log: group by stat type and compute splits
  const gameLogByStat = useMemo(() => {
    const map: Record<string, any[]> = {}
    for (const entry of gameLog) {
      const key = entry.stat_type
      if (!map[key]) map[key] = []
      map[key].push(entry)
    }
    return map
  }, [gameLog])

  // Compute splits from game log (projection vs actual, win/loss record)
  const splitsSummary = useMemo(() => {
    if (gameLog.length === 0) return null
    const graded = gameLog.filter(g => g.result)
    const wins = graded.filter(g => g.result === 'win' || g.result === 'W').length
    const losses = graded.filter(g => g.result === 'loss' || g.result === 'L').length
    const pushes = graded.filter(g => g.result === 'push' || g.result === 'P').length
    const overHits = graded.filter(g => g.direction === 'OVER' && (g.result === 'win' || g.result === 'W')).length
    const overTotal = graded.filter(g => g.direction === 'OVER').length
    const underHits = graded.filter(g => g.direction === 'UNDER' && (g.result === 'win' || g.result === 'W')).length
    const underTotal = graded.filter(g => g.direction === 'UNDER').length

    return { wins, losses, pushes, total: graded.length, overHits, overTotal, underHits, underTotal }
  }, [gameLog])

  const tabs: { key: Tab; label: string }[] = [
    { key: 'projections', label: 'Projections' },
    { key: 'game-log', label: 'Game Log' },
    { key: 'trends', label: 'Trends & Splits' },
  ]

  return (
    <>
      {/* Tab Navigation */}
      <div className="flex border-b border-gray-700 mb-6">
        {tabs.map(tab => (
          <button
            key={tab.key}
            onClick={() => setActiveTab(tab.key)}
            className={`px-4 py-2.5 text-sm font-medium border-b-2 transition-colors ${
              activeTab === tab.key
                ? 'border-blue-500 text-blue-400'
                : 'border-transparent text-slate-500 hover:text-slate-300'
            }`}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {/* ═══════════════════════════════════════════════════════════════ */}
      {/* PROJECTIONS TAB */}
      {/* ═══════════════════════════════════════════════════════════════ */}
      {activeTab === 'projections' && (
        <>
          {/* Stat Type Filter */}
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

          {/* Today's Edge Cards */}
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

          {/* Sportsbook Lines Table */}
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
                      <th className="py-2 px-4 text-xs font-medium text-slate-400 uppercase text-center">Proj</th>
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
                          <td className="py-2 px-4 text-slate-300">{statLabels[prop.market_key] || statLabels[statType] || prop.market_key}</td>
                          <td className="py-2 px-4 text-center font-semibold text-white">{prop.line}</td>
                          <td className="py-2 px-4 text-center text-slate-300">{prop.over_odds != null && `${prop.over_odds > 0 ? '+' : ''}${prop.over_odds}`}</td>
                          <td className="py-2 px-4 text-center text-slate-300">{prop.under_odds != null && `${prop.under_odds > 0 ? '+' : ''}${prop.under_odds}`}</td>
                          <td className="py-2 px-4 text-center font-semibold text-white">{matchProj ? matchProj.projection.toFixed(1) : '--'}</td>
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

          {/* Projection History */}
          <section className="mb-8">
            <h2 className="text-xl font-semibold text-white mb-4 pb-2 border-b border-gray-700">
              Projection History
              <span className="ml-2 text-sm font-normal text-slate-400">Last 14 days</span>
            </h2>
            {filteredProjections.length === 0 ? (
              <p className="text-slate-500 py-4">No historical projections found.</p>
            ) : (
              <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
                {filteredProjections.map((proj: any, i: number) => {
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
                      <div className="text-sm text-slate-400 mb-1">{statLabels[proj.stat_type] || proj.stat_type}</div>
                      <div className="text-2xl font-bold text-white">{proj.projection?.toFixed(1)}</div>
                      {(features.venue || features.opponent || features.opponent_pitcher) && (
                        <div className="text-xs text-slate-500 mt-2">
                          {features.opponent && `vs ${features.opponent}`}
                          {features.opponent_pitcher && `vs ${features.opponent_pitcher}`}
                          {features.venue && ` @ ${features.venue}`}
                        </div>
                      )}
                    </div>
                  )
                })}
              </div>
            )}
          </section>
        </>
      )}

      {/* ═══════════════════════════════════════════════════════════════ */}
      {/* GAME LOG TAB */}
      {/* ═══════════════════════════════════════════════════════════════ */}
      {activeTab === 'game-log' && (
        <section>
          <h2 className="text-xl font-semibold text-white mb-4 pb-2 border-b border-gray-700">
            Game Log
            <span className="ml-2 text-sm font-normal text-slate-400">Last 30 days</span>
          </h2>

          {gameLog.length === 0 ? (
            <p className="text-slate-500 py-4">No game log data available for this player.</p>
          ) : (
            Object.entries(gameLogByStat).map(([statType, entries]) => (
              <div key={statType} className="mb-6">
                <h3 className="text-sm font-medium text-slate-400 mb-3 uppercase tracking-wider">
                  {statLabels[statType] || statType}
                </h3>
                <div className="overflow-x-auto rounded-lg border border-gray-700">
                  <table className="min-w-full">
                    <thead>
                      <tr className="bg-gray-800 text-left">
                        <th className="py-2 px-3 text-xs font-medium text-slate-400">Date</th>
                        <th className="py-2 px-3 text-xs font-medium text-slate-400 text-center">Line</th>
                        <th className="py-2 px-3 text-xs font-medium text-slate-400 text-center">Proj</th>
                        <th className="py-2 px-3 text-xs font-medium text-slate-400 text-center">Actual</th>
                        <th className="py-2 px-3 text-xs font-medium text-slate-400 text-center">Dir</th>
                        <th className="py-2 px-3 text-xs font-medium text-slate-400 text-center">Edge</th>
                        <th className="py-2 px-3 text-xs font-medium text-slate-400 text-center">Grade</th>
                        <th className="py-2 px-3 text-xs font-medium text-slate-400 text-center">Result</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-gray-700">
                      {entries.map((entry: any, i: number) => {
                        const isWin = entry.result === 'win' || entry.result === 'W'
                        const isLoss = entry.result === 'loss' || entry.result === 'L'
                        return (
                          <tr key={i} className="hover:bg-gray-800/50">
                            <td className="py-2 px-3 text-xs text-slate-300">{entry.game_date}</td>
                            <td className="py-2 px-3 text-center text-white font-mono">{entry.line ?? '--'}</td>
                            <td className="py-2 px-3 text-center text-blue-400 font-mono">{entry.projection?.toFixed(1) ?? '--'}</td>
                            <td className="py-2 px-3 text-center text-white font-bold font-mono">{entry.actual_value ?? '--'}</td>
                            <td className="py-2 px-3 text-center">
                              {entry.direction && (
                                <span className={`text-xs font-bold ${entry.direction === 'OVER' ? 'text-green-400' : 'text-red-400'}`}>
                                  {entry.direction}
                                </span>
                              )}
                            </td>
                            <td className="py-2 px-3 text-center text-xs text-slate-400">
                              {entry.edge != null ? `${entry.edge > 0 ? '+' : ''}${Number(entry.edge).toFixed(1)}%` : '--'}
                            </td>
                            <td className="py-2 px-3 text-center text-xs text-slate-300">{entry.grade || '--'}</td>
                            <td className="py-2 px-3 text-center">
                              {entry.result ? (
                                <span className={`inline-flex items-center justify-center w-6 h-6 rounded-full text-xs font-bold ${
                                  isWin ? 'bg-green-900/50 text-green-400' :
                                  isLoss ? 'bg-red-900/50 text-red-400' :
                                  'bg-gray-700 text-slate-400'
                                }`}>
                                  {isWin ? 'W' : isLoss ? 'L' : 'P'}
                                </span>
                              ) : (
                                <span className="text-slate-600">--</span>
                              )}
                            </td>
                          </tr>
                        )
                      })}
                    </tbody>
                  </table>
                </div>
              </div>
            ))
          )}
        </section>
      )}

      {/* ═══════════════════════════════════════════════════════════════ */}
      {/* TRENDS & SPLITS TAB */}
      {/* ═══════════════════════════════════════════════════════════════ */}
      {activeTab === 'trends' && (
        <>
          {/* Picks Record Summary */}
          {splitsSummary && splitsSummary.total > 0 && (
            <section className="mb-8">
              <h2 className="text-xl font-semibold text-white mb-4 pb-2 border-b border-gray-700">
                Picks Record
                <span className="ml-2 text-sm font-normal text-slate-400">Last 30 days</span>
              </h2>
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
                <div className="bg-gray-800 border border-gray-700 rounded-lg p-4 text-center">
                  <div className="text-2xl font-bold text-white">
                    {splitsSummary.wins}-{splitsSummary.losses}
                    {splitsSummary.pushes > 0 && <span className="text-slate-500">-{splitsSummary.pushes}</span>}
                  </div>
                  <div className="text-xs text-slate-500 mt-1">Overall Record</div>
                </div>
                <div className="bg-gray-800 border border-gray-700 rounded-lg p-4 text-center">
                  <div className="text-2xl font-bold text-white">
                    {splitsSummary.total > 0 ? `${Math.round((splitsSummary.wins / splitsSummary.total) * 100)}%` : '--'}
                  </div>
                  <div className="text-xs text-slate-500 mt-1">Win Rate</div>
                </div>
                <div className="bg-gray-800 border border-gray-700 rounded-lg p-4 text-center">
                  <div className="text-2xl font-bold text-green-400">
                    {splitsSummary.overTotal > 0 ? `${splitsSummary.overHits}/${splitsSummary.overTotal}` : '--'}
                  </div>
                  <div className="text-xs text-slate-500 mt-1">Over Record</div>
                </div>
                <div className="bg-gray-800 border border-gray-700 rounded-lg p-4 text-center">
                  <div className="text-2xl font-bold text-red-400">
                    {splitsSummary.underTotal > 0 ? `${splitsSummary.underHits}/${splitsSummary.underTotal}` : '--'}
                  </div>
                  <div className="text-xs text-slate-500 mt-1">Under Record</div>
                </div>
              </div>
            </section>
          )}

          {/* Rolling Advanced Stats with Sparklines */}
          {rollingStats.length > 0 && (
            <section className="mb-8">
              <h2 className="text-xl font-semibold text-white mb-4 pb-2 border-b border-gray-700">
                Recent Performance Trends
                <span className="ml-2 text-sm font-normal text-slate-400">14-day rolling</span>
              </h2>
              <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
                {isPitcher ? (
                  <>
                    {/* Pitcher stats */}
                    <TrendCard
                      label="K Rate"
                      values={rollingStats.map(s => Number(s.k_rate_14d)).filter(v => !isNaN(v))}
                      format={(v) => `${(v * 100).toFixed(1)}%`}
                      color="text-blue-400"
                    />
                    <TrendCard
                      label="BB Rate"
                      values={rollingStats.map(s => Number(s.bb_rate_14d)).filter(v => !isNaN(v))}
                      format={(v) => `${(v * 100).toFixed(1)}%`}
                      color="text-red-400"
                      invertColor
                    />
                    <TrendCard
                      label="Whiff Rate"
                      values={rollingStats.map(s => Number(s.whiff_rate_14d)).filter(v => !isNaN(v))}
                      format={(v) => `${(v * 100).toFixed(1)}%`}
                      color="text-green-400"
                    />
                    <TrendCard
                      label="CSW%"
                      values={rollingStats.map(s => Number(s.csw_14d)).filter(v => !isNaN(v))}
                      format={(v) => `${(v * 100).toFixed(1)}%`}
                      color="text-emerald-400"
                    />
                    <TrendCard
                      label="SwStr%"
                      values={rollingStats.map(s => Number(s.swstr_14d)).filter(v => !isNaN(v))}
                      format={(v) => `${(v * 100).toFixed(1)}%`}
                      color="text-purple-400"
                    />
                    <TrendCard
                      label="Zone%"
                      values={rollingStats.map(s => Number(s.zone_14d)).filter(v => !isNaN(v))}
                      format={(v) => `${(v * 100).toFixed(1)}%`}
                      color="text-amber-400"
                    />
                  </>
                ) : (
                  <>
                    {/* Batter stats */}
                    <TrendCard
                      label="xBA"
                      values={rollingStats.map(s => Number(s.xba_14d)).filter(v => !isNaN(v))}
                      format={(v) => v.toFixed(3)}
                      color="text-blue-400"
                    />
                    <TrendCard
                      label="xSLG"
                      values={rollingStats.map(s => Number(s.xslg_14d)).filter(v => !isNaN(v))}
                      format={(v) => v.toFixed(3)}
                      color="text-green-400"
                    />
                    <TrendCard
                      label="Barrel%"
                      values={rollingStats.map(s => Number(s.barrel_rate_14d)).filter(v => !isNaN(v))}
                      format={(v) => `${(v * 100).toFixed(1)}%`}
                      color="text-emerald-400"
                    />
                    <TrendCard
                      label="Hard Hit%"
                      values={rollingStats.map(s => Number(s.hard_hit_14d)).filter(v => !isNaN(v))}
                      format={(v) => `${(v * 100).toFixed(1)}%`}
                      color="text-amber-400"
                    />
                    <TrendCard
                      label="Exit Velo"
                      values={rollingStats.map(s => Number(s.exit_velo_14d)).filter(v => !isNaN(v))}
                      format={(v) => `${v.toFixed(1)} mph`}
                      color="text-red-400"
                    />
                    <TrendCard
                      label="Chase%"
                      values={rollingStats.map(s => Number(s.chase_rate_14d)).filter(v => !isNaN(v))}
                      format={(v) => `${(v * 100).toFixed(1)}%`}
                      color="text-purple-400"
                      invertColor
                    />
                  </>
                )}
              </div>
            </section>
          )}

          {/* No data state */}
          {rollingStats.length === 0 && (!splitsSummary || splitsSummary.total === 0) && (
            <p className="text-slate-500 py-8 text-center">
              No trend or split data available yet. Data populates once the season is underway.
            </p>
          )}
        </>
      )}
    </>
  )
}

function TrendCard({
  label,
  values,
  format,
  color = 'text-blue-400',
  invertColor = false,
}: {
  label: string
  values: number[]
  format: (v: number) => string
  color?: string
  invertColor?: boolean
}) {
  if (values.length === 0) return null

  const current = values[values.length - 1]
  const prev = values.length >= 2 ? values[values.length - 2] : null
  const delta = prev != null ? current - prev : null
  const trendUp = delta != null && delta > 0
  const trendColor = delta == null ? 'text-slate-500' :
    invertColor
      ? (trendUp ? 'text-red-400' : 'text-green-400')
      : (trendUp ? 'text-green-400' : 'text-red-400')

  return (
    <div className="bg-gray-800 border border-gray-700 rounded-lg p-4">
      <div className="flex items-center justify-between mb-2">
        <span className="text-xs text-slate-500 font-medium uppercase tracking-wider">{label}</span>
        {delta != null && (
          <span className={`text-xs font-mono ${trendColor}`}>
            {trendUp ? '+' : ''}{format(delta)}
          </span>
        )}
      </div>
      <div className="flex items-end justify-between gap-3">
        <div className={`text-xl font-bold ${color}`}>{format(current)}</div>
        <Sparkline values={values} color={color} />
      </div>
    </div>
  )
}
