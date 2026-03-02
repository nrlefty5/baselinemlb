'use client'

import { useEffect, useState } from 'react'
import Link from 'next/link'
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  ReferenceLine,
  Cell,
} from 'recharts'

const STAT_LABELS: Record<string, string> = {
  pitcher_strikeouts: 'Strikeouts',
  batter_total_bases: 'Total Bases',
  batter_hits: 'Hits',
  batter_home_runs: 'Home Runs',
  batter_rbis: 'RBIs',
  batter_walks: 'Walks',
}

interface SimPlayer {
  player_name: string
  stat_type: string
  sim_mean: number
  sim_median: number
  sim_std: number
  sim_p10: number
  sim_p25: number
  sim_p75: number
  sim_p90: number
  prop_line: number | null
  p_over: number | null
  p_under: number | null
  edge_pct: number | null
  kelly_stake: number | null
  kelly_fraction: number | null
  confidence_tier: string | null
  direction: string | null
  n_simulations: number
  feature_contributions: any
  distribution_buckets: any
  mlbam_id: number
}

interface GameInfo {
  game_pk: number
  game_date: string
  game_time: string | null
  home_team: string
  away_team: string
  venue: string | null
  home_probable_pitcher: string | null
  away_probable_pitcher: string | null
}

function generateDemoBuckets(mean: number, std: number, line: number | null): { value: number; count: number }[] {
  const buckets: { value: number; count: number }[] = []
  const minVal = Math.max(0, Math.floor(mean - 3 * std))
  const maxVal = Math.ceil(mean + 3 * std)
  for (let v = minVal; v <= maxVal; v++) {
    const z = (v - mean) / (std || 1)
    const count = Math.round(3000 * Math.exp(-0.5 * z * z) / (std * Math.sqrt(2 * Math.PI)))
    buckets.push({ value: v, count: Math.max(0, count) })
  }
  return buckets
}

