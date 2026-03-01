'use client'

import { useState } from 'react'

type Status = 'idle' | 'loading' | 'success' | 'error'

export default function EmailSignup({
  variant = 'default',
}: {
  variant?: 'default' | 'compact'
}) {
  const [email, setEmail] = useState('')
  const [status, setStatus] = useState<Status>('idle')
  const [message, setMessage] = useState('')

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (!email || !email.includes('@')) {
      setMessage('Please enter a valid email address.')
      setStatus('error')
      return
    }

    setStatus('loading')
    setMessage('')

    try {
      const res = await fetch('/api/subscribe', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email }),
      })

      if (res.ok) {
        setStatus('success')
        setMessage("You're on the list! We'll send you picks before Opening Day 2026.")
        setEmail('')
      } else {
        const data = await res.json().catch(() => ({}))
        setStatus('error')
        setMessage(data.error || 'Something went wrong. Please try again.')
      }
    } catch {
      setStatus('error')
      setMessage('Network error. Please try again.')
    }
  }

  if (variant === 'compact') {
    return (
      <form onSubmit={handleSubmit} className="flex gap-2">
        <input
          type="email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          placeholder="your@email.com"
          disabled={status === 'loading' || status === 'success'}
          className="flex-1 min-w-0 px-3 py-2 text-sm bg-gray-800 border border-gray-700 rounded-lg text-white placeholder-slate-500 focus:outline-none focus:border-green-500 disabled:opacity-50"
        />
        <button
          type="submit"
          disabled={status === 'loading' || status === 'success'}
          className="px-4 py-2 text-sm font-semibold bg-green-600 hover:bg-green-500 text-white rounded-lg transition-colors disabled:opacity-50 whitespace-nowrap"
        >
          {status === 'loading' ? 'Joining...' : status === 'success' ? 'Joined ✓' : 'Get Updates'}
        </button>
        {message && (
          <p className={`text-xs mt-1 ${status === 'error' ? 'text-red-400' : 'text-green-400'}`}>
            {message}
          </p>
        )}
      </form>
    )
  }

  return (
    <div className="bg-gray-800/50 border border-gray-700 rounded-xl p-6">
      <div className="mb-4">
        <h3 className="text-lg font-semibold text-white mb-1">
          Get Early Access
        </h3>
        <p className="text-slate-400 text-sm">
          Prop picks + model updates before Opening Day 2026. No spam, unsubscribe anytime.
        </p>
      </div>

      {status === 'success' ? (
        <div className="flex items-center gap-3 p-4 bg-green-900/30 border border-green-700 rounded-lg">
          <span className="text-green-400 text-xl">✅</span>
          <p className="text-green-300 text-sm">{message}</p>
        </div>
      ) : (
        <form onSubmit={handleSubmit} className="space-y-3">
          <input
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="your@email.com"
            disabled={status === 'loading'}
            className="w-full px-4 py-3 bg-gray-900 border border-gray-700 rounded-lg text-white placeholder-slate-500 focus:outline-none focus:border-green-500 focus:ring-1 focus:ring-green-500 transition-colors disabled:opacity-50"
          />
          {status === 'error' && message && (
            <p className="text-red-400 text-xs">{message}</p>
          )}
          <button
            type="submit"
            disabled={status === 'loading'}
            className="w-full py-3 font-semibold bg-green-600 hover:bg-green-500 text-white rounded-lg transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {status === 'loading' ? (
              <span className="flex items-center justify-center gap-2">
                <svg className="animate-spin h-4 w-4" fill="none" viewBox="0 0 24 24">
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"/>
                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"/>
                </svg>
                Joining...
              </span>
            ) : (
              'Get Early Access →'
            )}
          </button>
        </form>
      )}
    </div>
  )
}
