import { Metadata } from 'next'
import { getPublicClient, isSupabaseConfigured } from '../lib/supabase'
import CalibrationChartWrapper from './CalibrationChartWrapper'

export const metadata: Metadata = {
  title: 'Calibration — BaselineMLB',
  description: 'Model calibration chart showing how well our confidence scores predict actual outcomes.',
  openGraph: {
    title: 'Calibration Chart — BaselineMLB',
    description: 'Is the model well-calibrated? When we say 70% confidence, are we right 70% of the time?',
  },
}

export const dynamic = 'force-dynamic'
export const revalidate = 0

export interface CalibrationBucket {
  range: string
  lower: number
  upper: number
  midpoint: number
  total: number
  hits: number
  hitRate: number
}

interface BacktestRow {
  date: string
  prop_type: string
  total_predictions: number
  correct_predictions: number
  accuracy_pct: number
  avg_edge: number
}

// ─────────────────────────────────────────────────────────────────────────────
// Data fetching: try backtest_results first, fall back to projections
// ─────────────────────────────────────────────────────────────────────────────

async function getCalibrationFromBacktest(): Promise<CalibrationBucket[]> {
  if (!isSupabaseConfigured()) return []
  try {
    const supabase = getPublicClient()
    const { data, error } = await supabase
      .from('backtest_results')
      .select('date, prop_type, total_predictions, correct_predictions, accuracy_pct, avg_edge')
      .neq('prop_type', 'ALL')
      .order('date', { ascending: true })

    if (error || !data || data.length === 0) return []

    const rows = data as BacktestRow[]

    // Group by avg_edge bucket to build calibration curve
    // avg_edge represents the model's predicted edge; accuracy_pct is the actual hit rate
    // We bucket by edge magnitude ranges (mapped to confidence-like buckets)
    const buckets: CalibrationBucket[] = [
      { range: '50-55%', lower: 0.50, upper: 0.55, midpoint: 52.5, total: 0, hits: 0, hitRate: 0 },
      { range: '55-60%', lower: 0.55, upper: 0.60, midpoint: 57.5, total: 0, hits: 0, hitRate: 0 },
      { range: '60-65%', lower: 0.60, upper: 0.65, midpoint: 62.5, total: 0, hits: 0, hitRate: 0 },
      { range: '65-70%', lower: 0.65, upper: 0.70, midpoint: 67.5, total: 0, hits: 0, hitRate: 0 },
      { range: '70-75%', lower: 0.70, upper: 0.75, midpoint: 72.5, total: 0, hits: 0, hitRate: 0 },
      { range: '75-80%', lower: 0.75, upper: 0.80, midpoint: 77.5, total: 0, hits: 0, hitRate: 0 },
      { range: '80-85%', lower: 0.80, upper: 0.85, midpoint: 82.5, total: 0, hits: 0, hitRate: 0 },
      { range: '85-90%', lower: 0.85, upper: 0.90, midpoint: 87.5, total: 0, hits: 0, hitRate: 0 },
      { range: '90-95%', lower: 0.90, upper: 0.95, midpoint: 92.5, total: 0, hits: 0, hitRate: 0 },
    ]

    // Map edge ranges to confidence: edge 0-5% → ~50-55%, edge 5-10% → ~55-60%, etc.
    for (const row of rows) {
      const edge = Math.abs(row.avg_edge || 0)
      const accPct = row.accuracy_pct || 0

      // Convert edge to approximate confidence bucket
      // Higher edges correspond to higher confidence predictions
      const confidence = Math.min(0.95, 0.50 + edge * 5)

      for (const bucket of buckets) {
        if (confidence >= bucket.lower && confidence < bucket.upper) {
          bucket.total += row.total_predictions || 0
          bucket.hits += row.correct_predictions || 0
          break
        }
      }
    }

    for (const bucket of buckets) {
      bucket.hitRate = bucket.total > 0 ? Math.round((bucket.hits / bucket.total) * 100) : 0
    }

    return buckets.filter(b => b.total > 0)
  } catch (e) {
    console.error('[CalibrationPage] backtest_results fetch error:', e)
    return []
  }
}