function DistributionChart({
  player,
  isSimData,
}: {
  player: SimPlayer | any
  isSimData: boolean
}) {
  const mean = isSimData ? player.sim_mean : player.projection
  const std = isSimData ? player.sim_std : (mean ? mean * 0.25 : 1)
  const line = isSimData ? player.prop_line : player._prop_line

  let buckets = isSimData && player.distribution_buckets
    ? (typeof player.distribution_buckets === 'string'
        ? JSON.parse(player.distribution_buckets)
        : player.distribution_buckets)
    : generateDemoBuckets(mean || 5, std || 1.5, line)

  if (!Array.isArray(buckets) || buckets.length === 0) {
    buckets = generateDemoBuckets(mean || 5, std || 1.5, line)
  }

  const CustomTooltip = ({ active, payload }: any) => {
    if (active && payload && payload.length) {
      const d = payload[0].payload
      return (
        <div className="bg-gray-900 border border-gray-700 rounded-lg px-3 py-2 text-xs">
          <p className="text-white font-semibold">{d.value} {STAT_LABELS[player.stat_type] || player.stat_type}</p>
          <p className="text-slate-400">{d.count} simulations ({((d.count / 3000) * 100).toFixed(1)}%)</p>
        </div>
      )
    }
    return null
  }

  return (
    <div className="h-48">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={buckets} margin={{ top: 5, right: 5, left: -20, bottom: 5 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#1f2937" />
          <XAxis
            dataKey="value"
            tick={{ fill: '#64748b', fontSize: 10 }}
            axisLine={{ stroke: '#374151' }}
          />
          <YAxis
            tick={{ fill: '#64748b', fontSize: 10 }}
            axisLine={{ stroke: '#374151' }}
          />
          <Tooltip content={<CustomTooltip />} />
          {line != null && (
            <ReferenceLine
              x={line}
              stroke="#f59e0b"
              strokeDasharray="5 5"
              strokeWidth={2}
              label={{
                value: `Line: ${line}`,
                position: 'top',
                fill: '#f59e0b',
                fontSize: 10,
              }}
            />
          )}
          <Bar dataKey="count" radius={[2, 2, 0, 0]}>
            {buckets.map((entry: any, index: number) => (
              <Cell
                key={`cell-${index}`}
                fill={
                  line != null && entry.value > line
                    ? '#22c55e'
                    : line != null && entry.value < line
                    ? '#6366f1'
                    : '#3b82f6'
                }
                fillOpacity={0.7}
              />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  )
}

function FeatureContribution({
  label,
  value,
  direction,
}: {
  label: string
  value: string
  direction: 'positive' | 'negative' | 'neutral'
}) {
  const color =
    direction === 'positive'
      ? 'text-green-400'
      : direction === 'negative'
      ? 'text-red-400'
      : 'text-slate-400'
  const bg =
    direction === 'positive'
      ? 'bg-green-900/20 border-green-800/30'
      : direction === 'negative'
      ? 'bg-red-900/20 border-red-800/30'
      : 'bg-gray-800/50 border-gray-700/30'
  return (
    <div className={`flex items-center justify-between px-3 py-2 rounded-lg border ${bg}`}>
      <span className="text-xs text-slate-300">{label}</span>
      <span className={`text-xs font-semibold font-mono ${color}`}>{value}</span>
    </div>
  )
}

function SHAPSection({ features, player }: { features: any; player: any }) {
  if (!features || Object.keys(features).length === 0) return null

  const contributions: { label: string; value: string; direction: 'positive' | 'negative' | 'neutral' }[] = []

  // SHAP-like feature contributions
  if (features.feature_impacts) {
    for (const [key, impact] of Object.entries(features.feature_impacts as Record<string, number>)) {
      contributions.push({
        label: formatFeatureLabel(key),
        value: `${impact > 0 ? '+' : ''}${(impact * 100).toFixed(1)}%`,
        direction: impact > 0 ? 'positive' : impact < 0 ? 'negative' : 'neutral',
      })
    }
  } else {
    // Build from available features
    if (features.umpire_factor && features.umpire_factor !== 1.0) {
      const impact = features.umpire_factor - 1.0
      contributions.push({
        label: `Umpire${features.umpire_name ? ` (${features.umpire_name})` : ''}: expanded zone`,
        value: `${impact > 0 ? '+' : ''}${(impact * 100).toFixed(1)}% K boost`,
        direction: impact > 0 ? 'positive' : 'negative',
      })
    }
    if (features.park_adjustment) {
      const park = typeof features.park_adjustment === 'string'
        ? parseFloat(features.park_adjustment)
        : features.park_adjustment
      if (park && park !== 1.0) {
        const impact = park - 1.0
        contributions.push({
          label: `Park factor${features.venue ? ` (${features.venue})` : ''}`,
          value: `${impact > 0 ? '+' : ''}${(impact * 100).toFixed(1)}%`,
          direction: impact > 0 ? 'positive' : 'negative',
        })
      }
    }
    if (features.opp_k_pct) {
      const leagueAvg = 0.224
      const diff = features.opp_k_pct - leagueAvg
      contributions.push({
        label: `Opponent K% (${(features.opp_k_pct * 100).toFixed(1)}% vs ${(leagueAvg * 100).toFixed(1)}% avg)`,
        value: `${diff > 0 ? '+' : ''}${(diff * 100).toFixed(1)}% above avg`,
        direction: diff > 0 ? 'positive' : 'negative',
      })
    }
    if (features.recent_k9 && features.baseline_k9) {
      const diff = features.recent_k9 - features.baseline_k9
      contributions.push({
        label: `Recent form: ${features.recent_k9} K/9 vs ${features.baseline_k9} career`,
        value: `${diff > 0 ? '+' : ''}${diff.toFixed(2)} K/9`,
        direction: diff > 0 ? 'positive' : 'negative',
      })
    }
    if (features.platoon_factor && features.platoon_factor !== 1.0) {
      const impact = features.platoon_factor - 1.0
      contributions.push({
        label: `Platoon advantage (${features.platoon_matchup || 'vs lineup'})`,
        value: `${impact > 0 ? '+' : ''}${(impact * 100).toFixed(1)}%`,
        direction: impact > 0 ? 'positive' : 'negative',
      })
    }
    if (features.expected_innings) {
      contributions.push({
        label: 'Expected innings pitched',
        value: `${features.expected_innings} IP`,
        direction: 'neutral',
      })
    }
    if (features.blended_k9) {
      contributions.push({
        label: 'Blended K/9 rate',
        value: `${features.blended_k9}`,
        direction: 'neutral',
      })
    }
  }

  // Sort by absolute impact
  contributions.sort((a, b) => {
    const aVal = Math.abs(parseFloat(a.value))
    const bVal = Math.abs(parseFloat(b.value))
    return bVal - aVal
  })

  return (
    <div className="space-y-1.5">
      {contributions.map((c, i) => (
        <FeatureContribution key={i} {...c} />
      ))}
    </div>
  )
}

function formatFeatureLabel(key: string): string {
  const labels: Record<string, string> = {
    umpire_expanded_zone: 'Umpire expanded zone',
    park_k_factor: 'Park K factor',
    opp_k_rate: 'Opponent K rate',
    recent_form: 'Recent form (30-day)',
    platoon_advantage: 'Platoon advantage',
    catcher_framing: 'Catcher framing',
    home_field: 'Home field',
    expected_ip: 'Expected innings',
    weather_wind: 'Weather/wind',
    lineup_position: 'Lineup position',
  }
  return labels[key] || key.replace(/_/g, ' ').replace(/\b\w/g, (l) => l.toUpperCase())
}

function PlayerSimCard({ player, isSimData }: { player: SimPlayer | any; isSimData: boolean }) {
  const [expanded, setExpanded] = useState(false)
  const statLabel = STAT_LABELS[player.stat_type] || player.stat_type
  const mean = isSimData ? player.sim_mean : player.projection
  const std = isSimData ? player.sim_std : null
  const line = isSimData ? player.prop_line : player._prop_line
  const pOver = isSimData ? player.p_over : null
  const pUnder = isSimData ? player.p_under : null
  const edge = isSimData ? player.edge_pct : player._edge_pct
  const direction = isSimData ? player.direction : player._direction
  const tier = isSimData ? player.confidence_tier : (
    player.confidence >= 0.75 ? 'A' : player.confidence >= 0.60 ? 'B' : 'C'
  )
  const kellyStake = isSimData ? player.kelly_stake : null

  let features: any = {}
  try {
    if (isSimData && player.feature_contributions) {
      features = typeof player.feature_contributions === 'string'
        ? JSON.parse(player.feature_contributions)
        : player.feature_contributions
    } else if (player.features) {
      features = typeof player.features === 'string'
        ? JSON.parse(player.features)
        : player.features
    }
  } catch {}

  const edgeColor =
    edge != null && Math.abs(edge) >= 5
      ? 'border-green-800/50'
      : edge != null && Math.abs(edge) >= 2
      ? 'border-yellow-800/50'
      : 'border-gray-800'

  return (
    <div className={`bg-gray-900/60 border ${edgeColor} rounded-xl overflow-hidden`}>
      {/* Player header */}
      <div className="px-4 py-3 border-b border-gray-800/50">
        <div className="flex items-center justify-between">
          <div>
            <h3 className="font-semibold text-white">{player.player_name}</h3>
            <div className="flex items-center gap-2 mt-0.5">
              <span className="text-[10px] font-semibold uppercase tracking-wider text-slate-500 bg-gray-800 px-1.5 py-0.5 rounded">
                {statLabel}
              </span>
              {direction && (
                <span className={`text-[10px] font-bold px-1.5 py-0.5 rounded ${
                  direction === 'OVER'
                    ? 'bg-green-900/40 text-green-400'
                    : 'bg-red-900/40 text-red-400'
                }`}>
                  {direction}
                </span>
              )}
              {tier && (
                <span className={`text-[10px] font-bold px-1.5 py-0.5 rounded ${
                  tier === 'A' ? 'bg-green-900/40 text-green-300' :
                  tier === 'B' ? 'bg-blue-900/40 text-blue-300' :
                  'bg-gray-700/40 text-slate-400'
                }`}>
                  Tier {tier}
                </span>
              )}
            </div>
          </div>
          {edge != null && (
            <div className="text-right">
              <div className={`text-xl font-bold ${
                Math.abs(edge) >= 5 ? 'text-green-400' :
                Math.abs(edge) >= 2 ? 'text-yellow-400' : 'text-slate-500'
              }`}>
                {edge > 0 ? '+' : ''}{Number(edge).toFixed(1)}%
              </div>
              <div className="text-[10px] text-slate-500 uppercase">Edge</div>
            </div>
          )}
        </div>
      </div>

      {/* Stats row */}
      <div className="grid grid-cols-4 gap-2 px-4 py-3 border-b border-gray-800/30">
        <div>
          <div className="text-[10px] uppercase text-slate-500 mb-0.5">Sim Mean</div>
          <div className="text-lg font-bold text-white">{mean != null ? Number(mean).toFixed(1) : '--'}</div>
        </div>
        <div>
          <div className="text-[10px] uppercase text-slate-500 mb-0.5">Line</div>
          <div className="text-lg font-bold text-slate-400">{line != null ? line : '--'}</div>
        </div>
        {pOver != null && (
          <div>
            <div className="text-[10px] uppercase text-slate-500 mb-0.5">P(Over)</div>
            <div className="text-lg font-bold text-green-400">{(pOver * 100).toFixed(0)}%</div>
          </div>
        )}
        {kellyStake != null && (
          <div>
            <div className="text-[10px] uppercase text-slate-500 mb-0.5">Kelly</div>
            <div className="text-lg font-bold text-purple-400">${Number(kellyStake).toFixed(0)}</div>
          </div>
        )}
        {std != null && !pOver && (
          <div>
            <div className="text-[10px] uppercase text-slate-500 mb-0.5">Std Dev</div>
            <div className="text-lg font-bold text-slate-400">{Number(std).toFixed(2)}</div>
          </div>
        )}
      </div>

      {/* Distribution chart */}
      <div className="px-4 py-3 border-b border-gray-800/30">
        <div className="text-[10px] uppercase text-slate-500 mb-2 font-semibold">
          Probability Distribution
          {!isSimData && <span className="text-slate-600 ml-1">(estimated)</span>}
        </div>
        <DistributionChart player={player} isSimData={isSimData} />
        {line != null && (
          <div className="flex items-center justify-center gap-4 mt-2 text-[10px]">
            <span className="flex items-center gap-1">
              <span className="w-2 h-2 rounded-full bg-green-500" />
              Over {line}
            </span>
            <span className="flex items-center gap-1">
              <span className="w-2 h-2 rounded-full bg-indigo-500" />
              Under {line}
            </span>
            <span className="flex items-center gap-1">
              <span className="w-2 h-2 rounded-full bg-yellow-500" />
              Prop line
            </span>
          </div>
        )}
      </div>

      {/* SHAP / Why this prediction */}
      {Object.keys(features).length > 0 && (
        <div className="px-4 py-3">
          <button
            onClick={() => setExpanded(!expanded)}
            className="flex items-center gap-2 text-xs text-slate-400 hover:text-white transition-colors w-full"
          >
            <svg
              className={`w-3 h-3 transition-transform ${expanded ? 'rotate-90' : ''}`}
              fill="none"
              viewBox="0 0 24 24"
              stroke="currentColor"
            >
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
            </svg>
            <span className="font-semibold uppercase tracking-wider">Why this prediction?</span>
          </button>
          {expanded && (
            <div className="mt-3">
              <SHAPSection features={features} player={player} />
            </div>
          )}
        </div>
      )}
    </div>
  )
}

export default function GameSimPage({ params }: { params: { gameId: string } }) {
  const [data, setData] = useState<{
    game: GameInfo | null
    simulations: SimPlayer[]
    projections: any[]
    umpire: any[]
    hasSimData: boolean
  } | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    async function load() {
      try {
        const res = await fetch(`/api/simulator/${params.gameId}`)
        if (!res.ok) throw new Error('Failed to load game data')
        const json = await res.json()
        setData(json)
      } catch (err: any) {
        setError(err.message)
      } finally {
        setLoading(false)
      }
    }
    load()
  }, [params.gameId])

  if (loading) {
    return (
      <div className="space-y-6">
        <div className="h-8 w-64 bg-gray-800 rounded animate-pulse" />
        <div className="h-4 w-96 bg-gray-800/50 rounded animate-pulse" />
        <div className="grid gap-6 md:grid-cols-2">
          {[...Array(4)].map((_, i) => (
            <div key={i} className="bg-gray-900/60 border border-gray-800 rounded-xl h-96 animate-pulse" />
          ))}
        </div>
      </div>
    )
  }

  if (error || !data || !data.game) {
    return (
      <div className="text-center py-16">
        <h2 className="text-xl font-semibold text-slate-300 mb-2">Game not found</h2>
        <p className="text-slate-500 mb-4">{error || 'Could not load simulation data for this game.'}</p>
        <Link href="/simulator" className="text-blue-400 hover:text-blue-300 text-sm">
          &larr; Back to simulator
        </Link>
      </div>
    )
  }

  const { game, simulations, projections, umpire, hasSimData } = data
  const players = hasSimData ? simulations : projections

  const gameTime = game.game_time
    ? new Date(`2000-01-01T${game.game_time}`).toLocaleTimeString('en-US', {
        hour: 'numeric',
        minute: '2-digit',
        timeZone: 'America/New_York',
      }) + ' ET'
    : 'TBD'

  return (
    <div>
      {/* Breadcrumb */}
      <div className="mb-6">
        <Link href="/simulator" className="text-xs text-slate-500 hover:text-blue-400 transition-colors">
          &larr; Back to simulator
        </Link>
      </div>

      {/* Game header */}
      <div className="bg-gray-900/60 border border-gray-800 rounded-xl p-5 mb-8">
        <div className="flex items-center justify-between mb-3">
          <div className="flex items-center gap-3">
            <span className="text-2xl font-bold text-white">{game.away_team}</span>
            <span className="text-slate-600">@</span>
            <span className="text-2xl font-bold text-white">{game.home_team}</span>
          </div>
          <div className="text-right text-sm text-slate-500">
            <div>{gameTime}</div>
            <div className="text-xs">{game.venue}</div>
          </div>
        </div>
        <div className="flex items-center justify-between text-sm text-slate-400 border-t border-gray-800 pt-3">
          <span>{game.away_probable_pitcher || 'SP TBD'}</span>
          <span className="text-xs text-slate-600">Starting Pitchers</span>
          <span>{game.home_probable_pitcher || 'SP TBD'}</span>
        </div>
        {umpire && umpire.length > 0 && (
          <div className="mt-2 pt-2 border-t border-gray-800/50 text-xs text-slate-500">
            HP Umpire: {umpire[0].umpire_name || 'TBD'}
            {umpire[0].strike_rate && (
              <span className="ml-2 text-slate-600">
                (Strike rate: {(umpire[0].strike_rate * 100).toFixed(1)}%)
              </span>
            )}
          </div>
        )}
      </div>

      {/* Sim stats summary */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-8">
        <div className="bg-gray-900/60 border border-gray-800 rounded-lg p-3">
          <div className="text-[10px] uppercase tracking-wider text-slate-500 mb-1">Players Simulated</div>
          <div className="text-2xl font-bold text-white">{players.length}</div>
        </div>
        <div className="bg-gray-900/60 border border-gray-800 rounded-lg p-3">
          <div className="text-[10px] uppercase tracking-wider text-slate-500 mb-1">Edge Props</div>
          <div className="text-2xl font-bold text-green-400">
            {players.filter((p: any) => {
              const e = hasSimData ? p.edge_pct : p._edge_pct
              return e != null && Math.abs(e) >= 5
            }).length}
          </div>
        </div>
        <div className="bg-gray-900/60 border border-gray-800 rounded-lg p-3">
          <div className="text-[10px] uppercase tracking-wider text-slate-500 mb-1">Simulations</div>
          <div className="text-2xl font-bold text-purple-400">
            {hasSimData ? '3,000' : '--'}
          </div>
        </div>
        <div className="bg-gray-900/60 border border-gray-800 rounded-lg p-3">
          <div className="text-[10px] uppercase tracking-wider text-slate-500 mb-1">Data Source</div>
          <div className="text-sm font-semibold text-slate-300">
            {hasSimData ? 'Monte Carlo' : 'Point Estimate'}
          </div>
        </div>
      </div>

      {/* Player cards */}
      {players.length === 0 ? (
        <div className="text-center py-16">
          <div className="text-4xl mb-4 opacity-50">&#x1F50D;</div>
          <h2 className="text-lg font-semibold text-slate-300 mb-2">No simulation data</h2>
          <p className="text-sm text-slate-500">Simulation results will appear here once the Monte Carlo engine runs for this game.</p>
        </div>
      ) : (
        <div className="grid gap-6 md:grid-cols-2">
          {players
            .sort((a: any, b: any) => {
              const eA = Math.abs(hasSimData ? (a.edge_pct || 0) : (a._edge_pct || 0))
              const eB = Math.abs(hasSimData ? (b.edge_pct || 0) : (b._edge_pct || 0))
              return eB - eA
            })
            .map((player: any, i: number) => (
              <PlayerSimCard
                key={`${player.player_name}-${player.stat_type}-${i}`}
                player={player}
                isSimData={hasSimData}
              />
            ))}
        </div>
      )}
    </div>
  )
}
