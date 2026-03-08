import type { Metadata } from 'next'
import { Inter } from 'next/font/google'
import './globals.css'
import Link from 'next/link'

const inter = Inter({ subsets: ['latin'] })

const siteUrl = 'https://fullcountprops.vercel.app'

export const metadata: Metadata = {
  metadataBase: new URL(siteUrl),
  title: {
    default: 'FullCountProps — Monte Carlo MLB Prop Analytics',
    template: '%s | FullCountProps',
  },
  description:
    'MLB player prop edges powered by 2,500 PA-level Monte Carlo simulations per game. LightGBM matchup model trained on 6M+ Statcast plate appearances. Glass-box transparency — every factor visible.',
  keywords: [
    'MLB props',
    'baseball prop bets',
    'Monte Carlo simulation',
    'MLB analytics',
    'strikeout props',
    'player props',
    'sports betting analytics',
    'Statcast',
    'FullCountProps',
  ],
  authors: [{ name: 'FullCountProps' }],
  creator: 'FullCountProps',
  openGraph: {
    type: 'website',
    locale: 'en_US',
    url: siteUrl,
    siteName: 'FullCountProps',
    title: 'FullCountProps — Monte Carlo MLB Prop Analytics',
    description:
      'MLB player prop edges powered by 2,500 PA-level Monte Carlo simulations per game. Glass-box transparency.',
    images: [
      {
        url: '/og-image.png',
        width: 1200,
        height: 630,
        alt: 'FullCountProps — Monte Carlo MLB Prop Analytics',
      },
    ],
  },
  twitter: {
    card: 'summary_large_image',
    title: 'FullCountProps — Monte Carlo MLB Prop Analytics',
    description:
      'MLB player prop edges powered by 2,500 PA-level Monte Carlo simulations. Glass-box transparency.',
    images: ['/og-image.png'],
    creator: '@fullcountprops',
  },
  robots: {
    index: true,
    follow: true,
    googleBot: {
      index: true,
      follow: true,
      'max-video-preview': -1,
      'max-image-preview': 'large',
      'max-snippet': -1,
    },
  },
  alternates: {
    canonical: siteUrl,
  },
}

function JsonLd() {
  const structuredData = {
    '@context': 'https://schema.org',
    '@type': 'WebApplication',
    name: 'FullCountProps',
    url: siteUrl,
    description:
      'MLB player prop analytics powered by Monte Carlo simulation. 2,500 PA-level simulations per game with glass-box transparency.',
    applicationCategory: 'SportsApplication',
    operatingSystem: 'Web',
    offers: [
      {
        '@type': 'Offer',
        name: 'Single-A',
        price: '0',
        priceCurrency: 'USD',
        description: 'Top 3 best bets daily with grade, direction, and edge %',
      },
      {
        '@type': 'Offer',
        name: 'Double-A',
        price: '7.99',
        priceCurrency: 'USD',
        description: 'Full daily best bets, edges page, basic SHAP, daily email digest',
      },
      {
        '@type': 'Offer',
        name: 'Triple-A',
        price: '29.99',
        priceCurrency: 'USD',
        description: 'Full SHAP breakdowns, probability distributions, Kelly sizing, simulator',
      },
      {
        '@type': 'Offer',
        name: 'The Show',
        price: '49.99',
        priceCurrency: 'USD',
        description: 'Everything in Triple-A plus REST API access, CSV export, priority support',
      },
    ],
    creator: {
      '@type': 'Organization',
      name: 'FullCountProps',
      url: siteUrl,
    },
  }

  return (
    <script
      type="application/ld+json"
      dangerouslySetInnerHTML={{ __html: JSON.stringify(structuredData) }}
    />
  )
}