async function getCalibrationFromProjections(): Promise<CalibrationBucket[]> {
  if (!isSupabaseConfigured()) return []
  try {
    const supabase = getPublicClient()

    const { data, error } = await supabase
      .from('projections')
      .select('confidence, projection, actual, stat_type')
      .not('actual', 'is', null)
      .not('confidence', 'is', null)
      .order('game_date', { ascending: false })
      .limit(5000)

    if (error || !data || data.length === 0) return []

    const buckets: CalibrationBucket[] = [
      { range: '50-55%', lower: 0.50, upper: 0.55, midpoint: 52.5, total: 0, hits: 0, hitRate: 0 },
      { range: '55-60%', lower: 0.55, upper: 0.60, midpoint: 57.5, total: 0, hits: 0, hitRate: 0 },
      { range: '60-65%', lower: 0.60, upper: 0.65, midpoint: 62.5, total: 0, hits: 0, hitRate: 0 },
      { range: '65-70%', lower: 0.65, upper: 0.70, midpoint: 67.5, total: 0, hits: 0, hitRate: 0 },
      { range: '70-75%', lower: 0.70, upper: 0.75, midpoint: 72.5, total: 0, hits: 0, hitRate: 0 },
      { range: '75-80%', lower: 0.75, upper: 0.80, midpoint: 77.5, total: 0, hits: 0, hitRate: 0 },
      { range: '80-85%', lower: 0.80, upper: 0.85, midpoint: 82.5, total: 0, hits: 0, hitRate: 0 },
      { range: '85-90%', lower: 0.85, upper: 0.90, midpoint: 87.5, total: 0, hits: 0, hitRate: 0 },
      { range: '90-95%', lower: 0.90, upper: 0.95, midpoint: 92.5, total: 0, hits: 0, hitRate: 0 },
    ]

    for (const row of data) {
      const conf = row.confidence
      if (conf == null || row.projection == null || row.actual == null) continue

      for (const bucket of buckets) {
        if (conf >= bucket.lower && conf < bucket.upper) {
          bucket.total++
          const pct_diff = Math.abs(row.projection - row.actual) / Math.max(row.actual, 0.1)
          if (pct_diff <= 0.20) {
            bucket.hits++
          }
          break
        }
      }
    }

    for (const bucket of buckets) {
      bucket.hitRate = bucket.total > 0 ? Math.round((bucket.hits / bucket.total) * 100) : 0
    }

    return buckets.filter(b => b.total > 0)
  } catch (e) {
    console.error('[CalibrationPage] projections fetch error:', e)
    return []
  }
}

async function getCalibrationData(): Promise<{ buckets: CalibrationBucket[]; source: 'backtest' | 'projections' | 'none' }> {
  // Try backtest_results first (more reliable, pre-aggregated)
  const backtestBuckets = await getCalibrationFromBacktest()
  if (backtestBuckets.length > 0) {
    return { buckets: backtestBuckets, source: 'backtest' }
  }

  // Fall back to projections table (needs graded data with actual values)
  const projBuckets = await getCalibrationFromProjections()
  if (projBuckets.length > 0) {
    return { buckets: projBuckets, source: 'projections' }
  }

  return { buckets: [], source: 'none' }
}

function CalibrationBar({ bucket, maxTotal }: { bucket: CalibrationBucket; maxTotal: number }) {
  const midpoint = (bucket.lower + bucket.upper) / 2 * 100

  const deviation = Math.abs(bucket.hitRate - midpoint)
  const color =
    deviation <= 5 ? 'bg-green-500' :
    deviation <= 10 ? 'bg-blue-500' :
    deviation <= 15 ? 'bg-yellow-500' :
    'bg-red-500'

  return (
    <div className="flex items-center gap-4 py-2">
      <div className="w-20 text-right text-sm text-slate-400 font-mono">{bucket.range}</div>
      <div className="flex-1 flex items-center gap-3">
        <div className="relative flex-1 h-8 bg-gray-800 rounded-lg overflow-hidden">
          <div
            className={`absolute left-0 top-0 h-full ${color} rounded-lg transition-all`}
            style={{ width: `${bucket.hitRate}%` }}
          />
          <div
            className="absolute top-0 h-full w-0.5 bg-white/30"
            style={{ left: `${midpoint}%` }}
          />
          <div className="absolute inset-0 flex items-center justify-center">
            <span className="text-xs font-medium text-white drop-shadow">
              {bucket.hitRate}% actual
            </span>
          </div>
        </div>
        <div className="w-16 text-right text-xs text-slate-500">n={bucket.total}</div>
      </div>
    </div>
  )
}

