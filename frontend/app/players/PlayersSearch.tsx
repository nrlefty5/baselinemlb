'use client'

import { useState, useMemo } from 'react'

interface Player {
  mlbam_id: number
  full_name: string
  team: string | null
  position: string | null
  bats: string | null
  throws: string | null
}

function PlayerCard({ player }: { player: Player }) {
  return (
    <div className="bg-gray-800 border border-gray-700 rounded-lg p-4 hover:border-green-500 transition-colors">
      <div className="flex items-start justify-between mb-3">
        <div>
          <div className="text-lg font-semibold text-white">{player.full_name}</div>
          <div className="text-sm text-slate-400 mt-0.5">
            {player.team || 'FA'} &bull; {player.position || '--'}
          </div>
        </div>
        <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-gray-700 text-slate-300">
          {player.position || '--'}
        </span>
      </div>
      {(player.bats || player.throws) && (
        <div className="mt-2 pt-2 border-t border-gray-700 flex gap-4 text-xs text-slate-400">
          {player.bats && (
            <span>Bats: <span className="text-slate-300">{player.bats}</span></span>
          )}
          {player.throws && (
            <span>Throws: <span className="text-slate-300">{player.throws}</span></span>
          )}
        </div>
      )}
    </div>
  )
}

const POSITIONS = ['ALL', 'SP', 'RP', 'C', '1B', '2B', '3B', 'SS', 'LF', 'CF', 'RF', 'DH', 'OF']

export default function PlayersSearch({ players }: { players: Player[] }) {
  const [query, setQuery] = useState('')
  const [posFilter, setPosFilter] = useState('ALL')

  const filtered = useMemo(() => {
    const q = query.toLowerCase().trim()
    return players.filter((p) => {
      const matchesQuery =
        !q ||
        p.full_name.toLowerCase().includes(q) ||
        (p.team || '').toLowerCase().includes(q) ||
        (p.position || '').toLowerCase().includes(q)

      const matchesPos =
        posFilter === 'ALL' || p.position === posFilter

      return matchesQuery && matchesPos
    })
  }, [players, query, posFilter])

  const pitchers = filtered.filter((p) => ['SP', 'RP', 'P'].includes(p.position || ''))
  const batters = filtered.filter((p) => !['SP', 'RP', 'P'].includes(p.position || ''))

  return (
    <div>
      {/* Search + Filter bar */}
      <div className="flex flex-col sm:flex-row gap-3 mb-8">
        <div className="relative flex-1">
          <input
            type="text"
            placeholder="Search by name, team, or position..."
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            className="w-full bg-gray-800 border border-gray-700 rounded-lg px-4 py-2.5 text-white placeholder-slate-500 focus:outline-none focus:border-blue-500 focus:ring-1 focus:ring-blue-500 transition-colors"
          />
          {query && (
            <button
              onClick={() => setQuery('')}
              className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-400 hover:text-white transition-colors"
            >
              ×
            </button>
          )}
        </div>
        <div className="flex flex-wrap gap-1.5">
          {POSITIONS.map((pos) => (
            <button
              key={pos}
              onClick={() => setPosFilter(pos)}
              className={`px-3 py-1.5 rounded-md text-xs font-medium transition-colors ${
                posFilter === pos
                  ? 'bg-blue-600 text-white'
                  : 'bg-gray-800 text-slate-400 hover:text-white border border-gray-700'
              }`}
            >
              {pos}
            </button>
          ))}
        </div>
      </div>

      {/* Results count */}
      <p className="text-slate-500 text-sm mb-6">
        {filtered.length} player{filtered.length !== 1 ? 's' : ''} found
        {query ? ` for "${query}"` : ''}
        {posFilter !== 'ALL' ? ` at ${posFilter}` : ''}
      </p>

      {filtered.length === 0 ? (
        <div className="text-center py-16">
          <div className="text-4xl mb-4">⚾</div>
          <h2 className="text-xl font-semibold text-slate-400 mb-2">No players found</h2>
          <p className="text-slate-500">
            Try a different search term or position filter.
          </p>
        </div>
      ) : (
        <div className="space-y-8">
          {pitchers.length > 0 && (
            <div>
              <h2 className="text-xl font-semibold text-white mb-4">
                Pitchers <span className="text-slate-500 font-normal text-base">({pitchers.length})</span>
              </h2>
              <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
                {pitchers.map((player) => (
                  <PlayerCard key={player.mlbam_id} player={player} />
                ))}
              </div>
            </div>
          )}
          {batters.length > 0 && (
            <div>
              <h2 className="text-xl font-semibold text-white mb-4">
                Position Players <span className="text-slate-500 font-normal text-base">({batters.length})</span>
              </h2>
              <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
                {batters.map((player) => (
                  <PlayerCard key={player.mlbam_id} player={player} />
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
