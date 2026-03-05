import { NextRequest, NextResponse } from 'next/server'
import { getPublicClient } from '@/app/lib/supabase'

// GET /api/boxscore/[gamePk] — Projected box score data for a game
export async function GET(
  request: NextRequest,
  { params }: { params: { gamePk: string } }
) {
  try {
    const gamePk = parseInt(params.gamePk, 10)
    if (isNaN(gamePk)) {
      return NextResponse.json({ error: 'Invalid gamePk' }, { status: 400 })
    }

    const supabase = getPublicClient()

    // 1. Get game info
    const { data: game, error: gameError } = await supabase
      .from('games')
      .select('*')
      .eq('game_pk', gamePk)
      .single()

    if (gameError || !game) {
      return NextResponse.json({ error: 'Game not found' }, { status: 404 })
    }

    // 2. Get lineups for both sides
    const { data: lineups } = await supabase
      .from('lineups')
      .select('*')
      .eq('game_pk', gamePk)

    // 3. Get all sim_results for this game
    const { data: simResults, error: simError } = await supabase
      .from('sim_results')
      .select('*')
      .eq('game_pk', gamePk)

    if (simError) {
      return NextResponse.json({ error: 'Failed to fetch sim results' }, { status: 500 })
    }

    // 4. Get weather data
    const { data: weather } = await supabase
      .from('weather')
      .select('*')
      .eq('game_pk', gamePk)
      .single()

    // Build player projection maps by pivoting sim_results
    // sim_results has one row per (player_id, stat_type) with sim_mean, sim_median, etc.
    const playerMap: Record<number, Record<string, number>> = {}
    const playerNames: Record<number, string> = {}

    if (simResults) {
      for (const row of simResults) {
        const pid = row.player_id
        if (!playerMap[pid]) playerMap[pid] = {}
        playerNames[pid] = row.player_name
        playerMap[pid][row.stat_type] = row.sim_mean
      }
    }

    // Separate batters from pitchers based on stat types present
    const pitcherStats = ['outs_recorded', 'hits_allowed', 'home_runs_allowed', 'earned_runs', 'runs_allowed']
    const isPitcher = (stats: Record<string, number>) =>
      pitcherStats.some(s => s in stats)

    // Build batter projections array
    const buildBatterRow = (pid: number) => {
      const stats = playerMap[pid] || {}
      return {
        player_id: pid,
        player_name: playerNames[pid] || `Player ${pid}`,
        pa: round(stats.pa || 0),
        h: round(stats.hits || 0),
        singles: round(stats.singles || 0),
        doubles: round(stats.doubles || 0),
        triples: round(stats.triples || 0),
        hr: round(stats.home_runs || 0),
        rbi: round(stats.rbis || 0),
        r: round(stats.runs_scored || 0),
        bb: round(stats.walks || 0),
        k: round(stats.strikeouts || 0),
        tb: round(stats.total_bases || 0),
        sb: round(stats.stolen_bases || 0),
      }
    }

    // Build pitcher projections
    const buildPitcherRow = (pid: number) => {
      const stats = playerMap[pid] || {}
      const outsRecorded = stats.outs_recorded || 0
      const ip = outsRecorded / 3
      return {
        player_id: pid,
        player_name: playerNames[pid] || `Player ${pid}`,
        ip: round(ip),
        h: round(stats.hits_allowed || 0),
        r: round(stats.runs_allowed || 0),
        er: round(stats.earned_runs || stats.runs_allowed || 0),
        k: round(stats.strikeouts || 0),
        bb: round(stats.walks || 0),
        hr: round(stats.home_runs_allowed || 0),
        pitches: round(stats.pitches || 0),
      }
    }

    // Get lineup orders from lineups table
    const homeLineup = lineups?.find(l => l.side === 'home')
    const awayLineup = lineups?.find(l => l.side === 'away')

    // Parse batting_order JSONB — expected format: [{mlbam_id, name, position}, ...]
    const parseLineupOrder = (lineup: typeof homeLineup): number[] => {
      if (!lineup?.batting_order) return []
      const order = typeof lineup.batting_order === 'string'
        ? JSON.parse(lineup.batting_order)
        : lineup.batting_order
      return Array.isArray(order) ? order.map((p: { mlbam_id?: number; id?: number }) => p.mlbam_id || p.id || 0) : []
    }

    const homeBatterIds = parseLineupOrder(homeLineup)
    const awayBatterIds = parseLineupOrder(awayLineup)

    // If lineups not in DB, fall back to all players with batter stats
    const allPlayerIds = Object.keys(playerMap).map(Number)
    const batterIds = allPlayerIds.filter(pid => !isPitcher(playerMap[pid]))
    const pitcherIds = allPlayerIds.filter(pid => isPitcher(playerMap[pid]))

    // Use lineup order if available, else just list all batters
    const homeBatters = (homeBatterIds.length > 0
      ? homeBatterIds.filter(pid => pid in playerMap)
      : batterIds.filter(pid => {
          // Try to match by team affiliation if available
          return true // fallback: include all
        })
    ).map(buildBatterRow)

    const awayBatters = (awayBatterIds.length > 0
      ? awayBatterIds.filter(pid => pid in playerMap)
      : []
    ).map(buildBatterRow)

    // If we couldn't split by team, put all batters under home (will need lineup data to split properly)
    const allBatters = homeBatters.length === 0 && awayBatters.length === 0
      ? batterIds.map(buildBatterRow)
      : null

    // Pitchers — use probable pitcher IDs from game data
    const homePitcher = game.home_probable_pitcher_id && pitcherIds.includes(game.home_probable_pitcher_id)
      ? buildPitcherRow(game.home_probable_pitcher_id)
      : pitcherIds.length > 0 ? buildPitcherRow(pitcherIds[0]) : null

    const awayPitcher = game.away_probable_pitcher_id && pitcherIds.includes(game.away_probable_pitcher_id)
      ? buildPitcherRow(game.away_probable_pitcher_id)
      : pitcherIds.length > 1 ? buildPitcherRow(pitcherIds[1]) : null

    // Team totals
    const sumBatters = (batters: ReturnType<typeof buildBatterRow>[]) => ({
      pa: round(batters.reduce((s, b) => s + b.pa, 0)),
      h: round(batters.reduce((s, b) => s + b.h, 0)),
      hr: round(batters.reduce((s, b) => s + b.hr, 0)),
      rbi: round(batters.reduce((s, b) => s + b.rbi, 0)),
      r: round(batters.reduce((s, b) => s + b.r, 0)),
      bb: round(batters.reduce((s, b) => s + b.bb, 0)),
      k: round(batters.reduce((s, b) => s + b.k, 0)),
      tb: round(batters.reduce((s, b) => s + b.tb, 0)),
    })

    return NextResponse.json({
      game: {
        game_pk: game.game_pk,
        game_date: game.game_date,
        game_time: game.game_time,
        home_team: game.home_team,
        away_team: game.away_team,
        venue: game.venue,
        home_probable_pitcher: game.home_probable_pitcher,
        away_probable_pitcher: game.away_probable_pitcher,
      },
      weather: weather ? {
        temperature_f: weather.temperature_f,
        wind_speed_mph: weather.wind_speed_mph,
        wind_direction: weather.wind_direction,
      } : null,
      home: {
        batters: homeBatters.length > 0 ? homeBatters : (allBatters ? allBatters.slice(0, 9) : []),
        pitcher: homePitcher,
        totals: sumBatters(homeBatters.length > 0 ? homeBatters : (allBatters ? allBatters.slice(0, 9) : [])),
      },
      away: {
        batters: awayBatters.length > 0 ? awayBatters : (allBatters ? allBatters.slice(9) : []),
        pitcher: awayPitcher,
        totals: sumBatters(awayBatters.length > 0 ? awayBatters : (allBatters ? allBatters.slice(9) : [])),
      },
    })
  } catch (err) {
    console.error('Boxscore API error:', err)
    return NextResponse.json({ error: 'Internal server error' }, { status: 500 })
  }
}

function round(n: number, decimals = 2): number {
  return Math.round(n * Math.pow(10, decimals)) / Math.pow(10, decimals)
}
