import type { FormEvent } from 'react'
import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../api'
import { computeTimeline, formatDate } from '../timeline'
import type { SetListItem } from '../types'

export default function Home() {
  const [sets, setSets] = useState<SetListItem[]>([])
  const [name, setName] = useState('Woodpecker Set')
  const [count, setCount] = useState(50)
  const [rating, setRating] = useState(1500)
  const [creating, setCreating] = useState(false)
  const navigate = useNavigate()

  useEffect(() => {
    void loadSets()
  }, [])

  async function loadSets(): Promise<void> {
    const data = await api<SetListItem[]>('/api/sets')
    setSets(data)
  }

  async function createSet(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault()
    setCreating(true)
    try {
      await api('/api/sets', {
        method: 'POST',
        body: JSON.stringify({ name: name.trim() || 'Untitled', count, rating }),
      })
      await loadSets()
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error)
      alert(`Failed to create set: ${message}`)
    } finally {
      setCreating(false)
    }
  }

  async function deleteSet(setId: number): Promise<void> {
    if (!confirm('Delete this set and all its cycles?')) return
    await api(`/api/sets/${setId}`, { method: 'DELETE' })
    await loadSets()
  }

  return (
    <>
      <form className="card" onSubmit={createSet}>
        <h2>Create New Set</h2>
        <div className="form-row">
          <label>Name</label>
          <input
            type="text"
            value={name}
            onChange={e => setName(e.target.value)}
            style={{ flex: 1 }}
          />
        </div>
        <div className="form-row">
          <label>Rating</label>
          <input
            type="number"
            value={rating}
            onChange={e => setRating(parseInt(e.target.value) || 1500)}
            min={400}
            max={3000}
            step={50}
            style={{ width: 100 }}
          />
        </div>
        <div className="form-row">
          <label>Count</label>
          <input
            type="number"
            value={count}
            onChange={e => setCount(parseInt(e.target.value) || 50)}
            min={5}
            max={500}
            style={{ width: 80 }}
          />
          <button type="submit" disabled={creating}>
            {creating ? 'Fetching...' : 'Fetch Puzzles'}
          </button>
        </div>
      </form>

      <h2>Your Sets</h2>
      {sets.length === 0 ? (
        <div className="card" style={{ color: 'var(--text-dim)' }}>
          No puzzle sets yet. Create one above.
        </div>
      ) : (
        sets.map(s => {
          const timeline = computeTimeline(s.cycles || [])
          return (
            <div key={s.id} className="card card-row">
              <div>
                <div>
                  <strong>{s.name}</strong>
                  {s.target_rating && (
                    <span style={{ color: 'var(--text-dim)', marginLeft: 8 }}>
                      {s.target_rating} rated
                    </span>
                  )}
                  <span style={{ color: 'var(--text-dim)', marginLeft: 8 }}>
                    {s.puzzle_count} puzzles
                  </span>
                </div>
                {timeline.state !== 'not-started' && (
                  <div style={{ fontSize: '0.8rem', color: 'var(--text-dim)', marginTop: 4 }}>
                    {formatDate(timeline.startDate)}
                    {' \u2192 '}
                    <span style={{
                      color: timeline.state === 'complete' ? 'var(--success)' : 'var(--text-dim)',
                    }}>
                      {timeline.state === 'complete'
                        ? formatDate(timeline.finishDate)
                        : formatDate(timeline.projectedFinish)}
                    </span>
                  </div>
                )}
              </div>
              <div style={{ display: 'flex', gap: 8 }}>
                <button onClick={() => navigate(`/sets/${s.id}`)}>Open</button>
                <button className="secondary" onClick={() => deleteSet(s.id)}>Delete</button>
              </div>
            </div>
          )
        })
      )}
    </>
  )
}
