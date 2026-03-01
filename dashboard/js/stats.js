/**
 * stats.js — BaselineMLB Public Accuracy Dashboard
 *
 * Fetches live accuracy and CLV metrics from Supabase using the anon key.
 * Populates stat cards, market table, and bookmaker table.
 * Displays today's projections with player handedness.
 * Handles pre-season state gracefully when no data exists.
 */

// ---------------------------------------------------------------------------
// Configuration — replace these with your actual Supabase project values
// ---------------------------------------------------------------------------
const SUPABASE_URL = 'https://YOUR_PROJECT_REF.supabase.co';
const SUPABASE_ANON_KEY = 'YOUR_ANON_KEY_HERE';

// ---------------------------------------------------------------------------
// Supabase REST helper (no SDK required — plain fetch)
// ---------------------------------------------------------------------------
async function sbGet(table, params = {}) {
  const url = new URL(`${SUPABASE_URL}/rest/v1/${table}`);
  Object.entries(params).forEach(([k, v]) => url.searchParams.append(k, v));
  const res = await fetch(url.toString(), {
    headers: {
      'apikey': SUPABASE_ANON_KEY,
      'Authorization': `Bearer ${SUPABASE_ANON_KEY}`,
      'Content-Type': 'application/json',
    },
  });
  if (!res.ok) throw new Error(`Supabase fetch failed: ${res.status} ${res.statusText}`);
  return res.json();
}

// ---------------------------------------------------------------------------
// Static JSON fallback — reads from grade_accuracy.py exports
// ---------------------------------------------------------------------------
async function loadFromStaticJSON() {
  try {
    const res = await fetch('./data/accuracy_summary.json');
    if (!res.ok) return null;
    return await res.json();
  } catch (e) {
    return null;
  }
}

async function updateLastUpdated(data) {
  const el = document.getElementById('last-updated');
  if (!el) return;
  if (data && data.updated_at) {
    const d = new Date(data.updated_at);
    el.textContent = 'Last updated: ' + d.toLocaleString('en-US', { timeZone: 'America/New_York' }) + ' ET';
  } else {
    el.textContent = 'Data updates nightly at 2 AM ET';
  }
}

// ---------------------------------------------------------------------------
// Data fetching
// ---------------------------------------------------------------------------
async function fetchDashboardStats() {
  try {
    // 1. Overall hit rate from accuracy_summary
    const overallRows = await sbGet('accuracy_summary', {
      select: 'total_picks,hits,hit_rate,season',
      order: 'season.desc',
      limit: 1,
    });
    const overall = overallRows && overallRows.length > 0 ? overallRows[0] : null;

    // 2. All CLV data for average calculation
    const clvRows = await sbGet('clv_tracking', {
      select: 'clv_percent,market',
    });

    // 3. Graded picks for market + bookmaker breakdown
    const picksRows = await sbGet('picks', {
      select: 'market,bookmaker,result',
      'result': 'not.is.null',
    });

    // Compute average CLV
    const avgCLV = clvRows && clvRows.length > 0
      ? (clvRows.reduce((sum, r) => sum + (r.clv_percent || 0), 0) / clvRows.length).toFixed(2)
      : null;

    // Aggregate by market
    const byMarket = aggregateByField(picksRows || [], 'market');

    // Aggregate by bookmaker
    const byBookmaker = aggregateByField(picksRows || [], 'bookmaker');

    // CLV by market (from clv_tracking)
    const clvByMarket = {};
    (clvRows || []).forEach(r => {
      if (!r.market) return;
      if (!clvByMarket[r.market]) clvByMarket[r.market] = [];
      clvByMarket[r.market].push(r.clv_percent || 0);
    });

    return {
      totalPicks: overall ? overall.total_picks : 0,
      hits: overall ? overall.hits : 0,
      hitRate: overall ? overall.hit_rate : null,
      avgCLV,
      byMarket,
      byBookmaker,
      clvByMarket,
    };
  } catch (err) {
    console.error('Failed to fetch dashboard stats:', err);
    return null;
  }
}

