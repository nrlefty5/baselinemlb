// ============================================================
// BaselineMLB — Shared TypeScript Types for API Layer
// ============================================================

// ── Subscription Tiers ──────────────────────────────────────────────
export type SubscriptionTier = 'free' | 'pro' | 'premium'

export interface Subscription {
  id: number
  email: string
  stripe_customer_id?: string
  stripe_subscription_id?: string
  tier: SubscriptionTier
  status: 'active' | 'canceled' | 'past_due'
  current_period_start?: string
  current_period_end?: string
  created_at: string
  updated_at: string
}

// ── API Keys ────────────────────────────────────────────────────────
export interface ApiKey {
  id: number
  key_hash: string
  key_prefix: string
  email: string
  tier: SubscriptionTier
  name: string
  requests_today: number
  last_request_at?: string
  active: boolean
  created_at: string
}

// ── Rate Limit Config ───────────────────────────────────────────────
export const RATE_LIMITS: Record<SubscriptionTier, { requests_per_hour: number; requests_per_day: number }> = {
  free:    { requests_per_hour: 20,   requests_per_day: 100   },
  pro:     { requests_per_hour: 200,  requests_per_day: 2000  },
  premium: { requests_per_hour: 1000, requests_per_day: 10000 },
}

// ── Tier Capabilities ───────────────────────────────────────────────
export const TIER_CAPS: Record<SubscriptionTier, {
  max_edges: number | null          // null = unlimited
  show_distributions: boolean
  show_shap: boolean
  show_kelly: boolean
  api_access: boolean
  export_csv: boolean
  custom_alerts: boolean
  email_alerts: boolean
}> = {
  free: {
    max_edges: 3,
    show_distributions: false,
    show_shap: false,
    show_kelly: false,
    api_access: false,
    export_csv: false,
    custom_alerts: false,
    email_alerts: false,
  },
  pro: {
    max_edges: null,
    show_distributions: true,
    show_shap: true,
    show_kelly: true,
    api_access: false,
    export_csv: false,
    custom_alerts: false,
    email_alerts: true,
  },
  premium: {
    max_edges: null,
    show_distributions: true,
    show_shap: true,
    show_kelly: true,
    api_access: true,
    export_csv: true,
    custom_alerts: true,
    email_alerts: true,
  },
}

// ── Edge / Pick ─────────────────────────────────────────────────────
export interface Edge {
  id: number
  game_date: string
  game_pk?: number
  player_name: string
  mlbam_id?: number
  stat_type: string
  line: number
  projection: number
  edge: number
  direction: string
  grade: string
  confidence?: number
  result?: string
  actual_value?: number
}

export interface EdgeWithDistribution extends Edge {
  distribution?: {
    mean: number
    std: number
    percentiles: Record<string, number>   // p10, p25, p50, p75, p90
    over_probability: number
    under_probability: number
  }
  shap_factors?: Record<string, number>   // feature → SHAP contribution
  kelly_fraction?: number
  kelly_unit_size?: number
}

// ── Player History ──────────────────────────────────────────────────
export interface PlayerPrediction {
  game_date: string
  stat_type: string
  line: number
  projection: number
  edge: number
  direction: string
  grade: string
  result?: 'hit' | 'miss' | 'push' | null
  actual_value?: number
}

export interface PlayerHistory {
  mlbam_id: number
  player_name: string
  total_predictions: number
  hits: number
  misses: number
  pushes: number
  hit_rate: number
  avg_edge: number
  predictions: PlayerPrediction[]
}

// ── Backtest / Accuracy ─────────────────────────────────────────────
export interface AccuracySummary {
  period: string
  stat_type?: string
  total_picks: number
  hits: number
  misses: number
  pushes: number
  hit_rate: number
  avg_edge: number
}

export interface BacktestSummary {
  model_version: string
  updated_at: string
  overall: AccuracySummary
  by_stat_type: AccuracySummary[]
  by_grade: AccuracySummary[]
}

// ── API Status ──────────────────────────────────────────────────────
export interface ApiStatus {
  status: 'healthy' | 'degraded' | 'down'
  model_version: string
  last_simulation_run: string
  games_today: number
  edges_today: number
  uptime: string
  database: 'connected' | 'error'
}

// ── Newsletter Digest ───────────────────────────────────────────────
export interface NewsletterDigest {
  id: number
  game_date: string
  subject: string
  edges: Edge[]
  results?: {
    total: number
    hits: number
    misses: number
    pushes: number
    hit_rate: number
    details: Array<{
      player_name: string
      stat_type: string
      line: number
      projection: number
      direction: string
      actual_value: number
      result: 'hit' | 'miss' | 'push'
    }>
  }
  sent_at?: string
  recipient_count: number
}

// ── API Response Wrappers ───────────────────────────────────────────
export interface ApiResponse<T> {
  data: T
  meta: {
    tier: SubscriptionTier
    timestamp: string
    cached?: boolean
  }
}

export interface ApiError {
  error: string
  code: string
  status: number
}
