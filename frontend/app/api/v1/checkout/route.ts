// ============================================================
// POST /api/v1/checkout
// Creates a Stripe Checkout Session for Pro or Premium tier.
// ============================================================

import { NextRequest, NextResponse } from 'next/server'
import Stripe from 'stripe'

const stripe = new Stripe(process.env.STRIPE_SECRET_KEY || '', {
  apiVersion: '2025-01-27.acacia',
})

const PRICE_IDS: Record<string, string> = {
  pro: process.env.STRIPE_PRICE_PRO || '',
  premium: process.env.STRIPE_PRICE_PREMIUM || '',
}

export async function POST(req: NextRequest) {
  try {
    const body = await req.json()
    const { tier, email, successUrl, cancelUrl } = body

    if (!tier || !['pro', 'premium'].includes(tier)) {
      return NextResponse.json(
        { error: 'Invalid tier. Must be pro or premium.', code: 'INVALID_TIER', status: 400 },
        { status: 400 }
      )
    }

    const priceId = PRICE_IDS[tier]
    if (!priceId) {
      return NextResponse.json(
        { error: `Stripe price ID not configured for ${tier} tier`, code: 'CONFIG_ERROR', status: 503 },
        { status: 503 }
      )
    }

    const session = await stripe.checkout.sessions.create({
      mode: 'subscription',
      payment_method_types: ['card'],
      customer_email: email || undefined,
      line_items: [{ price: priceId, quantity: 1 }],
      success_url: successUrl || `${process.env.NEXT_PUBLIC_APP_URL}/subscribe/success?session_id={CHECKOUT_SESSION_ID}`,
      cancel_url: cancelUrl || `${process.env.NEXT_PUBLIC_APP_URL}/subscribe`,
      metadata: { tier },
      subscription_data: {
        metadata: { tier },
      },
    })

    return NextResponse.json({ url: session.url, sessionId: session.id })
  } catch (err: unknown) {
    const message = err instanceof Error ? err.message : 'Unknown error'
    return NextResponse.json(
      { error: message, code: 'STRIPE_ERROR', status: 500 },
      { status: 500 }
    )
  }
}
