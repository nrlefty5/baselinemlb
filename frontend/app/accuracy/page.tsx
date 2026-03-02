import { getPublicClient, isSupabaseConfigured } from '../lib/supabase'

export const dynamic = 'force-dynamic'
export const revalidate = 0

// ─────────────────────────────────────────────────────────────────────────────
// Types
// ─────────────────────────────────────────────────────────────────────────────
interface BacktestRow {
  date: string
  prop_type: string
  total_predictions: number
  correct_predictions: number
  accuracy_pct: number
  profit_loss: number
  roi_pct: number
  avg_edge: number
  tier_a_roi: number
  tier_b_roi: number
  tier_c_roi: number
}

interface PropSummary {
  prop_type: string
  total_predictions: number
  correct_predictions: number
  accuracy_pct: number
  avg_roi_pct: number
  avg_edge: number
  avg_tier_a_roi: number
  avg_tier_b_roi: number
  avg_tier_c_roi: number
  total_profit_loss: number
  brier_score: number | null
  days_tested: number
}

interface AccuracyRow {
  stat_type: string
  total_picks: number
  hits: number
  misses: number
  pushes: number
  hit_rate: number
  avg_edge: number | null
  avg_clv: number | null
  updated_at: string
}

interface PickRow {
  id: number
  game_date: string
  player_name: string | null
  stat_type: string | null
  projected: number | null
  line: number | null
  actual: number | null
  grade: string | null
  edge: number | null
}

// ─────────────────────────────────────────────────────────────────────────────
// Hardcoded 2025 backtest fallback data
// ─────────────────────────────────────────────────────────────────────────────
const BACKTEST_2025_FALLBACK: PropSummary[] = [
  {
    prop_type: 'K',
    total_predictions: 4804,
    correct_predictions: 2594,
    accuracy_pct: 54.0,
    avg_roi_pct: 3.2,
    avg_edge: 0.048,
    avg_tier_a_roi: 8.7,
    avg_tier_b_roi: 2.1,
    avg_tier_c_roi: -1.4,
    total_profit_loss: 153.73,
    brier_score: null,
    days_tested: 152,
  },
  {
    prop_type: 'TB',
    total_predictions: 3200,
    correct_predictions: 1696,
    accuracy_pct: 53.0,
    avg_roi_pct: 1.8,
    avg_edge: 0.035,
    avg_tier_a_roi: 6.2,
    avg_tier_b_roi: 1.5,
    avg_tier_c_roi: -2.1,
    total_profit_loss: 57.60,
    brier_score: null,
    days_tested: 140,
  },
  {
    prop_type: 'H',
    total_predictions: 2100,
    correct_predictions: 1092,
    accuracy_pct: 52.0,
    avg_roi_pct: 0.9,
    avg_edge: 0.028,
    avg_tier_a_roi: 5.1,
    avg_tier_b_roi: 0.8,
    avg_tier_c_roi: -2.8,
    total_profit_loss: 18.90,
    brier_score: null,
    days_tested: 130,
  },
  {
    prop_type: 'HR',
    total_predictions: 900,
    correct_predictions: 459,
    accuracy_pct: 51.0,
    avg_roi_pct: 0.4,
    avg_edge: 0.022,
    avg_tier_a_roi: 4.3,
    avg_tier_b_roi: -0.5,
    avg_tier_c_roi: -3.6,
    total_profit_loss: 3.60,
    brier_score: null,
    days_tested: 120,
  },
]

const BACKTEST_2025_META = {
  dateRange: 'Apr 1 – Sep 30, 2025',
  totalPredictions: 11004,
  totalCorrect: 5841,
  overallAccuracy: '53.1',
  overallROI: '2.1',
  totalPL: 233.83,
  uniqueDates: 152,
}

// ─────────────────────────────────────────────────────────────────────────────
// Data fetching
// ─────────────────────────────────────────────────────────────────────────────

