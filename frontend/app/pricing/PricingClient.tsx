'use client'

import { useState } from 'react'
import Link from 'next/link'

interface PricingTier {
  name: string
  price: number | null
  period: string
  description: string
  features: string[]
  limitations?: string[]
  cta: string
  tier: 'free' | 'pro' | 'premium'
  highlighted: boolean
  badge?: string
}

const TIERS: PricingTier[] = [
  {
    name: 'Free',
    price: 0,
    period: '',
    description: 'Get started with daily MLB prop analytics',
    features: [
      'Top 3 best bets per day',
      'Grade + direction (Over/Under)',
      'Edge % vs market line',
      'Basic model accuracy page',
      'Daily slate overview',
    ],
    limitations: [
      'No SHAP factor breakdowns',
      'No probability distributions',
      'No Kelly criterion sizing',
    ],
    cta: 'Get Started Free',
    tier: 'free',
    highlighted: false,
  },
  {
    name: 'Pro',
    price: 29,
    period: '/month',
    description: 'Everything you need to bet with an edge',
    features: [
      'All best bets — full slate every day',
      'SHAP feature attribution on every pick',
      'Probability distributions',
      'Kelly criterion position sizing',
      'Daily email digest at 11am ET',
      'Player prediction history (50 games)',
      'Full backtest accuracy data',
      'Calibration chart access',
    ],
    cta: 'Upgrade to Pro',
    tier: 'pro',
    highlighted: true,
    badge: 'Most Popular',
  },
  {
    name: 'Premium',
    price: 49,
    period: '/month',
    description: 'Full API access for power users and builders',
    features: [
      'Everything in Pro',
      'REST API access (1,000 req/hr)',
      'API key management dashboard',
      'CSV export of all picks',
      'Custom alert thresholds',
      'Player history (200 games)',
      'Priority support',
      'Webhook notifications (coming soon)',
    ],
    cta: 'Upgrade to Premium',
    tier: 'premium',
    highlighted: false,
    badge: 'Power Users',
  },
]

const FAQ_ITEMS = [
  {
    q: 'What data sources power the model?',
    a: 'BaselineMLB combines Statcast pitch-level data, MLB Stats API for game/roster info, and The Odds API for real-time prop lines. We run 10,000+ Monte Carlo simulations per game to generate projections.',
  },
  {
    q: 'How are "edges" calculated?',
    a: 'Edge % is the difference between our model\'s projection and the sportsbook\'s prop line, expressed as a percentage of the line. A positive edge means our model projects a higher value than the market.',
  },
  {
    q: 'What are SHAP explanations?',
    a: 'SHAP (SHapley Additive exPlanations) breaks down exactly why each prediction was made — showing how factors like K/9 rate, opponent strikeout tendency, park factor, and umpire tendencies each contribute to the projection. No black boxes.',
  },
  {
    q: 'Can I cancel anytime?',
    a: 'Yes. Cancel anytime from your account page. You\'ll keep access through the end of your current billing period.',
  },
  {
    q: 'When does the 2026 season start?',
    a: 'Opening Day 2026 is March 26. Pre-season backtesting and model validation are available now. Live picks go live on Opening Day.',
  },
]

// ── Feature Comparison Table ─────────────────────────────────────────────
const COMPARISON_ROWS: { label: string; free: string; pro: string; premium: string }[] = [
  { label: 'Daily best bets', free: 'Top 3', pro: 'All picks', premium: 'All picks' },
  { label: 'Edge % display', free: '✓', pro: '✓', premium: '✓' },
  { label: 'Confidence grade', free: '✓', pro: '✓', premium: '✓' },
  { label: 'SHAP explanations', free: '—', pro: '✓', premium: '✓' },
  { label: 'Probability distributions', free: '—', pro: '✓', premium: '✓' },
  { label: 'Kelly criterion sizing', free: '—', pro: '✓', premium: '✓' },
  { label: 'Email digest (11am ET)', free: '—', pro: '✓', premium: '✓' },
  { label: 'Calibration chart', free: 'Basic', pro: 'Full', premium: 'Full' },
  { label: 'Player history', free: '—', pro: '50 games', premium: '200 games' },
  { label: 'REST API access', free: '—', pro: '—', premium: '1,000 req/hr' },
  { label: 'CSV export', free: '—', pro: '—', premium: '✓' },
  { label: 'Custom alerts', free: '—', pro: '—', premium: '✓' },
]

