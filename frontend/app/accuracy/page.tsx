export const dynamic = 'force-dynamic'

// Backtest data — hardcoded from 2025 season validation
const BACKTEST_DATA = {
  label: 'Model Validation: 2025 Season Backtest',
  season: '2025',
  model: 'v1.0-glass-box',
  dateRange: '2025-04-01 to 2025-09-30',
  totalProjections: 4804,
  daysProcessed: 183,
  daysWithGames: 179,
  gradedPicks: 0,
  note: 'Projection accuracy only — no prop lines available for 2025 backtest period',
  projectionAccuracy: {
    meanAbsoluteError: 1.91,
    medianError: 1.62,
    within1k: 32.8,
    within2k: 58.6,
    within3k: 78.7,
  },
}

export default function AccuracyPage() {
  const d = BACKTEST_DATA
  const acc = d.projectionAccuracy

  return (
    <div className="max-w-5xl mx-auto px-4 py-8">
      <h1 className="text-3xl font-bold mb-2">Model Accuracy</h1>
      <p className="text-slate-400 mb-8">Glass-box prop analytics — public accuracy tracking</p>

      {/* Backtest Banner */}
      <div className="bg-gradient-to-r from-blue-900/50 to-emerald-900/50 border border-blue-700/30 rounded-lg p-4 mb-8">
        <p className="text-sm font-semibold text-blue-300">
          {d.label} · {d.totalProjections.toLocaleString()} projections · {d.dateRange}
        </p>
        <p className="text-xs text-slate-400 mt-1">Live tracking begins Opening Day 2026</p>
      </div>

      {/* Summary Cards */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 mb-10">
        <StatCard label="MEAN ABS. ERROR" value={`${acc.meanAbsoluteError} K`} sub="Tracking begins Opening Day 2026" />
        <StatCard label="WITHIN 1K" value={`${acc.within1k}%`} sub={`2026 Season · ${d.totalProjections.toLocaleString()} picks`} />
        <StatCard label="WITHIN 2K" value={`${acc.within2k}%`} sub="Avg. line movement" />
        <StatCard label="WITHIN 3K" value={`${acc.within3k}%`} sub={`Confidence ≥ 65% · 0 picks`} />
      </div>

      {/* Hit Rate by Prop Market */}
      <h2 className="text-xl font-bold mb-4">Hit Rate by Prop Market</h2>
      <div className="bg-slate-800/50 border border-slate-700/50 rounded-lg overflow-hidden mb-10">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-slate-700/50">
              <th className="text-left px-4 py-3 text-xs text-slate-400 uppercase">Prop Type</th>
              <th className="text-left px-4 py-3 text-xs text-slate-400 uppercase">Projections</th>
              <th className="text-left px-4 py-3 text-xs text-slate-400 uppercase">MAE</th>
              <th className="text-left px-4 py-3 text-xs text-slate-400 uppercase">Median Error</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td className="px-4 py-3">Pitcher Strikeouts</td>
              <td className="px-4 py-3">{d.totalProjections.toLocaleString()}</td>
              <td className="px-4 py-3 text-blue-400">{acc.meanAbsoluteError} K</td>
              <td className="px-4 py-3 text-blue-400">{acc.medianError} K</td>
            </tr>
          </tbody>
        </table>
      </div>

      {/* Hit Rate by Bookmaker */}
      <h2 className="text-xl font-bold mb-4">Hit Rate by Bookmaker</h2>
      <div className="bg-slate-800/50 border border-slate-700/50 rounded-lg overflow-hidden mb-10">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-slate-700/50">
              <th className="text-left px-4 py-3 text-xs text-slate-400 uppercase">Accuracy Tier</th>
              <th className="text-left px-4 py-3 text-xs text-slate-400 uppercase">Rate</th>
              <th className="text-left px-4 py-3 text-xs text-slate-400 uppercase">Count</th>
              <th className="text-left px-4 py-3 text-xs text-slate-400 uppercase">CLV</th>
            </tr>
          </thead>
          <tbody>
            <TierRow label="Within 1 Strikeout" rate={acc.within1k} count={1576} />
            <TierRow label="Within 2 Strikeouts" rate={acc.within2k} count={2815} />
            <TierRow label="Within 3 Strikeouts" rate={acc.within3k} count={3781} />
          </tbody>
        </table>
      </div>

      <p className="text-center text-xs text-slate-500 mt-8">
        Data updates daily at 2 AM ET via GitHub Actions starting Opening Day 2026 ·{' '}
        <a href="https://github.com/nrlefty5/baselinemlb" className="text-green-400 hover:underline" target="_blank" rel="noopener noreferrer">View Source on GitHub</a>
      </p>
      <p className="text-center text-xs text-slate-500 mt-1">Powered by Statcast, MLB Stats API, and The Odds API</p>
    </div>
  )
}

function StatCard({ label, value, sub }: { label: string; value: string; sub: string }) {
  return (
    <div className="bg-slate-800/50 border border-slate-700/50 rounded-lg p-4">
      <p className="text-xs text-slate-400 uppercase mb-1">{label}</p>
      <p className="text-3xl font-bold">{value}</p>
      <p className="text-xs text-slate-500 mt-1">{sub}</p>
    </div>
  )
}

function TierRow({ label, rate, count }: { label: string; rate: number; count: number }) {
  return (
    <tr className="border-b border-slate-700/30">
      <td className="px-4 py-3">{label}</td>
      <td className="px-4 py-3">{rate}%</td>
      <td className="px-4 py-3">{count}</td>
      <td className="px-4 py-3 text-slate-500">—</td>
    </tr>
  )
}
