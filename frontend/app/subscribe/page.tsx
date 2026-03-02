// ============================================================
// /subscribe — Subscription Tier Comparison Page
// Server component with metadata; client interactions in
// SubscribeClient.tsx
// ============================================================

import { Metadata } from 'next'
import SubscribeClient from './SubscribeClient'

export const metadata: Metadata = {
  title: 'Subscribe — BaselineMLB',
  description: 'Unlock full MLB prop edges with Pro ($29/mo) or Premium ($49/mo). Daily email alerts, API access, and more.',
  openGraph: {
    title: 'Subscribe to BaselineMLB',
    description: 'Professional-grade MLB prop analytics. Upgrade to Pro or Premium for full edge access.',
  },
}

export default function SubscribePage() {
  return <SubscribeClient />
}
