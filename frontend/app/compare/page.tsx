import type { Metadata } from 'next'
import Link from 'next/link'

export const metadata: Metadata = {
  title: 'Why BaselineMLB? — Compare MLB Prop Analytics Tools',
  description:
    'See how BaselineMLB compares to BallparkPal, EV Analytics, Action Network, FanGraphs, and Dimers. Glass-box Monte Carlo simulation at $29/mo vs $10–85/mo competitors.',
  keywords: [
    'MLB prop analytics comparison',
    'BallparkPal alternative',
    'EV Analytics alternative',
    'Action Network alternative',
    'FanGraphs alternative',
    'Dimers alternative',
    'baseball betting tools comparison',
    'Monte Carlo simulation MLB',
    'sports betting analytics',
  ],
  openGraph: {
    title: 'Why BaselineMLB? — Compare MLB Prop Analytics Tools',
    description:
      'Glass-box analytics. No black boxes. See how BaselineMLB stacks up against every major MLB analytics platform.',
    type: 'website',
  },
}

/* ------------------------------------------------------------------ */
/*  Data                                                               */
/* ------------------------------------------------------------------ */

type Platform = {
  name: string
  price: string
  shortName: string
}

const platforms: Platform[] = [
  { name: 'BaselineMLB', price: '$29/mo', shortName: 'Baseline' },
  { name: 'BallparkPal', price: '$10/mo', shortName: 'BallparkPal' },
  { name: 'EV Analytics', price: '$85/mo', shortName: 'EV Analytics' },
  { name: 'Action Network', price: '$10/mo', shortName: 'Action Net.' },
  { name: 'FanGraphs', price: '$15/mo', shortName: 'FanGraphs' },
  { name: 'Dimers', price: '$25/mo', shortName: 'Dimers' },
]

type FeatureRow = {
  feature: string
  values: boolean[]          // one per platform, same order as `platforms`
}

const features: FeatureRow[] = [
  { feature: 'Monte Carlo Simulation',              values: [true,  true,  false, false, false, true ] },
  { feature: 'Transparent Methodology',              values: [true,  false, false, false, true,  false] },
  { feature: 'Player Props with Edge %',             values: [true,  true,  true,  true,  false, true ] },
  { feature: 'Kelly Criterion Sizing',               values: [true,  false, true,  false, false, false] },
  { feature: 'Best Bets with Confidence Grades',     values: [true,  true,  false, true,  false, true ] },
  { feature: 'Public Accuracy Tracking',             values: [true,  false, false, false, false, false] },
  { feature: 'Backtest Results',                     values: [true,  false, false, false, false, false] },
  { feature: 'Real-time Odds Comparison',            values: [true,  true,  true,  true,  false, true ] },
  { feature: 'Park Factor Adjustments',              values: [true,  true,  false, false, true,  false] },
  { feature: 'Free Tier Available',                  values: [true,  true,  false, true,  true,  false] },
]

const differentiators = [
  {
    title: 'Glass-Box Approach',
    subtitle: 'Show the Math',
    description:
      'Every projection includes a full SHAP-based breakdown of the factors that drove it — umpire tendencies, park effects, platoon splits, recent form. No hidden formulas. If we say a pitcher has a 62% chance of going over 5.5 K, you can see exactly why.',
    icon: (
      <svg className="w-7 h-7" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor">
        <path strokeLinecap="round" strokeLinejoin="round" d="M2.036 12.322a1.012 1.012 0 010-.639C3.423 7.51 7.36 4.5 12 4.5c4.638 0 8.573 3.007 9.963 7.178.07.207.07.431 0 .639C20.577 16.49 16.64 19.5 12 19.5c-4.638 0-8.573-3.007-9.963-7.178z" />
        <path strokeLinecap="round" strokeLinejoin="round" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
      </svg>
    ),
  },
  {
    title: 'LightGBM + Monte Carlo',
    subtitle: 'Simulation Engine',
    description:
      'A LightGBM matchup model trained on 6M+ Statcast plate appearances produces per-PA outcome probabilities. Then 2,500 Monte Carlo simulations per game resolve full probability distributions — not point estimates — for every player stat.',
    icon: (
      <svg className="w-7 h-7" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor">
        <path strokeLinecap="round" strokeLinejoin="round" d="M3.75 3v11.25A2.25 2.25 0 006 16.5h2.25M3.75 3h-1.5m1.5 0h16.5m0 0h1.5m-1.5 0v11.25A2.25 2.25 0 0118 16.5h-2.25m-7.5 0h7.5m-7.5 0l-1 3m8.5-3l1 3m0 0l.5 1.5m-.5-1.5h-9.5m0 0l-.5 1.5M9 11.25v1.5M12 9v3.75m3-6v6" />
      </svg>
    ),
  },
  {
    title: 'Public Accuracy Dashboard',
    subtitle: 'Backtest Validation',
    description:
      'Our accuracy page shows every prediction we have ever made, graded against real results. Calibration curves, ROI by confidence tier, and full backtest data are available for anyone to verify — no cherry-picking, no hiding bad calls.',
    icon: (
      <svg className="w-7 h-7" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor">
        <path strokeLinecap="round" strokeLinejoin="round" d="M9 12.75L11.25 15 15 9.75M21 12c0 1.268-.63 2.39-1.593 3.068a3.745 3.745 0 01-1.043 3.296 3.745 3.745 0 01-3.296 1.043A3.745 3.745 0 0112 21c-1.268 0-2.39-.63-3.068-1.593a3.746 3.746 0 01-3.296-1.043 3.745 3.745 0 01-1.043-3.296A3.745 3.745 0 013 12c0-1.268.63-2.39 1.593-3.068a3.745 3.745 0 011.043-3.296 3.746 3.746 0 013.296-1.043A3.746 3.746 0 0112 3c1.268 0 2.39.63 3.068 1.593a3.746 3.746 0 013.296 1.043 3.745 3.745 0 011.043 3.296A3.745 3.745 0 0121 12z" />
      </svg>
    ),
  },
  {
    title: 'Aggressive Pricing',
    subtitle: '$29/mo vs $10–85/mo',
    description:
      'Competitors charge $10 to $85 per month for less transparency and often fewer features. BaselineMLB Pro starts at $29/mo — the most affordable option with full Monte Carlo distributions, Kelly sizing, SHAP explanations, and confidence grades included.',
    icon: (
      <svg className="w-7 h-7" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor">
        <path strokeLinecap="round" strokeLinejoin="round" d="M12 6v12m-3-2.818l.879.659c1.171.879 3.07.879 4.242 0 1.172-.879 1.172-2.303 0-3.182C13.536 12.219 12.768 12 12 12c-.725 0-1.45-.22-2.003-.659-1.106-.879-1.106-2.303 0-3.182s2.9-.879 4.006 0l.415.33M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
      </svg>
    ),
  },
]

