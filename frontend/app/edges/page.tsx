import type { Metadata } from 'next'
import { createClient } from '@supabase/supabase-js'
import Link from 'next/link'

export const dynamic = 'force-dynamic'

export const metadata: Metadata = {
  title: "Today's Edges — MLB Prop Analytics",
  description:
    'Daily MLB player prop edges powered by Monte Carlo simulation. High-confidence projections with glass-box factor breakdowns.',
}

const supabaseUrl = process.env.NEXT_PUBLIC_SUPABASE_URL || ''
const supabaseAnonKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY || ''

// Opening Day 2026: March 26, 2026
const OPENING_DAY = new Date('2026-03-26T16:05:00-04:00')

const STAT_LABELS: Record<string, string> = {
  pitcher_strikeouts: 'Strikeouts',
  batter_total_bases: 'Total Bases',
  batter_hits: 'Hits',
  batter_home_runs: 'Home Runs',
  batter_rbis: 'RBIs',
  batter_walks: 'Walks',
  pitcher_earned_runs: 'Earned Runs',
  pitcher_outs: 'Outs Recorded',
  pitcher_hits_allowed: 'Hits Allowed',
}

const STAT_TYPE_OPTIONS = [
  { value: '', label: 'All Types' },
  { value: 'pitcher_strikeouts', label: 'Strikeouts' },
  { value: 'batter_total_bases', label: 'Total Bases' },
  { value: 'batter_hits', label: 'Hits' },
  { value: 'batter_home_runs', label: 'Home Runs' },
  { value: 'batter_rbis', label: 'RBIs' },
  { value: 'batter_walks', label: 'Walks' },
]

function getConfidenceTier(confidence: number): { label: string; color: string } {
  if (confidence >= 0.7) return { label: 'HIGH', color: 'bg-green-900 text-green-300 border-green-700' }
  if (confidence >= 0.5) return { label: 'MEDIUM', color: 'bg-blue-900 text-blue-300 border-blue-700' }
  return { label: 'LOW', color: 'bg-gray-700 text-slate-400 border-gray-600' }
}

async function getProjections(gameDate?: string, statType?: string) {
  if (!supabaseUrl || !supabaseAnonKey) return []

  const supabase = createClient(supabaseUrl, supabaseAnonKey)
  const date = gameDate || new Date().toISOString().split('T')[0]

  let query = supabase
    .from('projections')
    .select('*')
    .eq('game_date', date)
    .order('confidence', { ascending: false })
    .limit(150)

  if (statType) {
    query = query.eq('stat_type', statType)
  }

  const { data, error } = await query

  if (error) {
    console.error('Error fetching projections:', error)
    return []
  }

  return data || []
}

