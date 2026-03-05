// frontend/middleware.ts
// ============================================================
// BaselineMLB — Middleware (Password gate REMOVED per Issue #8)
// ============================================================
//
// The pre-launch password gate has been removed. The site is now
// fully open. This middleware handles only auth-related redirects
// for protected routes that require a subscription.
//
// Previously: checked for SITE_PASSWORD env var and site_auth cookie.
// Now: no password gate. Public pages are fully accessible.
// ============================================================

import { NextResponse } from 'next/server';
import type { NextRequest } from 'next/server';

export function middleware(request: NextRequest) {
  const { pathname } = request.nextUrl;

  // ---- Public routes — no auth required ----
  const publicPaths = [
    '/',
    '/edges',
    '/projections',
    '/compare',
    '/methodology',
    '/faq',
    '/accuracy',
    '/subscribe',
    '/pricing',
    '/players',
    '/props',
    '/newsletter',
    '/terms',
    '/privacy',
    '/login',
    '/signup',
    '/auth',
  ];

  // Allow all API routes, static files, images, and Next.js internals
  if (
    pathname.startsWith('/api/') ||
    pathname.startsWith('/_next/') ||
    pathname.startsWith('/static/') ||
    pathname.includes('.') // files with extensions (favicon, images, etc.)
  ) {
    return NextResponse.next();
  }

  // Allow all public paths
  if (publicPaths.some((p) => pathname === p || pathname.startsWith(p + '/'))) {
    return NextResponse.next();
  }

  // ---- Protected routes (require login) ----
  // Routes like /best-bets, /simulator, /account, /api-keys
  // are gated by Supabase auth on the page level, not middleware.
  // Middleware just passes through; the page component checks the session.

  return NextResponse.next();
}

export const config = {
  matcher: [
    /*
     * Match all request paths except:
     * - _next/static (static files)
     * - _next/image (image optimization files)
     * - favicon.ico (favicon file)
     */
    '/((?!_next/static|_next/image|favicon.ico).*)',
  ],
};
