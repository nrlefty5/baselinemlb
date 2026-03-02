import { createClient } from '@supabase/supabase-js'
import { NextRequest, NextResponse } from 'next/server'

const supabaseUrl = process.env.NEXT_PUBLIC_SUPABASE_URL || ''
const supabaseAnonKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY || ''

export const dynamic = 'force-dynamic'

export async function GET(
  req: NextRequest,
  { params }: { params: { gameId: string } }
) {
  try {
    if (!supabaseUrl || !supabaseAnonKey) {
      return NextResponse.json({ error: 'Supabase not configured' }, { status: 500 })
    }

    const supabase = createClient(supabaseUrl, supabaseAnonKey)
    const gameId = params.gameId

    // Fetch game info
    const { data: game, error: gameError } = await supabase
      .from('games')
      .select('*')
      .eq('game_pk', parseInt(gameId))
      .single()

    if (gameError || !game) {
      return NextResponse.json({ error: 'Game not found' }, { status: 404 })
    }

    // Fetch simulation results for this game
    const { data: simResults, error: simError } = await supabase
      .from('simulation_results')
      .select('*')
      .eq('game_pk', parseInt(gameId))
      .order('edge_pct', { ascending: false })

    if (simError) {
      console.error('Error fetching sim results:', simError)
    }

    // Fetch projections as fallback
    let projections: any[] = []
    if (!simResults || simResults.length === 0) {
      const { data: projData } = await supabase
        .from('projections')
        .select('*')
        .eq('game_pk', parseInt(gameId))
        .order('confidence', { ascending: false })

      projections = projData || []

      // Attach props
      const { data: props } = await supabase
        .from('props')
        .select('*')
        .eq('game_date', game.game_date)

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

    // Fetch umpire framing data for this game
    const { data: umpireData } = await supabase
      .from('umpire_framing')
      .select('*')
      .eq('game_pk', parseInt(gameId))

    return NextResponse.json({
      game,
      simulations: simResults || [],
      projections,
      umpire: umpireData || [],
      hasSimData: !!simResults && simResults.length > 0,
    })
  } catch (err) {
    console.error('[simulator/gameId] Unexpected error:', err)
    return NextResponse.json({ error: 'Internal server error' }, { status: 500 })
  }
}
