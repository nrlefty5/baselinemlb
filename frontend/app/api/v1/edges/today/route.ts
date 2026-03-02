// ============================================================
// GET /api/v1/edges/today
// Returns today's top prop edges.
// Free tier: top 3 edges only. Pro/Premium: all edges with
// full distributions, SHAP factors, and Kelly sizing.
// ============================================================

import { NextRequest, NextResponse } from 'next/server'
import { authenticateRequest } from '../../../lib/auth'
import { TIER_CAPS, type Edge, type EdgeWithDistribution, type ApiResponse } from '../../../lib/types'
import { getPublicClient } from '../../../lib/supabase'

export const dynamic = 'force-dynamic'

export async function GET(req: NextRequest) {
  // ── Authenticate ────────────────────────────────────────────────
  const authResult = await authenticateRequest(req)
  if ('error' in authResult) return authResult.error
  const { tier } = authResult.auth

  const caps = TIER_CAPS[tier]
  const supabase = getPublicClient()
  const today = new Date().toISOString().split('T')[0]

  // ── Query today's picks, ordered by edge descending ─────────────
  const { data: picks, error } = await supabase
    .from('picks')
    .select(`
      id, game_date, game_pk, player_name, mlbam_id,
      stat_type, line, projection, edge, direction, grade,
      result, actual_value
    `)
    .eq('game_date', today)
    .eq('published', true)
    .order('edge', { ascending: false })

  if (error) {
    return NextResponse.json(
      { error: 'Failed to fetch edges', code: 'DB_ERROR', status: 500 },
      { status: 500 }
    )
  }

  let edges: (Edge | EdgeWithDistribution)[] = picks || []

  // ── Free tier: limit to top 3 ───────────────────────────────────
  if (caps.max_edges !== null) {
    edges = edges.slice(0, caps.max_edges)
  }

  // ── Pro/Premium: enrich with distribution data ──────────────────
  if (caps.show_distributions && edges.length > 0) {
    const mlbamIds = edges.map(e => e.mlbam_id).filter(Boolean)

    const { data: projections } = await supabase
      .from('projections')
      .select('mlbam_id, stat_type, projection, confidence, features')
      .eq('game_date', today)
      .in('mlbam_id', mlbamIds)

    const projMap = new Map(
      (projections || []).map(p => [`${p.mlbam_id}-${p.stat_type}`, p])
    )

    edges = edges.map(edge => {
      const proj = projMap.get(`${edge.mlbam_id}-${edge.stat_type}`)
      const enriched: EdgeWithDistribution = { ...edge }

      if (proj) {
        const mean = Number(proj.projection)
        const confidence = Number(proj.confidence) || 0.5
        const std = mean * (1 - confidence) * 0.5

        enriched.distribution = {
          mean,
          std: Math.round(std * 100) / 100,
          percentiles: {
            p10: Math.round((mean - 1.28 * std) * 100) / 100,
            p25: Math.round((mean - 0.67 * std) * 100) / 100,
            p50: mean,
            p75: Math.round((mean + 0.67 * std) * 100) / 100,
            p90: Math.round((mean + 1.28 * std) * 100) / 100,
          },
          over_probability: Math.round((1 - normalCdf(edge.line, mean, std)) * 1000) / 10,
          under_probability: Math.round(normalCdf(edge.line, mean, std) * 1000) / 10,
        }

        if (caps.show_shap && proj.features) {
          enriched.shap_factors = proj.features as Record<string, number>
        }

        if (caps.show_kelly) {
          const impliedProb = 0.5
          const edgePct = Number(edge.edge)
          const trueProb = impliedProb + edgePct
          const kellyFull = (trueProb * 2 - 1) / 1
          const kellyQuarter = Math.max(0, kellyFull * 0.25)
          enriched.kelly_fraction = Math.round(kellyQuarter * 1000) / 1000
          enriched.kelly_unit_size = Math.round(kellyQuarter * 100 * 100) / 100
        }
      }

      return enriched
    })
  }

  if (!caps.show_distributions) {
    edges = edges.map(({ ...e }) => {
      const clean = e as Record<string, unknown>
      delete clean.distribution
      delete clean.shap_factors
      delete clean.kelly_fraction
      delete clean.kelly_unit_size
      return clean as Edge
    })
  }

  const response: ApiResponse<typeof edges> = {
    data: edges,
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

function normalCdf(x: number, mean: number, std: number): number {
  if (std === 0) return x >= mean ? 1 : 0
  const z = (x - mean) / std
  const t = 1 / (1 + 0.2316419 * Math.abs(z))
  const d = 0.3989422804014327 * Math.exp(-z * z / 2)
  const p = d * t * (0.3193815 + t * (-0.3565638 + t * (1.781478 + t * (-1.821256 + t * 1.330274))))
  return z > 0 ? 1 - p : p
}
