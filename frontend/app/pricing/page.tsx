// frontend/app/(main)/pricing/page.tsx
// ============================================================
// BaselineMLB — Pricing Page (Issue #8: 4-tier MiLB structure)
// ============================================================

import type { Metadata } from 'next';
import PricingClient from './PricingClient';

export const metadata: Metadata = {
  title: 'Pricing — BaselineMLB',
  description:
    'Choose your tier: Single-A (free), Double-A ($7.99/mo), Triple-A ($29.99/mo), or The Show ($49.99/mo). Glass-box MLB prop analytics with PA-level Monte Carlo simulations.',
  openGraph: {
    title: 'Pricing — BaselineMLB',
    description:
      'MLB prop analytics from $7.99/mo. Every projection transparent. Every result graded publicly.',
  },
};

export default function PricingPage() {
  return <PricingClient />;
}
