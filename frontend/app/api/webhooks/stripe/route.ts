// frontend/app/api/webhooks/stripe/route.ts
// ============================================================
// BaselineMLB — Stripe Webhook (Issue #8: 4-tier system)
//
// Maps Stripe price IDs → new tier names and updates
// user_metadata.subscription_tier in Supabase on:
//   - checkout.session.completed
//   - customer.subscription.updated
//   - customer.subscription.deleted
// ============================================================

import { NextRequest, NextResponse } from 'next/server';
import Stripe from 'stripe';
import { createClient } from '@supabase/supabase-js';
import { buildPriceToTierMap, type TierName } from '@/app/lib/tiers';

const stripe = new Stripe(process.env.STRIPE_SECRET_KEY!, {
  apiVersion: '2024-12-18.acacia',
});

const supabaseAdmin = createClient(
  process.env.NEXT_PUBLIC_SUPABASE_URL!,
  process.env.SUPABASE_SERVICE_ROLE_KEY!
);

const webhookSecret = process.env.STRIPE_WEBHOOK_SECRET!;

/** Resolve a Stripe price ID to a BaselineMLB tier name. */
function tierFromPriceId(priceId: string): TierName {
  const priceToTier = buildPriceToTierMap();
  return priceToTier[priceId] ?? 'single_a';
}

/** Update the user's subscription_tier in Supabase auth metadata. */
async function updateUserTier(
  customerId: string,
  tier: TierName,
  stripeSubscriptionId?: string
) {
  // Look up user by stripe_customer_id in user_metadata
  const { data: users, error: listError } =
    await supabaseAdmin.auth.admin.listUsers({ perPage: 1000 });

  if (listError) {
    console.error('Failed to list users:', listError);
    return;
  }

  const user = users.users.find(
    (u) => u.user_metadata?.stripe_customer_id === customerId
  );

  if (!user) {
    console.error(`No user found with stripe_customer_id: ${customerId}`);
    return;
  }

  const { error: updateError } =
    await supabaseAdmin.auth.admin.updateUserById(user.id, {
      user_metadata: {
        subscription_tier: tier,
        stripe_subscription_id: stripeSubscriptionId ?? user.user_metadata?.stripe_subscription_id,
        tier_updated_at: new Date().toISOString(),
      },
    });

  if (updateError) {
    console.error(`Failed to update tier for user ${user.id}:`, updateError);
  } else {
    console.log(`Updated user ${user.id} to tier: ${tier}`);
  }
}

export async function POST(request: NextRequest) {
  const body = await request.text();
  const sig = request.headers.get('stripe-signature');

  if (!sig) {
    return NextResponse.json(
      { error: 'Missing stripe-signature header' },
      { status: 400 }
    );
  }

  let event: Stripe.Event;

  try {
    event = stripe.webhooks.constructEvent(body, sig, webhookSecret);
  } catch (err) {
    const message = err instanceof Error ? err.message : 'Unknown error';
    console.error(`Webhook signature verification failed: ${message}`);
    return NextResponse.json(
      { error: `Webhook Error: ${message}` },
      { status: 400 }
    );
  }

  try {
    switch (event.type) {
      // ---- Checkout completed ----
      case 'checkout.session.completed': {
        const session = event.data.object as Stripe.Checkout.Session;
        const customerId = session.customer as string;
        const subscriptionId = session.subscription as string;

        if (subscriptionId) {
          // Fetch the subscription to get the price ID
          const subscription =
            await stripe.subscriptions.retrieve(subscriptionId);
          const priceId = subscription.items.data[0]?.price.id;

          if (priceId) {
            const tier = tierFromPriceId(priceId);
            await updateUserTier(customerId, tier, subscriptionId);
          }
        }
        break;
      }

      // ---- Subscription updated (upgrade/downgrade/renewal) ----
      case 'customer.subscription.updated': {
        const subscription = event.data.object as Stripe.Subscription;
        const customerId = subscription.customer as string;
        const priceId = subscription.items.data[0]?.price.id;

        if (priceId && subscription.status === 'active') {
          const tier = tierFromPriceId(priceId);
          await updateUserTier(customerId, tier, subscription.id);
        }
        break;
      }

      // ---- Subscription cancelled/expired ----
      case 'customer.subscription.deleted': {
        const subscription = event.data.object as Stripe.Subscription;
        const customerId = subscription.customer as string;

        // Downgrade to free tier
        await updateUserTier(customerId, 'single_a');
        break;
      }

      // ---- Invoice payment failed ----
      case 'invoice.payment_failed': {
        const invoice = event.data.object as Stripe.Invoice;
        const customerId = invoice.customer as string;
        console.warn(
          `Payment failed for customer ${customerId}, subscription ${invoice.subscription}`
        );
        // Don't immediately downgrade — Stripe will retry.
        // After final retry failure, subscription.deleted fires.
        break;
      }

      default:
        // Unhandled event type — log and acknowledge
        console.log(`Unhandled event type: ${event.type}`);
    }
  } catch (err) {
    console.error(`Error processing webhook event ${event.type}:`, err);
    return NextResponse.json(
      { error: 'Webhook handler failed' },
      { status: 500 }
    );
  }

  return NextResponse.json({ received: true });
}
