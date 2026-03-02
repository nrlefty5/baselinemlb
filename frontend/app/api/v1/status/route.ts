// ============================================================
// GET /api/v1/status
// API health check — public endpoint, no auth required.
// ============================================================

import { NextRequest, NextResponse } from 'next/server'
import { getPublicClient, isSupabaseConfigured } from '../../../lib/supabase'
import { type ApiStatus } from '../../../lib/types'

export const dynamic = 'force-dynamic'

export async function GET(_req: NextRequest) {
  const startTime = Date.now()

  if (!isSupabaseConfigured()) {
    const status: ApiStatus = {
      status: 'degraded',
      model_version: 'unknown',
      last_simulation_run: 'unknown',
      games_today: 0,
      edges_today: 0,
      uptime: process.uptime ? `${Math.floor(process.uptime())}s` : 'unknown',
      database: 'error',
    }
    return NextResponse.json(status, { status: 200 })
  }

  const supabase = getPublicClient()
  const today = new Date().toISOString().split('T')[0]

  const [modelMeta, gamesToday, edgesToday] = await Promise.allSettled([
    supabase
      .from('model_meta')
      .select('version, last_run_at')
      .order('last_run_at', { ascending: false })
      .limit(1)
      .single(),
    supabase
      .from('games')
      .select('id', { count: 'exact', head: true })
      .eq('game_date', today),
    supabase
      .from('picks')
      .select('id', { count: 'exact', head: true })
      .eq('game_date', today)
      .eq('published', true),
  ])

  const dbOk = modelMeta.status === 'fulfilled' && !modelMeta.value.error
  const meta = modelMeta.status === 'fulfilled' ? modelMeta.value.data : null
  const games = gamesToday.status === 'fulfilled' ? gamesToday.value.count ?? 0 : 0
  const edges = edgesToday.status === 'fulfilled' ? edgesToday.value.count ?? 0 : 0

  const responseTime = Date.now() - startTime
  const apiStatus: 'healthy' | 'degraded' | 'down' = !dbOk ? 'degraded' : 'healthy'

  const statusBody: ApiStatus = {
    status: apiStatus,
    model_version: meta?.version || 'unknown',
    last_simulation_run: meta?.last_run_at || 'unknown',
    games_today: games,
    edges_today: edges,
    uptime: process.uptime ? `${Math.floor(process.uptime())}s` : 'unknown',
    database: dbOk ? 'connected' : 'error',
  }

  return NextResponse.json(statusBody, {
    status: 200,
    headers: {
      'Cache-Control': 'no-store',
      'X-Response-Time': `${responseTime}ms`,
    },
  })
}
