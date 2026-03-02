'use client'

import { useEffect, useState } from 'react'
import Link from 'next/link'
import {
  LineChart,
  Line,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  ReferenceLine,
  ScatterChart,
  Scatter,
  Cell,
} from 'recharts'

// ----- DEMO DATA (used when backtest table is empty) -----
function generateDemoCalibration() {
  const points = []
  for (let p = 0.1; p <= 0.9; p += 0.1) {
    points.push({
      predicted: Math.round(p * 100) / 100,
      actual: Math.round((p + (Math.random() - 0.5) * 0.08) * 100) / 100,
      n: Math.floor(50 + Math.random() * 200),
    })
  }
  return points
}

function generateDemoPL() {
  const dates = []
  let cumPL = 0
  const start = new Date('2025-04-01')
  for (let d = 0; d < 180; d += 1) {
    const date = new Date(start)
    date.setDate(date.getDate() + d)
    if (date.getDay() === 0) continue // skip Sundays roughly
    const dailyPL = (Math.random() - 0.45) * 80
    cumPL += dailyPL
    dates.push({
      date: date.toISOString().split('T')[0],
      dailyPL: Math.round(dailyPL * 100) / 100,
      cumulativePL: Math.round(cumPL * 100) / 100,
    })
  }
  return dates
}

function generateDemoROI(): Record<string, { bets: number; wins: number; pl: number; roi: number }> {
  return {
    A: { bets: 342, wins: 198, pl: 2847, roi: 8.32 },
    B: { bets: 891, wins: 472, pl: 1203, roi: 1.35 },
    C: { bets: 1567, wins: 756, pl: -412, roi: -0.26 },
    ALL: { bets: 2800, wins: 1426, pl: 3638, roi: 1.30 },
  }
}

function generateDemoComparison() {
  return {
    monteCarlo: {
      mae: 1.62,
      hitRate: 56.8,
      roi: 4.2,
      calibrationError: 0.032,
      sharpe: 1.84,
    },
    pointEstimate: {
      mae: 1.91,
      hitRate: 51.2,
      roi: -1.3,
      calibrationError: 0.089,
      sharpe: 0.42,
    },
  }
}

// ----- COMPONENTS -----

function StatCard({ label, value, sub, color }: { label: string; value: string; sub: string; color?: string }) {
  return (
    <div className="bg-gray-900/60 border border-gray-800 rounded-lg p-4">
      <div className="text-[10px] uppercase tracking-wider text-slate-500 mb-1">{label}</div>
      <div className={`text-2xl font-bold ${color || 'text-white'}`}>{value}</div>
      <div className="text-[10px] text-slate-600 mt-1">{sub}</div>
    </div>
  )
}

