import { useState, useEffect, useCallback } from 'react'
import { useParams, Link } from 'react-router-dom'
import { api } from '../api.js'
import { computeTimeline } from '../timeline.js'
import Dashboard from '../components/Dashboard.jsx'
import RatingChart from '../components/RatingChart.jsx'
import TimelineBar from '../components/TimelineBar.jsx'
import Training from '../components/Training.jsx'

export default function SetDetail() {
  const { setId } = useParams()
  const [setData, setSetData] = useState(null)
  const [history, setHistory] = useState(null)
  const [activeCycle, setActiveCycle] = useState(null)

  const load = useCallback(async () => {
    const [sd, hist] = await Promise.all([
      api(`/api/sets/${setId}`),
      api(`/api/sets/${setId}/history`),
    ])
    setSetData(sd)
    setHistory(hist)
    const active = hist.cycles.find(c => c.completed_at === null)
    setActiveCycle(active || null)
  }, [setId])

  useEffect(() => { load() }, [load])

  async function startCycle() {
    const cycle = await api(`/api/sets/${setId}/cycles`, { method: 'POST' })
    setActiveCycle({ id: cycle.id, cycle_number: cycle.cycle_number, completed_at: null })
  }

  async function resetSet() {
    if (!confirm('Reset this set? All cycle history will be deleted.')) return
    await api(`/api/sets/${setId}/reset`, { method: 'POST' })
    await load()
  }

  if (!setData || !history) return null

  return (
    <>
      <Link to="/" className="back-link">&larr; Back to sets</Link>
      <div className="card-row" style={{ marginBottom: 12 }}>
        <h2 style={{ marginBottom: 0 }}>
          {setData.set.name}
          <span style={{ color: 'var(--text-dim)', fontSize: '0.85rem', marginLeft: 8 }}>
            {setData.puzzles.length} puzzles
            {setData.set.target_rating && ` / ${setData.set.target_rating} elo`}
          </span>
        </h2>
        <button className="secondary" onClick={resetSet}>Reset</button>
      </div>

      <TimelineBar history={history} />

      <Dashboard history={history} targetRating={setData.set.target_rating} />

      {activeCycle ? (
        <Training
          cycleId={activeCycle.id}
          cycleNumber={activeCycle.cycle_number}
          onFinish={load}
        >
          {(() => {
            const tl = computeTimeline(history.cycles)
            if (tl.state === 'not-started') return null
            const endDate = tl.state === 'complete' ? tl.finishDate : tl.projectedFinish
            return <RatingChart startDate={tl.startDate} endDate={endDate} />
          })()}
        </Training>
      ) : (
        <div style={{ marginTop: 16 }}>
          <button onClick={startCycle}>Start New Cycle</button>
        </div>
      )}
    </>
  )
}
