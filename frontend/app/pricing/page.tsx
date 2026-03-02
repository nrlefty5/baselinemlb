import { Metadata } from 'next'
import PricingClient from './PricingClient'

export const metadata: Metadata = {
  title: 'Pricing — BaselineMLB',
  description: 'Choose your plan. Free picks daily, Pro for full SHAP analysis, Premium for API access.',
  openGraph: {
    title: 'Pricing — BaselineMLB',
    description: 'MLB prop analytics pricing. Free, Pro ($29/mo), and Premium ($49/mo) plans.',
  },
}

export default function PricingPage() {
  return <PricingClient />
}