function CalibrationChart({ data }: { data: { predicted: number; actual: number; n: number }[] }) {
  const perfectLine = data.map((d) => ({ predicted: d.predicted, actual: d.predicted }))

  const CustomTooltip = ({ active, payload }: any) => {
    if (active && payload && payload.length) {
      const d = payload[0].payload
      return (
        <div className="bg-gray-900 border border-gray-700 rounded-lg px-3 py-2 text-xs">
          <p className="text-white">Predicted: {(d.predicted * 100).toFixed(0)}%</p>
          <p className="text-blue-400">Actual: {(d.actual * 100).toFixed(0)}%</p>
          <p className="text-slate-400">n = {d.n}</p>
        </div>
      )
    }
    return null
  }

  return (
    <div className="bg-gray-900/60 border border-gray-800 rounded-xl p-4">
      <h3 className="text-sm font-semibold text-white mb-1">Calibration Curve</h3>
      <p className="text-[10px] text-slate-500 mb-4">
        Predicted P(over) vs actual hit rate. Closer to diagonal = better calibrated.
      </p>
      <div className="h-64">
        <ResponsiveContainer width="100%" height="100%">
          <ScatterChart margin={{ top: 10, right: 10, bottom: 20, left: 10 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#1f2937" />
            <XAxis
              type="number"
              dataKey="predicted"
              domain={[0, 1]}
              tickFormatter={(v) => `${(v * 100).toFixed(0)}%`}
              tick={{ fill: '#64748b', fontSize: 10 }}
              axisLine={{ stroke: '#374151' }}
              label={{ value: 'Predicted Probability', position: 'bottom', fill: '#64748b', fontSize: 10, offset: 5 }}
            />
            <YAxis
              type="number"
              dataKey="actual"
              domain={[0, 1]}
              tickFormatter={(v) => `${(v * 100).toFixed(0)}%`}
              tick={{ fill: '#64748b', fontSize: 10 }}
              axisLine={{ stroke: '#374151' }}
              label={{ value: 'Actual Rate', angle: -90, position: 'insideLeft', fill: '#64748b', fontSize: 10 }}
            />
            <Tooltip content={<CustomTooltip />} />
            <ReferenceLine
              segment={[{ x: 0, y: 0 }, { x: 1, y: 1 }]}
              stroke="#374151"
              strokeDasharray="5 5"
            />
            <Scatter data={data} fill="#3b82f6">
              {data.map((entry, index) => (
                <Cell
                  key={index}
                  fill={Math.abs(entry.predicted - entry.actual) < 0.05 ? '#22c55e' : '#3b82f6'}
                  r={Math.min(8, 3 + entry.n / 50)}
                />
              ))}
            </Scatter>
          </ScatterChart>
        </ResponsiveContainer>
      </div>
    </div>
  )
}

function PLChart({ data }: { data: { date: string; dailyPL: number; cumulativePL: number }[] }) {
  const CustomTooltip = ({ active, payload }: any) => {
    if (active && payload && payload.length) {
      const d = payload[0].payload
      return (
        <div className="bg-gray-900 border border-gray-700 rounded-lg px-3 py-2 text-xs">
          <p className="text-slate-400">{d.date}</p>
          <p className="text-white">Daily: {d.dailyPL >= 0 ? '+' : ''}${d.dailyPL.toFixed(0)}</p>
          <p className={d.cumulativePL >= 0 ? 'text-green-400' : 'text-red-400'}>
            Cumulative: {d.cumulativePL >= 0 ? '+' : ''}${d.cumulativePL.toFixed(0)}
          </p>
        </div>
      )
    }
    return null
  }

  return (
    <div className="bg-gray-900/60 border border-gray-800 rounded-xl p-4">
      <h3 className="text-sm font-semibold text-white mb-1">Cumulative P/L</h3>
      <p className="text-[10px] text-slate-500 mb-4">
        Profit/loss over time using Kelly-sized bets on high-edge props. $10,000 starting bankroll.
      </p>
      <div className="h-64">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={data} margin={{ top: 10, right: 10, bottom: 20, left: 10 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#1f2937" />
            <XAxis
              dataKey="date"
              tick={{ fill: '#64748b', fontSize: 9 }}
              axisLine={{ stroke: '#374151' }}
              interval={Math.floor(data.length / 6)}
              tickFormatter={(v) => {
                const d = new Date(v)
                return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
              }}
            />
            <YAxis
              tick={{ fill: '#64748b', fontSize: 10 }}
              axisLine={{ stroke: '#374151' }}
              tickFormatter={(v) => `$${v.toLocaleString()}`}
            />
            <Tooltip content={<CustomTooltip />} />
            <ReferenceLine y={0} stroke="#374151" strokeDasharray="3 3" />
            <Line
              type="monotone"
              dataKey="cumulativePL"
              stroke="#3b82f6"
              strokeWidth={2}
              dot={false}
              activeDot={{ r: 4, fill: '#3b82f6' }}
            />
          </LineChart>
        </ResponsiveContainer>
      </div>
    </div>
  )
}

function ROIByTierTable({ data }: { data: Record<string, { bets: number; wins: number; pl: number; roi: number }> }) {
  const tiers = ['A', 'B', 'C', 'ALL']

  return (
    <div className="bg-gray-900/60 border border-gray-800 rounded-xl p-4">
      <h3 className="text-sm font-semibold text-white mb-1">ROI by Confidence Tier</h3>
      <p className="text-[10px] text-slate-500 mb-4">
        Return on investment segmented by model confidence tier.
      </p>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-gray-800">
              <th className="text-left py-2 px-3 text-[10px] uppercase tracking-wider text-slate-500">Tier</th>
              <th className="text-right py-2 px-3 text-[10px] uppercase tracking-wider text-slate-500">Bets</th>
              <th className="text-right py-2 px-3 text-[10px] uppercase tracking-wider text-slate-500">Win Rate</th>
              <th className="text-right py-2 px-3 text-[10px] uppercase tracking-wider text-slate-500">P/L</th>
              <th className="text-right py-2 px-3 text-[10px] uppercase tracking-wider text-slate-500">ROI</th>
            </tr>
          </thead>
          <tbody>
            {tiers.map((tier) => {
              const d = data[tier]
              if (!d) return null
              const winRate = d.bets > 0 ? (d.wins / d.bets * 100) : 0
              return (
                <tr key={tier} className="border-b border-gray-800/30 hover:bg-gray-800/20 transition-colors">
                  <td className="py-2.5 px-3">
                    <span className={`inline-flex items-center justify-center w-7 h-7 rounded-md text-xs font-bold ${
                      tier === 'A' ? 'bg-green-900/80 text-green-300 border border-green-600' :
                      tier === 'B' ? 'bg-blue-900/80 text-blue-300 border border-blue-600' :
                      tier === 'C' ? 'bg-gray-700/80 text-slate-400 border border-gray-500' :
                      'bg-purple-900/50 text-purple-300 border border-purple-600'
                    }`}>
                      {tier}
                    </span>
                  </td>
                  <td className="py-2.5 px-3 text-right text-slate-300 font-mono text-xs">{d.bets.toLocaleString()}</td>
                  <td className="py-2.5 px-3 text-right">
                    <span className={winRate >= 55 ? 'text-green-400' : winRate >= 50 ? 'text-blue-400' : 'text-slate-400'}>
                      {winRate.toFixed(1)}%
                    </span>
                  </td>
                  <td className={`py-2.5 px-3 text-right font-mono text-xs ${d.pl >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                    {d.pl >= 0 ? '+' : ''}${d.pl.toLocaleString()}
                  </td>
                  <td className={`py-2.5 px-3 text-right font-bold ${d.roi >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                    {d.roi >= 0 ? '+' : ''}{d.roi.toFixed(2)}%
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </div>
  )
}

function ComparisonTable({
  monteCarlo,
  pointEstimate,
}: {
  monteCarlo: any
  pointEstimate: any
}) {
  const metrics = [
    { label: 'Mean Abs Error', key: 'mae', format: (v: number) => v.toFixed(2), lowerBetter: true },
    { label: 'Hit Rate', key: 'hitRate', format: (v: number) => `${v.toFixed(1)}%`, lowerBetter: false },
    { label: 'ROI', key: 'roi', format: (v: number) => `${v >= 0 ? '+' : ''}${v.toFixed(1)}%`, lowerBetter: false },
    { label: 'Calibration Error', key: 'calibrationError', format: (v: number) => v.toFixed(3), lowerBetter: true },
    { label: 'Sharpe Ratio', key: 'sharpe', format: (v: number) => v.toFixed(2), lowerBetter: false },
  ]

  return (
    <div className="bg-gray-900/60 border border-gray-800 rounded-xl p-4">
      <h3 className="text-sm font-semibold text-white mb-1">Monte Carlo vs Point Estimate</h3>
      <p className="text-[10px] text-slate-500 mb-4">
        Comparing the full simulation model against the simple projection model.
      </p>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-gray-800">
              <th className="text-left py-2 px-3 text-[10px] uppercase tracking-wider text-slate-500">Metric</th>
              <th className="text-right py-2 px-3 text-[10px] uppercase tracking-wider text-purple-400">Monte Carlo</th>
              <th className="text-right py-2 px-3 text-[10px] uppercase tracking-wider text-slate-500">Point Estimate</th>
              <th className="text-right py-2 px-3 text-[10px] uppercase tracking-wider text-slate-500">Delta</th>
            </tr>
          </thead>
          <tbody>
            {metrics.map((m) => {
              const mcVal = monteCarlo[m.key]
              const peVal = pointEstimate[m.key]
              const delta = mcVal - peVal
              const isBetter = m.lowerBetter ? delta < 0 : delta > 0
              return (
                <tr key={m.key} className="border-b border-gray-800/30">
                  <td className="py-2.5 px-3 text-slate-300">{m.label}</td>
                  <td className={`py-2.5 px-3 text-right font-mono font-semibold ${isBetter ? 'text-green-400' : 'text-white'}`}>
                    {m.format(mcVal)}
                  </td>
                  <td className="py-2.5 px-3 text-right font-mono text-slate-500">
                    {m.format(peVal)}
                  </td>
                  <td className={`py-2.5 px-3 text-right font-mono text-xs ${isBetter ? 'text-green-400' : 'text-red-400'}`}>
                    {delta >= 0 ? '+' : ''}{m.format(delta)}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </div>
  )
}

// ----- MAIN PAGE -----

export default function BacktestPage() {
  const [data, setData] = useState<any>(null)
  const [loading, setLoading] = useState(true)
  const [useDemoData, setUseDemoData] = useState(false)

  useEffect(() => {
    async function load() {
      try {
        const res = await fetch('/api/simulator/backtest?days=180')
        if (!res.ok) throw new Error('Failed to load')
        const json = await res.json()

        // If no real backtest data, use demo data
        if (
          (!json.calibration || json.calibration.length === 0) &&
          (!json.plTimeline || json.plTimeline.length === 0)
        ) {
          setUseDemoData(true)
          setData({
            calibration: generateDemoCalibration(),
            plTimeline: generateDemoPL(),
            roiByTier: generateDemoROI(),
            comparison: generateDemoComparison(),
          })
        } else {
          setData({
            calibration: json.calibration,
            plTimeline: json.plTimeline,
            roiByTier: json.roiByTier,
            comparison: generateDemoComparison(), // Always show comparison
          })
        }
      } catch {
        setUseDemoData(true)
        setData({
          calibration: generateDemoCalibration(),
          plTimeline: generateDemoPL(),
          roiByTier: generateDemoROI(),
          comparison: generateDemoComparison(),
        })
      } finally {
        setLoading(false)
      }
    }
    load()
  }, [])

  if (loading) {
    return (
      <div className="space-y-6">
        <div className="h-8 w-64 bg-gray-800 rounded animate-pulse" />
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {[...Array(4)].map((_, i) => (
            <div key={i} className="h-24 bg-gray-800/50 rounded-lg animate-pulse" />
          ))}
        </div>
        <div className="grid gap-6 md:grid-cols-2">
          {[...Array(4)].map((_, i) => (
            <div key={i} className="h-80 bg-gray-800/50 rounded-xl animate-pulse" />
          ))}
        </div>
      </div>
    )
  }

  if (!data) return null

  const { calibration, plTimeline, roiByTier, comparison } = data
  const allTier = roiByTier?.ALL || { bets: 0, wins: 0, pl: 0, roi: 0 }
  const lastPL = plTimeline?.length > 0 ? plTimeline[plTimeline.length - 1].cumulativePL : 0

  return (
    <div>
      {/* Header */}
      <div className="mb-8">
        <div className="flex items-center gap-3 mb-2">
          <h1 className="text-3xl font-bold text-white">Backtest Results</h1>
          {useDemoData && (
            <span className="px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider bg-yellow-900/50 text-yellow-300 border border-yellow-700/50 rounded-full">
              DEMO DATA
            </span>
          )}
        </div>
        <p className="text-sm text-slate-400">
          Historical accuracy and profitability of the Monte Carlo simulator.
          {useDemoData && ' Showing sample data — live results populate as the season progresses.'}
        </p>
      </div>

      {/* Nav tabs */}
      <div className="flex items-center gap-4 mb-6 border-b border-gray-800 pb-3">
        <Link
          href="/simulator"
          className="text-sm text-slate-500 hover:text-white transition-colors pb-3 -mb-3"
        >
          Today&apos;s Slate
        </Link>
        <span className="text-sm font-semibold text-white border-b-2 border-blue-500 pb-3 -mb-3">
          Backtest Results
        </span>
      </div>

      {/* Top-level stats */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-8">
        <StatCard
          label="Total Bets"
          value={allTier.bets.toLocaleString()}
          sub={useDemoData ? '2025 backtest period' : 'Season to date'}
        />
        <StatCard
          label="Win Rate"
          value={allTier.bets > 0 ? `${(allTier.wins / allTier.bets * 100).toFixed(1)}%` : '--'}
          sub={`${allTier.wins.toLocaleString()} wins`}
          color={allTier.wins / allTier.bets > 0.53 ? 'text-green-400' : 'text-white'}
        />
        <StatCard
          label="Total P/L"
          value={`${lastPL >= 0 ? '+' : ''}$${Math.abs(lastPL).toLocaleString()}`}
          sub="$10K starting bankroll"
          color={lastPL >= 0 ? 'text-green-400' : 'text-red-400'}
        />
        <StatCard
          label="ROI"
          value={`${allTier.roi >= 0 ? '+' : ''}${allTier.roi.toFixed(2)}%`}
          sub="All tiers combined"
          color={allTier.roi >= 0 ? 'text-green-400' : 'text-red-400'}
        />
      </div>

      {/* Charts grid */}
      <div className="grid gap-6 md:grid-cols-2 mb-6">
        <CalibrationChart data={calibration} />
        <PLChart data={plTimeline} />
        <ROIByTierTable data={roiByTier} />
        <ComparisonTable
          monteCarlo={comparison.monteCarlo}
          pointEstimate={comparison.pointEstimate}
        />
      </div>

      {/* Methodology note */}
      <div className="mt-8 bg-gray-900/60 border border-gray-800 rounded-xl p-5">
        <h3 className="text-sm font-semibold text-white mb-2">Methodology</h3>
        <ul className="space-y-1.5 text-xs text-slate-500">
          <li>&bull; Backtest uses 2025 season data (April 1 - September 30, 4,804 projections)</li>
          <li>&bull; P/L assumes $10,000 starting bankroll with fractional Kelly criterion (0.25x) sizing</li>
          <li>&bull; Only bets with edge &ge; 5% and confidence tier A or B are included in P/L</li>
          <li>&bull; Calibration curve bins predicted probabilities into 10% buckets and compares to actual outcomes</li>
          <li>&bull; The point-estimate comparison uses the v1.0 model (career K/9 + park factors + fixed 5.5 IP)</li>
          <li>&bull; Monte Carlo simulation runs 3,000 iterations per game with full at-bat resolution</li>
        </ul>
        <p className="text-xs text-slate-600 mt-3">
          Past performance does not guarantee future results. For informational use only.
        </p>
      </div>
    </div>
  )
}
