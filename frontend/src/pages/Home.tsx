import type { FormEvent } from 'react'
import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../api'
import LoadingCard from '../components/LoadingCard'
import { computeTimeline, formatDate } from '../timeline'
import type { SetListItem } from '../types'

const DEFAULT_PUZZLE_COUNT = 500

export default function Home() {
  const [sets, setSets] = useState<SetListItem[] | null>(null)
  const [setsError, setSetsError] = useState<string | null>(null)
  const [isLoadingSets, setIsLoadingSets] = useState(true)
  const [name, setName] = useState('Woodpecker Set')
  const [count, setCount] = useState(DEFAULT_PUZZLE_COUNT)
  const [rating, setRating] = useState(1500)
  const [creating, setCreating] = useState(false)
  const navigate = useNavigate()

  useEffect(() => {
    void loadSets().catch(error => {
      console.error(error)
    })
  }, [])

  async function loadSets(): Promise<void> {
    setIsLoadingSets(true)
    setSetsError(null)

    try {
      const data = await api<SetListItem[]>('/api/sets')
      setSets(data)
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error)
      setSetsError(message)
      throw error
    } finally {
      setIsLoadingSets(false)
    }
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
      <p className="home-intro">
        Based on{' '}
        <a
          href="https://qualitychess.co.uk/products/improvement/327/the_woodpecker_method_by_axel_smith_and_hans_tikkanen/"
          target="_blank"
          rel="noreferrer"
        >
          The Woodpecker Method
        </a>
        {' '}by GMs Smith and Tikkanen.
        <br />
        Solve a fixed set of Lichess puzzles, then repeat it across six faster cycles: 4 weeks, 2
        weeks, 1 week, 4 days, 2 days, and 1 day until the patterns becomes automatic.
      </p>

      <form className="card" onSubmit={createSet}>
        <h2>Create New Set</h2>
        <p className="form-help">
          Sets are pulled from the Lichess puzzle database. Enter a rating and the app randomly
          draws puzzles from the -200 to +200 Elo band around it.
        </p>
        <div className="set-form-row">
          <label className="set-form-field set-form-field-name">
            <span>Name</span>
            <input
              type="text"
              value={name}
              onChange={e => setName(e.target.value)}
            />
          </label>
          <label className="set-form-field">
            <span>Rating</span>
            <input
              type="number"
              value={rating}
              onChange={e => setRating(parseInt(e.target.value) || 1500)}
              min={400}
              max={3000}
              step={50}
            />
          </label>
          <label className="set-form-field">
            <span>Count</span>
            <input
              type="number"
              value={count}
              onChange={e => setCount(parseInt(e.target.value) || DEFAULT_PUZZLE_COUNT)}
              min={5}
              max={500}
            />
          </label>
          <button type="submit" disabled={creating}>
            {creating ? 'Creating...' : 'Create Puzzle Set'}
          </button>
        </div>
      </form>

      <h2>Your Sets</h2>
      {isLoadingSets ? (
        <LoadingCard>Loading...</LoadingCard>
      ) : setsError ? (
        <div className="card" style={{ color: 'var(--text-dim)' }}>
          Could not load sets: {setsError}
        </div>
      ) : sets && sets.length === 0 ? (
        <div className="card" style={{ color: 'var(--text-dim)' }}>
          No puzzle sets yet. Create one above.
        </div>
      ) : (
        sets?.map(s => {
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
