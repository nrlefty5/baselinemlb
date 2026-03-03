// ============================================================
// POST /api/checkout
// Creates a Stripe Checkout Session for Pro Monthly or Pro Annual.
// Requires a logged-in Supabase Auth user.
// ============================================================

import { NextRequest, NextResponse } from 'next/server'
import Stripe from 'stripe'
import { createClient } from '@supabase/supabase-js'

// Lazy-init Stripe to avoid build-time crash when env vars are missing
let _stripe: Stripe | null = null
function getStripe(): Stripe {
  if (!_stripe) {
    const key = process.env.STRIPE_SECRET_KEY
    if (!key) {
      throw new Error('STRIPE_SECRET_KEY is not configured')
    }
    _stripe = new Stripe(key, {
      apiVersion: '2025-01-27.acacia' as any,
    })
  }
  return _stripe
}

const PRICE_IDS: Record<string, string> = {
  pro_monthly: process.env.STRIPE_PRO_MONTHLY_PRICE_ID || '',
  pro_annual: process.env.STRIPE_PRO_ANNUAL_PRICE_ID || '',
}

export async function POST(req: NextRequest) {
  try {
    const body = await req.json()
    const { plan, access_token } = body

    // -- Validate plan
    if (!plan || !['pro_monthly', 'pro_annual'].includes(plan)) {
      return NextResponse.json(
        { error: 'Invalid plan. Must be pro_monthly or pro_annual.', code: 'INVALID_PLAN' },
        { status: 400 }
      )
    }

    const priceId = PRICE_IDS[plan]
    if (!priceId) {
      return NextResponse.json(
        { error: `Stripe price ID not configured for ${plan}`, code: 'CONFIG_ERROR' },
        { status: 503 }
      )
    }

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

    // -- Check for existing Stripe customer
    const existingCustomerId = (user as any).user_metadata?.stripe_customer_id
    let customerId: string | undefined
    if (existingCustomerId) {
      customerId = existingCustomerId
    }

    // -- Create Checkout Session
    const stripe = getStripe()
    const appUrl = process.env.NEXT_PUBLIC_APP_URL || 'https://baselinemlb.vercel.app'

    const sessionParams: Stripe.Checkout.SessionCreateParams = {
      mode: 'subscription',
      payment_method_types: ['card'],
      line_items: [{ price: priceId, quantity: 1 }],
      success_url: `${appUrl}/best-bets?checkout=success`,
      cancel_url: `${appUrl}/pricing`,
      metadata: {
        supabase_user_id: user.id,
        plan,
      },
      subscription_data: {
        metadata: {
          supabase_user_id: user.id,
          plan,
        },
      },
    }

    // Attach existing customer or pre-fill email
    if (customerId) {
      sessionParams.customer = customerId
    } else {
      sessionParams.customer_email = user.email
    }

    const session = await stripe.checkout.sessions.create(sessionParams)

    return NextResponse.json({ url: session.url, sessionId: session.id })
  } catch (err: unknown) {
    const message = err instanceof Error ? err.message : 'Unknown error'
    console.error('[checkout] Error:', message)
    return NextResponse.json(
      { error: message, code: 'STRIPE_ERROR' },
      { status: 500 }
    )
  }
}