function EdgeCard({ proj }: { proj: any }) {
  const statLabel = STAT_LABELS[proj.stat_type] || proj.stat_type
  const confidence = proj.confidence ?? 0
  const tier = getConfidenceTier(confidence)

  let features: Record<string, any> = {}
  try {
    features = typeof proj.features === 'string' ? JSON.parse(proj.features) : (proj.features || {})
  } catch { /* ignore parse errors */ }

  // Build factor breakdown entries from features JSON
  const factors: { label: string; value: string; highlight: boolean }[] = []

  if (features.blended_k9 || features.baseline_k9) {
    factors.push({
      label: 'Base K/9',
      value: String(features.blended_k9 || features.baseline_k9),
      highlight: false,
    })
  }
  if (features.recent_k9) {
    factors.push({ label: '14-day K/9', value: String(features.recent_k9), highlight: false })
  }
  if (features.park_adjustment && features.park_adjustment !== 1.0) {
    factors.push({
      label: 'Park factor',
      value: `${Number(features.park_adjustment) > 1 ? '+' : ''}${((Number(features.park_adjustment) - 1) * 100).toFixed(1)}%`,
      highlight: Number(features.park_adjustment) !== 1,
    })
  }
  if (features.umpire_factor && features.umpire_factor !== 1.0) {
    factors.push({
      label: 'Umpire tendency',
      value: `${Number(features.umpire_factor) > 1 ? '+' : ''}${((Number(features.umpire_factor) - 1) * 100).toFixed(1)}%`,
      highlight: true,
    })
  }
  if (features.umpire_name) {
    factors.push({ label: 'Umpire', value: features.umpire_name, highlight: false })
  }
  if (features.opp_k_pct) {
    factors.push({ label: 'Opp K%', value: `${(features.opp_k_pct * 100).toFixed(1)}%`, highlight: false })
  }
  if (features.expected_innings) {
    factors.push({ label: 'Expected IP', value: String(features.expected_innings), highlight: false })
  }
  if (features.opponent) {
    factors.push({ label: 'Opponent', value: features.opponent, highlight: false })
  }
  if (features.venue) {
    factors.push({ label: 'Venue', value: features.venue, highlight: false })
  }
  if (features.platoon_matchup && features.platoon_matchup !== 'unknown') {
    factors.push({
      label: 'Platoon',
      value: `${features.platoon_matchup}${features.platoon_factor ? ` (${features.platoon_factor}x)` : ''}`,
      highlight: false,
    })
  }
  if (features.career_tb_per_pa) {
    factors.push({ label: 'Career TB/PA', value: String(features.career_tb_per_pa), highlight: false })
  }

  return (
    <div className="bg-slate-900 border border-slate-700 rounded-2xl overflow-hidden hover:border-slate-500 transition-colors">
      {/* Header */}
      <div className="px-5 py-3 border-b border-slate-700 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className={`text-xs px-2 py-0.5 rounded border font-bold ${tier.color}`}>
            {tier.label}
          </span>
          <span className="text-xs text-slate-500">{statLabel}</span>
        </div>
        <span className="text-xs text-green-400 font-mono font-bold">
          {Math.round(confidence * 100)}% conf
        </span>
      </div>

      {/* Main */}
      <div className="px-5 py-4">
        <div className="flex items-center justify-between mb-3">
          <div className="min-w-0 flex-1">
            <Link
              href={`/players/${proj.mlbam_id}`}
              className="font-semibold text-white truncate block hover:text-blue-400 transition-colors"
            >
              {proj.player_name}
            </Link>
            <div className="text-xs text-slate-500 mt-0.5">
              {features.venue && <span>{features.venue}</span>}
              {features.opponent && <span> vs {features.opponent}</span>}
            </div>
          </div>
          <div className="text-right ml-3">
            <div className="text-white font-bold text-lg">
              {proj.projection != null ? proj.projection.toFixed(1) : '--'}
            </div>
            <div className="text-xs text-slate-500">Projected</div>
          </div>
        </div>

        {/* Factor Breakdown */}
        {factors.length > 0 && (
          <div className="mt-3 pt-3 border-t border-slate-800 space-y-1.5">
            <div className="text-xs text-slate-500 uppercase tracking-wider mb-2">Factor Breakdown</div>
            {factors.map((f) => (
              <div key={f.label} className="flex justify-between text-xs">
                <span className="text-slate-400">{f.label}</span>
                <span className={f.highlight ? 'text-blue-400' : 'text-slate-300'}>{f.value}</span>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Footer */}
      <div className="px-5 py-2.5 bg-slate-800/50 border-t border-slate-700">
        <div className="flex items-center justify-between text-xs">
          <span className="text-slate-500">Model {proj.model_version || 'v2.0'}</span>
          <span className="text-slate-500">ID: {proj.mlbam_id}</span>
        </div>
      </div>
    </div>
  )
}

export default async function EdgesPage({
  searchParams,
}: {
  searchParams: Promise<{ date?: string; stat_type?: string }>
}) {
  const params = await searchParams
  const selectedDate = params.date || new Date().toISOString().split('T')[0]
  const selectedStatType = params.stat_type || ''

  const projections = await getProjections(selectedDate, selectedStatType)

  const daysUntil = Math.max(0, Math.ceil((OPENING_DAY.getTime() - Date.now()) / (1000 * 60 * 60 * 24)))
  const isPreSeason = daysUntil > 0

  const displayDate = new Date(selectedDate + 'T12:00:00').toLocaleDateString('en-US', {
    weekday: 'long',
    month: 'long',
    day: 'numeric',
    year: 'numeric',
  })

  // Group by confidence tier
  const high = projections.filter((p: any) => p.confidence != null && p.confidence >= 0.7)
  const medium = projections.filter((p: any) => p.confidence != null && p.confidence >= 0.5 && p.confidence < 0.7)
  const low = projections.filter((p: any) => p.confidence == null || p.confidence < 0.5)

  return (
    <div className="min-h-screen">
      {/* Hero */}
      <section className="relative overflow-hidden">
        <div className="absolute inset-0 bg-gradient-to-b from-green-950/20 via-transparent to-transparent pointer-events-none" />
        <div className="absolute top-0 left-1/2 -translate-x-1/2 w-[700px] h-[400px] bg-green-500/8 blur-[120px] rounded-full pointer-events-none" />

        <div className="relative max-w-6xl mx-auto px-4 pt-16 pb-10">
          <div className="text-sm text-green-400 font-medium uppercase tracking-wider mb-2">
            Edge Finder
          </div>
          <h1 className="text-3xl sm:text-4xl font-bold tracking-tight mb-3">
            Today&apos;s Edges
          </h1>
          <p className="text-slate-400 text-lg max-w-2xl leading-relaxed">
            Projections ranked by model confidence. Each card shows the factors driving the number
            &mdash; park effects, umpire tendency, recent form &mdash; so you can verify the edge yourself.
          </p>
        </div>
      </section>

      {/* Pre-season banner */}
      {isPreSeason && (
        <div className="max-w-6xl mx-auto px-4 mb-6">
          <div className="flex items-start gap-3 p-4 bg-yellow-900/20 border border-yellow-700/40 rounded-xl">
            <span className="text-yellow-400 text-lg shrink-0">&#9888;</span>
            <div>
              <p className="text-yellow-300 font-medium text-sm">
                Pre-Season &mdash; Opening Day is March 26, 2026 ({daysUntil} days away)
              </p>
              <p className="text-yellow-200/60 text-xs mt-1">
                Projections shown are from backtesting on historical data. Live game-day edges with
                real odds comparison will begin once the 2026 MLB season starts. Current data
                demonstrates model output format and factor breakdowns.
              </p>
            </div>
          </div>
        </div>
      )}

      {/* Filters */}
      <div className="max-w-6xl mx-auto px-4 mb-8">
        <form className="flex flex-wrap items-end gap-4">
          <div>
            <label htmlFor="date" className="block text-xs text-slate-500 uppercase tracking-wider mb-1.5">
              Date
            </label>
            <input
              type="date"
              id="date"
              name="date"
              defaultValue={selectedDate}
              className="px-3 py-2 text-sm bg-slate-800 border border-slate-700 rounded-lg text-white focus:outline-none focus:border-green-500 [color-scheme:dark]"
            />
          </div>
          <div>
            <label htmlFor="stat_type" className="block text-xs text-slate-500 uppercase tracking-wider mb-1.5">
              Stat Type
            </label>
            <select
              id="stat_type"
              name="stat_type"
              defaultValue={selectedStatType}
              className="px-3 py-2 text-sm bg-slate-800 border border-slate-700 rounded-lg text-white focus:outline-none focus:border-green-500"
            >
              {STAT_TYPE_OPTIONS.map((opt) => (
                <option key={opt.value} value={opt.value}>
                  {opt.label}
                </option>
              ))}
            </select>
          </div>
          <button
            type="submit"
            className="px-5 py-2 text-sm font-medium bg-green-600 hover:bg-green-500 text-white rounded-lg transition-colors"
          >
            Filter
          </button>
        </form>
      </div>

      {/* Results */}
      <div className="max-w-6xl mx-auto px-4 pb-20">
        {projections.length === 0 ? (
          <div className="text-center py-20">
            <div className="text-5xl mb-4">&#9898;</div>
            <h2 className="text-xl font-semibold text-slate-300 mb-3">
              No edges available for {displayDate}
            </h2>
            <p className="text-slate-500 max-w-md mx-auto mb-6">
              {isPreSeason
                ? 'The 2026 MLB season has not started yet. Edges will populate automatically once games are scheduled and lineups are confirmed starting Opening Day (March 26, 2026).'
                : 'No projections were generated for this date. This could mean no games are scheduled, or the model has not yet run for this slate. Try selecting a different date.'}
            </p>
            <div className="flex items-center justify-center gap-4 flex-wrap">
              <Link
                href="/methodology"
                className="text-sm text-green-400 hover:text-green-300 font-medium transition-colors"
              >
                How the model works &rarr;
              </Link>
              <Link
                href="/accuracy"
                className="text-sm text-slate-400 hover:text-slate-200 font-medium transition-colors"
              >
                View backtest results &rarr;
              </Link>
            </div>
          </div>
        ) : (
          <div className="space-y-10">
            {/* Summary */}
            <div className="flex flex-wrap gap-4 text-sm">
              <div className="px-4 py-2 bg-slate-800/60 border border-slate-700 rounded-lg">
                <span className="text-slate-400">{displayDate}</span>
              </div>
              <div className="px-4 py-2 bg-slate-800/60 border border-slate-700 rounded-lg">
                <span className="text-slate-400">{projections.length} projections</span>
              </div>
              {high.length > 0 && (
                <div className="px-4 py-2 bg-green-900/30 border border-green-700/40 rounded-lg">
                  <span className="text-green-400">{high.length} high confidence</span>
                </div>
              )}
            </div>

            {/* High Confidence */}
            {high.length > 0 && (
              <section>
                <h2 className="text-xl font-semibold text-white mb-4 pb-2 border-b border-green-800">
                  High Confidence
                  <span className="ml-2 text-sm font-normal text-green-500">
                    70%+ ({high.length})
                  </span>
                </h2>
                <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
                  {high.map((proj: any, i: number) => (
                    <EdgeCard key={`high-${proj.player_name}-${proj.stat_type}-${i}`} proj={proj} />
                  ))}
                </div>
              </section>
            )}

            {/* Medium Confidence */}
            {medium.length > 0 && (
              <section>
                <h2 className="text-xl font-semibold text-white mb-4 pb-2 border-b border-blue-800">
                  Medium Confidence
                  <span className="ml-2 text-sm font-normal text-blue-400">
                    50&ndash;69% ({medium.length})
                  </span>
                </h2>
                <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
                  {medium.map((proj: any, i: number) => (
                    <EdgeCard key={`med-${proj.player_name}-${proj.stat_type}-${i}`} proj={proj} />
                  ))}
                </div>
              </section>
            )}

            {/* Low Confidence */}
            {low.length > 0 && (
              <section>
                <h2 className="text-xl font-semibold text-white mb-4 pb-2 border-b border-gray-700">
                  Low Confidence
                  <span className="ml-2 text-sm font-normal text-slate-400">
                    &lt;50% ({low.length})
                  </span>
                </h2>
                <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
                  {low.map((proj: any, i: number) => (
                    <EdgeCard key={`low-${proj.player_name}-${proj.stat_type}-${i}`} proj={proj} />
                  ))}
                </div>
              </section>
            )}
          </div>
        )}
      </div>
    </div>
  )
}
