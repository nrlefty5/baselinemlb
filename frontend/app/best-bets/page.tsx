import { createClient } from '@supabase/supabase-js'
import Link from 'next/link'
import { Metadata } from 'next'

export const metadata: Metadata = {
  title: 'Best Bets — BaselineMLB',
  description: 'Top MLB player prop picks ranked by edge percentage. Powered by Monte Carlo simulations.',
  openGraph: {
    title: 'Best Bets — BaselineMLB',
    description: 'Today\'s highest-edge MLB player props, ranked by confidence and edge %.',
  },
}

export const dynamic = 'force-dynamic'

const supabaseUrl = process.env.NEXT_PUBLIC_SUPABASE_URL || ''
const supabaseAnonKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY || ''

const STAT_LABELS: Record<string, string> = {
  pitcher_strikeouts: 'Strikeouts',
  batter_total_bases: 'Total Bases',
  batter_hits: 'Hits',
  batter_home_runs: 'Home Runs',
  batter_rbis: 'RBIs',
  batter_walks: 'Walks',
  batter_strikeouts: 'Batter Ks',
  pitcher_hits_allowed: 'Hits Allowed',
  pitcher_earned_runs: 'Earned Runs',
  pitcher_outs: 'Outs Recorded',
}

interface BestBet {
  player_name: string
  mlbam_id?: number
  stat_type: string
  projection: number
  line: number | null
  edge: number
  direction: string
  confidence: number
  grade: string
  team?: string | null
  features?: Record<string, any>
  shap_factors?: Record<string, number>
  over_odds?: number | null
  under_odds?: number | null
}

async function getBestBets(): Promise<BestBet[]> {
  if (!supabaseUrl || !supabaseAnonKey) {
    return []
  }
  const supabase = createClient(supabaseUrl, supabaseAnonKey)
  const today = new Date().toISOString().split('T')[0]

  // Query daily_projections table for today's projections
  const { data: projections, error: projError } = await supabase
    .from('daily_projections')
    .select('*')
    .eq('game_date', today)
    .order('confidence', { ascending: false })
    .limit(200)

  // Fallback: try 'projections' table if daily_projections doesn't exist
  let projectionsData = projections
  if (projError || !projections) {
    const { data: fallbackProj } = await supabase
      .from('projections')
      .select('*')
      .eq('game_date', today)
      .gte('confidence', 0.60)
      .order('confidence', { ascending: false })
      .limit(200)
    projectionsData = fallbackProj
  }

  if (!projectionsData || projectionsData.length === 0) return []

  // Query find_edges table for today's edges
  const { data: edges } = await supabase
    .from('find_edges')
    .select('*')
    .eq('game_date', today)

  // Fallback: try 'props' table if find_edges doesn't exist
  let edgesData = edges
  if (!edges) {
    const { data: fallbackEdges } = await supabase
      .from('props')
      .select('player_name, stat_type, market_key, line, over_odds, under_odds, edge_pct')
      .eq('game_date', today)
    edgesData = fallbackEdges
  }

  // Build edge lookup map
  const edgeMap: Record<string, any> = {}
  if (edgesData) {
    for (const edge of edgesData) {
      const key = `${edge.player_name}__${edge.stat_type || edge.market_key}`
      edgeMap[key] = edge
    }
  }

  // Fetch team info
  const mlbamIds = projectionsData.map((p: any) => p.mlbam_id).filter(Boolean)
  let teamMap: Record<string, string> = {}
  if (mlbamIds.length > 0) {
    const { data: players } = await supabase
      .from('players')
      .select('mlbam_id, team')
      .in('mlbam_id', mlbamIds)
    players?.forEach((p: any) => { teamMap[p.mlbam_id] = p.team })
  }

  // Match projections with edges and rank
  const bestBets: BestBet[] = []

  for (const proj of projectionsData) {
    const statType = proj.stat_type
    const edgeKey = `${proj.player_name}__${statType}`
    const match = edgeMap[edgeKey]

    let edge: number | null = null
    let line: number | null = null
    let direction: string | null = null

    if (match) {
      line = match.line
      edge = match.edge_pct ?? match.edge ?? null

      // Calculate edge if not provided
      if (edge == null && match.line != null && proj.projection != null) {
        const diff = proj.projection - match.line
        edge = match.line > 0 ? (diff / match.line) * 100 : null
      }

      if (edge != null && proj.projection != null && line != null) {
        direction = proj.projection > line ? 'OVER' : 'UNDER'
      }
    }

    // Include plays with meaningful edge (5%+) and decent confidence (60%+)
    if (edge != null && Math.abs(edge) >= 5 && (proj.confidence ?? 0) >= 0.60) {
      let features: Record<string, any> = {}
      let shapFactors: Record<string, number> | undefined = undefined
      try {
        const rawFeatures = typeof proj.features === 'string' ? JSON.parse(proj.features) : (proj.features || {})
        features = rawFeatures

        // Extract SHAP values if available
        if (proj.shap_values) {
          shapFactors = typeof proj.shap_values === 'string' ? JSON.parse(proj.shap_values) : proj.shap_values
        } else if (rawFeatures.shap_contributions) {
          shapFactors = rawFeatures.shap_contributions
        }
      } catch {}

      // Calculate grade
      const absEdge = Math.abs(edge)
      const conf = proj.confidence ?? 0
      let grade = 'C'
      if (conf >= 0.80 && absEdge >= 15) grade = 'A+'
      else if (conf >= 0.75 && absEdge >= 10) grade = 'A'
      else if (conf >= 0.70 && absEdge >= 8) grade = 'B+'
      else if (conf >= 0.65 && absEdge >= 5) grade = 'B'
      else if (conf >= 0.60 && absEdge >= 5) grade = 'B-'

      bestBets.push({
        player_name: proj.player_name,
        mlbam_id: proj.mlbam_id,
        stat_type: statType,
        projection: proj.projection,
        line,
        edge,
        direction: direction || 'OVER',
        confidence: proj.confidence ?? 0,
        grade,
        team: teamMap[proj.mlbam_id] || null,
        features,
        shap_factors: shapFactors,
        over_odds: match?.over_odds ?? null,
        under_odds: match?.under_odds ?? null,
      })
    }
  }

  // Sort by absolute edge descending, take top 15
  bestBets.sort((a, b) => Math.abs(b.edge) - Math.abs(a.edge))
  return bestBets.slice(0, 15)
}

