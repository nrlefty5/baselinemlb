import { createClient } from '@supabase/supabase-js'

export const dynamic = 'force-dynamic'

const supabaseUrl = process.env.NEXT_PUBLIC_SUPABASE_URL || ''
const supabaseAnonKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY || ''

const STAT_LABELS: Record<string, string> = {
  pitcher_strikeouts: 'Strikeouts',
  batter_total_bases: 'Total Bases',
  batter_hits: 'Hits',
  batter_home_runs: 'Home Runs',
}

async function getBestBets() {
  if (!supabaseUrl || !supabaseAnonKey) {
    return []
  }
  const supabase = createClient(supabaseUrl, supabaseAnonKey)
  const today = new Date().toISOString().split('T')[0]

  // Fetch high-confidence projections
  const { data: projections } = await supabase
    .from('projections')
    .select('*')
    .eq('game_date', today)
    .gte('confidence', 0.65)
    .order('confidence', { ascending: false })
    .limit(100)

  if (!projections || projections.length === 0) return []

  // Fetch today's props
  const { data: props } = await supabase
    .from('props')
    .select('player_name, market_key, line, over_odds, under_odds, edge_pct')
    .eq('game_date', today)

  // Fetch team names
  const mlbamIds = projections.map((p: any) => p.mlbam_id).filter(Boolean)
  let teamMap: Record<string, string> = {}
  if (mlbamIds.length > 0) {
    const { data: players } = await supabase
      .from('players')
      .select('mlbam_id, team')
      .in('mlbam_id', mlbamIds)
    players?.forEach((p: any) => { teamMap[p.mlbam_id] = p.team })
  }

  // Match projections with props and calculate edges
  const STAT_TO_MARKET: Record<string, string> = {
    pitcher_strikeouts: 'pitcher_strikeouts',
    batter_total_bases: 'batter_total_bases',
  }

  const edgeMap: Record<string, any> = {}
  if (props) {
    for (const prop of props) {
      const key = `${prop.player_name}__${prop.market_key}`
      edgeMap[key] = prop
    }
  }

  const bestBets = []
  for (const proj of projections) {
    const marketKey = STAT_TO_MARKET[proj.stat_type] || proj.stat_type
    const edgeKey = `${proj.player_name}__${marketKey}`
    const match = edgeMap[edgeKey]

    let edge = null
    let line = null
    let direction = null

    if (match) {
      line = match.line
      edge = match.edge_pct
      if (edge == null && match.line != null && proj.projection != null) {
        const diff = proj.projection - match.line
        edge = match.line > 0 ? (diff / match.line) * 100 : null
      }
      if (edge != null && proj.projection != null && line != null) {
        direction = proj.projection > line ? 'OVER' : 'UNDER'
      }
    }

    // Only include plays with meaningful edge
    if (edge != null && Math.abs(edge) >= 5 && proj.confidence >= 0.65) {
      let features: any = {}
      try {
        features = typeof proj.features === 'string' ? JSON.parse(proj.features) : (proj.features || {})
      } catch {}

      bestBets.push({
        ...proj,
        team: teamMap[proj.mlbam_id] || null,
        edge,
        line,
        direction,
        features,
        over_odds: match?.over_odds,
        under_odds: match?.under_odds,
      })
    }
  }

  // Sort by absolute edge value
  bestBets.sort((a, b) => Math.abs(b.edge) - Math.abs(a.edge))

  return bestBets
}

function GradeBadge({ confidence, edge }: { confidence: number; edge: number }) {
  const absEdge = Math.abs(edge)
  let grade = 'C'
  let color = 'bg-gray-700 text-slate-400'

  if (confidence >= 0.80 && absEdge >= 15) {
    grade = 'A+'
    color = 'bg-green-800 text-green-200'
  } else if (confidence >= 0.75 && absEdge >= 10) {
    grade = 'A'
    color = 'bg-green-900 text-green-300'
  } else if (confidence >= 0.70 && absEdge >= 8) {
    grade = 'B+'
    color = 'bg-blue-900 text-blue-300'
  } else if (confidence >= 0.65 && absEdge >= 5) {
    grade = 'B'
    color = 'bg-blue-900/50 text-blue-400'
  }

  return (
    <span className={`inline-flex items-center justify-center w-10 h-10 rounded-lg text-lg font-bold ${color}`}>
      {grade}
    </span>
  )
}

