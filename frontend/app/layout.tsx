import type { Metadata } from 'next'
import { Inter } from 'next/font/google'
import './globals.css'
import Link from 'next/link'

const inter = Inter({ subsets: ['latin'] })

export const metadata: Metadata = {
  title: 'BaselineMLB — Monte Carlo MLB Prop Edges',
  description: 'Statistically significant MLB prop picks powered by 10,000+ Monte Carlo simulations per game.',
  openGraph: {
    title: 'BaselineMLB',
    description: 'Monte Carlo MLB prop edges. Updated daily.',
    type: 'website',
  },
}

export default function RootLayout({
  children,
}: {
  children: React.ReactNode
}) {
  return (
    <html lang="en">
      <body className={`${inter.className} bg-slate-950 text-slate-100 antialiased`}>

        {/* ── Navigation ── */}
        <nav className="border-b border-slate-800 bg-slate-950/80 backdrop-blur-sm sticky top-0 z-50">
          <div className="max-w-6xl mx-auto px-4 h-14 flex items-center justify-between">

            {/* Logo */}
            <Link href="/" className="font-bold text-lg tracking-tight hover:text-white transition-colors">
              ⚾ BaselineMLB
            </Link>

            {/* Nav Links */}
            <div className="flex items-center gap-6 text-sm">
              <Link
                href="/"
                className="text-slate-400 hover:text-slate-100 transition-colors"
              >
                Edges
              </Link>
              <Link
                href="/newsletter"
                className="text-slate-400 hover:text-slate-100 transition-colors"
              >
                Newsletter
              </Link>
              <Link
                href="/subscribe"
                className="bg-blue-600 hover:bg-blue-500 text-white px-4 py-1.5 rounded-lg font-medium transition-colors"
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
        <footer className="border-t border-slate-800 mt-20">
          <div className="max-w-6xl mx-auto px-4 py-8 flex flex-col sm:flex-row items-center justify-between gap-4">
            <p className="text-slate-500 text-sm">
              © {new Date().getFullYear()} BaselineMLB. For entertainment purposes only.
            </p>
            <div className="flex items-center gap-4 text-sm text-slate-500">
              <Link href="/subscribe" className="hover:text-slate-300 transition-colors">Pricing</Link>
              <Link href="/newsletter" className="hover:text-slate-300 transition-colors">Newsletter</Link>
              <a
                href="/api/v1/status"
                target="_blank"
                rel="noopener noreferrer"
                className="hover:text-slate-300 transition-colors"
              >
                API Status
              </a>
            </div>
          </div>
        </footer>

      </body>
    </html>
  )
}
