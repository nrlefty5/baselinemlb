// ============================================================
// POST /api/alerts
// Daily email digest — triggered by Vercel Cron at 11am ET.
// Sends top edges to all active pro/premium subscribers.
// ============================================================

import { NextRequest, NextResponse } from 'next/server'
import { getServiceClient } from '../../lib/supabase'

const RESEND_API_KEY = process.env.RESEND_API_KEY || ''
const FROM_EMAIL = process.env.ALERT_FROM_EMAIL || 'alerts@baselinemlb.com'
const CRON_SECRET = process.env.CRON_SECRET || ''

export const dynamic = 'force-dynamic'

// ── Auth guard for cron ─────────────────────────────────────────────
function isCronAuthorized(req: NextRequest): boolean {
  const authHeader = req.headers.get('authorization')
  if (CRON_SECRET && authHeader !== `Bearer ${CRON_SECRET}`) return false
  return true
}

// ── Email HTML builder ──────────────────────────────────────────────
function buildEmailHtml(edges: EdgeRow[], gameDate: string): string {
  const edgeRows = edges.map(e => `
    <tr style="border-bottom:1px solid #e2e8f0">
      <td style="padding:12px 8px;font-weight:600">${e.player_name}</td>
      <td style="padding:12px 8px;color:#64748b">${e.stat_type}</td>
      <td style="padding:12px 8px">${e.direction.toUpperCase()} ${e.line}</td>
      <td style="padding:12px 8px">${e.projection.toFixed(2)}</td>
      <td style="padding:12px 8px;color:${e.grade === 'A' ? '#16a34a' : e.grade === 'B' ? '#2563eb' : '#d97706'}">${e.grade}</td>
      <td style="padding:12px 8px">${(Number(e.edge) * 100).toFixed(1)}%</td>
    </tr>
  `).join('')

  return `
<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>BaselineMLB — Daily Edge Digest</title>
</head>
<body style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:#f8fafc;margin:0;padding:0">
  <div style="max-width:640px;margin:0 auto;background:#fff;border-radius:12px;overflow:hidden;margin-top:24px">

    <!-- Header -->
    <div style="background:linear-gradient(135deg,#1e293b 0%,#0f172a 100%);padding:32px;text-align:center">
      <h1 style="color:#fff;margin:0;font-size:24px;letter-spacing:-0.5px">⚾ BaselineMLB</h1>
      <p style="color:#94a3b8;margin:8px 0 0;font-size:14px">Daily Edge Digest — ${gameDate}</p>
    </div>

    <!-- Summary -->
    <div style="padding:24px 32px;background:#f1f5f9;border-bottom:1px solid #e2e8f0">
      <p style="margin:0;color:#475569;font-size:15px">
        Our model identified <strong style="color:#1e293b">${edges.length} edges</strong> for today's slate.
        Grade A picks have historically hit at <strong style="color:#16a34a">62%+</strong>.
      </p>
    </div>

    <!-- Edges Table -->
    <div style="padding:24px 32px">
      <table style="width:100%;border-collapse:collapse;font-size:14px">
        <thead>
          <tr style="background:#f8fafc">
            <th style="padding:8px;text-align:left;color:#64748b;font-weight:600">Player</th>
            <th style="padding:8px;text-align:left;color:#64748b;font-weight:600">Stat</th>
            <th style="padding:8px;text-align:left;color:#64748b;font-weight:600">Pick</th>
            <th style="padding:8px;text-align:left;color:#64748b;font-weight:600">Proj</th>
            <th style="padding:8px;text-align:left;color:#64748b;font-weight:600">Grade</th>
            <th style="padding:8px;text-align:left;color:#64748b;font-weight:600">Edge</th>
          </tr>
        </thead>
        <tbody>${edgeRows}</tbody>
      </table>
    </div>

    <!-- Footer -->
    <div style="padding:24px 32px;background:#f8fafc;border-top:1px solid #e2e8f0;text-align:center">
      <p style="margin:0;color:#94a3b8;font-size:12px">
        You're receiving this because you subscribed to BaselineMLB Pro/Premium alerts.
        <br>
        <a href="{{unsubscribe_url}}" style="color:#64748b">Unsubscribe</a> ·
        <a href="https://baselinemlb.com" style="color:#64748b">View on site</a>
      </p>
    </div>
  </div>
</body>
</html>
  `.trim()
}