// Fetch today's projections with player info (including handedness)
async function fetchTodaysProjections() {
  try {
    const today = new Date().toISOString().split('T')[0];
    
    // Get today's projections
    const projections = await sbGet('projections', {
      select: 'mlbam_id,player_name,stat_type,projection,confidence',
      'game_date': `eq.${today}`,
      order: 'confidence.desc',
      limit: 20,
    });

    if (!projections || projections.length === 0) return [];

    // Get player details (including handedness) for all projected players
    const playerIds = [...new Set(projections.map(p => p.mlbam_id))];
    const players = await sbGet('players', {
      select: 'mlbam_id,full_name,team,position,bats,throws',
      'mlbam_id': `in.(${playerIds.join(',')})`,
    });

    // Create lookup map
    const playerMap = {};
    players.forEach(p => {
      playerMap[p.mlbam_id] = p;
    });

    // Merge projections with player data
    return projections.map(proj => ({
      ...proj,
      playerInfo: playerMap[proj.mlbam_id] || {}
    }));
  } catch (err) {
    console.error('Failed to fetch today\'s projections:', err);
    return [];
  }
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------
function aggregateByField(rows, field) {
  const acc = {};
  rows.forEach(row => {
    const key = row[field] || 'Unknown';
    if (!acc[key]) acc[key] = { total: 0, wins: 0 };
    acc[key].total += 1;
    if (row.result === 'win' || row.result === 'W' || row.result === true || row.result === 1) {
      acc[key].wins += 1;
    }
  });
  return Object.entries(acc)
    .map(([name, data]) => ({
      name,
      total: data.total,
      wins: data.wins,
      hitRate: data.total > 0 ? ((data.wins / data.total) * 100).toFixed(1) : '—',
    }))
    .sort((a, b) => b.total - a.total);
}

function formatHitRate(rate) {
  if (rate === null || rate === undefined || rate === '') return '—';
  const num = parseFloat(rate);
  if (isNaN(num)) return '—';
  // Handle both 0-1 range and 0-100 range
  return num <= 1 ? `${(num * 100).toFixed(1)}%` : `${num.toFixed(1)}%`;
}

function formatCLV(clv) {
  if (clv === null || clv === undefined) return '—';
  const num = parseFloat(clv);
  if (isNaN(num)) return '—';
  return num >= 0 ? `+${num}%` : `${num}%`;
}

function formatHandedness(bats, throws) {
  const b = bats || '?';
  const t = throws || '?';
  return `${b}/${t}`;
}

// ---------------------------------------------------------------------------
// DOM population
// ---------------------------------------------------------------------------
function showPrelaunchState() {
  const banner = document.getElementById('prelaunch-banner');
  if (banner) banner.style.display = 'block';

  // Keep stat values as dashes
  ['stat-total-picks', 'stat-hit-rate', 'stat-season-hit-rate', 'stat-avg-clv', 'stat-high-conf'].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.textContent = '—';
  });

  renderEmptyTable('market-table-body', 4);
  renderEmptyTable('bookmaker-table-body', 4);
  
  // Hide projections section if no data
  const projectionsSection = document.getElementById('projections-section');
  if (projectionsSection) projectionsSection.style.display = 'none';
}

function renderEmptyTable(tbodyId, colspan) {
  const tbody = document.getElementById(tbodyId);
  if (!tbody) return;
  tbody.innerHTML = `<tr class="empty-row"><td colspan="${colspan}">No data yet — tracking begins Opening Day 2026</td></tr>`;
}

