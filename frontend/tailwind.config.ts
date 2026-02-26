import type { Config } from 'tailwindcss'

const config: Config = {
  content: [
    './pages/**/*.{js,ts,jsx,tsx,mdx}',
    './components/**/*.{js,ts,jsx,tsx,mdx}',
    './app/**/*.{js,ts,jsx,tsx,mdx}',
  ],
  theme: {
    extend: {
      colors: {
        'baseline-bg': '#0a0e1a',
        'baseline-card': '#111827',
        'baseline-border': '#1f2937',
        'baseline-accent': '#3b82f6',
        'baseline-green': '#10b981',
        'baseline-red': '#ef4444',
        'baseline-yellow': '#f59e0b',
      },
    },
  },
  plugins: [],
}
export default config
