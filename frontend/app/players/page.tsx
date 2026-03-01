import { createClient } from '@supabase/supabase-js'
import PlayersSearch from './PlayersSearch'

export const dynamic = 'force-dynamic'

const supabaseUrl = process.env.NEXT_PUBLIC_SUPABASE_URL || ''
const supabaseAnonKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY || ''

async function getAllPlayers() {
  if (!supabaseUrl || !supabaseAnonKey) {
    return []
  }
  const supabase = createClient(supabaseUrl, supabaseAnonKey)
  const { data, error } = await supabase
    .from('players')
    .select('*')
    .order('full_name', { ascending: true })
    .limit(2000)
  if (error) {
    console.error('Error fetching players:', error)
    return []
  }
  return data || []
}

export default async function PlayersPage() {
  const players = await getAllPlayers()

  return (
    <div>
      <div className="mb-8">
        <h1 className="text-3xl font-bold text-white mb-2">Player Tracker</h1>
        <p className="text-slate-400">
          40-man roster data updated daily. {players.length.toLocaleString()} players tracked.
        </p>
      </div>
      <PlayersSearch players={players} />
    </div>
  )
}