export default function RootLayout({
  children,
}: {
  children: React.ReactNode
}) {
  return (
    <html lang="en">
      <head>
        <JsonLd />
      </head>
      <body className={`${inter.className} bg-slate-950 text-slate-100 antialiased`}>

        {/* ── Navigation ── */}
        <nav className="border-b border-slate-800 bg-slate-950/80 backdrop-blur-sm sticky top-0 z-50">
          <div className="max-w-6xl mx-auto px-4 h-14 flex items-center justify-between">

            {/* Logo */}
            <Link href="/" className="font-bold text-lg tracking-tight hover:text-white transition-colors">
              ⚾ FullCountProps
            </Link>

            {/* Nav Links */}
            <div className="flex items-center gap-6 text-sm">
              <Link
                href="/edges"
                className="text-slate-400 hover:text-slate-100 transition-colors hidden sm:inline"
              >
                Edges
              </Link>
              <Link
                href="/park-factors"
                className="text-slate-400 hover:text-slate-100 transition-colors hidden sm:inline"
              >
                Park Factors
              </Link>
              <Link
                href="/compare"
                className="text-slate-400 hover:text-slate-100 transition-colors hidden sm:inline"
              >
                Compare
              </Link>
              <Link
                href="/methodology"
                className="text-slate-400 hover:text-slate-100 transition-colors hidden sm:inline"
              >
                Methodology
              </Link>
              <Link
                href="/faq"
                className="text-slate-400 hover:text-slate-100 transition-colors hidden sm:inline"
              >
                FAQ
              </Link>
              <Link
                href="/subscribe"
                className="bg-green-600 hover:bg-green-500 text-white px-4 py-1.5 rounded-lg font-medium transition-colors"
              >
                Subscribe
              </Link>
            </div>
          </div>
        </nav>

        {/* ── Page Content ── */}
        <main>
          {children}
        </main>

        {/* ── Footer ── */}
        <footer className="border-t border-slate-800 mt-20 bg-slate-950">
          <div className="max-w-6xl mx-auto px-4 py-12">
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-8 mb-8">
              {/* Brand */}
              <div>
                <div className="font-bold text-lg mb-3">⚾ FullCountProps</div>
                <p className="text-slate-500 text-sm leading-relaxed">
                  Monte Carlo MLB prop analytics with glass-box transparency.
                  Every factor visible. Every result graded publicly.
                </p>
              </div>

              {/* Product */}
              <div>
                <h3 className="text-sm font-semibold text-slate-300 uppercase tracking-wider mb-3">
                  Product
                </h3>
                <ul className="space-y-2 text-sm">
                  <li>
                    <Link href="/props" className="text-slate-500 hover:text-slate-300 transition-colors">
                      Today&apos;s Props
                    </Link>
                  </li>
                  <li>
                    <Link href="/projections" className="text-slate-500 hover:text-slate-300 transition-colors">
                      Projections
                    </Link>
                  </li>
                  <li>
                    <Link href="/players" className="text-slate-500 hover:text-slate-300 transition-colors">
                      Players
                    </Link>
                  </li>
                  <li>
                    <Link href="/park-factors" className="text-slate-500 hover:text-slate-300 transition-colors">
                      Park Factors
                    </Link>
                  </li>
                  <li>
                    <Link href="/compare" className="text-slate-500 hover:text-slate-300 transition-colors">
                      Compare
                    </Link>
                  </li>
                  <li>
                    <Link href="/subscribe" className="text-slate-500 hover:text-slate-300 transition-colors">
                      Pricing
                    </Link>
                  </li>
                </ul>
              </div>

              {/* Resources */}
              <div>
                <h3 className="text-sm font-semibold text-slate-300 uppercase tracking-wider mb-3">
                  Resources
                </h3>
                <ul className="space-y-2 text-sm">
                  <li>
                    <Link href="/methodology" className="text-slate-500 hover:text-slate-300 transition-colors">
                      Methodology
                    </Link>
                  </li>
                  <li>
                    <Link href="/faq" className="text-slate-500 hover:text-slate-300 transition-colors">
                      FAQ
                    </Link>
                  </li>
                  <li>
                    <Link href="/accuracy" className="text-slate-500 hover:text-slate-300 transition-colors">
                      Accuracy
                    </Link>
                  </li>
                  <li>
                    <Link href="/newsletter" className="text-slate-500 hover:text-slate-300 transition-colors">
                      Newsletter Archive
                    </Link>
                  </li>
                </ul>
              </div>

              {/* Connect */}
              <div>
                <h3 className="text-sm font-semibold text-slate-300 uppercase tracking-wider mb-3">
                  Connect
                </h3>
                <ul className="space-y-2 text-sm">
                  <li>
                    <a
                      href="https://twitter.com/fullcountprops"
                      target="_blank"
                      rel="noopener noreferrer"
                      className="text-slate-500 hover:text-slate-300 transition-colors inline-flex items-center gap-1.5"
                    >
                      <svg className="w-4 h-4" fill="currentColor" viewBox="0 0 24 24" aria-hidden="true">
                        <path d="M18.244 2.25h3.308l-7.227 8.26 8.502 11.24H16.17l-5.214-6.817L4.99 21.75H1.68l7.73-8.835L1.254 2.25H8.08l4.713 6.231zm-1.161 17.52h1.833L7.084 4.126H5.117z" />
                      </svg>
                      Twitter / X
                    </a>
                  </li>
                  <li>
                    <a
                      href="https://github.com/fullcountprops/fullcountprops"
                      target="_blank"
                      rel="noopener noreferrer"
                      className="text-slate-500 hover:text-slate-300 transition-colors inline-flex items-center gap-1.5"
                    >
                      <svg className="w-4 h-4" fill="currentColor" viewBox="0 0 24 24" aria-hidden="true">
                        <path fillRule="evenodd" d="M12 2C6.477 2 2 6.484 2 12.017c0 4.425 2.865 8.18 6.839 9.504.5.092.682-.217.682-.483 0-.237-.008-.868-.013-1.703-2.782.605-3.369-1.343-3.369-1.343-.454-1.158-1.11-1.466-1.11-1.466-.908-.62.069-.608.069-.608 1.003.07 1.531 1.032 1.531 1.032.892 1.53 2.341 1.088 2.91.832.092-.647.35-1.088.636-1.338-2.22-.253-4.555-1.113-4.555-4.951 0-1.093.39-1.988 1.029-2.688-.103-.253-.446-1.272.098-2.65 0 0 .84-.27 2.75 1.026A9.564 9.564 0 0112 6.844c.85.004 1.705.115 2.504.337 1.909-1.296 2.747-1.027 2.747-1.027.546 1.379.202 2.398.1 2.651.64.7 1.028 1.595 1.028 2.688 0 3.848-2.339 4.695-4.566 4.943.359.309.678.92.678 1.855 0 1.338-.012 2.419-.012 2.747 0 .268.18.58.688.482A10.019 10.019 0 0022 12.017C22 6.484 17.522 2 12 2z" clipRule="evenodd" />
                      </svg>
                      GitHub
                    </a>
                  </li>
                  <li>
                    <a
                      href="/api/v1/status"
                      target="_blank"
                      rel="noopener noreferrer"
                      className="text-slate-500 hover:text-slate-300 transition-colors"
                    >
                      API Status
                    </a>
                  </li>
                </ul>
              </div>
            </div>

            {/* Bottom bar */}
            <div className="border-t border-slate-800 pt-8 flex flex-col sm:flex-row items-center justify-between gap-4">
              <p className="text-slate-600 text-xs">
                &copy; {new Date().getFullYear()} FullCountProps. For entertainment purposes only. Not gambling advice.
              </p>
                            <p className="text-slate-600 text-xs mt-2">
                If you or someone you know has a gambling problem, call 1-800-GAMBLER (1-800-426-2537). Must be 21+ to use this service.
              </p>
              <div className="flex items-center gap-4 text-xs text-slate-600">
                <Link href="/terms" className="hover:text-slate-400 transition-colors">
                  Terms of Use
                                </Link>
                                
                <Link href="/privacy" className="hover:text-slate-400 transition-colors">
                  Privacy Policy
                </Link>
              </div>
            </div>
          </div>
                </footer>
  

      </body>
    </html>
  )
}
