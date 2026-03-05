// frontend/app/(main)/pricing/PricingClient.tsx
// ============================================================
// BaselineMLB — Pricing Page Client Component (Issue #8)
// 4-tier MiLB-themed pricing with CSV export rows
// ============================================================

'use client';

import { useState } from 'react';
import { useRouter } from 'next/navigation';
import { TIER_DISPLAY, type TierName } from '@/app/lib/tiers';
import { getPublicClient } from '@/app/lib/supabase';

export default function PricingClient() {
  const router = useRouter();
    const supabase = getPublicClient();
  const [loading, setLoading] = useState<TierName | null>(null);

  async function handleCheckout(plan: TierName) {
    if (plan === 'single_a') {
      router.push('/signup');
      return;
    }

    setLoading(plan);
    try {
      const {
        data: { session },
      } = await supabase.auth.getSession();

      if (!session) {
        router.push(`/login?redirect=/pricing&plan=${plan}`);
        return;
      }

      const res = await fetch('/api/checkout', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${session.access_token}`,
        },
        body: JSON.stringify({ plan, period: 'monthly' }),
      });

      const data = await res.json();

      if (data.url) {
        window.location.href = data.url;
      } else {
        console.error('Checkout error:', data.error);
        alert(data.error || 'Something went wrong. Please try again.');
      }
    } catch (err) {
      console.error('Checkout error:', err);
      alert('Something went wrong. Please try again.');
    } finally {
      setLoading(null);
    }
  }

  return (
    <div className="min-h-screen bg-gray-950 text-white">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-16">
        {/* Header */}
        <div className="text-center mb-16">
          <h1 className="text-4xl font-bold tracking-tight sm:text-5xl">
            Choose Your Level
          </h1>
          <p className="mt-4 text-lg text-gray-400 max-w-2xl mx-auto">
            From free scouting to big-league analytics. Every tier includes
            glass-box transparency — you always see what drives the projection.
          </p>
        </div>

        {/* Pricing Cards */}
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6 lg:gap-4">
          {TIER_DISPLAY.map((tier) => {
            const isPopular = tier.badge === 'Most Popular';
            const isLoading = loading === tier.id;

            return (
              <div
                key={tier.id}
                className={`relative rounded-2xl border p-6 flex flex-col ${
                  isPopular
                    ? 'border-emerald-500 bg-gray-900 ring-2 ring-emerald-500/50'
                    : 'border-gray-800 bg-gray-900/50'
                }`}
              >
                {/* Badge */}
                {tier.badge && (
                  <div className="absolute -top-3 left-1/2 -translate-x-1/2">
                    <span className="inline-flex items-center rounded-full bg-emerald-500 px-3 py-1 text-xs font-semibold text-white">
                      {tier.badge}
                    </span>
                  </div>
                )}

                {/* Tier name + tagline */}
                <div className="mb-4">
                  <h3 className="text-xl font-bold text-white">{tier.name}</h3>
                  <p className="text-sm text-gray-400 mt-1">{tier.tagline}</p>
                </div>

                {/* Price */}
                <div className="mb-6">
                  {tier.price === 0 ? (
                    <div className="flex items-baseline">
                      <span className="text-4xl font-bold">Free</span>
                    </div>
                  ) : (
                    <div className="flex items-baseline">
                      <span className="text-4xl font-bold">
                        ${tier.price.toFixed(2)}
                      </span>
                      <span className="text-gray-400 ml-1">/mo</span>
                    </div>
                  )}
                </div>

                {/* CTA Button */}
                <button
                  onClick={() => handleCheckout(tier.id)}
                  disabled={isLoading}
                  className={`w-full rounded-lg py-3 px-4 text-sm font-semibold transition-colors mb-6 ${
                    isPopular
                      ? 'bg-emerald-600 hover:bg-emerald-500 text-white'
                      : tier.id === 'the_show'
                      ? 'bg-amber-600 hover:bg-amber-500 text-white'
                      : 'bg-gray-800 hover:bg-gray-700 text-white'
                  } disabled:opacity-50 disabled:cursor-not-allowed`}
                >
                  {isLoading ? 'Loading...' : tier.cta}
                </button>

                {/* Features list */}
                <ul className="space-y-3 flex-1">
                  {tier.features.map((feature, i) => (
                    <li key={i} className="flex items-start text-sm">
                      <svg
                        className="h-4 w-4 text-emerald-400 mr-2 mt-0.5 shrink-0"
                        fill="none"
                        viewBox="0 0 24 24"
                        strokeWidth={2.5}
                        stroke="currentColor"
                      >
                        <path
                          strokeLinecap="round"
                          strokeLinejoin="round"
                          d="M4.5 12.75l6 6 9-13.5"
                        />
                      </svg>
                      <span className="text-gray-300">{feature}</span>
                    </li>
                  ))}
                </ul>

                {/* CSV Export line */}
                <div className="mt-4 pt-4 border-t border-gray-800">
                  <div className="flex items-center text-sm">
                    <svg
                      className={`h-4 w-4 mr-2 shrink-0 ${
                        tier.id === 'single_a'
                          ? 'text-gray-600'
                          : 'text-emerald-400'
                      }`}
                      fill="none"
                      viewBox="0 0 24 24"
                      strokeWidth={2}
                      stroke="currentColor"
                    >
                      <path
                        strokeLinecap="round"
                        strokeLinejoin="round"
                        d="M3 16.5v2.25A2.25 2.25 0 005.25 21h13.5A2.25 2.25 0 0021 18.75V16.5M16.5 12L12 16.5m0 0L7.5 12m4.5 4.5V3"
                      />
                    </svg>
                    <span
                      className={
                        tier.id === 'single_a'
                          ? 'text-gray-500'
                          : 'text-gray-300'
                      }
                    >
                      {tier.csvLine}
                    </span>
                  </div>
                </div>
              </div>
            );
          })}
        </div>

        {/* Feature Comparison Table */}
        <div className="mt-20">
          <h2 className="text-2xl font-bold text-center mb-8">
            Feature Comparison
          </h2>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-gray-800">
                  <th className="text-left py-3 px-4 text-gray-400 font-medium">
                    Feature
                  </th>
                  <th className="text-center py-3 px-4 text-gray-400 font-medium">
                    Single-A
                  </th>
                  <th className="text-center py-3 px-4 text-emerald-400 font-medium">
                    Double-A
                  </th>
                  <th className="text-center py-3 px-4 text-gray-400 font-medium">
                    Triple-A
                  </th>
                  <th className="text-center py-3 px-4 text-amber-400 font-medium">
                    The Show
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-800/50">
                {COMPARISON_ROWS.map((row, i) => (
                  <tr
                    key={i}
                    className="hover:bg-gray-900/50 transition-colors"
                  >
                    <td className="py-3 px-4 text-gray-300">{row.feature}</td>
                    <td className="py-3 px-4 text-center">
                      <CellValue value={row.singleA} />
                    </td>
                    <td className="py-3 px-4 text-center">
                      <CellValue value={row.doubleA} />
                    </td>
                    <td className="py-3 px-4 text-center">
                      <CellValue value={row.tripleA} />
                    </td>
                    <td className="py-3 px-4 text-center">
                      <CellValue value={row.theShow} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>

        {/* FAQ */}
        <div className="mt-20 max-w-3xl mx-auto">
          <h2 className="text-2xl font-bold text-center mb-8">
            Frequently Asked Questions
          </h2>
          <div className="space-y-6">
            {FAQ_ITEMS.map((item, i) => (
              <div key={i} className="border-b border-gray-800 pb-6">
                <h3 className="text-base font-semibold text-white mb-2">
                  {item.q}
                </h3>
                <p className="text-sm text-gray-400 leading-relaxed">
                  {item.a}
                </p>
              </div>
            ))}
          </div>
        </div>

        {/* Footer CTA */}
        <div className="mt-16 text-center">
          <p className="text-gray-500 text-sm">
            All plans include glass-box transparency. Every result graded
            publicly.
          </p>
          <p className="text-gray-600 text-xs mt-2">
            For entertainment purposes only. Not gambling advice. If you or
            someone you know has a gambling problem, call 1-800-GAMBLER. Must be
            21+.
          </p>
        </div>
      </div>
    </div>
  );
}

// ---- Comparison table data ----

type CellVal = boolean | string;

interface ComparisonRow {
  feature: string;
  singleA: CellVal;
  doubleA: CellVal;
  tripleA: CellVal;
  theShow: CellVal;
}

const COMPARISON_ROWS: ComparisonRow[] = [
  {
    feature: 'Daily best bets',
    singleA: 'Top 3',
    doubleA: 'Full slate',
    tripleA: 'Full slate',
    theShow: 'Full slate',
  },
  {
    feature: 'Edge % vs market line',
    singleA: true,
    doubleA: true,
    tripleA: true,
    theShow: true,
  },
  {
    feature: 'Full edges page',
    singleA: false,
    doubleA: true,
    tripleA: true,
    theShow: true,
  },
  {
    feature: 'SHAP explanations',
    singleA: false,
    doubleA: 'Top 3 factors',
    tripleA: 'Full breakdown',
    theShow: 'Full breakdown',
  },
  {
    feature: 'Probability distributions',
    singleA: false,
    doubleA: false,
    tripleA: true,
    theShow: true,
  },
  {
    feature: 'Kelly criterion sizing',
    singleA: false,
    doubleA: false,
    tripleA: true,
    theShow: true,
  },
  {
    feature: 'Game simulator',
    singleA: false,
    doubleA: false,
    tripleA: true,
    theShow: true,
  },
  {
    feature: 'Player history depth',
    singleA: '7 days',
    doubleA: '14 days',
    tripleA: '50 games',
    theShow: '200 games',
  },
  {
    feature: 'Backtest accuracy & calibration',
    singleA: 'Basic',
    doubleA: 'Basic',
    tripleA: 'Full',
    theShow: 'Full',
  },
  {
    feature: 'CSV exports',
    singleA: false,
    doubleA: '3/week (best bets)',
    tripleA: 'Unlimited (all data)',
    theShow: 'Unlimited + historical',
  },
  {
    feature: 'Email digest (11 AM ET)',
    singleA: false,
    doubleA: true,
    tripleA: true,
    theShow: true,
  },
  {
    feature: 'Umpire framing & park composites',
    singleA: false,
    doubleA: false,
    tripleA: true,
    theShow: true,
  },
  {
    feature: 'REST API access (1,000 req/hr)',
    singleA: false,
    doubleA: false,
    tripleA: false,
    theShow: true,
  },
  {
    feature: 'Custom alert thresholds',
    singleA: false,
    doubleA: false,
    tripleA: false,
    theShow: true,
  },
  {
    feature: 'Priority support',
    singleA: false,
    doubleA: false,
    tripleA: false,
    theShow: true,
  },
];

function CellValue({ value }: { value: CellVal }) {
  if (value === true) {
    return (
      <svg
        className="h-5 w-5 text-emerald-400 mx-auto"
        fill="none"
        viewBox="0 0 24 24"
        strokeWidth={2.5}
        stroke="currentColor"
      >
        <path
          strokeLinecap="round"
          strokeLinejoin="round"
          d="M4.5 12.75l6 6 9-13.5"
        />
      </svg>
    );
  }
  if (value === false) {
    return <span className="text-gray-600">—</span>;
  }
  return <span className="text-gray-300 text-xs">{value}</span>;
}

// ---- FAQ data ----

const FAQ_ITEMS = [
  {
    q: 'Can I start with Single-A and upgrade later?',
    a: 'Yes. Single-A is free forever. When you upgrade, you get immediate access to the higher tier. Your billing starts the day you subscribe.',
  },
  {
    q: 'What are CSV exports?',
    a: "CSV exports let you download today's best bets, edges, projections, or player data as a spreadsheet file. Double-A gets 3 exports per week (best bets only). Triple-A and The Show get unlimited exports with full SHAP factor data, probabilities, and Kelly sizing columns.",
  },
  {
    q: 'What happens if I cancel?',
    a: "You keep access through the end of your current billing period. After that, you're automatically moved to Single-A (free). No data is deleted — you can re-subscribe anytime.",
  },
  {
    q: "What's the difference between Double-A and Triple-A SHAP explanations?",
    a: 'Double-A shows the top 3 contributing factors for each pick (e.g., park factor, umpire, framing). Triple-A shows the full breakdown of all factors with exact SHAP values, probability distributions, and Kelly criterion sizing.',
  },
  {
    q: 'Do you have annual pricing?',
    a: 'Annual plans are coming soon and will include a discount. Subscribe monthly now and switch to annual when available — early subscribers lock in their rate.',
  },
  {
    q: 'What does the REST API include?',
    a: 'The Show tier includes API access at 1,000 requests/hour. You can pull projections, edges, and player data programmatically. API key management is in your account dashboard. Documentation is at /api/docs.',
  },
  {
    q: 'How is this different from BallparkPal?',
    a: "We're glass-box: every projection shows exactly what drove it (park factor, umpire tendency, catcher framing, weather, platoon splits). We publicly grade every prediction nightly and never hide bad nights. Our model also incorporates ABS Challenge System adjustments for 2026 — no other prop tool does this yet.",
  },
];
