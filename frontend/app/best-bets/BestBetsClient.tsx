'use client'

// ============================================================
// BestBetsClient — Renders best bets with paywall enforcement
// Free users: see top 3, rest are blurred with upgrade CTA
// Pro users: see everything
// ============================================================

import Link from 'next/link'

interface BestBet {
  player_name: string
  mlbam_id?: number
  stat_type: string
  projection: number
  confidence: number
  edge: number
  line: number | null
  direction: string | null
  team: string | null
  features: any
  over_odds?: number
  under_odds?: number
}

interface BestBetsClientProps {
  bestBets: BestBet[]
    subscriptionTier: string
  today: string
  statLabels: Record<string, string>
}

function GradeBadge({ confidence, edge }: { confidence: number; edge: number }) {
  const absEdge = Math.abs(edge)
  let grade = 'C'
  let color = 'bg-gray-700 text-slate-400'

  if (confidence >= 0.85 && absEdge >= 12) {
    grade = 'A+'
    color = 'bg-emerald-800 text-emerald-200'
  } else if (confidence >= 0.75 && absEdge >= 10) {
    grade = 'A'
    color = 'bg-green-900 text-green-300'
  } else if (confidence >= 0.65 && absEdge >= 8) {
    grade = 'B+'
    color = 'bg-blue-900 text-blue-300'
  } else if (confidence >= 0.55 && absEdge >= 5) {
    grade = 'B'
    color = 'bg-blue-900/50 text-blue-400'
  } else if (confidence >= 0.40 && absEdge >= 5) {
    grade = 'B-'
    color = 'bg-slate-700 text-slate-300'
  }

  return (
    <span className={`inline-flex items-center justify-center w-10 h-10 rounded-lg text-lg font-bold ${color}`}>
      {grade}
    </span>
  )
}

