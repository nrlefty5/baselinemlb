// frontend/app/components/ExportButton.tsx
// ============================================================
// BaselineMLB — Tier-Aware CSV Export Button (Issue #8)
//
// Usage:
//   <ExportButton exportType="best_bets" />
//   <ExportButton exportType="edges" />
//   <ExportButton exportType="projections" />
//   <ExportButton exportType="players" filters={{ player_id: '12345' }} />
//
// Handles:
//   - single_a: locked state with upgrade CTA
//   - double_a: shows remaining count, blocks when at limit
//   - triple_a/the_show: unlimited, no counter
// ============================================================

'use client';

import { useState, useEffect, useCallback } from 'react';
import { createClientComponentClient } from '@supabase/auth-helpers-nextjs';
import { normalizeTier, hasAccess, EXPORT_LIMITS, type TierName, type ExportType } from '@/app/lib/tiers';

interface ExportButtonProps {
  exportType: ExportType;
  filters?: Record<string, string>;
  className?: string;
}

interface ExportStatus {
  tier: TierName;
  exports_used: number | null;
  exports_limit: number | null;
  exports_remaining: number | null;
  unlimited: boolean;
  allowed_types: string[];
}

export default function ExportButton({
  exportType,
  filters,
  className = '',
}: ExportButtonProps) {
  const supabase = createClientComponentClient();
  const [status, setStatus] = useState<ExportStatus | null>(null);
  const [loading, setLoading] = useState(false);
  const [downloading, setDownloading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetchStatus = useCallback(async () => {
    try {
      const {
        data: { session },
      } = await supabase.auth.getSession();
      if (!session) {
        setStatus(null);
        return;
      }

      const res = await fetch('/api/export', {
        method: 'GET',
        headers: {
          Authorization: `Bearer ${session.access_token}`,
        },
      });

      if (res.ok) {
        const data = await res.json();
        setStatus(data);
      }
    } catch {
      // Silently fail — button will show in locked state
    }
  }, [supabase]);

  useEffect(() => {
    fetchStatus();
  }, [fetchStatus]);

  async function handleExport() {
    setError(null);
    setDownloading(true);

    try {
      const {
        data: { session },
      } = await supabase.auth.getSession();

      if (!session) {
        window.location.href = '/login?redirect=' + window.location.pathname;
        return;
      }

      const res = await fetch('/api/export', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${session.access_token}`,
        },
        body: JSON.stringify({ export_type: exportType, filters }),
      });

      if (!res.ok) {
        const data = await res.json();
        if (res.status === 403 || res.status === 429) {
          setError(data.error);
        } else {
          setError(data.error || 'Export failed');
        }
        return;
      }

      // Trigger file download
      const blob = await res.blob();
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download =
        res.headers.get('content-disposition')?.match(/filename="(.+)"/)?.[1] ||
        `baselinemlb_${exportType}.csv`;
      document.body.appendChild(a);
      a.click();
      window.URL.revokeObjectURL(url);
      a.remove();

      // Refresh status to update remaining count
      await fetchStatus();
    } catch {
      setError('Export failed. Please try again.');
    } finally {
      setDownloading(false);
    }
  }

  // ---- Determine button state ----

  // Not logged in
  if (!status) {
    return (
      <a
        href="/login"
        className={`inline-flex items-center gap-2 rounded-lg bg-gray-800 px-3 py-2 text-xs font-medium text-gray-400 hover:bg-gray-700 transition-colors ${className}`}
      >
        <DownloadIcon className="h-4 w-4" />
        Log in to export
      </a>
    );
  }

  // Tier doesn't support this export type
  const limits = EXPORT_LIMITS[status.tier];
  const typeAllowed = limits.allowed_types.includes(exportType);

  if (!typeAllowed) {
    const requiredTier =
      exportType === 'historical'
        ? 'The Show'
        : limits.max_per_week === 0
        ? 'Double-A'
        : 'Triple-A';

    return (
      <a
        href="/pricing"
        className={`inline-flex items-center gap-2 rounded-lg bg-gray-800/50 border border-gray-700 px-3 py-2 text-xs font-medium text-gray-500 hover:border-emerald-600 hover:text-emerald-400 transition-colors ${className}`}
      >
        <LockIcon className="h-4 w-4" />
        Upgrade to {requiredTier} for CSV export
      </a>
    );
  }

  // At weekly limit (Double-A)
  if (
    status.exports_remaining !== null &&
    status.exports_remaining !== undefined &&
    status.exports_remaining <= 0 &&
    !status.unlimited
  ) {
    return (
      <div className={`inline-flex flex-col gap-1 ${className}`}>
        <button
          disabled
          className="inline-flex items-center gap-2 rounded-lg bg-gray-800/50 px-3 py-2 text-xs font-medium text-gray-500 cursor-not-allowed"
        >
          <DownloadIcon className="h-4 w-4" />
          Weekly limit reached
        </button>
        <a
          href="/pricing"
          className="text-xs text-emerald-500 hover:text-emerald-400"
        >
          Upgrade for unlimited →
        </a>
      </div>
    );
  }

  // Available to export
  return (
    <div className={`inline-flex flex-col gap-1 ${className}`}>
      <button
        onClick={handleExport}
        disabled={downloading}
        className="inline-flex items-center gap-2 rounded-lg bg-emerald-600/20 border border-emerald-600/40 px-3 py-2 text-xs font-medium text-emerald-400 hover:bg-emerald-600/30 hover:border-emerald-500 transition-colors disabled:opacity-50"
      >
        <DownloadIcon className="h-4 w-4" />
        {downloading ? 'Downloading...' : 'Download CSV'}
      </button>

      {/* Show remaining count for limited tiers */}
      {!status.unlimited &&
        status.exports_remaining !== null &&
        status.exports_remaining !== undefined && (
          <span className="text-xs text-gray-500">
            {status.exports_remaining} of {status.exports_limit} weekly exports
            remaining
          </span>
        )}

      {/* Error message */}
      {error && <span className="text-xs text-red-400">{error}</span>}
    </div>
  );
}

// ---- Icons ----

function DownloadIcon({ className }: { className?: string }) {
  return (
    <svg
      className={className}
      fill="none"
      viewBox="0 0 24 24"
      strokeWidth={2}
      stroke="currentColor"
    >
      <path
        strokeLinecap="round"
        strokeLinejoin="round"
        d="M3 16.5v2.25A2.25 2.25 0 005.25 21h13.5A2.25 2.25 0 0021 18.75V16.5M16.5 12L12 16.5m0 0L7.5 12m4.5 4.5V3"
      />
    </svg>
  );
}

function LockIcon({ className }: { className?: string }) {
  return (
    <svg
      className={className}
      fill="none"
      viewBox="0 0 24 24"
      strokeWidth={2}
      stroke="currentColor"
    >
      <path
        strokeLinecap="round"
        strokeLinejoin="round"
        d="M16.5 10.5V6.75a4.5 4.5 0 10-9 0v3.75m-.75 11.25h10.5a2.25 2.25 0 002.25-2.25v-6.75a2.25 2.25 0 00-2.25-2.25H6.75a2.25 2.25 0 00-2.25 2.25v6.75a2.25 2.25 0 002.25 2.25z"
      />
    </svg>
  );
}