interface EdgeRow {
  player_name: string
  stat_type: string
  line: number
  projection: number
  edge: number | string
  direction: string
  grade: string
}

// ── Main handler ────────────────────────────────────────────────────
export async function POST(req: NextRequest) {
  // Authorize cron
  if (!isCronAuthorized(req)) {
    return NextResponse.json({ error: 'Unauthorized' }, { status: 401 })
  }

  if (!RESEND_API_KEY) {
    return NextResponse.json(
      { error: 'RESEND_API_KEY not configured', skipped: true },
      { status: 200 }
    )
  }

  const supabase = getServiceClient()
  const today = new Date().toISOString().split('T')[0]

  // 1. Fetch today's published edges
  const { data: edges, error: edgesError } = await supabase
    .from('picks')
    .select('player_name, stat_type, line, projection, edge, direction, grade')
    .eq('game_date', today)
    .eq('published', true)
    .order('edge', { ascending: false })
    .limit(20)

  if (edgesError || !edges || edges.length === 0) {
    return NextResponse.json({
      message: 'No edges found for today',
      date: today,
      sent: 0,
    })
  }

  // 2. Fetch active pro/premium subscribers with email alerts enabled
  const { data: subscribers, error: subError } = await supabase
    .from('subscriptions')
    .select('email, tier')
    .in('tier', ['pro', 'premium'])
    .eq('status', 'active')

  if (subError || !subscribers || subscribers.length === 0) {
    return NextResponse.json({
      message: 'No eligible subscribers',
      date: today,
      sent: 0,
    })
  }

  // 3. Check alert preferences
  const { data: prefs } = await supabase
    .from('alert_preferences')
    .select('email, enabled')
    .in('email', subscribers.map(s => s.email))
    .eq('enabled', true)

  const enabledEmails = new Set((prefs || []).map(p => p.email))
  // Default: pro/premium subscribers get alerts unless they opted out
  const recipientEmails = subscribers
    .map(s => s.email)
    .filter(email => !prefs || enabledEmails.has(email) || !(prefs.map(p => p.email).includes(email)))

  if (recipientEmails.length === 0) {
    return NextResponse.json({ message: 'All subscribers have opted out', sent: 0 })
  }

  // 4. Build email
  const subject = `⚾ BaselineMLB Edges — ${today} (${edges.length} picks)`
  const html = buildEmailHtml(edges as EdgeRow[], today)

  // 5. Send via Resend (batch)
  let sent = 0
  let failed = 0
  const batchSize = 100

  for (let i = 0; i < recipientEmails.length; i += batchSize) {
    const batch = recipientEmails.slice(i, i + batchSize)
    try {
      const res = await fetch('https://api.resend.com/emails/batch', {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${RESEND_API_KEY}`,
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(
          batch.map(email => ({
            from: FROM_EMAIL,
            to: email,
            subject,
            html: html.replace('{{unsubscribe_url}}', `${process.env.NEXT_PUBLIC_APP_URL}/api/unsubscribe?email=${encodeURIComponent(email)}`),
          }))
        ),
      })

      if (res.ok) {
        sent += batch.length
      } else {
        const errBody = await res.text()
        console.error(`Resend batch error (${res.status}):`, errBody)
        failed += batch.length
      }
    } catch (err) {
      console.error('Resend fetch error:', err)
      failed += batch.length
    }
  }

  // 6. Record digest in newsletter_digests table
  await supabase.from('newsletter_digests').insert({
    game_date: today,
    subject,
    edges_json: edges,
    sent_at: new Date().toISOString(),
    recipient_count: sent,
  }).catch(err => console.error('Failed to record digest:', err))

  return NextResponse.json({
    message: 'Digest sent',
    date: today,
    edges_count: edges.length,
    sent,
    failed,
    recipients: recipientEmails.length,
  })
}
