// ============================================================
// BaselineMLB — Rate Limiting & API Key Authentication
// Middleware for API v1 routes
// ============================================================

import { NextRequest, NextResponse } from 'next/server'
import { createClient } from '@supabase/supabase-js'
import { RATE_LIMITS, type SubscriptionTier, type ApiError } from './types'

const supabaseUrl = process.env.NEXT_PUBLIC_SUPABASE_URL || ''
const supabaseServiceKey = process.env.SUPABASE_SERVICE_ROLE_KEY || ''

// ── Helpers ─────────────────────────────────────────────────────────

function hashKey(key: string): string {
  // Use Web Crypto API (available in Edge Runtime)
  // For synchronous hashing in middleware, we use a simple hash
  let hash = 0
  for (let i = 0; i < key.length; i++) {
    const char = key.charCodeAt(i)
    hash = ((hash << 5) - hash) + char
    hash |= 0
  }
  return Math.abs(hash).toString(36)
}

async function sha256(message: string): Promise<string> {
  const encoder = new TextEncoder()
  const data = encoder.encode(message)
  const hashBuffer = await crypto.subtle.digest('SHA-256', data)
  const hashArray = Array.from(new Uint8Array(hashBuffer))
  return hashArray.map(b => b.toString(16).padStart(2, '0')).join('')
}

function jsonError(error: string, code: string, status: number): NextResponse {
  const body: ApiError = { error, code, status }
  return NextResponse.json(body, { status })
}

function getWindowStart(): string {
  const now = new Date()
  now.setMinutes(0, 0, 0)
  return now.toISOString()
}

// ── IP-Based Rate Limiting (Free / Unauthenticated) ─────────────────

const ipRequestCounts = new Map<string, { count: number; windowStart: number }>()

function checkIpRateLimit(ip: string): { allowed: boolean; remaining: number } {
  const now = Date.now()
  const windowMs = 60 * 60 * 1000 // 1 hour
  const limit = RATE_LIMITS.free.requests_per_hour

  const record = ipRequestCounts.get(ip)

  if (!record || now - record.windowStart > windowMs) {
    ipRequestCounts.set(ip, { count: 1, windowStart: now })
    return { allowed: true, remaining: limit - 1 }
  }

  record.count++
  const remaining = Math.max(0, limit - record.count)
  return { allowed: record.count <= limit, remaining }
}

// Periodically clean up stale entries (every 5 min)
if (typeof setInterval !== 'undefined') {
  setInterval(() => {
    const now = Date.now()
    const windowMs = 60 * 60 * 1000
    for (const [ip, record] of ipRequestCounts.entries()) {
      if (now - record.windowStart > windowMs) {
        ipRequestCounts.delete(ip)
      }
    }
  }, 5 * 60 * 1000)
}

// ── Core Auth & Rate Limit Function ─────────────────────────────────

export interface AuthResult {
  tier: SubscriptionTier
  email?: string
  keyPrefix?: string
}

/**
 * Authenticate and rate-limit an API request.
 *
 * - No API key → free tier with IP-based rate limiting
 * - Valid API key → tier-based rate limiting via Supabase
 * - Invalid key → 401
 * - Rate exceeded → 429
 */
export async function authenticateRequest(
  req: NextRequest
): Promise<{ auth: AuthResult } | { error: NextResponse }> {

  const apiKey = req.headers.get('x-api-key') || req.nextUrl.searchParams.get('api_key')

  // ── No API key → free tier ──────────────────────────────────────
  if (!apiKey) {
    const ip = req.headers.get('x-forwarded-for')?.split(',')[0]?.trim()
      || req.headers.get('x-real-ip')
      || '0.0.0.0'

    const { allowed, remaining } = checkIpRateLimit(ip)

    if (!allowed) {
      const res = jsonError(
        'Rate limit exceeded. Upgrade to Pro for higher limits.',
        'RATE_LIMIT_EXCEEDED',
        429
      )
      res.headers.set('X-RateLimit-Limit', String(RATE_LIMITS.free.requests_per_hour))
      res.headers.set('X-RateLimit-Remaining', '0')
      res.headers.set('Retry-After', '3600')
      return { error: res }
    }

    return {
      auth: { tier: 'free' },
    }
  }

  // ── API key provided → validate ──────────────────────────────────
  if (!supabaseUrl || !supabaseServiceKey) {
    return { error: jsonError('API authentication is not configured', 'AUTH_UNAVAILABLE', 503) }
  }

  const supabase = createClient(supabaseUrl, supabaseServiceKey)
  const keyHash = await sha256(apiKey)

  const { data: keyRecord, error } = await supabase
    .from('api_keys')
    .select('*')
    .eq('key_hash', keyHash)
    .eq('active', true)
    .single()

  if (error || !keyRecord) {
    return { error: jsonError('Invalid or inactive API key', 'INVALID_API_KEY', 401) }
  }

  // Check subscription is active
  const { data: sub } = await supabase
    .from('subscriptions')
    .select('tier, status')
    .eq('email', keyRecord.email)
    .eq('status', 'active')
    .single()

  const tier: SubscriptionTier = (sub?.tier as SubscriptionTier) || keyRecord.tier || 'free'

  // ── Key-based rate limiting ──────────────────────────────────────
  const windowStart = getWindowStart()
  const limits = RATE_LIMITS[tier]

  // Upsert rate limit counter
  const { data: rateRecord } = await supabase
    .from('rate_limits')
    .upsert(
      { key_hash: keyHash, window_start: windowStart, request_count: 1 },
      { onConflict: 'key_hash,window_start' }
    )
    .select('request_count')
    .single()

  if (rateRecord && rateRecord.request_count > limits.requests_per_hour) {
    await supabase.rpc('increment_rate_limit', {
      p_key_hash: keyHash,
      p_window_start: windowStart,
    }).catch(() => {})

    const res = jsonError(
      `Rate limit exceeded (${limits.requests_per_hour}/hour for ${tier} tier). Upgrade for higher limits.`,
      'RATE_LIMIT_EXCEEDED',
      429
    )
    res.headers.set('X-RateLimit-Limit', String(limits.requests_per_hour))
    res.headers.set('X-RateLimit-Remaining', '0')
    res.headers.set('Retry-After', '3600')
    return { error: res }
  }

  // Update last_request_at
  await supabase
    .from('api_keys')
    .update({ last_request_at: new Date().toISOString() })
    .eq('key_hash', keyHash)

  return {
    auth: {
      tier,
      email: keyRecord.email,
      keyPrefix: keyRecord.key_prefix,
    },
  }
}

/**
 * Require a minimum tier for an endpoint.
 * Returns an error response if the tier is insufficient.
 */
export function requireTier(
  auth: AuthResult,
  minTier: SubscriptionTier
): NextResponse | null {
  const tierOrder: SubscriptionTier[] = ['free', 'pro', 'premium']
  const authLevel = tierOrder.indexOf(auth.tier)
  const requiredLevel = tierOrder.indexOf(minTier)

  if (authLevel < requiredLevel) {
    return jsonError(
      `This endpoint requires a ${minTier} subscription. Current tier: ${auth.tier}`,
      'INSUFFICIENT_TIER',
      403
    )
  }

  return null
}