export default async function CalibrationPage() {
  const { buckets, source } = await getCalibrationData()

  const today = new Date().toLocaleDateString('en-US', {
    weekday: 'long',
    month: 'long',
    day: 'numeric',
    timeZone: 'America/New_York',
  })

  const totalPredictions = buckets.reduce((sum, b) => sum + b.total, 0)
  const maxTotal = Math.max(...buckets.map(b => b.total), 1)

  return (
    <div className="max-w-4xl mx-auto px-4 py-8">
      <div className="mb-8">
        <h1 className="text-3xl font-bold text-white mb-2">Confidence Calibration</h1>
        <p className="text-slate-400">
          {today} &bull; {totalPredictions.toLocaleString()} graded predictions
        </p>
        <p className="text-sm text-slate-500 mt-2">
          A well-calibrated model means: when we say 70% confidence, about 70% of those predictions should be accurate.
          The diagonal line below represents perfect calibration.
        </p>
      </div>

      {/* Data source indicator */}
      {source === 'backtest' && (
        <div className="bg-gradient-to-r from-blue-900/40 to-purple-900/30 border border-blue-700/30 rounded-lg p-3 mb-6">
          <p className="text-xs text-blue-300">
            Data source: backtest_results table &mdash; aggregated Monte Carlo backtest accuracy
          </p>
        </div>
      )}
      {source === 'projections' && (
        <div className="bg-gradient-to-r from-slate-800/40 to-slate-700/30 border border-slate-600/30 rounded-lg p-3 mb-6">
          <p className="text-xs text-slate-400">
            Data source: projections table &mdash; graded individual predictions with confidence scores
          </p>
        </div>
      )}

      {buckets.length === 0 ? (
        <div className="text-center py-16">
          <div className="text-4xl mb-4">&#x1F4C8;</div>
          <h2 className="text-xl font-semibold text-slate-300 mb-2">No calibration data yet</h2>
          <p className="text-slate-500 max-w-md mx-auto">
            Calibration data appears once projections have been graded against actual results.
            Run the backtest to populate: <code className="bg-slate-800 px-2 py-0.5 rounded text-xs">
              python scripts/backtest_full_aug_sep.py --upload
            </code>
          </p>
        </div>
      ) : (
        <div>
          {/* Recharts Calibration Chart */}
          <div className="bg-gray-800/50 border border-gray-700 rounded-lg p-6 mb-8">
            <div className="flex items-center justify-between mb-4">
              <h2 className="text-lg font-semibold text-white">Calibration Plot</h2>
              <div className="flex items-center gap-4 text-xs text-slate-500">
                <div className="flex items-center gap-1.5">
                  <div className="w-3 h-0.5 bg-blue-400" />
                  <span>Model accuracy</span>
                </div>
                <div className="flex items-center gap-1.5">
                  <div className="w-3 h-0.5 bg-slate-500 opacity-50" style={{ borderTop: '1px dashed' }} />
                  <span>Perfect calibration</span>
                </div>
              </div>
            </div>

            <CalibrationChartWrapper buckets={buckets} />
          </div>

          {/* Bar Chart */}
          <div className="bg-gray-800/50 border border-gray-700 rounded-lg p-6 mb-8">
            <div className="flex items-center justify-between mb-4">
              <h2 className="text-lg font-semibold text-white">Accuracy by Confidence Bucket</h2>
              <div className="flex items-center gap-4 text-xs text-slate-500">
                <div className="flex items-center gap-1.5">
                  <div className="w-3 h-3 bg-green-500 rounded" />
                  <span>Well calibrated (within 5%)</span>
                </div>
                <div className="flex items-center gap-1.5">
                  <div className="w-3 h-3 bg-yellow-500 rounded" />
                  <span>Slightly off (10-15%)</span>
                </div>
                <div className="flex items-center gap-1.5">
                  <div className="w-0.5 h-3 bg-white/30" />
                  <span>Expected</span>
                </div>
              </div>
            </div>

            <div className="space-y-1">
              {buckets.map((bucket) => (
                <CalibrationBar key={bucket.range} bucket={bucket} maxTotal={maxTotal} />
              ))}
            </div>
          </div>

          {/* Summary Stats */}
          <div className="grid gap-4 sm:grid-cols-3 mb-8">
            <div className="bg-gray-800 border border-gray-700 rounded-lg p-4 text-center">
              <div className="text-2xl font-bold text-white">{totalPredictions.toLocaleString()}</div>
              <div className="text-xs text-slate-500 mt-1">Total Graded Predictions</div>
            </div>
            <div className="bg-gray-800 border border-gray-700 rounded-lg p-4 text-center">
              <div className="text-2xl font-bold text-white">{buckets.length}</div>
              <div className="text-xs text-slate-500 mt-1">Confidence Buckets</div>
            </div>
            <div className="bg-gray-800 border border-gray-700 rounded-lg p-4 text-center">
              {(() => {
                const wellCalibrated = buckets.filter(b => {
                  const mid = (b.lower + b.upper) / 2 * 100
                  return Math.abs(b.hitRate - mid) <= 10
                })
                const pct = buckets.length > 0 ? Math.round((wellCalibrated.length / buckets.length) * 100) : 0
                return <div className="text-2xl font-bold text-white">{pct}%</div>
              })()}
              <div className="text-xs text-slate-500 mt-1">Buckets Within 10%</div>
            </div>
          </div>

          {/* Raw Data Table */}
          <div className="overflow-x-auto rounded-lg border border-gray-700">
            <table className="min-w-full">
              <thead>
                <tr className="bg-gray-800 text-left">
                  <th className="py-2 px-4 text-xs font-medium text-slate-400 uppercase">Confidence Range</th>
                  <th className="py-2 px-4 text-xs font-medium text-slate-400 uppercase text-center">Predictions</th>
                  <th className="py-2 px-4 text-xs font-medium text-slate-400 uppercase text-center">Hits</th>
                  <th className="py-2 px-4 text-xs font-medium text-slate-400 uppercase text-center">Actual Rate</th>
                  <th className="py-2 px-4 text-xs font-medium text-slate-400 uppercase text-center">Expected</th>
                  <th className="py-2 px-4 text-xs font-medium text-slate-400 uppercase text-center">Deviation</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-700">
                {buckets.map((bucket) => {
                  const expected = Math.round((bucket.lower + bucket.upper) / 2 * 100)
                  const deviation = bucket.hitRate - expected
                  return (
                    <tr key={bucket.range} className="hover:bg-gray-800/50 transition-colors">
                      <td className="py-2 px-4 font-mono text-slate-300">{bucket.range}</td>
                      <td className="py-2 px-4 text-center text-slate-400">{bucket.total}</td>
                      <td className="py-2 px-4 text-center text-slate-400">{bucket.hits}</td>
                      <td className="py-2 px-4 text-center font-medium text-white">{bucket.hitRate}%</td>
                      <td className="py-2 px-4 text-center text-slate-500">{expected}%</td>
                      <td className="py-2 px-4 text-center">
                        <span className={
                          Math.abs(deviation) <= 5 ? 'text-green-400' :
                          Math.abs(deviation) <= 10 ? 'text-yellow-400' :
                          'text-red-400'
                        }>
                          {deviation > 0 ? '+' : ''}{deviation}%
                        </span>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>

          {/* Methodology note */}
          <div className="mt-8 p-4 bg-gray-900/50 rounded-lg border border-gray-800 text-xs text-slate-500">
            <p className="font-medium text-slate-400 mb-1">Calibration methodology:</p>
            <ul className="space-y-0.5">
              <li>&bull; Projections are bucketed by their model-assigned confidence level</li>
              <li>&bull; A prediction is scored as a &ldquo;hit&rdquo; if the actual value was within 20% of the projection</li>
              <li>&bull; Perfect calibration means actual hit rate matches the confidence bucket midpoint</li>
              <li>&bull; The diagonal line in the chart above represents perfect calibration</li>
              <li>&bull; Data sourced from {source === 'backtest' ? 'backtest_results' : 'projections'} table</li>
            </ul>
          </div>
        </div>
      )}
    </div>
  )
}