// ── Grade Badge ──────────────────────────────────────────────────────────
function GradeBadge({ grade }: { grade: string }) {
  const colors: Record<string, string> = {
    'A+': 'bg-green-800 text-green-200 border-green-600/40',
    'A': 'bg-green-900 text-green-300 border-green-700/40',
    'B+': 'bg-blue-900 text-blue-300 border-blue-700/40',
    'B': 'bg-blue-900/50 text-blue-400 border-blue-700/30',
    'B-': 'bg-slate-700 text-slate-300 border-slate-600/40',
    'C': 'bg-slate-800 text-slate-400 border-slate-700/40',
  }
  const style = colors[grade] || colors['C']
  return (
    <span className={`inline-flex items-center justify-center w-11 h-11 rounded-lg text-lg font-bold border ${style}`}>
      {grade}
    </span>
  )
}

// ── SHAP Factor Bar ─────────────────────────────────────────────────────
function ShapFactors({ factors }: { factors: Record<string, number> }) {
  const sorted = Object.entries(factors)
    .filter(([, val]) => Math.abs(val) > 0.01)
    .sort((a, b) => Math.abs(b[1]) - Math.abs(a[1]))
    .slice(0, 6)

  if (sorted.length === 0) return null

  const maxAbs = Math.max(...sorted.map(([, v]) => Math.abs(v)))

  const FEATURE_LABELS: Record<string, string> = {
    blended_k9: 'K/9 Rate',
    opp_k_pct: 'Opp K%',
    expected_innings: 'Exp IP',
    park_adjustment: 'Park Factor',
    umpire_k_rate: 'Ump K Rate',
    platoon_matchup: 'Platoon',
    recent_form: 'Recent Form',
    weather_impact: 'Weather',
    venue: 'Venue',
    pitch_mix: 'Pitch Mix',
    rest_days: 'Rest Days',
    bullpen_usage: 'Bullpen',
  }

  return (
    <div className="mt-3 pt-3 border-t border-gray-700">
      <div className="text-xs text-slate-500 mb-2 font-medium uppercase tracking-wider">SHAP Factors</div>
      <div className="space-y-1.5">
        {sorted.map(([key, value]) => {
          const barWidth = Math.max((Math.abs(value) / maxAbs) * 100, 8)
          const isPositive = value > 0
          return (
            <div key={key} className="flex items-center gap-2">
              <span className="text-xs text-slate-400 w-20 truncate">
                {FEATURE_LABELS[key] || key.replace(/_/g, ' ')}
              </span>
              <div className="flex-1 flex items-center">
                <div className="w-full h-3 bg-gray-800 rounded-sm overflow-hidden relative">
                  <div
                    className={`h-full rounded-sm ${isPositive ? 'bg-green-600/70' : 'bg-red-600/70'}`}
                    style={{ width: `${barWidth}%` }}
                  />
                </div>
              </div>
              <span className={`text-xs font-mono w-14 text-right ${isPositive ? 'text-green-400' : 'text-red-400'}`}>
                {isPositive ? '+' : ''}{value.toFixed(2)}
              </span>
            </div>
          )
        })}
      </div>
    </div>
  )
}

