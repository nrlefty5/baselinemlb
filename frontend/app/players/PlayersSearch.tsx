'use client'

import { useState } from 'react'

interface Player {
  mlbam_id: number
  full_name: string
  team: string
  position: string
  bats?: string
  throws?: string
}

export default function PlayersSearch({ players }: { players: Player[] }) {
  const [search, setSearch] = useState('')
  const [posFilter, setPosFilter] = useState('all')

  const positions = ['all', 'C', '1B', '2B', '3B', 'SS', 'LF', 'CF', 'RF', 'DH', 'SP', 'RP']

  const filtered = players.filter((p) => {
    const matchesSearch = p.full_name?.toLowerCase().includes(search.toLowerCase()) ||
      p.team?.toLowerCase().includes(search.toLowerCase())
    const matchesPos = posFilter === 'all' || p.position === posFilter
    return matchesSearch && matchesPos
  })

  return (
    <div>
      <div className="flex flex-col sm:flex-row gap-3 mb-6">
        <input
          type="text"
          placeholder="Search players or teams..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="flex-1 px-4 py-2 bg-gray-800 border border-gray-700 rounded-lg text-white placeholder-slate-500 focus:outline-none focus:border-blue-500"
        />
        <div className="flex gap-1 flex-wrap">
          {positions.map((pos) => (
            <button
              key={pos}
              onClick={() => setPosFilter(pos)}
              className={`px-3 py-1.5 text-xs font-medium rounded-lg transition-colors ${
                posFilter === pos
                  ? 'bg-blue-600 text-white'
                  : 'bg-gray-800 text-slate-400 hover:bg-gray-700'
              }`}
            >
              {pos === 'all' ? 'All' : pos}
            </button>
          ))}
        </div>
      </div>

      <p className="text-xs text-slate-500 mb-4">
        Showing {filtered.length} of {players.length} players
      </p>

      <div className="overflow-x-auto rounded-lg border border-gray-700">
        <table className="min-w-full">
          <thead>
            <tr className="bg-gray-800 text-left">
              <th className="py-2 px-4 text-xs font-medium text-slate-400 uppercase tracking-wider">Player</th>
              <th className="py-2 px-4 text-xs font-medium text-slate-400 uppercase tracking-wider">Team</th>
              <th className="py-2 px-4 text-xs font-medium text-slate-400 uppercase tracking-wider text-center">Pos</th>
              <th className="py-2 px-4 text-xs font-medium text-slate-400 uppercase tracking-wider text-center">Bats</th>
              <th className="py-2 px-4 text-xs font-medium text-slate-400 uppercase tracking-wider text-center">Throws</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-700">
            {filtered.slice(0, 100).map((p) => (
              <tr key={p.mlbam_id} className="hover:bg-gray-750 transition-colors">
                <td className="py-2 px-4">
                  <a
                    href={`/players/${p.mlbam_id}`}
                    className="font-medium text-blue-400 hover:text-blue-300 transition-colors"
                  >
                    {p.full_name}
                  </a>
                </td>
                <td className="py-2 px-4 text-slate-300">{p.team}</td>
                <td className="py-2 px-4 text-center text-slate-400">{p.position}</td>
                <td className="py-2 px-4 text-center text-slate-400">{p.bats || '--'}</td>
                <td className="py-2 px-4 text-center text-slate-400">{p.throws || '--'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {filtered.length > 100 && (
        <p className="text-xs text-slate-500 mt-3 text-center">
          Showing first 100 of {filtered.length} results. Use search to narrow down.
        </p>
      )}
    </div>
  )
}
