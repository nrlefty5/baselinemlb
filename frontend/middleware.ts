// ===========================================================
// Next.js Middleware — BaselineMLB
// Handles:
//   1. Pre-launch password gate (set SITE_PASSWORD env var to enable)
//   2. API v1 CORS headers (for external API consumers)
//   3. Rate-limit header passthrough
//   4. Logging of API v1 requests (path + tier from headers)
// ===========================================================

import { NextRequest, NextResponse } from 'next/server'

// Routes that need CORS headers for external API access
const API_V1_PATTERN = /^\/api\/v1\//

// Allowed origins for CORS
const ALLOWED_ORIGINS = [
  'https://baselinemlb.com',
  'https://www.baselinemlb.com',
  'http://localhost:3000',
]

// Paths that bypass password protection
const PUBLIC_PATHS = [
  '/api/',           // All API routes (webhooks, subscribe, checkout)
  '/_next/',         // Next.js assets
  '/favicon.ico',
  '/gate',           // The password gate page itself
]

export function middleware(req: NextRequest) {
  const { pathname } = req.nextUrl

  // —— Password Gate ————————————————————————————————————
  const sitePassword = process.env.SITE_PASSWORD
  if (sitePassword) {
    const isPublicPath = PUBLIC_PATHS.some(p => pathname.startsWith(p))
    if (!isPublicPath) {
      const authCookie = req.cookies.get('site_auth')?.value
      if (authCookie !== sitePassword) {
        // Check if this is a POST to /gate (password submission)
        if (pathname === '/gate' && req.method === 'POST') {
          // Let the page handle the POST
          return NextResponse.next()
        }
        // Redirect to gate page
        const gateUrl = req.nextUrl.clone()
        gateUrl.pathname = '/gate'
        return NextResponse.rewrite(gateUrl)
      }
    }
  }

  // —— API v1: add CORS headers ——————————————————————————
  if (API_V1_PATTERN.test(pathname)) {
    const origin = req.headers.get('origin') || ''
    const allowedOrigin = ALLOWED_ORIGINS.includes(origin) ? origin : ALLOWED_ORIGINS[0]

    // Handle preflight OPTIONS requests
    if (req.method === 'OPTIONS') {
      return new NextResponse(null, {
        status: 204,
        headers: corsHeaders(allowedOrigin),
      })
    }

    // Clone and forward with CORS on the response
    const response = NextResponse.next()
    Object.entries(corsHeaders(allowedOrigin)).forEach(([k, v]) => response.headers.set(k, v))
    return response
  }

  return NextResponse.next()
}

function corsHeaders(origin: string): Record<string, string> {
  return {
    'Access-Control-Allow-Origin': origin,
    'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
    'Access-Control-Allow-Headers': 'Content-Type, Authorization, x-api-key',
    'Access-Control-Max-Age': '86400',
  }
}

export const config = {
  matcher: [
    '/((?!_next/static|_next/image|favicon.ico).*)',
  ],
}
