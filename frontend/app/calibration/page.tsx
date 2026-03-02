import { createClient } from '@supabase/supabase-js'

export const dynamic = 'force-dynamic'

const supabaseUrl = process.env.NEXT_PUBLIC_SUPABASE_URL || ''
const supabaseAnonKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY || ''

interface CalibrationBucket {
  range: string
  lower: number
  upper: number
  total: number
  hits: number
  hitRate: number
}

async function getCalibrationData(): Promise<CalibrationBucket[]> {
  if (!supabaseUrl || !supabaseAnonKey) {
    return []
  }
  const supabase = createClient(supabaseUrl, supabaseAnonKey)

  // Fetch graded projections (ones with actual results)
  const { data, error } = await supabase
    .from('projections')
    .select('confidence, projection, actual, stat_type')
    .not('actual', 'is', null)
    .not('confidence', 'is', null)
    .order('game_date', { ascending: false })
    .limit(5000)

  if (error || !data || data.length === 0) {
    return []
  }

  // Bucket projections by confidence level
  const buckets: CalibrationBucket[] = [
    { range: '50-55%', lower: 0.50, upper: 0.55, total: 0, hits: 0, hitRate: 0 },
    { range: '55-60%', lower: 0.55, upper: 0.60, total: 0, hits: 0, hitRate: 0 },
    { range: '60-65%', lower: 0.60, upper: 0.65, total: 0, hits: 0, hitRate: 0 },
    { range: '65-70%', lower: 0.65, upper: 0.70, total: 0, hits: 0, hitRate: 0 },
    { range: '70-75%', lower: 0.70, upper: 0.75, total: 0, hits: 0, hitRate: 0 },
    { range: '75-80%', lower: 0.75, upper: 0.80, total: 0, hits: 0, hitRate: 0 },
    { range: '80-85%', lower: 0.80, upper: 0.85, total: 0, hits: 0, hitRate: 0 },
    { range: '85-90%', lower: 0.85, upper: 0.90, total: 0, hits: 0, hitRate: 0 },
    { range: '90-95%', lower: 0.90, upper: 0.95, total: 0, hits: 0, hitRate: 0 },
  ]

  for (const row of data) {
    const conf = row.confidence
    if (conf == null || row.projection == null || row.actual == null) continue

    // Find the bucket
    for (const bucket of buckets) {
      if (conf >= bucket.lower && conf < bucket.upper) {
        bucket.total++
        // "Hit" = projection was within 20% of actual OR direction was correct
        const pct_diff = Math.abs(row.projection - row.actual) / Math.max(row.actual, 0.1)
        if (pct_diff <= 0.20) {
          bucket.hits++
        }
        break
      }
    }
  }

  // Calculate hit rates
  for (const bucket of buckets) {
    bucket.hitRate = bucket.total > 0 ? Math.round((bucket.hits / bucket.total) * 100) : 0
  }

  return buckets.filter(b => b.total > 0)
}

function CalibrationBar({ bucket, maxTotal }: { bucket: CalibrationBucket; maxTotal: number }) {
  const barWidth = bucket.total > 0 ? Math.max((bucket.total / maxTotal) * 100, 5) : 0
  const midpoint = (bucket.lower + bucket.upper) / 2 * 100

  // Color based on calibration: green if hitRate close to confidence, red if far off
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
        {/* Expected confidence line */}
        <div className="relative flex-1 h-8 bg-gray-800 rounded-lg overflow-hidden">
          <div
            className={`absolute left-0 top-0 h-full ${color} rounded-lg transition-all`}
            style={{ width: `${bucket.hitRate}%` }}
          />
          {/* Expected marker */}
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
  const buckets = await getCalibrationData()

  const today = new Date().toLocaleDateString('en-US', {
    weekday: 'long',
    month: 'long',
    day: 'numeric',
    timeZone: 'America/New_York',
  })

  const totalPredictions = buckets.reduce((sum, b) => sum + b.total, 0)
  const maxTotal = Math.max(...buckets.map(b => b.total), 1)

  return (
    <div>
      <div className="mb-8">
        <h1 className="text-3xl font-bold text-white mb-2">Confidence Calibration</h1>
        <p className="text-slate-400">
          {today} &bull; {totalPredictions.toLocaleString()} graded predictions
        </p>
        <p className="text-sm text-slate-500 mt-2">
          A well-calibrated model means: when we say 70% confidence, about 70% of those predictions should be accurate.
        </p>
      </div>

      {buckets.length === 0 ? (
        <div className="text-center py-16">
          <div className="text-4xl mb-4">📈</div>
          <h2 className="text-xl font-semibold text-slate-300 mb-2">No calibration data yet</h2>
          <p className="text-slate-500 max-w-md mx-auto">
            Calibration data appears once projections have been graded against actual results.
            This requires at least a few days of games to have been played and scored.
          </p>
        </div>
      ) : (
        <div>
          {/* Calibration Chart */}
          <div className="bg-gray-800/50 border border-gray-700 rounded-lg p-6 mb-8">
            <div className="flex items-center justify-between mb-4">
              <h2 className="text-lg font-semibold text-white">Calibration Chart</h2>
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
                    <tr key={bucket.range} className="hover:bg-gray-750">
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
        </div>
      )}
    </div>
  )
}
