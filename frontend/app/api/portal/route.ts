// ============================================================
// POST /api/portal
// Creates a Stripe Customer Portal session so users can manage
// their subscription (cancel, change plan, update payment).
// ============================================================

import { NextRequest, NextResponse } from 'next/server'
import Stripe from 'stripe'
import { createClient } from '@supabase/supabase-js'

// Lazy-init Stripe to avoid build-time crash
let _stripe: Stripe | null = null
function getStripe(): Stripe {
  if (!_stripe) {
    const key = process.env.STRIPE_SECRET_KEY
    if (!key) throw new Error('STRIPE_SECRET_KEY is not configured')
    _stripe = new Stripe(key, { apiVersion: '2025-01-27.acacia' as any })
  }
  return _stripe
}

export async function POST(req: NextRequest) {
  try {
    const body = await req.json()
    const { access_token } = body

    // -- Authenticate via Supabase
    if (!access_token) {
      return NextResponse.json(
        { error: 'Authentication required. Please sign in.', code: 'AUTH_REQUIRED' },
        { status: 401 }
      )
    }

    const supabase = createClient(
      process.env.NEXT_PUBLIC_SUPABASE_URL || '',
      process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY || '',
      { global: { headers: { Authorization: `Bearer ${access_token}` } } }
    )

    const { data: { user }, error: authError } = await supabase.auth.getUser()
    if (authError || !user) {
      return NextResponse.json(
        { error: 'Invalid session. Please sign in again.', code: 'INVALID_SESSION' },
        { status: 401 }
      )
    }

    // -- Get Stripe customer ID from user metadata
    const customerId = (user as any).user_metadata?.stripe_customer_id
    if (!customerId) {
      return NextResponse.json(
        { error: 'No subscription found. Subscribe first.', code: 'NO_SUBSCRIPTION' },
        { status: 404 }
      )
    }

    // -- Create Customer Portal Session
    const stripe = getStripe()
    const appUrl = process.env.NEXT_PUBLIC_APP_URL || 'https://baselinemlb.vercel.app'

    const portalSession = await stripe.billingPortal.sessions.create({
      customer: customerId,
      return_url: `${appUrl}/best-bets`,
    })

    return NextResponse.json({ url: portalSession.url })
  } catch (err: unknown) {
    const message = err instanceof Error ? err.message : 'Unknown error'
    console.error('[portal] Error:', message)
    return NextResponse.json(
      { error: message, code: 'PORTAL_ERROR' },
      { status: 500 }
    )
  }
}
