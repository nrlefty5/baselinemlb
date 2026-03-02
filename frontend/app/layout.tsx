import type { Metadata } from 'next'
import Image from 'next/image'
import './globals.css'

export const metadata: Metadata = {
  title: 'Baseline MLB — Glass-Box MLB Analytics',
  description: 'MLB player prop analytics with transparent, glass-box AI projections. Every factor logged. Every result graded publicly.',
  keywords: 'MLB, baseball, analytics, player props, betting, strikeouts, Statcast',
  openGraph: {
    title: 'Baseline MLB',
    description: 'Glass-box MLB prop analytics. No black boxes.',
    url: 'https://baselinemlb.com',
    siteName: 'Baseline MLB',
  },
}

export default function RootLayout({
  children,
}: {
  children: React.ReactNode
}) {
  return (
    <html lang="en">
      <body className="min-h-screen bg-[#0a0e1a] text-slate-100">
        <nav className="border-b border-gray-800 px-6 py-4">
          <div className="max-w-7xl mx-auto flex items-center justify-between">
            <div className="flex items-center gap-2">
              <a href="/" className="flex items-center gap-2">
                <Image
                  src="/logo.svg"
                  alt="Baseline MLB"
                  width={36}
                  height={36}
                  className="rounded-full"
                />
                <span className="text-xl font-bold text-blue-400">BASELINE</span>
                <span className="text-xl font-bold text-white">MLB</span>
              </a>
              <span className="ml-2 px-2 py-0.5 text-xs bg-blue-900 text-blue-300 rounded-full border border-blue-700">BETA</span>
            </div>
            <div className="flex items-center gap-6 text-sm">
              <a href="/" className="text-slate-300 hover:text-white transition-colors">Today</a>
              <a href="/props" className="text-slate-300 hover:text-white transition-colors">Props</a>
              <a href="/projections" className="text-slate-300 hover:text-white transition-colors">Projections</a>
              <a href="/players" className="text-slate-300 hover:text-white transition-colors">Players</a>
              <a href="/best-bets" className="text-slate-300 hover:text-white transition-colors">Best Bets</a>
              <a href="/accuracy" className="text-slate-300 hover:text-white transition-colors">Accuracy</a>
              <a href="https://twitter.com/baselinemlb" target="_blank" className="text-blue-400 hover:text-blue-300 transition-colors">@baselinemlb</a>
            </div>
          </div>
        </nav>

        <main className="max-w-7xl mx-auto px-6 py-8">
          {children}
        </main>

        <footer className="border-t border-gray-800 px-6 py-8 mt-16">
          <div className="max-w-7xl mx-auto">
            <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4">
              <div>
                <div className="flex items-center gap-2 mb-1">
                  <Image src="/logo.svg" alt="Baseline MLB" width={24} height={24} className="rounded-full" />
                  <span className="font-bold text-blue-400">BASELINE</span>
                  <span className="font-bold text-white">MLB</span>
                </div>
                <p className="text-xs text-slate-500">Glass-box MLB prop analytics. No black boxes.</p>
              </div>
              <div className="flex flex-col sm:items-end gap-1">
                <a href="/" className="text-slate-400 hover:text-white">Today</a>
                <a href="/props" className="text-slate-400 hover:text-white">Props</a>
                <a href="/projections" className="text-slate-400 hover:text-white">Projections</a>
                <a href="/players" className="text-slate-400 hover:text-white">Players</a>
                <a href="/best-bets" className="text-slate-400 hover:text-white">Best Bets</a>
                <a href="/accuracy" className="text-slate-400 hover:text-white">Accuracy</a>
              </div>
            </div>
            <p className="text-xs text-slate-600 mt-4">
              Data: MLB Stats API, The Odds API, Baseball Savant &bull; For informational use only
            </p>
          </div>
        </footer>
      </body>
    </html>
  )
}