function populateDashboard(stats) {
  if (!stats || stats.totalPicks === 0) {
    showPrelaunchState();
    return;
  }

  // Hide pre-launch banner when real data exists
  const banner = document.getElementById('prelaunch-banner');
  if (banner) banner.style.display = 'none';

  // Populate stat cards
  const totalPicksEl = document.getElementById('stat-total-picks');
  if (totalPicksEl) totalPicksEl.textContent = stats.totalPicks.toLocaleString();

  const hitRateEl = document.getElementById('stat-hit-rate');
  if (hitRateEl) hitRateEl.textContent = formatHitRate(stats.hitRate);

  const seasonHitRateEl = document.getElementById('stat-season-hit-rate');
  if (seasonHitRateEl) seasonHitRateEl.textContent = formatHitRate(stats.hitRate);

  const avgClvEl = document.getElementById('stat-avg-clv');
  if (avgClvEl) avgClvEl.textContent = formatCLV(stats.avgCLV);

  const highConfEl = document.getElementById('stat-high-conf');
  if (highConfEl) {
    const highConfRate = stats.byMarket.length > 0 ? formatHitRate(stats.byMarket[0].hitRate) : '—';
    highConfEl.textContent = highConfRate;
  }

  // Render market table
  renderMarketTable(stats.byMarket, stats.clvByMarket);

  // Render bookmaker table
  renderBookmakerTable(stats.byBookmaker);

  // Update last-updated timestamp
  const updatedEl = document.getElementById('last-updated');
  if (updatedEl) updatedEl.textContent = new Date().toLocaleString();
}

function renderMarketTable(byMarket, clvByMarket) {
  const tbody = document.getElementById('market-table-body');
  if (!tbody) return;

  if (!byMarket || byMarket.length === 0) {
    renderEmptyTable('market-table-body', 4);
    return;
  }

  tbody.innerHTML = byMarket.map(row => {
    const clvArr = clvByMarket[row.name] || [];
    const avgClv = clvArr.length > 0
      ? formatCLV((clvArr.reduce((s, v) => s + v, 0) / clvArr.length).toFixed(2))
      : '—';
    return `
      <tr>
        <td>${escapeHtml(row.name)}</td>
        <td>${row.hitRate}%</td>
        <td>${row.total}</td>
        <td>${avgClv}</td>
      </tr>
    `;
  }).join('');
}

function renderBookmakerTable(byBookmaker) {
  const tbody = document.getElementById('bookmaker-table-body');
  if (!tbody) return;

  if (!byBookmaker || byBookmaker.length === 0) {
    renderEmptyTable('bookmaker-table-body', 4);
    return;
  }

  tbody.innerHTML = byBookmaker.map(row => `
    <tr>
      <td>${escapeHtml(row.name)}</td>
      <td>${row.hitRate}%</td>
      <td>${row.total}</td>
      <td>—</td>
    </tr>
  `).join('');
}

function renderProjections(projections) {
  const section = document.getElementById('projections-section');
  const tbody = document.getElementById('projections-table-body');
  
  if (!tbody || !section) return;

  if (!projections || projections.length === 0) {
    section.style.display = 'none';
    return;
  }

  section.style.display = 'block';
  
  tbody.innerHTML = projections.map(proj => {
    const p = proj.playerInfo || {};
    const handedness = formatHandedness(p.bats, p.throws);
    const conf = proj.confidence ? `${(proj.confidence * 100).toFixed(0)}%` : '—';
    
    return `
      <tr>
        <td>
          <strong>${escapeHtml(proj.player_name || 'Unknown')}</strong>
          <br>
          <span style="font-size: 0.85rem; color: #a0aec0;">
            ${escapeHtml(p.team || '')} · ${escapeHtml(p.position || '')} · ${handedness}
          </span>
        </td>
        <td>${escapeHtml(proj.stat_type || '')}</td>
        <td><strong>${proj.projection ? proj.projection.toFixed(1) : '—'}</strong></td>
        <td>${conf}</td>
      </tr>
    `;
  }).join('');
}

function escapeHtml(str) {
  const div = document.createElement('div');
  div.appendChild(document.createTextNode(String(str)));
  return div.innerHTML;
}

// ---------------------------------------------------------------------------
// Entry point
// ---------------------------------------------------------------------------
document.addEventListener('DOMContentLoaded', async () => {
  // Show loading state
  ['stat-total-picks', 'stat-hit-rate', 'stat-season-hit-rate', 'stat-avg-clv', 'stat-high-conf'].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.textContent = '...';
  });

  // Fetch all data in parallel
  const [stats, projections] = await Promise.all([
    fetchDashboardStats(),
    fetchTodaysProjections()
  ]);

  populateDashboard(stats);
  
    // Also try static JSON for last-updated timestamp and fallback data
    const staticData = await loadFromStaticJSON();
    updateLastUpdated(staticData);
  renderProjections(projections);
});