export default function PricingClient() {
  const [loading, setLoading] = useState<string | null>(null)
  const [email, setEmail] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [openFaq, setOpenFaq] = useState<number | null>(null)

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
          cancelUrl: `${window.location.origin}/pricing`,
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
      <div className="max-w-5xl mx-auto px-4 pt-16 pb-10 text-center">
        <h1 className="text-4xl font-bold tracking-tight mb-4">
          Pick the plan that fits your edge
        </h1>
        <p className="text-slate-400 text-lg max-w-xl mx-auto">
          BaselineMLB runs 10,000+ Monte Carlo simulations per game to surface
          statistically significant prop bets. Every plan includes transparent methodology.
        </p>
      </div>

      {/* Email Input */}
      <div className="max-w-md mx-auto px-4 mb-10">
        <label className="block text-sm text-slate-400 mb-2">Email address (for checkout)</label>
        <input
          type="email"
          value={email}
          onChange={e => setEmail(e.target.value)}
          placeholder="you@example.com"
          className="w-full bg-slate-900 border border-slate-700 rounded-lg px-4 py-3 text-slate-100 placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-blue-500 transition-colors"
        />
        {error && (
          <p className="mt-2 text-sm text-red-400">{error}</p>
        )}
      </div>

      {/* Pricing Cards */}
      <div className="max-w-5xl mx-auto px-4 pb-16 grid grid-cols-1 md:grid-cols-3 gap-6">
        {TIERS.map(tier => (
          <div
            key={tier.tier}
            className={`rounded-2xl p-6 border relative ${
              tier.highlighted
                ? 'border-blue-500 bg-blue-950/30 ring-1 ring-blue-500'
                : 'border-slate-700 bg-slate-900'
            }`}
          >
            {tier.badge && (
              <div className={`text-xs font-semibold uppercase tracking-wider mb-3 ${
                tier.highlighted ? 'text-blue-400' : 'text-slate-500'
              }`}>
                {tier.badge}
              </div>
            )}

            <h2 className="text-2xl font-bold">{tier.name}</h2>
            <div className="mt-2 mb-4">
              {tier.price === 0 ? (
                <span className="text-3xl font-bold">Free</span>
              ) : (
                <>
                  <span className="text-3xl font-bold">${tier.price}</span>
                  <span className="text-slate-400 text-sm">{tier.period}</span>
                </>
              )}
            </div>

            <p className="text-slate-400 text-sm mb-6">{tier.description}</p>

            <ul className="space-y-2 mb-4">
              {tier.features.map((f, i) => (
                <li key={i} className="flex items-start gap-2 text-sm">
                  <span className="text-green-400 mt-0.5 shrink-0">&#10003;</span>
                  <span className="text-slate-300">{f}</span>
                </li>
              ))}
            </ul>

            {tier.limitations && (
              <ul className="space-y-1.5 mb-6">
                {tier.limitations.map((l, i) => (
                  <li key={i} className="flex items-start gap-2 text-sm">
                    <span className="text-slate-600 mt-0.5 shrink-0">&times;</span>
                    <span className="text-slate-500">{l}</span>
                  </li>
                ))}
              </ul>
            )}

            {!tier.limitations && <div className="mb-6" />}

            {tier.tier === 'free' ? (
              <Link
                href="/best-bets"
                className="block w-full py-3 rounded-lg bg-slate-700 hover:bg-slate-600 text-slate-300 font-medium text-center transition-colors"
              >
                {tier.cta}
              </Link>
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
                {loading === tier.tier ? 'Redirecting to Stripe...' : tier.cta}
              </button>
            )}
          </div>
        ))}
      </div>

      {/* Feature Comparison Table */}
      <div className="max-w-4xl mx-auto px-4 pb-16">
        <h2 className="text-2xl font-bold text-center mb-8">Feature Comparison</h2>
        <div className="overflow-x-auto rounded-xl border border-slate-700">
          <table className="w-full text-sm">
            <thead>
              <tr className="bg-slate-800 border-b border-slate-700">
                <th className="text-left px-4 py-3 text-xs text-slate-400 uppercase tracking-wider">Feature</th>
                <th className="text-center px-4 py-3 text-xs text-slate-400 uppercase tracking-wider">Free</th>
                <th className="text-center px-4 py-3 text-xs text-blue-400 uppercase tracking-wider font-bold">Pro</th>
                <th className="text-center px-4 py-3 text-xs text-slate-400 uppercase tracking-wider">Premium</th>
              </tr>
            </thead>
            <tbody>
              {COMPARISON_ROWS.map((row, i) => (
                <tr key={i} className="border-b border-slate-700/50 hover:bg-slate-800/30 transition-colors">
                  <td className="px-4 py-3 text-slate-300">{row.label}</td>
                  <td className="px-4 py-3 text-center text-slate-400">{row.free}</td>
                  <td className="px-4 py-3 text-center text-slate-200 font-medium bg-blue-950/10">{row.pro}</td>
                  <td className="px-4 py-3 text-center text-slate-300">{row.premium}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* FAQ Section */}
      <div className="max-w-2xl mx-auto px-4 pb-16">
        <h2 className="text-2xl font-bold text-center mb-8">Frequently Asked Questions</h2>
        <div className="space-y-2">
          {FAQ_ITEMS.map((item, i) => (
            <div key={i} className="border border-slate-700 rounded-lg overflow-hidden">
              <button
                onClick={() => setOpenFaq(openFaq === i ? null : i)}
                className="w-full flex items-center justify-between px-4 py-3 text-left text-slate-200 hover:bg-slate-800/50 transition-colors"
              >
                <span className="text-sm font-medium">{item.q}</span>
                <svg
                  className={`w-4 h-4 text-slate-400 transition-transform ${openFaq === i ? 'rotate-180' : ''}`}
                  fill="none"
                  stroke="currentColor"
                  viewBox="0 0 24 24"
                >
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
                </svg>
              </button>
              {openFaq === i && (
                <div className="px-4 pb-3">
                  <p className="text-sm text-slate-400">{item.a}</p>
                </div>
              )}
            </div>
          ))}
        </div>
      </div>

      {/* Footer CTA */}
      <div className="max-w-2xl mx-auto px-4 pb-20 text-center">
        <p className="text-slate-500 text-sm">
          All plans billed monthly. Cancel anytime. Payments processed securely by Stripe.
        </p>
        <p className="text-slate-600 text-xs mt-2">
          Questions? Reach out at{' '}
          <a href="mailto:support@baselinemlb.com" className="text-blue-400 hover:underline">
            support@baselinemlb.com
          </a>
        </p>
      </div>
    </div>
  )
}
