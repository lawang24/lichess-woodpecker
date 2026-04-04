import { useState, useEffect, useCallback, useMemo, useRef } from 'react'
import { Line } from 'react-chartjs-2'
import {
  Chart as ChartJS,
  CategoryScale,
  LinearScale,
  PointElement,
  LineElement,
  Filler,
  Legend,
  Tooltip,
} from 'chart.js'
import { api } from '../api.js'
import { getScheduleForCycle } from '../schedule.js'

ChartJS.register(CategoryScale, LinearScale, PointElement, LineElement, Filler, Legend, Tooltip)

function toDateStr(d) {
  return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
}

export default function Training({ cycleId, cycleNumber, onFinish, children }) {
  const [puzzles, setPuzzles] = useState([])
  const [cycle, setCycle] = useState(null)
  const currentRef = useRef(null)

  const loadCycle = useCallback(async () => {
    const data = await api(`/api/cycles/${cycleId}`)
    setPuzzles(data.puzzles)
    setCycle(data.cycle)
  }, [cycleId])

  useEffect(() => { loadCycle() }, [loadCycle])

  async function completePuzzle(puzzleId) {
    await api(`/api/cycles/${cycleId}/complete/${puzzleId}`, { method: 'POST' })
    await loadCycle()
  }

  async function uncompletePuzzle(puzzleId) {
    await api(`/api/cycles/${cycleId}/complete/${puzzleId}`, { method: 'DELETE' })
    await loadCycle()
  }

  async function finishCycle() {
    await api(`/api/cycles/${cycleId}/finish`, { method: 'PATCH' })
    onFinish()
  }

  const chartData = useMemo(() => {
    if (!cycle || puzzles.length === 0) return null

    const total = puzzles.length
    const schedule = getScheduleForCycle(cycle.cycle_number)
    const startDate = new Date(cycle.started_at)
    startDate.setHours(0, 0, 0, 0)

    const today = new Date()
    today.setHours(0, 0, 0, 0)

    // Build day labels from cycle start to max(today, target end)
    const targetEnd = new Date(startDate)
    targetEnd.setDate(targetEnd.getDate() + schedule.days - 1)
    const endDate = today > targetEnd ? today : targetEnd

    const days = []
    const d = new Date(startDate)
    while (d <= endDate) {
      days.push(new Date(d))
      d.setDate(d.getDate() + 1)
    }

    // Cumulative target: linear ramp to total over target days
    const dailyGoal = total / schedule.days
    const targetLine = days.map((_, i) => Math.min(total, Math.round(dailyGoal * (i + 1))))

    // Count completions per day
    const completionsByDay = {}
    for (const p of puzzles) {
      if (p.completed_at) {
        const cd = new Date(p.completed_at * 1000)
        const key = `${cd.getFullYear()}-${cd.getMonth()}-${cd.getDate()}`
        completionsByDay[key] = (completionsByDay[key] || 0) + 1
      }
    }

    // Cumulative actual
    let cumulative = 0
    const actualLine = days.map(day => {
      const key = `${day.getFullYear()}-${day.getMonth()}-${day.getDate()}`
      cumulative += (completionsByDay[key] || 0)
      // Only plot up to today
      return day <= today ? cumulative : null
    })

    return {
      labels: days.map(toDateStr),
      datasets: [
        {
          label: 'Target',
          data: targetLine,
          borderColor: '#4ecca3',
          borderDash: [5, 5],
          backgroundColor: 'transparent',
          fill: false,
          tension: 0.1,
          pointRadius: 0,
        },
        {
          label: 'Actual',
          data: actualLine,
          borderColor: '#e94560',
          backgroundColor: 'rgba(233,69,96,0.1)',
          fill: true,
          tension: 0.1,
          spanGaps: false,
        },
      ],
    }
  }, [cycle, puzzles])

  if (!cycle) return null

  const completed = puzzles.filter(p => p.completed).length
  const total = puzzles.length
  const firstUncompleted = puzzles.findIndex(p => !p.completed)
  const schedule = getScheduleForCycle(cycle.cycle_number)
  const dailyGoal = Math.ceil(total / schedule.days)
  const startDate = new Date(cycle.started_at)
  const daysElapsed = Math.max(1, Math.floor((Date.now() - startDate) / 86400000) + 1)
  const daysRemaining = Math.max(0, schedule.days - daysElapsed)
  const allDone = completed === total && total > 0

  const chartOptions = {
    responsive: true,
    plugins: {
      legend: { labels: { color: '#999' } },
      tooltip: {
        callbacks: {
          label: (ctx) => `${ctx.dataset.label}: ${ctx.parsed.y}`,
        },
      },
    },
    scales: {
      y: { beginAtZero: true, grid: { color: '#333' }, ticks: { color: '#999' } },
      x: { grid: { color: '#333' }, ticks: { color: '#999' } },
    },
  }

  return (
    <div style={{ marginTop: 16 }}>
      <div className="card">
        <div className="card-row">
          <div>
            <strong>Active Cycle</strong>
            <span style={{ color: 'var(--text-dim)' }}> #{cycleNumber}</span>
          </div>
          <div style={{ display: 'flex', gap: 8 }}>
            {firstUncompleted >= 0 && (
              <button
                className="secondary"
                onClick={() => currentRef.current?.scrollIntoView({ behavior: 'smooth', block: 'center' })}
              >
                Jump to current
              </button>
            )}
            <button
              onClick={finishCycle}
              style={allDone ? { background: 'var(--success)' } : undefined}
            >
              Finish Cycle
            </button>
          </div>
        </div>

        <div className="cycle-goals">
          <div className="goals-grid">
            <div className="goal-item">
              <div className="goal-value">{schedule.label}</div>
              <div className="goal-label">Target</div>
            </div>
            <div className="goal-item">
              <div className="goal-value">{dailyGoal}/day</div>
              <div className="goal-label">Daily Goal</div>
            </div>
            <div className="goal-item">
              <div className="goal-value">{completed}/{total}</div>
              <div className="goal-label">Progress</div>
            </div>
            <div className="goal-item">
              <div className="goal-value">{daysRemaining}d</div>
              <div className="goal-label">Remaining</div>
            </div>
          </div>
        </div>

        <div className="progress-bar">
          <div
            className="progress-fill"
            style={{ width: `${total > 0 ? (completed / total) * 100 : 0}%` }}
          />
        </div>
        <div style={{ textAlign: 'center', color: 'var(--text-dim)', fontSize: '0.85rem', marginBottom: 12 }}>
          {completed} / {total}
        </div>
      </div>

      {chartData && (
        <div className="card">
          <Line data={chartData} options={chartOptions} />
        </div>
      )}

      {children}

      <ul className="puzzle-list">
        {puzzles.map((p, i) => {
          const showSeparator = i > 0 && i % dailyGoal === 0
          const dayNum = Math.floor(i / dailyGoal) + 1
          return (
            <li key={p.puzzle_id} ref={i === firstUncompleted ? currentRef : undefined}>
              {showSeparator && (
                <div className="day-separator">Day {dayNum}</div>
              )}
              <div className={`puzzle-item ${p.completed ? 'completed' : ''}`}>
                <a
                  className="puzzle-link"
                  href={`https://lichess.org/training/${p.puzzle_id}`}
                  target="_blank"
                  rel="noopener noreferrer"
                  onClick={() => { if (!p.completed) completePuzzle(p.puzzle_id) }}
                  onContextMenu={(e) => { if (p.completed) { e.preventDefault(); uncompletePuzzle(p.puzzle_id) } }}
                >
                  <span className="check">{p.completed ? '\u2713' : ''}</span>
                  <span className="num">#{i + 1}</span>
                  <span>{p.puzzle_id}</span>
                  {p.completed && <span className="rating">{p.rating}</span>}
                </a>
              </div>
            </li>
          )
        })}
      </ul>
    </div>
  )
}
