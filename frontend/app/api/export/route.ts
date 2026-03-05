// frontend/app/api/export/route.ts
// ============================================================
// BaselineMLB — CSV Export API (Issue #8)
//
// POST /api/export
// Body: { export_type: string, filters?: Record<string, string> }
// Auth: Supabase access token in Authorization header
//
// Tier gating:
//   single_a  → 403
//   double_a  → 3/week, best_bets only, no SHAP/prob/Kelly
//   triple_a  → unlimited, all types, full columns
//   the_show  → unlimited, all types + historical, full columns
// ============================================================

import { NextRequest, NextResponse } from 'next/server';
import { createClient } from '@supabase/supabase-js';
import {
  normalizeTier,
  EXPORT_LIMITS,
  type TierName,
  type ExportType,
} from '@/app/lib/tiers';

const supabaseUrl = process.env.NEXT_PUBLIC_SUPABASE_URL!;
const supabaseServiceKey = process.env.SUPABASE_SERVICE_ROLE_KEY!;

export async function POST(request: NextRequest) {
  try {
    // ---- 1. Authenticate ----
    const authHeader = request.headers.get('authorization');
    if (!authHeader?.startsWith('Bearer ')) {
      return NextResponse.json(
        { error: 'Missing or invalid authorization header' },
        { status: 401 }
      );
    }
    const accessToken = authHeader.replace('Bearer ', '');

    // Create a Supabase client with the user's token for auth
    const supabaseAuth = createClient(
      supabaseUrl,
      process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!,
      { global: { headers: { Authorization: `Bearer ${accessToken}` } } }
    );

    const {
      data: { user },
      error: authError,
    } = await supabaseAuth.auth.getUser(accessToken);

    if (authError || !user) {
      return NextResponse.json(
        { error: 'Invalid or expired token' },
        { status: 401 }
      );
    }

    // ---- 2. Determine tier ----
    const tier: TierName = normalizeTier(
      user.user_metadata?.subscription_tier
    );
    const limits = EXPORT_LIMITS[tier];

    // ---- 3. Parse request body ----
    const body = await request.json().catch(() => ({}));
    const exportType = body.export_type as ExportType | undefined;

    if (!exportType) {
      return NextResponse.json(
        { error: 'export_type is required' },
        { status: 400 }
      );
    }

    // ---- 4. Check tier allows any exports ----
    if (limits.max_per_week === 0 || limits.allowed_types.length === 0) {
      return NextResponse.json(
        {
          error: 'CSV exports require a Double-A subscription or higher.',
          upgrade_url: '/pricing',
        },
        { status: 403 }
      );
    }

    // ---- 5. Check export type is allowed for this tier ----
    if (!limits.allowed_types.includes(exportType)) {
      const requiredTier =
        exportType === 'historical' ? 'The Show' : 'Triple-A';
      return NextResponse.json(
        {
          error: `${exportType} exports require a ${requiredTier} subscription.`,
          upgrade_url: '/pricing',
        },
        { status: 403 }
      );
    }

    // ---- 6. Check weekly limit (Double-A only) ----
    const supabaseAdmin = createClient(supabaseUrl, supabaseServiceKey);

    if (limits.max_per_week !== null) {
      const oneWeekAgo = new Date();
      oneWeekAgo.setDate(oneWeekAgo.getDate() - 7);

      const { count, error: countError } = await supabaseAdmin
        .from('csv_exports')
        .select('*', { count: 'exact', head: true })
        .eq('user_id', user.id)
        .gte('created_at', oneWeekAgo.toISOString());

      if (countError) {
        console.error('Error checking export count:', countError);
        return NextResponse.json(
          { error: 'Failed to check export limits' },
          { status: 500 }
        );
      }

      const usedThisWeek = count ?? 0;
      if (usedThisWeek >= limits.max_per_week) {
        return NextResponse.json(
          {
            error: `You've used all ${limits.max_per_week} CSV exports this week. Resets in 7 days, or upgrade to Triple-A for unlimited exports.`,
            exports_used: usedThisWeek,
            exports_limit: limits.max_per_week,
            upgrade_url: '/pricing',
          },
          { status: 429 }
        );
      }
    }

    // ---- 7. Fetch data based on export type ----
    let rows: Record<string, unknown>[] = [];
    let columns: string[] = [];

    switch (exportType) {
      case 'best_bets': {
        const { data, error } = await supabaseAdmin
          .from('daily_best_bets')
          .select('*')
          .order('edge_pct', { ascending: false });

        if (error) throw error;
        rows = data ?? [];

        // Column filtering based on tier
        if (limits.include_shap) {
          columns = [
            'player',
            'prop_type',
            'direction',
            'grade',
            'edge_pct',
            'line',
            'book',
            'sim_mean',
            'prob_over',
            'prob_under',
            'kelly_fraction',
            'park_factor',
            'umpire_k_rate',
            'catcher_framing',
            'weather_adj',
            'platoon_split',
            'shap_park',
            'shap_umpire',
            'shap_framing',
            'shap_weather',
            'shap_platoon',
            'shap_base_matchup',
          ];
        } else {
          // Double-A: stripped columns
          columns = [
            'player',
            'prop_type',
            'direction',
            'grade',
            'edge_pct',
            'line',
          ];
        }
        break;
      }

      case 'edges': {
        const { data, error } = await supabaseAdmin
          .from('daily_edges')
          .select('*')
          .order('edge_pct', { ascending: false });

        if (error) throw error;
        rows = data ?? [];
        columns = [
          'player',
          'prop_type',
          'direction',
          'edge_pct',
          'line',
          'book',
          'sim_mean',
          'prob_over',
          'prob_under',
          'kelly_fraction',
          'confidence_tier',
          'park_factor',
          'umpire_k_rate',
          'catcher_framing',
          'shap_park',
          'shap_umpire',
          'shap_framing',
          'shap_weather',
          'shap_platoon',
          'shap_base_matchup',
        ];
        break;
      }

      case 'projections': {
        const { data, error } = await supabaseAdmin
          .from('daily_projections')
          .select('*')
          .order('game_date', { ascending: true });

        if (error) throw error;
        rows = data ?? [];
        columns = [
          'player',
          'team',
          'opponent',
          'prop_type',
          'sim_mean',
          'sim_median',
          'sim_std',
          'prob_over',
          'prob_under',
          'park_factor',
          'umpire_k_rate',
          'catcher_framing',
          'weather_adj',
        ];
        break;
      }

      case 'players': {
        const { data, error } = await supabaseAdmin
          .from('player_projections')
          .select('*')
          .order('player_name', { ascending: true });

        if (error) throw error;
        rows = data ?? [];
        columns = [
          'player_name',
          'team',
          'position',
          'prop_type',
          'season_avg',
          'last_7',
          'last_30',
          'sim_mean',
          'matchup_grade',
        ];
        break;
      }

      case 'historical': {
        const { data, error } = await supabaseAdmin
          .from('graded_predictions')
          .select('*')
          .order('game_date', { ascending: false })
          .limit(5000);

        if (error) throw error;
        rows = data ?? [];
        columns = [
          'game_date',
          'player',
          'prop_type',
          'direction',
          'line',
          'projected',
          'actual',
          'result',
          'edge_pct',
          'confidence_tier',
        ];
        break;
      }

      default:
        return NextResponse.json(
          { error: `Unknown export type: ${exportType}` },
          { status: 400 }
        );
    }

    // ---- 8. Generate CSV ----
    const csvHeader = columns.join(',');
    const csvRows = rows.map((row) =>
      columns
        .map((col) => {
          const val = row[col];
          if (val === null || val === undefined) return '';
          const str = String(val);
          // Escape values containing commas, quotes, or newlines
          if (str.includes(',') || str.includes('"') || str.includes('\n')) {
            return `"${str.replace(/"/g, '""')}"`;
          }
          return str;
        })
        .join(',')
    );
    const csv = [csvHeader, ...csvRows].join('\n');

    // ---- 9. Log export ----
    const { error: logError } = await supabaseAdmin
      .from('csv_exports')
      .insert({
        user_id: user.id,
        export_type: exportType,
        row_count: rows.length,
      });

    if (logError) {
      console.error('Failed to log CSV export:', logError);
      // Non-blocking — still return the CSV
    }

    // ---- 10. Return CSV file ----
    const today = new Date().toISOString().slice(0, 10);
    const filename = `baselinemlb_${exportType}_${today}.csv`;

    return new NextResponse(csv, {
      status: 200,
      headers: {
        'Content-Type': 'text/csv; charset=utf-8',
        'Content-Disposition': `attachment; filename="${filename}"`,
        'Cache-Control': 'no-store',
      },
    });
  } catch (err) {
    console.error('Export API error:', err);
    return NextResponse.json(
      { error: 'Internal server error' },
      { status: 500 }
    );
  }
}

