// ============================================================
// GET /api/v1/backtest/summary
// Model accuracy metrics across all historical predictions.
// ============================================================

import { NextRequest, NextResponse } from 'next/server'
import { authenticateRequest } from '../../../lib/auth'
import { type ApiResponse, type BacktestSummary, type AccuracySummary } from '../../../lib/types'
import { getPublicClient } from '../../../lib/supabase'

export const dynamic = 'force-dynamic'

export async function GET(req: NextRequest) {
  const authResult = await authenticateRequest(req)
  if ('error' in authResult) return authResult.error
  const { tier } = authResult.auth

  const supabase = getPublicClient()

  // Fetch all resolved picks
  const { data: picks, error } = await supabase
    .from('picks')
    .select('game_date, stat_type, grade, result, edge, projection, actual_value')
    .not('result', 'is', null)
    .order('game_date', { ascending: false })

  if (error) {
    return NextResponse.json(
      { error: 'Failed to fetch backtest data', code: 'DB_ERROR', status: 500 },
      { status: 500 }
    )
  }

  const allPicks = picks || []

  // Fetch model version
  const { data: meta } = await supabase
    .from('model_meta')
    .select('version, last_run_at')
    .order('last_run_at', { ascending: false })
    .limit(1)
    .single()

  // Helper: compute accuracy summary for a slice of picks
  function summarize(slice: typeof allPicks, period: string, statType?: string): AccuracySummary {
    const hits = slice.filter(p => p.result === 'hit').length
    const misses = slice.filter(p => p.result === 'miss').length
    const pushes = slice.filter(p => p.result === 'push').length
    const decided = hits + misses
    const hitRate = decided > 0 ? Math.round((hits / decided) * 1000) / 10 : 0
    const avgEdge = slice.length > 0
      ? Math.round(slice.reduce((sum, p) => sum + Number(p.edge), 0) / slice.length * 1000) / 10
      : 0

    return {
      period,
      ...(statType ? { stat_type: statType } : {}),
      total_picks: slice.length,
      hits,
      misses,
      pushes,
      hit_rate: hitRate,
      avg_edge: avgEdge,
    }
  }

  // Overall accuracy
  const overall = summarize(allPicks, 'all-time')

  // By stat type
  const statTypes = [...new Set(allPicks.map(p => p.stat_type))]
  const by_stat_type = statTypes.map(st =>
    summarize(allPicks.filter(p => p.stat_type === st), 'all-time', st)
  )

  // By grade
  const grades = [...new Set(allPicks.map(p => p.grade))]
  const by_grade = grades.map(g => ({
    ...summarize(allPicks.filter(p => p.grade === g), 'all-time'),
    stat_type: g, // reuse stat_type field for grade label
  }))

  const summary: BacktestSummary = {
    model_version: meta?.version || 'unknown',
    updated_at: meta?.last_run_at || new Date().toISOString(),
    overall,
    by_stat_type,
    by_grade,
  }

  const response: ApiResponse<BacktestSummary> = {
    data: summary,
    meta: { tier, timestamp: new Date().toISOString() },
  }

  return NextResponse.json(response, {
    headers: { 'Cache-Control': 'public, s-maxage=3600, stale-while-revalidate=300' },
  })
}
