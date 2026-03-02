// ============================================================
// GET /api/v1/player/[playerId]/history
// Player's prediction history and accuracy metrics.
// ============================================================

import { NextRequest, NextResponse } from 'next/server'
import { authenticateRequest } from '../../../../../lib/auth'
import { type ApiResponse, type PlayerHistory } from '../../../../../lib/types'
import { getPublicClient } from '../../../../../lib/supabase'

export const dynamic = 'force-dynamic'

export async function GET(
  req: NextRequest,
  { params }: { params: Promise<{ playerId: string }> }
) {
  const { playerId } = await params
  const mlbamId = parseInt(playerId, 10)

  if (isNaN(mlbamId)) {
    return NextResponse.json(
      { error: 'Invalid player ID. Use MLBAM ID (numeric).', code: 'INVALID_PARAM', status: 400 },
      { status: 400 }
    )
  }

  const authResult = await authenticateRequest(req)
  if ('error' in authResult) return authResult.error
  const { tier } = authResult.auth

  const supabase = getPublicClient()

  const { data: player } = await supabase
    .from('players')
    .select('mlbam_id, name, team, position')
    .eq('mlbam_id', mlbamId)
    .single()

  if (!player) {
    return NextResponse.json(
      { error: 'Player not found', code: 'NOT_FOUND', status: 404 },
      { status: 404 }
    )
  }

  const limit = tier === 'free' ? 10 : tier === 'pro' ? 50 : 200

  const { data: picks, error } = await supabase
    .from('picks')
    .select(`
      game_date, stat_type, line, projection, edge,
      direction, grade, result, actual_value
    `)
    .eq('mlbam_id', mlbamId)
    .not('result', 'is', null)
    .order('game_date', { ascending: false })
    .limit(limit)

  if (error) {
    return NextResponse.json(
      { error: 'Failed to fetch history', code: 'DB_ERROR', status: 500 },
      { status: 500 }
    )
  }

  const predictions = picks || []
  const hits = predictions.filter(p => p.result === 'hit').length
  const misses = predictions.filter(p => p.result === 'miss').length
  const pushes = predictions.filter(p => p.result === 'push').length
  const decided = hits + misses
  const hitRate = decided > 0 ? Math.round((hits / decided) * 1000) / 10 : 0
  const avgEdge = predictions.length > 0
    ? Math.round(predictions.reduce((sum, p) => sum + Number(p.edge), 0) / predictions.length * 1000) / 10
    : 0

  const history: PlayerHistory = {
    mlbam_id: player.mlbam_id,
    player_name: player.name,
    total_predictions: predictions.length,
    hits,
    misses,
    pushes,
    hit_rate: hitRate,
    avg_edge: avgEdge,
    predictions: predictions.map(p => ({
      game_date: p.game_date,
      stat_type: p.stat_type,
      line: Number(p.line),
      projection: Number(p.projection),
      edge: Number(p.edge),
      direction: p.direction,
      grade: p.grade,
      result: p.result as 'hit' | 'miss' | 'push' | null,
      actual_value: p.actual_value ? Number(p.actual_value) : undefined,
    })),
  }

  const response: ApiResponse<PlayerHistory> = {
    data: history,
    meta: { tier, timestamp: new Date().toISOString() },
  }

  return NextResponse.json(response, {
    headers: { 'Cache-Control': 'public, s-maxage=300, stale-while-revalidate=60' },
  })
}