// Also support GET for checking remaining exports
export async function GET(request: NextRequest) {
  try {
    const authHeader = request.headers.get('authorization');
    if (!authHeader?.startsWith('Bearer ')) {
      return NextResponse.json(
        { error: 'Missing authorization' },
        { status: 401 }
      );
    }
    const accessToken = authHeader.replace('Bearer ', '');

    const supabaseAuth = createClient(
      supabaseUrl,
      process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!,
      { global: { headers: { Authorization: `Bearer ${accessToken}` } } }
    );

    const {
      data: { user },
    } = await supabaseAuth.auth.getUser(accessToken);
    if (!user) {
      return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
    }

    const tier: TierName = normalizeTier(
      user.user_metadata?.subscription_tier
    );
    const limits = EXPORT_LIMITS[tier];

    if (limits.max_per_week === null) {
      return NextResponse.json({
        tier,
        exports_used: null,
        exports_limit: null,
        unlimited: true,
        allowed_types: limits.allowed_types,
      });
    }

    if (limits.max_per_week === 0) {
      return NextResponse.json({
        tier,
        exports_used: 0,
        exports_limit: 0,
        unlimited: false,
        allowed_types: [],
      });
    }

    const supabaseAdmin = createClient(supabaseUrl, supabaseServiceKey);
    const oneWeekAgo = new Date();
    oneWeekAgo.setDate(oneWeekAgo.getDate() - 7);

    const { count } = await supabaseAdmin
      .from('csv_exports')
      .select('*', { count: 'exact', head: true })
      .eq('user_id', user.id)
      .gte('created_at', oneWeekAgo.toISOString());

    return NextResponse.json({
      tier,
      exports_used: count ?? 0,
      exports_limit: limits.max_per_week,
      exports_remaining: Math.max(0, limits.max_per_week - (count ?? 0)),
      unlimited: false,
      allowed_types: limits.allowed_types,
    });
  } catch {
    return NextResponse.json(
      { error: 'Internal server error' },
      { status: 500 }
    );
  }
}