// ── Visible Best Bet Card ───────────────────────────────────────────────
function BestBetCard({ bet, rank }: { bet: BestBet; rank: number }) {
  const statLabel = STAT_LABELS[bet.stat_type] || bet.stat_type

  return (
    <div className="bg-gray-800 border border-gray-700 rounded-lg p-5 hover:border-gray-500 transition-colors">
      <div className="flex items-start gap-4">
        {/* Rank */}
        <div className="flex flex-col items-center gap-2">
          <span className="text-xs text-slate-500 font-mono">#{rank}</span>
          <GradeBadge grade={bet.grade} />
        </div>

        <div className="flex-1 min-w-0">
          {/* Header */}
          <div className="flex items-center justify-between">
            <a
              href={bet.mlbam_id ? `/players/${bet.mlbam_id}` : '#'}
              className="font-semibold text-white text-lg hover:text-blue-400 transition-colors"
            >
              {bet.player_name}
            </a>
            <span className={`text-lg font-bold px-3 py-0.5 rounded-md ${
              bet.direction === 'OVER'
                ? 'text-green-400 bg-green-900/30'
                : 'text-red-400 bg-red-900/30'
            }`}>
              {bet.direction}
            </span>
          </div>

          {/* Subtitle */}
          <div className="text-sm text-slate-400 mt-0.5">
            {bet.team && <span>{bet.team} &bull; </span>}
            {statLabel}
            {bet.features?.venue && <span> &bull; {bet.features.venue}</span>}
          </div>

          {/* Stats Row */}
          <div className="flex items-center gap-6 mt-3">
            <div>
              <div className="text-2xl font-bold text-white">{bet.projection?.toFixed(1)}</div>
              <div className="text-xs text-slate-500">Projected</div>
            </div>
            {bet.line != null && (
              <div>
                <div className="text-2xl font-bold text-slate-400">{bet.line}</div>
                <div className="text-xs text-slate-500">Line</div>
              </div>
            )}
            <div>
              <div className={`text-2xl font-bold ${bet.edge > 0 ? 'text-green-400' : 'text-red-400'}`}>
                {bet.edge > 0 ? '+' : ''}{bet.edge.toFixed(1)}%
              </div>
              <div className="text-xs text-slate-500">Edge</div>
            </div>
            <div>
              <div className="text-2xl font-bold text-blue-400">{Math.round(bet.confidence * 100)}%</div>
              <div className="text-xs text-slate-500">Confidence</div>
            </div>
          </div>

          {/* Odds row */}
          {(bet.over_odds != null || bet.under_odds != null) && (
            <div className="mt-2 flex items-center gap-4 text-xs text-slate-500">
              {bet.over_odds != null && (
                <span>Over: <span className="text-slate-300">{bet.over_odds > 0 ? '+' : ''}{bet.over_odds}</span></span>
              )}
              {bet.under_odds != null && (
                <span>Under: <span className="text-slate-300">{bet.under_odds > 0 ? '+' : ''}{bet.under_odds}</span></span>
              )}
            </div>
          )}

          {/* Key factors (always shown) */}
          <div className="mt-3 pt-2 border-t border-gray-700 flex flex-wrap gap-3 text-xs text-slate-500">
            {bet.features?.blended_k9 && <span>K/9: {bet.features.blended_k9}</span>}
            {bet.features?.opp_k_pct && <span>Opp K%: {(bet.features.opp_k_pct * 100).toFixed(1)}%</span>}
            {bet.features?.umpire_name && <span>Ump: {bet.features.umpire_name}</span>}
            {bet.features?.platoon_matchup && bet.features.platoon_matchup !== 'unknown' && (
              <span>Platoon: {bet.features.platoon_matchup}</span>
            )}
            {bet.features?.expected_innings && <span>Exp IP: {bet.features.expected_innings}</span>}
            {bet.features?.park_adjustment && <span>Park: {bet.features.park_adjustment}</span>}
          </div>

          {/* SHAP explanation (pro/premium only — rendered when factors exist) */}
          {bet.shap_factors && Object.keys(bet.shap_factors).length > 0 && (
            <ShapFactors factors={bet.shap_factors} />
          )}
        </div>
      </div>
    </div>
  )
}