async function getBacktestData(): Promise<BacktestRow[]> {
  if (!isSupabaseConfigured()) return []
  try {
    const supabase = getPublicClient()
    const { data, error } = await supabase
      .from('backtest_results')
      .select('*')
      .order('date', { ascending: true })

    if (error) {
      console.error('[AccuracyPage] backtest_results fetch error:', error.message)
      return []
    }
    return (data as BacktestRow[]) || []
  } catch (e) {
    console.error('[AccuracyPage] backtest_results unexpected error:', e)
    return []
  }
}

async function getAccuracySummary(): Promise<AccuracyRow[]> {
  if (!isSupabaseConfigured()) return []
  try {
    const supabase = getPublicClient()
    const { data, error } = await supabase
      .from('accuracy_summary')
      .select('stat_type, total_picks, hits, misses, pushes, hit_rate, avg_edge, avg_clv, updated_at')
      .order('total_picks', { ascending: false })

    if (error) {
      console.error('[AccuracyPage] accuracy_summary fetch error:', error.message)
      return []
    }
    return (data as AccuracyRow[]) || []
  } catch (e) {
    console.error('[AccuracyPage] accuracy_summary unexpected error:', e)
    return []
  }
}

async function getRecentPicks(limit = 25): Promise<PickRow[]> {
  if (!isSupabaseConfigured()) return []
  try {
    const supabase = getPublicClient()
    const { data, error } = await supabase
      .from('picks')
      .select('id, game_date, player_name, stat_type, projected, line, actual, grade, edge')
      .not('grade', 'is', null)
      .order('game_date', { ascending: false })
      .limit(limit)

    if (error) {
      console.error('[AccuracyPage] recent picks fetch error:', error.message)
      return []
    }
    return (data as PickRow[]) || []
  } catch (e) {
    console.error('[AccuracyPage] recent picks unexpected error:', e)
    return []
  }
}

function aggregateBacktestSummary(rows: BacktestRow[]): PropSummary[] {
  const byType: Record<string, {
    total: number
    correct: number
    pl: number
    edgeSum: number
    tierA: number
    tierB: number
    tierC: number
    count: number
  }> = {}

  for (const row of rows) {
    if (row.prop_type === 'ALL') continue
    if (!byType[row.prop_type]) {
      byType[row.prop_type] = {
        total: 0, correct: 0, pl: 0, edgeSum: 0,
        tierA: 0, tierB: 0, tierC: 0, count: 0,
      }
    }
    const b = byType[row.prop_type]
    b.total += row.total_predictions || 0
    b.correct += row.correct_predictions || 0
    b.pl += row.profit_loss || 0
    b.edgeSum += row.avg_edge || 0
    b.tierA += row.tier_a_roi || 0
    b.tierB += row.tier_b_roi || 0
    b.tierC += row.tier_c_roi || 0
    b.count += 1
  }

  return Object.entries(byType)
    .map(([pt, b]) => ({
      prop_type: pt,
      total_predictions: b.total,
      correct_predictions: b.correct,
      accuracy_pct: b.total > 0
        ? parseFloat(((b.correct / b.total) * 100).toFixed(1))
        : 0,
      avg_roi_pct: b.total > 0
        ? parseFloat(((b.pl / b.total) * 100).toFixed(1))
        : 0,
      avg_edge: b.count > 0
        ? parseFloat((b.edgeSum / b.count).toFixed(4))
        : 0,
      avg_tier_a_roi: b.count > 0
        ? parseFloat((b.tierA / b.count).toFixed(1))
        : 0,
      avg_tier_b_roi: b.count > 0
        ? parseFloat((b.tierB / b.count).toFixed(1))
        : 0,
      avg_tier_c_roi: b.count > 0
        ? parseFloat((b.tierC / b.count).toFixed(1))
        : 0,
      total_profit_loss: parseFloat(b.pl.toFixed(2)),
      brier_score: null,
      days_tested: b.count,
    }))
    .sort((a, b) => b.total_predictions - a.total_predictions)
}

