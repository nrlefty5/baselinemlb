// ============================================================
// POST /api/webhooks/stripe
// Handles Stripe webhook events:
//   - checkout.session.completed
//   - customer.subscription.updated
//   - customer.subscription.deleted
//   - invoice.payment_failed
//
// Updates Supabase auth.users metadata with:
//   subscription_tier ('free' | 'pro')
//   stripe_customer_id
// ============================================================

import { NextRequest, NextResponse } from 'next/server'
import Stripe from 'stripe'
import { createClient } from '@supabase/supabase-js'

const stripe = new Stripe(process.env.STRIPE_SECRET_KEY || '', {
  apiVersion: '2025-01-27.acacia' as any,
})

// Service role client — bypasses RLS, can update auth.users
const supabaseAdmin = createClient(
  process.env.NEXT_PUBLIC_SUPABASE_URL || '',
  process.env.SUPABASE_SERVICE_ROLE_KEY || '',
  { auth: { autoRefreshToken: false, persistSession: false } }
)

// ── Helpers ──────────────────────────────────────────────────────

function tierFromSubscription(sub: Stripe.Subscription): 'free' | 'pro' {
  const status = sub.status
  if (status === 'active' || status === 'trialing') return 'pro'
  return 'free'
}

async function updateUserMetadata(
  userId: string,
  metadata: Record<string, unknown>
) {
  const { error } = await supabaseAdmin.auth.admin.updateUserById(userId, {
    user_metadata: metadata,
  })
  if (error) {
    console.error(`[stripe-webhook] Failed to update user ${userId} metadata:`, error.message)
    throw error
  }
  console.log(`[stripe-webhook] Updated user ${userId} metadata:`, JSON.stringify(metadata))
}

async function findUserByStripeCustomerId(customerId: string): Promise<string | null> {
  // List all users and find the one with matching stripe_customer_id
  // For production scale, you'd use a lookup table — this works for <10K users
  const { data, error } = await supabaseAdmin.auth.admin.listUsers({ perPage: 1000 })
  if (error) {
    console.error('[stripe-webhook] Failed to list users:', error.message)
    return null
  }
  const user = data.users.find(u => u.user_metadata?.stripe_customer_id === customerId)
  return user?.id || null
}

// ── Webhook Handler ─────────────────────────────────────────────

export async function POST(req: NextRequest) {
  const body = await req.text()
  const signature = req.headers.get('stripe-signature')

  if (!signature) {
    console.error('[stripe-webhook] Missing stripe-signature header')
    return NextResponse.json(
      { error: 'Missing stripe-signature header' },
      { status: 400 }
    )
  }

  const webhookSecret = process.env.STRIPE_WEBHOOK_SECRET
  if (!webhookSecret) {
    console.error('[stripe-webhook] STRIPE_WEBHOOK_SECRET is not set')
    return NextResponse.json(
      { error: 'Webhook secret not configured' },
      { status: 500 }
    )
  }

  let event: Stripe.Event

  try {
    event = stripe.webhooks.constructEvent(body, signature, webhookSecret)
  } catch (err: unknown) {
    const message = err instanceof Error ? err.message : 'Unknown error'
    console.error('[stripe-webhook] Signature verification failed:', message)
    return NextResponse.json(
      { error: `Webhook signature verification failed: ${message}` },
      { status: 400 }
    )
  }

  console.log(`[stripe-webhook] Received event: ${event.type} (${event.id})`)

  try {
    switch (event.type) {
      // ────────────────────────────────────────────────────────────
      // checkout.session.completed
      // Customer just finished a Checkout Session.
      // Set subscription_tier = 'pro' and store stripe_customer_id.
      // ────────────────────────────────────────────────────────────
      case 'checkout.session.completed': {
        const session = event.data.object as Stripe.Checkout.Session

        const userId = session.metadata?.supabase_user_id
        if (!userId) {
          console.error('[stripe-webhook] checkout.session.completed: missing supabase_user_id in metadata')
          break
        }

        const customerId =
          typeof session.customer === 'string'
            ? session.customer
            : session.customer?.id || null

        await updateUserMetadata(userId, {
          subscription_tier: 'pro',
          stripe_customer_id: customerId,
        })

        console.log(`[stripe-webhook] Activated pro for user ${userId}`)
        break
      }

      // ────────────────────────────────────────────────────────────
      // customer.subscription.updated
      // Subscription changed — upgrade, downgrade, renewal, etc.
      // Re-derive the tier from the subscription status.
      // ────────────────────────────────────────────────────────────
      case 'customer.subscription.updated': {
        const sub = event.data.object as Stripe.Subscription

        const userId = sub.metadata?.supabase_user_id
        const customerId =
          typeof sub.customer === 'string' ? sub.customer : sub.customer.id

        // Try metadata first, then look up by stripe_customer_id
        let targetUserId = userId
        if (!targetUserId) {
          targetUserId = await findUserByStripeCustomerId(customerId)
        }

        if (!targetUserId) {
          console.error(`[stripe-webhook] subscription.updated: cannot find user for customer ${customerId}`)
          break
        }

        const tier = tierFromSubscription(sub)

        await updateUserMetadata(targetUserId, {
          subscription_tier: tier,
          stripe_customer_id: customerId,
        })

        console.log(`[stripe-webhook] Updated user ${targetUserId} to tier=${tier}`)
        break
      }

      // ────────────────────────────────────────────────────────────
      // customer.subscription.deleted
      // Subscription canceled or expired. Reset to free.
      // ────────────────────────────────────────────────────────────
      case 'customer.subscription.deleted': {
        const sub = event.data.object as Stripe.Subscription
        const customerId =
          typeof sub.customer === 'string' ? sub.customer : sub.customer.id

        const userId =
          sub.metadata?.supabase_user_id ||
          (await findUserByStripeCustomerId(customerId))

        if (!userId) {
          console.error(`[stripe-webhook] subscription.deleted: cannot find user for customer ${customerId}`)
          break
        }

        await updateUserMetadata(userId, {
          subscription_tier: 'free',
          stripe_customer_id: customerId,
        })

        console.log(`[stripe-webhook] Downgraded user ${userId} to free (subscription deleted)`)
        break
      }

      // ────────────────────────────────────────────────────────────
      // invoice.payment_failed
      // Payment failed — downgrade to free until resolved.
      // ────────────────────────────────────────────────────────────
      case 'invoice.payment_failed': {
        const invoice = event.data.object as Stripe.Invoice
        const customerId =
          typeof invoice.customer === 'string'
            ? invoice.customer
            : invoice.customer?.id || null

        if (!customerId) {
          console.error('[stripe-webhook] invoice.payment_failed: missing customer ID')
          break
        }

        const userId = await findUserByStripeCustomerId(customerId)
        if (userId) {
          await updateUserMetadata(userId, {
            subscription_tier: 'free',
          })
          console.log(`[stripe-webhook] Set user ${userId} to free due to payment failure`)
        }
        break
      }

      default:
        console.log(`[stripe-webhook] Unhandled event type: ${event.type}`)
    }
  } catch (err: unknown) {
    const message = err instanceof Error ? err.message : 'Unknown error'
    console.error(`[stripe-webhook] Error processing ${event.type}:`, message)
    // Return 200 so Stripe doesn't retry on our processing errors
    return NextResponse.json(
      { error: 'Internal processing error', received: true },
      { status: 200 }
    )
  }

  return NextResponse.json({ received: true }, { status: 200 })
}
