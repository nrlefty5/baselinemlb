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
    const tier = searchParams.get('tier') || 'ALL'
    const days = parseInt(searchParams.get('days') || '90')

    const startDate = new Date()
    startDate.setDate(startDate.getDate() - days)
    const startStr = startDate.toISOString().split('T')[0]

    // Fetch backtest results
    const { data: backtestData, error: btError } = await supabase
      .from('simulation_backtest')
      .select('*')
      .gte('game_date', startStr)
      .order('game_date', { ascending: true })

    if (btError) {
      console.error('Error fetching backtest data:', btError)
    }

    // Fetch accuracy summary for comparison vs point-estimate model
    const { data: accuracyData, error: accError } = await supabase
      .from('accuracy_summary')
      .select('*')
      .order('total_picks', { ascending: false })

    if (accError) {
      console.error('Error fetching accuracy data:', accError)
    }

    // Fetch recent picks with grades for P/L calculation
    const { data: gradedPicks, error: picksError } = await supabase
      .from('picks')
      .select('game_date, stat_type, grade, edge, direction')
      .not('grade', 'is', null)
      .gte('game_date', startStr)
      .order('game_date', { ascending: true })

    if (picksError) {
      console.error('Error fetching picks:', picksError)
    }

    // Build calibration data from backtest
    const calibration: { predicted: number; actual: number; n: number }[] = []
    if (backtestData) {
      const buckets: Record<string, { predicted: number; actual: number; count: number }> = {}
      for (const row of backtestData) {
        if (!row.predicted_prob || !row.actual_rate) continue
        const bucket = (Math.round(row.predicted_prob * 10) / 10).toFixed(1)
        if (!buckets[bucket]) {
          buckets[bucket] = { predicted: parseFloat(bucket), actual: 0, count: 0 }
        }
        buckets[bucket].actual += row.actual_rate * (row.sample_size || 1)
        buckets[bucket].count += row.sample_size || 1
      }
      for (const b of Object.values(buckets)) {
        if (b.count > 0) {
          calibration.push({
            predicted: b.predicted,
            actual: b.actual / b.count,
            n: b.count,
          })
        }
      }
      calibration.sort((a, b) => a.predicted - b.predicted)
    }

    // Build P/L timeline
    const plTimeline: { date: string; dailyPL: number; cumulativePL: number }[] = []
    let cumulativePL = 0
    if (backtestData) {
      const byDate: Record<string, number> = {}
      for (const row of backtestData) {
        const d = row.game_date
        if (!byDate[d]) byDate[d] = 0
        byDate[d] += row.profit_loss || 0
      }
      const sortedDates = Object.keys(byDate).sort()
      for (const d of sortedDates) {
        cumulativePL += byDate[d]
        plTimeline.push({
          date: d,
          dailyPL: byDate[d],
          cumulativePL: Math.round(cumulativePL * 100) / 100,
        })
      }
    }

    // ROI by tier
    const roiByTier: Record<string, { bets: number; wins: number; pl: number; roi: number }> = {}
    if (backtestData) {
      for (const row of backtestData) {
        const t = row.tier || 'ALL'
        if (!roiByTier[t]) roiByTier[t] = { bets: 0, wins: 0, pl: 0, roi: 0 }
        roiByTier[t].bets += row.total_bets || 0
        roiByTier[t].wins += row.wins || 0
        roiByTier[t].pl += row.profit_loss || 0
      }
      for (const t of Object.keys(roiByTier)) {
        if (roiByTier[t].bets > 0) {
          roiByTier[t].roi = (roiByTier[t].pl / (roiByTier[t].bets * 100)) * 100
        }
      }
    }

    return NextResponse.json({
      backtest: backtestData || [],
      accuracy: accuracyData || [],
      gradedPicks: gradedPicks || [],
      calibration,
      plTimeline,
      roiByTier,
      period: { start: startStr, days },
    })
  } catch (err) {
    console.error('[simulator/backtest] Unexpected error:', err)
    return NextResponse.json({ error: 'Internal server error' }, { status: 500 })
  }
}
