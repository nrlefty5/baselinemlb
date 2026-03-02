// ============================================================
// GET /api/v1/edges/[gameId]
// Full simulation breakdown for a specific game.
// ============================================================

import { NextRequest, NextResponse } from 'next/server'
import { authenticateRequest } from '../../../../lib/auth'
import { TIER_CAPS, type ApiResponse, type Edge } from '../../../../lib/types'
import { getPublicClient } from '../../../../lib/supabase'

export const dynamic = 'force-dynamic'

export async function GET(
  req: NextRequest,
  { params }: { params: Promise<{ gameId: string }> }
) {
  const { gameId } = await params
  const gamePk = parseInt(gameId, 10)

  if (isNaN(gamePk)) {
    return NextResponse.json(
      { error: 'Invalid game ID', code: 'INVALID_PARAM', status: 400 },
      { status: 400 }
    )
  }

  const authResult = await authenticateRequest(req)
  if ('error' in authResult) return authResult.error
  const { tier } = authResult.auth
  const caps = TIER_CAPS[tier]

  const supabase = getPublicClient()

  const { data: game, error: gameError } = await supabase
    .from('games')
    .select('*')
    .eq('game_pk', gamePk)
    .single()

  if (gameError || !game) {
    return NextResponse.json(
      { error: 'Game not found', code: 'NOT_FOUND', status: 404 },
      { status: 404 }
    )
  }

  const { data: picks, error: picksError } = await supabase
    .from('picks')
    .select(`
      id, game_date, game_pk, player_name, mlbam_id,
      stat_type, line, projection, edge, direction, grade,
      result, actual_value
    `)
    .eq('game_pk', gamePk)
    .order('edge', { ascending: false })

  if (picksError) {
    return NextResponse.json(
      { error: 'Failed to fetch edges', code: 'DB_ERROR', status: 500 },
      { status: 500 }
    )
  }

  const { data: projections } = await supabase
    .from('projections')
    .select('mlbam_id, stat_type, projection, confidence, features, model_version')
    .eq('game_pk', gamePk)

  const projMap = new Map(
    (projections || []).map(p => [`${p.mlbam_id}-${p.stat_type}`, p])
  )

  let edges = (picks || []).map((pick: Edge) => {
    const proj = projMap.get(`${pick.mlbam_id}-${pick.stat_type}`)
    return {
      ...pick,
      confidence: proj?.confidence ? Number(proj.confidence) : undefined,
      model_version: proj?.model_version,
      features: caps.show_shap && proj?.features ? proj.features : undefined,
    }
  })

  if (caps.max_edges !== null) {
    edges = edges.slice(0, caps.max_edges)
  }

  const response: ApiResponse<{
    game: typeof game
    edges: typeof edges
    edge_count: number
  }> = {
    data: {
      game: {
        game_pk: game.game_pk,
        game_date: game.game_date,
        away_team: game.away_team,
        home_team: game.home_team,
        away_starter: game.away_starter,
        home_starter: game.home_starter,
        venue: game.venue,
        status: game.status,
      },
      edges,
      edge_count: (picks || []).length,
    },
    meta: {
      tier,
      timestamp: new Date().toISOString(),
    },
  }

  return NextResponse.json(response, {
    headers: {
      'Cache-Control': 'public, s-maxage=120, stale-while-revalidate=60',
    },
  })
}