function BestBetCard({ bet }: { bet: any }) {
  const statLabel = STAT_LABELS[bet.stat_type] || bet.stat_type

  return (
    <div className="bg-gray-800 border border-gray-700 rounded-lg p-5 hover:border-gray-500 transition-colors">
      <div className="flex items-start gap-4">
        <GradeBadge confidence={bet.confidence} edge={bet.edge} />

        <div className="flex-1">
          <div className="flex items-center justify-between">
            <a href={`/players/${bet.mlbam_id}`} className="font-semibold text-white text-lg hover:text-blue-400 transition-colors">
              {bet.player_name}
            </a>
            <span className={`text-lg font-bold ${bet.direction === 'OVER' ? 'text-green-400' : 'text-red-400'}`}>
              {bet.direction}
            </span>
          </div>

          <div className="text-sm text-slate-400 mt-0.5">
            {bet.team && <span>{bet.team} &bull; </span>}
            {statLabel}
            {bet.features?.venue && <span> &bull; {bet.features.venue}</span>}
          </div>

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

          {/* Key factors */}
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
        </div>
      </div>
    </div>
  )
}

export default async function BestBetsPage() {
  const bestBets = await getBestBets()

  const today = new Date().toLocaleDateString('en-US', {
    weekday: 'long',
    month: 'long',
    day: 'numeric',
    timeZone: 'America/New_York',
  })

  const overBets = bestBets.filter((b: any) => b.direction === 'OVER')
  const underBets = bestBets.filter((b: any) => b.direction === 'UNDER')

  return (
    <div>
      <div className="mb-8">
        <h1 className="text-3xl font-bold text-white mb-2">Best Bets</h1>
        <p className="text-slate-400">
          {today} &bull; Top plays graded by edge + confidence &bull; {bestBets.length} plays
        </p>
        <p className="text-xs text-slate-500 mt-2">
          Minimum thresholds: 65% model confidence + 5% edge vs market line
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
          {overBets.length > 0 && (
            <section>
              <h2 className="text-xl font-semibold text-white mb-4 pb-2 border-b border-green-800">
                Over Plays
                <span className="ml-2 text-sm font-normal text-green-500">({overBets.length})</span>
              </h2>
              <div className="space-y-4">
                {overBets.map((bet: any, i: number) => (
                  <BestBetCard key={`over-${bet.player_name}-${bet.stat_type}-${i}`} bet={bet} />
                ))}
              </div>
            </section>
          )}

          {underBets.length > 0 && (
            <section>
              <h2 className="text-xl font-semibold text-white mb-4 pb-2 border-b border-red-800">
                Under Plays
                <span className="ml-2 text-sm font-normal text-red-500">({underBets.length})</span>
              </h2>
              <div className="space-y-4">
                {underBets.map((bet: any, i: number) => (
                  <BestBetCard key={`under-${bet.player_name}-${bet.stat_type}-${i}`} bet={bet} />
                ))}
              </div>
            </section>
          )}

          <div className="mt-8 p-4 bg-gray-900/50 rounded-lg border border-gray-800 text-xs text-slate-500">
            <p className="font-medium text-slate-400 mb-1">How Best Bets are calculated:</p>
            <ul className="space-y-0.5">
              <li>&bull; Model confidence must be 65%+ (based on data availability and factor coverage)</li>
              <li>&bull; Edge must be 5%+ vs the market prop line</li>
              <li>&bull; Grade combines confidence + edge magnitude (A+ = 80% conf + 15% edge)</li>
              <li>&bull; All factors are shown transparently - no black boxes</li>
            </ul>
          </div>
        </div>
      )}
    </div>
  )
}