function BestBetCard({ bet, statLabels }: { bet: BestBet; statLabels: Record<string, string> }) {
  const statLabel = statLabels[bet.stat_type] || bet.stat_type

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

function BlurredBetCard() {
  return (
    <div className="bg-gray-800 border border-gray-700 rounded-lg p-5 relative overflow-hidden">
      <div className="filter blur-sm pointer-events-none select-none" aria-hidden="true">
        <div className="flex items-start gap-4">
          <span className="inline-flex items-center justify-center w-10 h-10 rounded-lg text-lg font-bold bg-green-900 text-green-300">
            A
          </span>
          <div className="flex-1">
            <div className="flex items-center justify-between">
              <span className="font-semibold text-white text-lg">Player Name</span>
              <span className="text-lg font-bold text-green-400">OVER</span>
            </div>
            <div className="text-sm text-slate-400 mt-0.5">TEA &bull; Strikeouts</div>
            <div className="flex items-center gap-6 mt-3">
              <div>
                <div className="text-2xl font-bold text-white">7.2</div>
                <div className="text-xs text-slate-500">Projected</div>
              </div>
              <div>
                <div className="text-2xl font-bold text-slate-400">5.5</div>
                <div className="text-xs text-slate-500">Line</div>
              </div>
              <div>
                <div className="text-2xl font-bold text-green-400">+12.4%</div>
                <div className="text-xs text-slate-500">Edge</div>
              </div>
              <div>
                <div className="text-2xl font-bold text-blue-400">78%</div>
                <div className="text-xs text-slate-500">Confidence</div>
              </div>
            </div>
          </div>
        </div>
      </div>
      {/* Overlay */}
      <div className="absolute inset-0 bg-gradient-to-t from-slate-950/90 via-slate-950/60 to-transparent flex items-center justify-center">
        <div className="text-center">
          <div className="text-sm text-slate-300 font-medium mb-2">Pro members only</div>
          <Link
            href="/pricing"
            className="inline-flex items-center gap-1.5 bg-blue-600 hover:bg-blue-500 text-white text-sm font-medium px-4 py-2 rounded-lg transition-colors"
          >
            Unlock All Picks
          </Link>
        </div>
      </div>
    </div>
  )
}

function PaywallBanner({ totalBets }: { totalBets: number }) {
  return (
    <div className="bg-gradient-to-r from-blue-950/50 to-purple-950/50 border border-blue-800/50 rounded-xl p-6 mb-6 text-center">
      <h3 className="text-lg font-semibold text-white mb-1">
        {totalBets - 3} more picks available today
      </h3>
      <p className="text-sm text-slate-400 mb-4">
        Upgrade to Pro to see the full slate with SHAP explanations, probability distributions, and Kelly sizing.
      </p>
      <Link
        href="/pricing"
        className="inline-flex items-center gap-2 bg-blue-600 hover:bg-blue-500 text-white font-medium px-6 py-2.5 rounded-lg transition-colors"
      >
        Upgrade to Double-A — $7.99/mo
      </Link>
    </div>
  )
}

export default function BestBetsClient({
  bestBets,
  subscriptionTier,
  today,
  statLabels,
}: BestBetsClientProps) {
    const isPro = subscriptionTier !== 'single_a'
  const FREE_LIMIT = 3

  const overBets = bestBets.filter((b) => b.direction === 'OVER')
  const underBets = bestBets.filter((b) => b.direction === 'UNDER')

  // For free users, only show first FREE_LIMIT total, rest are blurred
  const allBets = [...overBets, ...underBets]
  const visibleBets = isPro ? allBets : allBets.slice(0, FREE_LIMIT)
  const hiddenCount = isPro ? 0 : Math.max(0, allBets.length - FREE_LIMIT)

  const visibleOver = visibleBets.filter((b) => b.direction === 'OVER')
  const visibleUnder = visibleBets.filter((b) => b.direction === 'UNDER')

  return (
    <div>
      <div className="mb-8">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-3xl font-bold text-white mb-2">Best Bets</h1>
            <p className="text-slate-400">
              {today} &bull; Top plays graded by edge + confidence &bull; {bestBets.length} plays
            </p>
            <p className="text-xs text-slate-500 mt-2">
              Minimum thresholds: 65% model confidence + 5% edge vs market line
            </p>
          </div>
          {isPro && (
            <span className="inline-flex items-center gap-1.5 bg-blue-600/20 text-blue-400 text-xs font-medium px-3 py-1 rounded-full border border-blue-600/30">
              PRO
            </span>
          )}
        </div>
      </div>

      {bestBets.length === 0 ? (
        <div className="text-center py-16">
          <div className="text-4xl mb-4">🎯</div>
          <h2 className="text-xl font-semibold text-slate-300 mb-2">No best bets today</h2>
          <p className="text-slate-500 max-w-md mx-auto">
            Best bets require high-confidence projections with meaningful edge vs prop lines. Check back after the morning pipeline runs.
          </p>
        </div>
      ) : (
        <div className="space-y-10">
          {/* Paywall banner for free users */}
          {!isPro && hiddenCount > 0 && (
            <PaywallBanner totalBets={bestBets.length} />
          )}

          {visibleOver.length > 0 && (
            <section>
              <h2 className="text-xl font-semibold text-white mb-4 pb-2 border-b border-green-800">
                Over Plays
                <span className="ml-2 text-sm font-normal text-green-500">
                  ({isPro ? overBets.length : visibleOver.length}{!isPro && overBets.length > visibleOver.length ? ` of ${overBets.length}` : ''})
                </span>
              </h2>
              <div className="space-y-4">
                {visibleOver.map((bet, i) => (
                  <BestBetCard key={`over-${bet.player_name}-${bet.stat_type}-${i}`} bet={bet} statLabels={statLabels} />
                ))}
              </div>
            </section>
          )}

          {visibleUnder.length > 0 && (
            <section>
              <h2 className="text-xl font-semibold text-white mb-4 pb-2 border-b border-red-800">
                Under Plays
                <span className="ml-2 text-sm font-normal text-red-500">
                  ({isPro ? underBets.length : visibleUnder.length}{!isPro && underBets.length > visibleUnder.length ? ` of ${underBets.length}` : ''})
                </span>
              </h2>
              <div className="space-y-4">
                {visibleUnder.map((bet, i) => (
                  <BestBetCard key={`under-${bet.player_name}-${bet.stat_type}-${i}`} bet={bet} statLabels={statLabels} />
                ))}
              </div>
            </section>
          )}

          {/* Blurred cards for free users */}
          {!isPro && hiddenCount > 0 && (
            <section>
              <h2 className="text-xl font-semibold text-slate-500 mb-4 pb-2 border-b border-slate-800">
                Locked Picks
                <span className="ml-2 text-sm font-normal text-slate-600">({hiddenCount})</span>
              </h2>
              <div className="space-y-4">
                {Array.from({ length: Math.min(hiddenCount, 3) }).map((_, i) => (
                  <BlurredBetCard key={`blurred-${i}`} />
                ))}
                {hiddenCount > 3 && (
                  <div className="text-center py-4">
                    <p className="text-sm text-slate-500">
                      + {hiddenCount - 3} more picks available with Pro
                    </p>
                  </div>
                )}
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