// ── Locked/Blurred Card ─────────────────────────────────────────────────
function LockedBetCard({ bet, rank }: { bet: BestBet; rank: number }) {
  const statLabel = STAT_LABELS[bet.stat_type] || bet.stat_type

  return (
    <div className="bg-gray-800 border border-gray-700 rounded-lg p-5 relative overflow-hidden">
      {/* Blur overlay */}
      <div className="absolute inset-0 backdrop-blur-md bg-gray-900/60 z-10 flex flex-col items-center justify-center">
        <svg className="w-8 h-8 text-slate-400 mb-2" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M16.5 10.5V6.75a4.5 4.5 0 10-9 0v3.75m-.75 11.25h10.5a2.25 2.25 0 002.25-2.25v-6.75a2.25 2.25 0 00-2.25-2.25H6.75a2.25 2.25 0 00-2.25 2.25v6.75a2.25 2.25 0 002.25 2.25z" />
        </svg>
        <p className="text-sm font-medium text-slate-300 mb-1">Pro Pick #{rank}</p>
        <p className="text-xs text-slate-500 mb-3">Upgrade to see full analysis</p>
        <Link
          href="/pricing"
          className="bg-blue-600 hover:bg-blue-500 text-white text-sm font-medium px-4 py-2 rounded-lg transition-colors"
        >
          Unlock All Picks
        </Link>
      </div>

      {/* Blurred content (still rendered but not readable) */}
      <div className="flex items-start gap-4 select-none" aria-hidden="true">
        <div className="flex flex-col items-center gap-2">
          <span className="text-xs text-slate-500 font-mono">#{rank}</span>
          <GradeBadge grade={bet.grade} />
        </div>
        <div className="flex-1">
          <div className="flex items-center justify-between">
            <span className="font-semibold text-white text-lg">
              {bet.player_name.split(' ').map(w => w[0] + '***').join(' ')}
            </span>
            <span className={`text-lg font-bold px-3 py-0.5 rounded-md ${
              bet.direction === 'OVER'
                ? 'text-green-400 bg-green-900/30'
                : 'text-red-400 bg-red-900/30'
            }`}>
              {bet.direction}
            </span>
          </div>
          <div className="text-sm text-slate-400 mt-0.5">{statLabel}</div>
          <div className="flex items-center gap-6 mt-3">
            <div>
              <div className="text-2xl font-bold text-slate-600">?.?</div>
              <div className="text-xs text-slate-500">Projected</div>
            </div>
            <div>
              <div className="text-2xl font-bold text-slate-600">?.?</div>
              <div className="text-xs text-slate-500">Line</div>
            </div>
            <div>
              <div className="text-2xl font-bold text-slate-600">+?.?%</div>
              <div className="text-xs text-slate-500">Edge</div>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}

// ── Main Page ───────────────────────────────────────────────────────────
export default async function BestBetsPage() {
  const bestBets = await getBestBets()

  const today = new Date().toLocaleDateString('en-US', {
    weekday: 'long',
    month: 'long',
    day: 'numeric',
    timeZone: 'America/New_York',
  })

  // Free tier: show top 3, lock the rest
  const FREE_LIMIT = 3

  const overBets = bestBets.filter(b => b.direction === 'OVER')
  const underBets = bestBets.filter(b => b.direction === 'UNDER')

  return (
    <div className="max-w-4xl mx-auto px-4 py-8">
      {/* Header */}
      <div className="mb-8">
        <div className="flex items-center gap-3 mb-2">
          <h1 className="text-3xl font-bold text-white">Best Bets</h1>
          <span className="text-xs px-2 py-1 rounded-full bg-green-900/50 text-green-400 border border-green-700/30 font-medium">
            Updated Daily
          </span>
        </div>
        <p className="text-slate-400">
          {today} &bull; Top plays ranked by edge % + confidence &bull; {bestBets.length} plays
        </p>
        <p className="text-xs text-slate-500 mt-2">
          Minimum thresholds: 60% model confidence + 5% edge vs market line.
          Top 3 picks are free &mdash; <Link href="/pricing" className="text-blue-400 hover:underline">upgrade</Link> for full access with SHAP explanations.
        </p>
      </div>

      {bestBets.length === 0 ? (
        <div className="text-center py-16">
          <div className="text-4xl mb-4">🎯</div>
          <h2 className="text-xl font-semibold text-slate-300 mb-2">No best bets today</h2>
          <p className="text-slate-500 max-w-md mx-auto">
            {!supabaseUrl
              ? 'Configure Supabase environment variables.'
              : 'Best bets require high-confidence projections with meaningful edge vs prop lines. Check back after the morning pipeline runs.'}
          </p>
        </div>
      ) : (
        <div className="space-y-10">
          {/* Over Plays */}
          {overBets.length > 0 && (
            <section>
              <h2 className="text-xl font-semibold text-white mb-4 pb-2 border-b border-green-800">
                Over Plays
                <span className="ml-2 text-sm font-normal text-green-500">({overBets.length})</span>
              </h2>
              <div className="space-y-4">
                {overBets.map((bet, i) => {
                  const globalIndex = bestBets.indexOf(bet) + 1
                  return globalIndex <= FREE_LIMIT ? (
                    <BestBetCard key={`over-${bet.player_name}-${bet.stat_type}-${i}`} bet={bet} rank={globalIndex} />
                  ) : (
                    <LockedBetCard key={`over-locked-${bet.player_name}-${bet.stat_type}-${i}`} bet={bet} rank={globalIndex} />
                  )
                })}
              </div>
            </section>
          )}

          {/* Under Plays */}
          {underBets.length > 0 && (
            <section>
              <h2 className="text-xl font-semibold text-white mb-4 pb-2 border-b border-red-800">
                Under Plays
                <span className="ml-2 text-sm font-normal text-red-500">({underBets.length})</span>
              </h2>
              <div className="space-y-4">
                {underBets.map((bet, i) => {
                  const globalIndex = bestBets.indexOf(bet) + 1
                  return globalIndex <= FREE_LIMIT ? (
                    <BestBetCard key={`under-${bet.player_name}-${bet.stat_type}-${i}`} bet={bet} rank={globalIndex} />
                  ) : (
                    <LockedBetCard key={`under-locked-${bet.player_name}-${bet.stat_type}-${i}`} bet={bet} rank={globalIndex} />
                  )
                })}
              </div>
            </section>
          )}

          {/* CTA Banner */}
          {bestBets.length > FREE_LIMIT && (
            <div className="bg-gradient-to-r from-blue-900/40 to-purple-900/40 border border-blue-700/30 rounded-xl p-6 text-center">
              <h3 className="text-xl font-bold text-white mb-2">
                {bestBets.length - FREE_LIMIT} more picks available
              </h3>
              <p className="text-slate-400 text-sm mb-4 max-w-md mx-auto">
                Pro subscribers get all picks with full SHAP explanations,
                probability distributions, and Kelly criterion sizing.
              </p>
              <Link
                href="/pricing"
                className="inline-block bg-blue-600 hover:bg-blue-500 text-white font-medium px-6 py-3 rounded-lg transition-colors"
              >
                View Plans &rarr;
              </Link>
            </div>
          )}

          {/* Methodology */}
          <div className="mt-8 p-4 bg-gray-900/50 rounded-lg border border-gray-800 text-xs text-slate-500">
            <p className="font-medium text-slate-400 mb-1">How Best Bets are calculated:</p>
            <ul className="space-y-0.5">
              <li>&bull; Model confidence must be 60%+ (based on data availability and factor coverage)</li>
              <li>&bull; Edge must be 5%+ vs the market prop line</li>
              <li>&bull; Grade combines confidence + edge magnitude (A+ = 80% conf + 15% edge)</li>
              <li>&bull; Ranked by absolute edge percentage, top 15 shown daily</li>
              <li>&bull; All factors are shown transparently &mdash; no black boxes</li>
            </ul>
          </div>
        </div>
      )}
    </div>
  )
}
