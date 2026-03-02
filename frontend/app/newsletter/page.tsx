// ============================================================
// /newsletter — Archive of past email digests with results
// ============================================================

import { Metadata } from 'next'
import { getPublicClient } from '../lib/supabase'

export const metadata: Metadata = {
  title: 'Newsletter Archive — BaselineMLB',
  description: 'Browse past daily edge digests and see how our picks performed.',
  openGraph: {
    title: 'BaselineMLB Newsletter Archive',
    description: 'Every daily edge digest, with results tracked.',
  },
}

export const revalidate = 3600 // ISR — refresh hourly

interface DigestRow {
  id: number
  game_date: string
  subject: string
  edges_json: EdgeSnippet[]
  sent_at: string
  recipient_count: number
  results_json?: ResultsSummary | null
}

interface EdgeSnippet {
  player_name: string
  stat_type: string
  line: number
  projection: number
  direction: string
  grade: string
  edge: number | string
  result?: 'hit' | 'miss' | 'push' | null
  actual_value?: number | null
}

interface ResultsSummary {
  total: number
  hits: number
  misses: number
  pushes: number
  hit_rate: number
}

async function getDigests(): Promise<DigestRow[]> {
  try {
    const supabase = getPublicClient()
    const { data, error } = await supabase
      .from('newsletter_digests')
      .select('id, game_date, subject, edges_json, sent_at, recipient_count, results_json')
      .order('game_date', { ascending: false })
      .limit(30)

    if (error || !data) return []
    return data as DigestRow[]
  } catch {
    return []
  }
}

function ResultsBadge({ results }: { results?: ResultsSummary | null }) {
  if (!results) {
    return (
      <span className="text-xs px-2 py-0.5 rounded-full bg-slate-700 text-slate-400">
        Pending
      </span>
    )
  }
  const color = results.hit_rate >= 60 ? 'bg-green-900 text-green-300'
    : results.hit_rate >= 50 ? 'bg-blue-900 text-blue-300'
    : 'bg-red-900 text-red-300'

  return (
    <span className={`text-xs px-2 py-1 rounded-full font-semibold ${color}`}>
      {results.hit_rate}% ({results.hits}/{results.hits + results.misses})
    </span>
  )
}

function GradeChip({ grade }: { grade: string }) {
  const colors: Record<string, string> = {
    A: 'bg-green-900 text-green-300',
    B: 'bg-blue-900 text-blue-300',
    C: 'bg-yellow-900 text-yellow-300',
  }
  return (
    <span className={`text-xs px-1.5 py-0.5 rounded font-bold ${colors[grade] || 'bg-slate-700 text-slate-400'}`}>
      {grade}
    </span>
  )
}

function ResultChip({ result }: { result?: 'hit' | 'miss' | 'push' | null }) {
  if (!result) return null
  const styles = {
    hit: 'text-green-400',
    miss: 'text-red-400',
    push: 'text-slate-400',
  }
  const labels = { hit: '✓ Hit', miss: '✗ Miss', push: '— Push' }
  return <span className={`text-xs font-semibold ${styles[result]}`}>{labels[result]}</span>
}

export default async function NewsletterPage() {
  const digests = await getDigests()

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100">
      <div className="max-w-4xl mx-auto px-4 py-16">

        {/* Header */}
        <div className="mb-10">
          <h1 className="text-3xl font-bold tracking-tight mb-2">Newsletter Archive</h1>
          <p className="text-slate-400">
            Every daily edge digest we've sent — with results tracked as games complete.
          </p>
        </div>

        {digests.length === 0 && (
          <div className="text-center py-16 text-slate-500">
            <p className="text-lg">No digests yet.</p>
            <p className="text-sm mt-2">Check back after the first daily send.</p>
          </div>
        )}

        {/* Digest Cards */}
        <div className="space-y-6">
          {digests.map(digest => (
            <div
              key={digest.id}
              className="bg-slate-900 border border-slate-700 rounded-2xl overflow-hidden"
            >
              {/* Digest Header */}
              <div className="px-6 py-4 flex items-center justify-between border-b border-slate-700">
                <div>
                  <h2 className="font-semibold text-slate-100">{digest.subject}</h2>
                  <p className="text-xs text-slate-500 mt-0.5">
                    {new Date(digest.sent_at).toLocaleDateString('en-US', {
                      weekday: 'long', year: 'numeric', month: 'long', day: 'numeric'
                    })}
                    {' '}· {digest.recipient_count.toLocaleString()} recipients
                  </p>
                </div>
                <ResultsBadge results={digest.results_json} />
              </div>

              {/* Edges */}
              <div className="divide-y divide-slate-800">
                {(digest.edges_json || []).map((edge, idx) => (
                  <div key={idx} className="px-6 py-3 flex items-center gap-4 text-sm">
                    <div className="flex-1 min-w-0">
                      <span className="font-medium text-slate-100">{edge.player_name}</span>
                      <span className="text-slate-500 ml-2">{edge.stat_type}</span>
                    </div>
                    <div className="text-slate-300 text-xs shrink-0">
                      {edge.direction.toUpperCase()} {edge.line}
                      <span className="text-slate-500 ml-1">(proj {edge.projection})</span>
                    </div>
                    <GradeChip grade={edge.grade} />
                    <div className="text-slate-400 text-xs shrink-0 w-12 text-right">
                      {(Number(edge.edge) * 100).toFixed(1)}%
                    </div>
                    <div className="shrink-0 w-14 text-right">
                      <ResultChip result={edge.result} />
                    </div>
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div>

        {/* Subscribe CTA */}
        {digests.length > 0 && (
          <div className="mt-12 text-center py-10 border border-slate-700 rounded-2xl bg-slate-900">
            <h3 className="text-xl font-semibold mb-2">Get these in your inbox</h3>
            <p className="text-slate-400 text-sm mb-6">
              Pro and Premium subscribers receive the daily digest at 11am ET.
            </p>
            <a
              href="/subscribe"
              className="inline-block bg-blue-600 hover:bg-blue-500 text-white font-medium px-6 py-3 rounded-lg transition-colors"
            >
              View Plans
            </a>
          </div>
        )}
      </div>
    </div>
  )
}