/* ------------------------------------------------------------------ */
/*  Check / X icons                                                    */
/* ------------------------------------------------------------------ */

function Check() {
  return (
    <svg className="w-5 h-5 text-green-400 mx-auto" fill="none" viewBox="0 0 24 24" strokeWidth={2.5} stroke="currentColor">
      <path strokeLinecap="round" strokeLinejoin="round" d="M4.5 12.75l6 6 9-13.5" />
    </svg>
  )
}

function Cross() {
  return (
    <svg className="w-5 h-5 text-slate-600 mx-auto" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor">
      <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
    </svg>
  )
}

/* ------------------------------------------------------------------ */
/*  Page                                                               */
/* ------------------------------------------------------------------ */

export default function ComparePage() {
  return (
    <div className="min-h-screen">
      {/* ── Hero ── */}
      <section className="relative overflow-hidden">
        {/* Background glow */}
        <div className="absolute inset-0 bg-gradient-to-b from-blue-950/30 via-transparent to-transparent pointer-events-none" />
        <div className="absolute top-0 left-1/2 -translate-x-1/2 w-[700px] h-[400px] bg-blue-500/8 blur-[120px] rounded-full pointer-events-none" />

        <div className="relative max-w-5xl mx-auto px-4 pt-20 pb-16 text-center">
          <p className="text-blue-400 font-medium text-sm tracking-wider uppercase mb-4">
            Why BaselineMLB?
          </p>
          <h1 className="text-4xl sm:text-5xl lg:text-6xl font-bold tracking-tight leading-tight mb-6">
            Glass-Box Analytics.
            <br />
            <span className="text-transparent bg-clip-text bg-gradient-to-r from-green-400 to-emerald-300">
              No Black Boxes.
            </span>
          </h1>
          <p className="text-slate-400 text-lg sm:text-xl max-w-2xl mx-auto leading-relaxed mb-10">
            Most MLB analytics platforms hide their methodology behind closed doors.
            BaselineMLB shows you every factor, every weight, every simulation —
            so you can verify our edge before you bet on it.
          </p>
          <div className="flex flex-col sm:flex-row items-center justify-center gap-4">
            <Link
              href="/subscribe"
              className="bg-green-600 hover:bg-green-500 text-white px-8 py-3 rounded-lg font-semibold text-lg transition-colors"
            >
              Get Started — $29/mo
            </Link>
            <Link
              href="/accuracy"
              className="border border-slate-700 hover:border-slate-500 text-slate-300 hover:text-white px-8 py-3 rounded-lg font-medium transition-colors"
            >
              View Our Track Record
            </Link>
          </div>
        </div>
      </section>

      {/* ── Comparison Table ── */}
      <section className="max-w-6xl mx-auto px-4 py-16">
        <div className="text-center mb-12">
          <h2 className="text-3xl font-bold mb-3">Feature Comparison</h2>
          <p className="text-slate-400 max-w-xl mx-auto">
            How BaselineMLB stacks up against the most popular MLB prop analytics platforms.
          </p>
        </div>

        {/* Desktop table */}
        <div className="hidden lg:block overflow-x-auto rounded-xl border border-slate-800">
          <table className="w-full text-sm">
            <thead>
              <tr className="bg-slate-900/60">
                <th className="text-left py-4 px-5 font-semibold text-slate-300 w-[240px]">Feature</th>
                {platforms.map((p, i) => (
                  <th key={p.name} className="py-4 px-3 text-center min-w-[120px]">
                    <div className={`font-semibold ${i === 0 ? 'text-green-400' : 'text-slate-300'}`}>
                      {p.name}
                    </div>
                    <div className={`text-xs mt-0.5 ${i === 0 ? 'text-green-400/70' : 'text-slate-500'}`}>
                      {p.price}
                    </div>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {features.map((row, ri) => (
                <tr
                  key={row.feature}
                  className={`border-t border-slate-800/60 ${ri % 2 === 0 ? 'bg-slate-950/40' : 'bg-slate-900/20'}`}
                >
                  <td className="py-3.5 px-5 font-medium text-slate-300">{row.feature}</td>
                  {row.values.map((v, ci) => (
                    <td
                      key={ci}
                      className={`py-3.5 px-3 text-center ${ci === 0 ? 'bg-green-950/20' : ''}`}
                    >
                      {v ? <Check /> : <Cross />}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        {/* Mobile cards */}
        <div className="lg:hidden space-y-4">
          {features.map((row) => (
            <div
              key={row.feature}
              className="rounded-xl border border-slate-800 bg-slate-900/30 p-4"
            >
              <h3 className="font-semibold text-slate-200 mb-3">{row.feature}</h3>
              <div className="grid grid-cols-3 gap-2 text-xs">
                {platforms.map((p, pi) => (
                  <div
                    key={p.name}
                    className={`flex flex-col items-center gap-1 rounded-lg py-2 px-1 ${
                      pi === 0
                        ? 'bg-green-950/30 border border-green-900/40'
                        : 'bg-slate-800/30'
                    }`}
                  >
                    <span className={pi === 0 ? 'text-green-400 font-medium' : 'text-slate-400'}>
                      {p.shortName}
                    </span>
                    {row.values[pi] ? <Check /> : <Cross />}
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div>

        {/* Score summary */}
        <div className="mt-8 rounded-xl border border-slate-800 bg-slate-900/40 p-6">
          <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-4 text-center">
            {platforms.map((p, i) => {
              const score = features.reduce((sum, f) => sum + (f.values[i] ? 1 : 0), 0)
              return (
                <div key={p.name} className={`rounded-lg p-3 ${i === 0 ? 'bg-green-950/30 border border-green-900/40' : 'bg-slate-800/30'}`}>
                  <div className={`text-2xl font-bold ${i === 0 ? 'text-green-400' : 'text-slate-300'}`}>
                    {score}/{features.length}
                  </div>
                  <div className={`text-xs mt-1 ${i === 0 ? 'text-green-400/70' : 'text-slate-500'}`}>
                    {p.name}
                  </div>
                  <div className={`text-xs ${i === 0 ? 'text-green-400/50' : 'text-slate-600'}`}>
                    {p.price}
                  </div>
                </div>
              )
            })}
          </div>
        </div>
      </section>

      {/* ── What Makes Us Different ── */}
      <section className="max-w-5xl mx-auto px-4 py-16">
        <div className="text-center mb-14">
          <h2 className="text-3xl font-bold mb-3">What Makes Us Different</h2>
          <p className="text-slate-400 max-w-xl mx-auto">
            BaselineMLB was built from day one around transparency, accuracy, and value.
          </p>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          {differentiators.map((d) => (
            <div
              key={d.title}
              className="rounded-xl border border-slate-800 bg-slate-900/30 p-6 hover:border-slate-700 transition-colors"
            >
              <div className="flex items-start gap-4">
                <div className="flex-shrink-0 w-12 h-12 rounded-lg bg-blue-950/50 border border-blue-900/30 flex items-center justify-center text-blue-400">
                  {d.icon}
                </div>
                <div>
                  <h3 className="font-semibold text-lg text-slate-100">{d.title}</h3>
                  <p className="text-blue-400 text-sm font-medium mb-2">{d.subtitle}</p>
                  <p className="text-slate-400 text-sm leading-relaxed">{d.description}</p>
                </div>
              </div>
            </div>
          ))}
        </div>
      </section>

      {/* ── CTA ── */}
      <section className="max-w-3xl mx-auto px-4 py-16 text-center">
        <div className="rounded-2xl border border-slate-800 bg-gradient-to-b from-slate-900/80 to-slate-950 p-10">
          <h2 className="text-2xl sm:text-3xl font-bold mb-4">
            Ready to See the Full Picture?
          </h2>
          <p className="text-slate-400 mb-8 max-w-lg mx-auto">
            Start with our free tier — 3 daily edges, full accuracy dashboard access, and complete
            methodology documentation. Upgrade anytime for $29/mo.
          </p>
          <div className="flex flex-col sm:flex-row items-center justify-center gap-4">
            <Link
              href="/subscribe"
              className="bg-green-600 hover:bg-green-500 text-white px-8 py-3 rounded-lg font-semibold transition-colors"
            >
              Start Free
            </Link>
            <Link
              href="/methodology"
              className="text-slate-400 hover:text-slate-200 font-medium transition-colors"
            >
              Read Our Methodology &rarr;
            </Link>
          </div>
        </div>
      </section>
    </div>
  )
}
