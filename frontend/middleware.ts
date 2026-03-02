// ============================================================
// Next.js Middleware — BaselineMLB
// Handles:
//   1. API v1 CORS headers (for external API consumers)
//   2. Rate-limit header passthrough
//   3. Logging of API v1 requests (path + tier from headers)
// ============================================================

import { NextRequest, NextResponse } from 'next/server'

// Routes that need CORS headers for external API access
const API_V1_PATTERN = /^\/api\/v1\//

export function middleware(req: NextRequest) {
  const { pathname } = req.nextUrl

  // ── API v1: add CORS headers ─────────────────────────────────────
  if (API_V1_PATTERN.test(pathname)) {
    // Handle preflight OPTIONS requests
    if (req.method === 'OPTIONS') {
      return new NextResponse(null, {
        status: 204,
        headers: corsHeaders(),
      })
    }

    // Clone and forward with CORS on the response
    const response = NextResponse.next()
    Object.entries(corsHeaders()).forEach(([k, v]) => response.headers.set(k, v))
    return response
  }

  return NextResponse.next()
}

function corsHeaders(): Record<string, string> {
  return {
    'Access-Control-Allow-Origin': '*',
    'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
    'Access-Control-Allow-Headers': 'Content-Type, Authorization, x-api-key',
    'Access-Control-Max-Age': '86400',
  }
}

export const config = {
  matcher: [
    '/api/v1/:path*',
  ],
}