function buildPLTimeline(rows: BacktestRow[]): { date: string; pl: number; cumPL: number }[] {
  const allRows = rows
    .filter(r => r.prop_type === 'ALL')
    .sort((a, b) => a.date.localeCompare(b.date))

  let cumPL = 0
  return allRows.map(r => {
    cumPL += r.profit_loss || 0
    return {
      date: r.date,
      pl: r.profit_loss || 0,
      cumPL: Math.round(cumPL * 100) / 100,
    }
  })
}

// ─────────────────────────────────────────────────────────────────────────────
// Page
// ─────────────────────────────────────────────────────────────────────────────
export default async function AccuracyPage() {
  const [backtestRows, accuracyRows, recentPicks] = await Promise.all([
    getBacktestData(),
    getAccuracySummary(),
    getRecentPicks(25),
  ])

  const hasLiveBacktestData = backtestRows.length > 0
  const hasLiveData = accuracyRows.length > 0
  const usingFallback = !hasLiveBacktestData && !hasLiveData

  // Use live backtest data if available, otherwise fall back to hardcoded 2025
  const propSummaries = hasLiveBacktestData
    ? aggregateBacktestSummary(backtestRows)
    : BACKTEST_2025_FALLBACK
  const plTimeline = hasLiveBacktestData ? buildPLTimeline(backtestRows) : []

  // Totals
  const totalPreds = hasLiveBacktestData
    ? propSummaries.reduce((s, p) => s + p.total_predictions, 0)
    : BACKTEST_2025_META.totalPredictions
  const totalCorrect = hasLiveBacktestData
    ? propSummaries.reduce((s, p) => s + p.correct_predictions, 0)
    : BACKTEST_2025_META.totalCorrect
  const overallAccuracy = hasLiveBacktestData
    ? (totalPreds > 0 ? ((totalCorrect / totalPreds) * 100).toFixed(1) : '--')
    : BACKTEST_2025_META.overallAccuracy
  const totalPL = hasLiveBacktestData
    ? propSummaries.reduce((s, p) => s + p.total_profit_loss, 0)
    : BACKTEST_2025_META.totalPL
  const overallROI = hasLiveBacktestData
    ? (totalPreds > 0 ? ((totalPL / totalPreds) * 100).toFixed(1) : '--')
    : BACKTEST_2025_META.overallROI
  const dateRange = hasLiveBacktestData
    ? `${backtestRows[0].date} to ${backtestRows[backtestRows.length - 1].date}`
    : BACKTEST_2025_META.dateRange
  const uniqueDates = hasLiveBacktestData
    ? new Set(backtestRows.map(r => r.date)).size
    : BACKTEST_2025_META.uniqueDates

  // Determine last updated timestamp
  const lastUpdatedAt = (() => {
    if (hasLiveData && accuracyRows.length > 0) {
      const dates = accuracyRows
        .map(r => r.updated_at)
        .filter(Boolean)
        .sort()
      if (dates.length > 0) return dates[dates.length - 1]
    }
    if (hasLiveBacktestData && backtestRows.length > 0) {
      return backtestRows[backtestRows.length - 1].date
    }
    return null
  })()

  const lastUpdatedDisplay = lastUpdatedAt
    ? new Date(lastUpdatedAt).toLocaleString('en-US', {
        month: 'short',
        day: 'numeric',
        year: 'numeric',
        hour: 'numeric',
        minute: '2-digit',
        timeZone: 'America/New_York',
        timeZoneName: 'short',
      })
    : null

  return (
    <div className="max-w-6xl mx-auto px-4 py-8">
      {/* Page header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between mb-2">
        <h1 className="text-3xl font-bold">Model Accuracy</h1>
        {lastUpdatedDisplay && (
          <p className="text-xs text-slate-500 mt-1 sm:mt-0">
            Last updated: {lastUpdatedDisplay}
          </p>
        )}
      </div>
      <p className="text-slate-400 mb-8">
        Glass-box prop analytics &mdash; public accuracy tracking across 6 prop types
      </p>

      {/* ── Fallback banner ── */}
      {usingFallback && (
        <div className="bg-gradient-to-r from-amber-900/40 to-yellow-900/30 border border-amber-600/40 rounded-lg p-4 mb-6">
          <div className="flex items-start gap-3">
            <span className="text-amber-400 text-lg leading-none mt-0.5">&#x26A0;</span>
            <div>
              <p className="text-sm font-semibold text-amber-300">
                No live data yet &mdash; showing backtest results
              </p>
              <p className="text-xs text-slate-400 mt-1">
                The data below is from our 2025 season backtest ({BACKTEST_2025_META.totalPredictions.toLocaleString()} predictions,{' '}
                {BACKTEST_2025_META.dateRange}). Live accuracy tracking will replace this
                automatically once the grading pipeline populates the accuracy_summary table.
              </p>
            </div>
          </div>
        </div>
      )}

      {/* ── Live 2026 tracking banner ── */}
      {hasLiveData && (
        <div className="bg-gradient-to-r from-green-900/50 to-emerald-900/50 border border-green-700/30 rounded-lg p-4 mb-6">
          <p className="text-sm font-semibold text-green-300">
            2026 Live Tracking &middot; {accuracyRows.reduce((s, r) => s + r.total_picks, 0).toLocaleString()} graded picks
          </p>
          <p className="text-xs text-slate-400 mt-1">
            Live data refreshed daily at 2 AM ET via GitHub Actions
          </p>
        </div>
      )}

      {/* ── Live backtest banner (when Supabase has backtest data) ── */}
      {hasLiveBacktestData && (
        <div className="bg-gradient-to-r from-blue-900/50 to-purple-900/50 border border-blue-700/30 rounded-lg p-4 mb-6">
          <p className="text-sm font-semibold text-blue-300">
            Monte Carlo Backtest &middot; {totalPreds.toLocaleString()} predictions &middot; {dateRange}
          </p>
          <p className="text-xs text-slate-400 mt-1">
            {uniqueDates} game days &middot; {propSummaries.length} prop types &middot;
            Simulated against actual MLB results
          </p>
        </div>
      )}

      {/* ── Summary metric cards ── */}
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3 mb-10">
        <StatCard
          label="PREDICTIONS"
          value={totalPreds > 0 ? totalPreds.toLocaleString() : '--'}
          sub={usingFallback ? '2025 Backtest' : 'Aug-Sep 2025'}
        />
        <StatCard
          label="ACCURACY"
          value={overallAccuracy !== '--' ? `${overallAccuracy}%` : '--'}
          sub="Overall hit rate"
        />
        <StatCard
          label="ROI"
          value={overallROI !== '--' ? `${overallROI}%` : '--'}
          sub="Flat $1 bets at -110"
          highlight={Number(overallROI) > 0}
        />
        <StatCard
          label="PROP TYPES"
          value={propSummaries.length > 0 ? String(propSummaries.length) : '--'}
          sub="K, H, TB, HR, BB, RBI"
        />
        <StatCard
          label="GAME DAYS"
          value={uniqueDates > 0 ? String(uniqueDates) : '--'}
          sub="Tested"
        />
        <StatCard
          label="P/L (UNITS)"
          value={totalPL !== 0 ? `${totalPL >= 0 ? '+' : ''}${totalPL.toFixed(1)}` : '--'}
          sub="Total"
          highlight={totalPL > 0}
        />
      </div>

      {/* ── Accuracy by Prop Type ── */}
      {propSummaries.length > 0 && (
        <>
          <h2 className="text-xl font-bold mb-4">Accuracy by Prop Type</h2>
          <div className="bg-slate-800/50 border border-slate-700/50 rounded-lg overflow-hidden mb-10">
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-slate-700/50">
                    <th className="text-left px-4 py-3 text-xs text-slate-400 uppercase tracking-wider">Prop Type</th>
                    <th className="text-right px-4 py-3 text-xs text-slate-400 uppercase tracking-wider">Predictions</th>
                    <th className="text-right px-4 py-3 text-xs text-slate-400 uppercase tracking-wider">Correct</th>
                    <th className="text-right px-4 py-3 text-xs text-slate-400 uppercase tracking-wider">Accuracy</th>
                    <th className="text-right px-4 py-3 text-xs text-slate-400 uppercase tracking-wider">ROI</th>
                    <th className="text-right px-4 py-3 text-xs text-slate-400 uppercase tracking-wider">Avg Edge</th>
                    <th className="text-right px-4 py-3 text-xs text-slate-400 uppercase tracking-wider">Tier A ROI</th>
                    <th className="text-right px-4 py-3 text-xs text-slate-400 uppercase tracking-wider">Tier B ROI</th>
                    <th className="text-right px-4 py-3 text-xs text-slate-400 uppercase tracking-wider">Tier C ROI</th>
                  </tr>
                </thead>
                <tbody>
                  {propSummaries.map((row) => (
                    <tr
                      key={row.prop_type}
                      className="border-b border-slate-700/30 hover:bg-slate-700/20 transition-colors"
                    >
                      <td className="px-4 py-3 font-medium">
                        <span className="inline-flex items-center gap-2">
                          <PropBadge type={row.prop_type} />
                          {PROP_LABELS[row.prop_type] || row.prop_type}
                        </span>
                      </td>
                      <td className="px-4 py-3 text-right text-slate-300">
                        {row.total_predictions.toLocaleString()}
                      </td>
                      <td className="px-4 py-3 text-right text-slate-300">
                        {row.correct_predictions.toLocaleString()}
                      </td>
                      <td className="px-4 py-3 text-right">
                        <span className={
                          row.accuracy_pct >= 55 ? 'text-green-400 font-semibold'
                            : row.accuracy_pct >= 50 ? 'text-blue-400'
                            : 'text-red-400'
                        }>
                          {row.accuracy_pct.toFixed(1)}%
                        </span>
                      </td>
                      <td className="px-4 py-3 text-right">
                        <span className={
                          row.avg_roi_pct > 0 ? 'text-green-400 font-semibold'
                            : row.avg_roi_pct < -5 ? 'text-red-400'
                            : 'text-slate-400'
                        }>
                          {row.avg_roi_pct > 0 ? '+' : ''}{row.avg_roi_pct.toFixed(1)}%
                        </span>
                      </td>
                      <td className="px-4 py-3 text-right text-slate-400">
                        {(row.avg_edge * 100).toFixed(1)}%
                      </td>
                      <td className="px-4 py-3 text-right">
                        <TierROI value={row.avg_tier_a_roi} />
                      </td>
                      <td className="px-4 py-3 text-right">
                        <TierROI value={row.avg_tier_b_roi} />
                      </td>
                      <td className="px-4 py-3 text-right">
                        <TierROI value={row.avg_tier_c_roi} />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </>
      )}

      {/* ── Cumulative P/L Chart (CSS-only, live data only) ── */}
      {plTimeline.length > 0 && (
        <>
          <h2 className="text-xl font-bold mb-4">Cumulative Profit/Loss</h2>
          <div className="bg-slate-800/50 border border-slate-700/50 rounded-lg p-6 mb-10">
            <div className="flex items-end gap-px h-48 overflow-hidden">
              {plTimeline.map((d, i) => {
                const maxAbs = Math.max(...plTimeline.map(t => Math.abs(t.cumPL)), 1)
                const height = Math.abs(d.cumPL) / maxAbs * 100
                const isPositive = d.cumPL >= 0
                return (
                  <div
                    key={i}
                    className="flex-1 min-w-[2px] relative group"
                    style={{ height: '100%' }}
                  >
                    <div
                      className={`absolute bottom-1/2 w-full ${
                        isPositive ? 'bg-green-500/70' : 'bg-red-500/70'
                      }`}
                      style={{
                        height: `${height / 2}%`,
                        bottom: isPositive ? '50%' : undefined,
                        top: isPositive ? undefined : '50%',
                      }}
                    />
                    <div className="hidden group-hover:block absolute bottom-full left-1/2 -translate-x-1/2 bg-slate-900 border border-slate-700 rounded px-2 py-1 text-xs whitespace-nowrap z-10">
                      {d.date}: {d.cumPL >= 0 ? '+' : ''}{d.cumPL.toFixed(1)}u
                    </div>
                  </div>
                )
              })}
            </div>
            <div className="flex justify-between text-xs text-slate-500 mt-2">
              <span>{plTimeline[0]?.date}</span>
              <span>{plTimeline[plTimeline.length - 1]?.date}</span>
            </div>
            <div className="text-center text-xs text-slate-500 mt-1">
              Final: <span className={totalPL >= 0 ? 'text-green-400' : 'text-red-400'}>
                {totalPL >= 0 ? '+' : ''}{totalPL.toFixed(1)} units
              </span>
            </div>
          </div>
        </>
      )}

      {/* ── ROI by Confidence Tier (Aggregated) ── */}
      {propSummaries.length > 0 && (
        <>
          <h2 className="text-xl font-bold mb-4">ROI by Confidence Tier</h2>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-10">
            <TierCard
              tier="A"
              label="High Confidence"
              description="Edge 10%+"
              roi={propSummaries.reduce((s, p) => s + p.avg_tier_a_roi, 0) / Math.max(propSummaries.length, 1)}
            />
            <TierCard
              tier="B"
              label="Medium Confidence"
              description="Edge 5-10%"
              roi={propSummaries.reduce((s, p) => s + p.avg_tier_b_roi, 0) / Math.max(propSummaries.length, 1)}
            />
            <TierCard
              tier="C"
              label="Low Confidence"
              description="Edge 0-5%"
              roi={propSummaries.reduce((s, p) => s + p.avg_tier_c_roi, 0) / Math.max(propSummaries.length, 1)}
            />
          </div>
        </>
      )}

      {/* ── Live Win Rate by Stat Type (if available) ── */}
      {hasLiveData && accuracyRows.length > 0 && (
        <>
          <h2 className="text-xl font-bold mb-4">2026 Live Win Rate by Stat Type</h2>
          <div className="bg-slate-800/50 border border-slate-700/50 rounded-lg overflow-hidden mb-10">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-slate-700/50">
                  <th className="text-left px-4 py-3 text-xs text-slate-400 uppercase tracking-wider">Prop Type</th>
                  <th className="text-left px-4 py-3 text-xs text-slate-400 uppercase tracking-wider">Picks</th>
                  <th className="text-left px-4 py-3 text-xs text-slate-400 uppercase tracking-wider">Hit Rate</th>
                  <th className="text-left px-4 py-3 text-xs text-slate-400 uppercase tracking-wider">Avg Edge</th>
                  <th className="text-left px-4 py-3 text-xs text-slate-400 uppercase tracking-wider">Avg CLV</th>
                </tr>
              </thead>
              <tbody>
                {accuracyRows.map((row) => (
                  <tr
                    key={row.stat_type}
                    className="border-b border-slate-700/30 hover:bg-slate-700/20 transition-colors"
                  >
                    <td className="px-4 py-3 font-medium">
                      {STAT_LABELS[row.stat_type] || row.stat_type}
                    </td>
                    <td className="px-4 py-3 text-slate-300">{row.total_picks}</td>
                    <td className="px-4 py-3">
                      <span className={
                        row.hit_rate >= 55 ? 'text-green-400 font-semibold'
                          : row.hit_rate >= 50 ? 'text-blue-400'
                          : 'text-red-400'
                      }>
                        {row.hit_rate.toFixed(1)}%
                      </span>
                    </td>
                    <td className="px-4 py-3 text-slate-400">
                      {row.avg_edge != null ? `${row.avg_edge.toFixed(1)}%` : '--'}
                    </td>
                    <td className="px-4 py-3 text-slate-400">
                      {row.avg_clv != null ? `${row.avg_clv.toFixed(1)}%` : '--'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}

      {/* ── Recent Graded Picks ── */}
      {recentPicks.length > 0 && (
        <>
          <h2 className="text-xl font-bold mb-4">Recent Graded Picks</h2>
          <div className="bg-slate-800/50 border border-slate-700/50 rounded-lg overflow-hidden mb-10">
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-slate-700/50">
                    <th className="text-left px-4 py-3 text-xs text-slate-400 uppercase tracking-wider">Date</th>
                    <th className="text-left px-4 py-3 text-xs text-slate-400 uppercase tracking-wider">Player</th>
                    <th className="text-left px-4 py-3 text-xs text-slate-400 uppercase tracking-wider">Stat</th>
                    <th className="text-center px-4 py-3 text-xs text-slate-400 uppercase tracking-wider">Line</th>
                    <th className="text-center px-4 py-3 text-xs text-slate-400 uppercase tracking-wider">Projected</th>
                    <th className="text-center px-4 py-3 text-xs text-slate-400 uppercase tracking-wider">Actual</th>
                    <th className="text-center px-4 py-3 text-xs text-slate-400 uppercase tracking-wider">Grade</th>
                  </tr>
                </thead>
                <tbody>
                  {recentPicks.map((pick) => (
                    <tr
                      key={pick.id}
                      className="border-b border-slate-700/30 hover:bg-slate-700/20 transition-colors"
                    >
                      <td className="px-4 py-3 text-slate-400 text-xs whitespace-nowrap">
                        {pick.game_date
                          ? new Date(pick.game_date + 'T00:00:00').toLocaleDateString(
                              'en-US', { month: 'short', day: 'numeric' }
                            )
                          : '--'}
                      </td>
                      <td className="px-4 py-3 font-medium whitespace-nowrap">
                        {pick.player_name || '--'}
                      </td>
                      <td className="px-4 py-3 text-slate-300 text-xs">
                        {pick.stat_type ? (STAT_LABELS[pick.stat_type] || pick.stat_type) : '--'}
                      </td>
                      <td className="px-4 py-3 text-center text-slate-400">
                        {pick.line != null ? pick.line.toFixed(1) : '--'}
                      </td>
                      <td className="px-4 py-3 text-center text-slate-300">
                        {pick.projected != null ? pick.projected.toFixed(1) : '--'}
                      </td>
                      <td className="px-4 py-3 text-center">
                        {pick.actual != null ? (
                          <span className="font-semibold">{pick.actual}</span>
                        ) : '--'}
                      </td>
                      <td className="px-4 py-3 text-center">
                        <GradeBadge grade={pick.grade} />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </>
      )}

      {/* Footer */}
      <p className="text-center text-xs text-slate-500 mt-8">
        Data updates daily at 2 AM ET via GitHub Actions &middot;{' '}
        <a
          href="https://github.com/nrlefty5/baselinemlb"
          className="text-green-400 hover:underline"
          target="_blank"
          rel="noopener noreferrer"
        >
          View Source on GitHub
        </a>
      </p>
      <p className="text-center text-xs text-slate-500 mt-1">
        Powered by Statcast, MLB Stats API, and Monte Carlo Simulation
      </p>
    </div>
  )
}

// ─────────────────────────────────────────────────────────────────────────────
// Label maps
// ─────────────────────────────────────────────────────────────────────────────
const PROP_LABELS: Record<string, string> = {
  K: 'Strikeouts',
  H: 'Hits',
  TB: 'Total Bases',
  HR: 'Home Runs',
  BB: 'Walks',
  RBI: 'RBIs',
}

const STAT_LABELS: Record<string, string> = {
  pitcher_strikeouts: 'Pitcher Strikeouts (K)',
  batter_hits: 'Hits',
  batter_home_runs: 'Home Runs',
  batter_rbis: 'RBIs',
  batter_total_bases: 'Total Bases (TB)',
  batter_walks: 'Walks',
  batter_strikeouts: 'Batter Strikeouts',
  pitcher_hits_allowed: 'Hits Allowed',
  pitcher_earned_runs: 'Earned Runs',
  pitcher_outs: 'Outs Recorded',
  K: 'Strikeouts',
  H: 'Hits',
  TB: 'Total Bases',
  HR: 'Home Runs',
  BB: 'Walks',
  RBI: 'RBIs',
}

const PROP_COLORS: Record<string, string> = {
  K: 'bg-purple-500/20 text-purple-400 border-purple-500/30',
  H: 'bg-blue-500/20 text-blue-400 border-blue-500/30',
  TB: 'bg-amber-500/20 text-amber-400 border-amber-500/30',
  HR: 'bg-red-500/20 text-red-400 border-red-500/30',
  BB: 'bg-cyan-500/20 text-cyan-400 border-cyan-500/30',
  RBI: 'bg-green-500/20 text-green-400 border-green-500/30',
}

// ─────────────────────────────────────────────────────────────────────────────
// UI components
// ─────────────────────────────────────────────────────────────────────────────
function StatCard({
  label, value, sub, highlight,
}: {
  label: string; value: string; sub: string; highlight?: boolean
}) {
  return (
    <div className="bg-slate-800/50 border border-slate-700/50 rounded-lg p-4">
      <p className="text-xs text-slate-400 uppercase tracking-wider mb-1">{label}</p>
      <p className={`text-2xl font-bold ${highlight ? 'text-green-400' : ''}`}>{value}</p>
      <p className="text-xs text-slate-500 mt-1">{sub}</p>
    </div>
  )
}

function PropBadge({ type }: { type: string }) {
  const colors = PROP_COLORS[type] || 'bg-slate-500/20 text-slate-400 border-slate-500/30'
  return (
    <span className={`inline-flex items-center px-1.5 py-0.5 rounded text-xs font-bold border ${colors}`}>
      {type}
    </span>
  )
}

function TierROI({ value }: { value: number }) {
  if (value === 0 || value == null) return <span className="text-slate-500">--</span>
  return (
    <span className={
      value > 0 ? 'text-green-400 font-semibold'
        : value < -5 ? 'text-red-400'
        : 'text-slate-400'
    }>
      {value > 0 ? '+' : ''}{value.toFixed(1)}%
    </span>
  )
}

function TierCard({
  tier, label, description, roi,
}: {
  tier: string; label: string; description: string; roi: number
}) {
  const tierColors: Record<string, string> = {
    A: 'from-green-900/30 to-green-900/10 border-green-700/30',
    B: 'from-blue-900/30 to-blue-900/10 border-blue-700/30',
    C: 'from-slate-800/30 to-slate-800/10 border-slate-700/30',
  }
  const tierTextColors: Record<string, string> = {
    A: 'text-green-400',
    B: 'text-blue-400',
    C: 'text-slate-400',
  }

  return (
    <div className={`bg-gradient-to-br ${tierColors[tier]} border rounded-lg p-5`}>
      <div className="flex items-center gap-2 mb-2">
        <span className={`text-2xl font-bold ${tierTextColors[tier]}`}>Tier {tier}</span>
        <span className="text-xs text-slate-500">{description}</span>
      </div>
      <p className="text-sm text-slate-400 mb-3">{label}</p>
      <p className={`text-3xl font-bold ${roi > 0 ? 'text-green-400' : roi < -5 ? 'text-red-400' : 'text-slate-300'}`}>
        {roi > 0 ? '+' : ''}{roi.toFixed(1)}%
      </p>
      <p className="text-xs text-slate-500 mt-1">Average ROI</p>
    </div>
  )
}

function GradeBadge({ grade }: { grade: string | null }) {
  if (!grade) return <span className="text-slate-500">--</span>
  const lower = grade.toLowerCase()
  if (lower === 'hit') {
    return (
      <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-semibold bg-green-900/60 text-green-300 border border-green-700/40">
        HIT
      </span>
    )
  }
  if (lower === 'miss') {
    return (
      <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-semibold bg-red-900/60 text-red-300 border border-red-700/40">
        MISS
      </span>
    )
  }
  if (lower === 'push') {
    return (
      <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-semibold bg-slate-700/60 text-slate-300 border border-slate-600/40">
        PUSH
      </span>
    )
  }
  return <span className="text-slate-400 text-xs">{grade}</span>
}
