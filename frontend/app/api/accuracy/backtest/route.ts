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

    // 1. Fetch aggregated backtest summary by prop type
    const { data: backtestSummary, error: bsError } = await supabase
      .rpc('get_backtest_summary')

    if (bsError) {
      console.error('[accuracy/backtest] RPC error, falling back to direct query:', bsError.message)
    }

    // 2. Fetch daily backtest_results for charts (all dates)
    const { data: dailyResults, error: drError } = await supabase
      .from('backtest_results')
      .select('date, prop_type, total_predictions, correct_predictions, accuracy_pct, profit_loss, roi_pct, avg_edge, tier_a_roi, tier_b_roi, tier_c_roi')
      .order('date', { ascending: true })

    if (drError) {
      console.error('[accuracy/backtest] daily results error:', drError.message)
    }

    // 3. Fallback: compute summary from daily rows if RPC is not available
    let summary = backtestSummary
    if (!summary || summary.length === 0) {
      if (dailyResults && dailyResults.length > 0) {
        const byType: Record<string, any> = {}
        for (const row of dailyResults) {
          if (row.prop_type === 'ALL') continue
          if (!byType[row.prop_type]) {
            byType[row.prop_type] = {
              prop_type: row.prop_type,
              total_predictions: 0,
              correct_predictions: 0,
              total_profit_loss: 0,
              avg_edge_sum: 0,
              tier_a_sum: 0,
              tier_b_sum: 0,
              tier_c_sum: 0,
              count: 0,
              first_date: row.date,
              last_date: row.date,
            }
          }
          const b = byType[row.prop_type]
          b.total_predictions += row.total_predictions || 0
          b.correct_predictions += row.correct_predictions || 0
          b.total_profit_loss += row.profit_loss || 0
          b.avg_edge_sum += row.avg_edge || 0
          b.tier_a_sum += row.tier_a_roi || 0
          b.tier_b_sum += row.tier_b_roi || 0
          b.tier_c_sum += row.tier_c_roi || 0
          b.count += 1
          if (row.date < b.first_date) b.first_date = row.date
          if (row.date > b.last_date) b.last_date = row.date
        }

        summary = Object.values(byType).map((b: any) => ({
          prop_type: b.prop_type,
          total_predictions: b.total_predictions,
          correct_predictions: b.correct_predictions,
          accuracy_pct: b.total_predictions > 0
            ? parseFloat(((b.correct_predictions / b.total_predictions) * 100).toFixed(1))
            : 0,
          avg_roi_pct: b.count > 0 ? parseFloat(((b.total_profit_loss / Math.max(b.total_predictions, 1)) * 100).toFixed(1)) : 0,
          avg_edge: b.count > 0 ? parseFloat((b.avg_edge_sum / b.count).toFixed(4)) : 0,
          avg_tier_a_roi: b.count > 0 ? parseFloat((b.tier_a_sum / b.count).toFixed(1)) : 0,
          avg_tier_b_roi: b.count > 0 ? parseFloat((b.tier_b_sum / b.count).toFixed(1)) : 0,
          avg_tier_c_roi: b.count > 0 ? parseFloat((b.tier_c_sum / b.count).toFixed(1)) : 0,
          total_profit_loss: parseFloat(b.total_profit_loss.toFixed(2)),
          days_tested: b.count,
          first_date: b.first_date,
          last_date: b.last_date,
        }))
      }
    }

    // 4. Build cumulative P/L timeline from daily ALL rows
    const plTimeline: { date: string; dailyPL: number; cumulativePL: number }[] = []
    let cumulativePL = 0
    if (dailyResults) {
      const allRows = dailyResults
        .filter((r: any) => r.prop_type === 'ALL')
        .sort((a: any, b: any) => a.date.localeCompare(b.date))
      for (const row of allRows) {
        cumulativePL += row.profit_loss || 0
        plTimeline.push({
          date: row.date,
          dailyPL: row.profit_loss || 0,
          cumulativePL: Math.round(cumulativePL * 100) / 100,
        })
      }
    }

    // 5. Build daily accuracy by prop type (for chart)
    const dailyAccuracy: Record<string, { date: string; accuracy: number }[]> = {}
    if (dailyResults) {
      for (const row of dailyResults) {
        if (row.prop_type === 'ALL') continue
        if (!dailyAccuracy[row.prop_type]) dailyAccuracy[row.prop_type] = []
        dailyAccuracy[row.prop_type].push({
          date: row.date,
          accuracy: row.accuracy_pct || 0,
        })
      }
    }

    return NextResponse.json({
      summary: summary || [],
      dailyResults: dailyResults || [],
      plTimeline,
      dailyAccuracy,
    })
  } catch (err) {
    console.error('[accuracy/backtest] Unexpected error:', err)
    return NextResponse.json({ error: 'Internal server error' }, { status: 500 })
  }
}
