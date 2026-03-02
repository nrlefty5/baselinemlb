import { createClient } from '@supabase/supabase-js'
import { NextRequest, NextResponse } from 'next/server'

const supabaseUrl = process.env.NEXT_PUBLIC_SUPABASE_URL || ''
const supabaseAnonKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY || ''

export const dynamic = 'force-dynamic'

export async function GET(req: NextRequest) {
  try {
    if (!supabaseUrl || !supabaseAnonKey) {
      return NextResponse.json({ error: 'Supabase not configured' }, { status: 500 })
    }

    const supabase = createClient(supabaseUrl, supabaseAnonKey)
    const { searchParams } = new URL(req.url)
    const gameDate = searchParams.get('date') || new Date().toISOString().split('T')[0]

    // Fetch today's games
    const { data: games, error: gamesError } = await supabase
      .from('games')
      .select('*')
      .eq('game_date', gameDate)
      .order('game_time', { ascending: true })

    if (gamesError) {
      console.error('Error fetching games:', gamesError)
      return NextResponse.json({ error: 'Failed to fetch games' }, { status: 500 })
    }

    // Fetch simulation results for this date
    const { data: simResults, error: simError } = await supabase
      .from('simulation_results')
      .select('*')
      .eq('game_date', gameDate)
      .order('edge_pct', { ascending: false })

    if (simError) {
      console.error('Error fetching sim results:', simError)
    }

    // Fetch projections as fallback if no sim results exist
    let projections: any[] = []
    if (!simResults || simResults.length === 0) {
      const { data: projData } = await supabase
        .from('projections')
        .select('*')
        .eq('game_date', gameDate)
        .order('confidence', { ascending: false })

      projections = projData || []

      // Also fetch props to calculate edges
      const { data: props } = await supabase
        .from('props')
        .select('*')
        .eq('game_date', gameDate)

      // Merge props into projections
      if (props && props.length > 0) {
        const propMap: Record<string, any> = {}
        for (const prop of props) {
          propMap[`${prop.player_name}__${prop.stat_type || prop.market_key}`] = prop
        }
        for (const proj of projections) {
          const match = propMap[`${proj.player_name}__${proj.stat_type}`]
          if (match) {
            proj._prop_line = match.line
            proj._over_odds = match.over_odds
            proj._under_odds = match.under_odds
            if (match.line && proj.projection) {
              const diff = proj.projection - match.line
              proj._edge_pct = match.line > 0 ? (diff / match.line) * 100 : 0
              proj._direction = diff > 0 ? 'OVER' : 'UNDER'
            }
          }
        }
      }
    }

    // Group simulation results by game_pk
    const simByGame: Record<string, any[]> = {}
    if (simResults) {
      for (const sim of simResults) {
        const gk = sim.game_pk?.toString() || 'unknown'
        if (!simByGame[gk]) simByGame[gk] = []
        simByGame[gk].push(sim)
      }
    }

    // Group projections by game_pk as fallback
    const projByGame: Record<string, any[]> = {}
    for (const proj of projections) {
      const gk = proj.game_pk?.toString() || 'unknown'
      if (!projByGame[gk]) projByGame[gk] = []
      projByGame[gk].push(proj)
    }

    return NextResponse.json({
      date: gameDate,
      games: games || [],
      simulations: simByGame,
      projections: projByGame,
      hasSimData: !!simResults && simResults.length > 0,
      totalSims: simResults?.length || 0,
      totalProjections: projections.length,
    })
  } catch (err) {
    console.error('[simulator/today] Unexpected error:', err)
    return NextResponse.json({ error: 'Internal server error' }, { status: 500 })
  }
}
