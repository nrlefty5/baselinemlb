'use client'

// ============================================================
// SubscribeClient — Tier comparison & Stripe checkout flow
// ============================================================

import { useState } from 'react'

interface PricingTier {
  name: string
  price: number | null
  description: string
  features: string[]
  cta: string
  tier: 'free' | 'pro' | 'premium'
  highlighted: boolean
}

const TIERS: PricingTier[] = [
  {
    name: 'Free',
    price: 0,
    description: 'Get started with MLB prop analytics',
    features: [
      'Top 3 edges per day',
      'Grade & direction (Over/Under)',
      'Basic model accuracy stats',
      'Daily slate overview',
    ],
    cta: 'Get Started',
    tier: 'free',
    highlighted: false,
  },
  {
    name: 'Pro',
    price: 29,
    description: 'Everything you need to bet smarter',
    features: [
      'All edges — full slate every day',
      'Probability distributions',
      'SHAP feature attribution',
      'Kelly criterion sizing',
      'Daily email digest at 11am ET',
      'Player prediction history (50 games)',
      'Backtest accuracy by stat type',
    ],
    cta: 'Upgrade to Pro',
    tier: 'pro',
    highlighted: true,
  },
  {
    name: 'Premium',
    price: 49,
    description: 'Full API access for power users',
    features: [
      'Everything in Pro',
      'REST API access (1,000 req/hr)',
      'API key management',
      'CSV export',
      'Custom alert thresholds',
      'Player history (200 games)',
      'Webhook notifications (coming soon)',
    ],
    cta: 'Upgrade to Premium',
    tier: 'premium',
    highlighted: false,
  },
]

export default function SubscribeClient() {
  const [loading, setLoading] = useState<string | null>(null)
  const [email, setEmail] = useState('')
  const [error, setError] = useState<string | null>(null)

  async function handleCheckout(tier: 'pro' | 'premium') {
    if (!email.trim()) {
      setError('Please enter your email address')
      return
    }
    if (!/^[^@]+@[^@]+\.[^@]+$/.test(email)) {
      setError('Please enter a valid email address')
      return
    }

    setError(null)
    setLoading(tier)

    try {
      const res = await fetch('/api/v1/checkout', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          tier,
          email,
          successUrl: `${window.location.origin}/subscribe/success?session_id={CHECKOUT_SESSION_ID}`,
          cancelUrl: `${window.location.origin}/subscribe`,
        }),
      })

      const data = await res.json()

      if (!res.ok || !data.url) {
        throw new Error(data.error || 'Failed to create checkout session')
      }

      window.location.href = data.url
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : 'Something went wrong'
      setError(message)
      setLoading(null)
    }
  }

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100">
      {/* Hero */}
      <div className="max-w-5xl mx-auto px-4 py-16 text-center">
        <h1 className="text-4xl font-bold tracking-tight mb-4">
          Upgrade Your Edge
        </h1>
        <p className="text-slate-400 text-lg max-w-xl mx-auto">
          BaselineMLB runs 10,000+ Monte Carlo simulations per game to surface
          statistically significant prop bets. Choose the plan that fits your workflow.
        </p>
      </div>

      {/* Email Input */}
      <div className="max-w-md mx-auto px-4 mb-10">
        <label className="block text-sm text-slate-400 mb-2">Email address</label>
        <input
          type="email"
          value={email}
          onChange={e => setEmail(e.target.value)}
          placeholder="you@example.com"
          className="w-full bg-slate-900 border border-slate-700 rounded-lg px-4 py-3 text-slate-100 placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-blue-500"
        />
        {error && (
          <p className="mt-2 text-sm text-red-400">{error}</p>
        )}
      </div>

      {/* Pricing Cards */}
      <div className="max-w-5xl mx-auto px-4 pb-20 grid grid-cols-1 md:grid-cols-3 gap-6">
        {TIERS.map(tier => (
          <div
            key={tier.tier}
            className={`rounded-2xl p-6 border ${
              tier.highlighted
                ? 'border-blue-500 bg-blue-950/30 ring-1 ring-blue-500'
                : 'border-slate-700 bg-slate-900'
            }`}
          >
            {tier.highlighted && (
              <div className="text-xs font-semibold text-blue-400 uppercase tracking-wider mb-3">
                Most Popular
              </div>
            )}

            <h2 className="text-2xl font-bold">{tier.name}</h2>
            <div className="mt-2 mb-4">
              {tier.price === 0 ? (
                <span className="text-3xl font-bold">Free</span>
              ) : (
                <>
                  <span className="text-3xl font-bold">${tier.price}</span>
                  <span className="text-slate-400 text-sm">/month</span>
                </>
              )}
            </div>

            <p className="text-slate-400 text-sm mb-6">{tier.description}</p>

            <ul className="space-y-2 mb-8">
              {tier.features.map((f, i) => (
                <li key={i} className="flex items-start gap-2 text-sm">
                  <span className="text-green-400 mt-0.5">✓</span>
                  <span className="text-slate-300">{f}</span>
                </li>
              ))}
            </ul>

            {tier.tier === 'free' ? (
              <button
                disabled
                className="w-full py-3 rounded-lg bg-slate-700 text-slate-400 font-medium cursor-not-allowed"
              >
                Current Plan
              </button>
            ) : (
              <button
                onClick={() => handleCheckout(tier.tier as 'pro' | 'premium')}
                disabled={loading !== null}
                className={`w-full py-3 rounded-lg font-medium transition-colors ${
                  tier.highlighted
                    ? 'bg-blue-600 hover:bg-blue-500 text-white'
                    : 'bg-slate-700 hover:bg-slate-600 text-slate-100'
                } disabled:opacity-50 disabled:cursor-not-allowed`}
              >
                {loading === tier.tier ? 'Redirecting...' : tier.cta}
              </button>
            )}
          </div>
        ))}
      </div>

      {/* FAQ / Guarantee */}
      <div className="max-w-2xl mx-auto px-4 pb-20 text-center">
        <p className="text-slate-500 text-sm">
          All plans billed monthly. Cancel anytime. Payments processed securely by Stripe.
        </p>
      </div>
    </div>
  )
}
