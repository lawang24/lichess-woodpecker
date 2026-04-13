import type { RefObject } from 'react'
import { useMemo } from 'react'
import { Line } from 'react-chartjs-2'
import {
  Chart as ChartJS,
  CategoryScale,
  Filler,
  Legend,
  LineElement,
  LinearScale,
  PointElement,
  Tooltip,
  type ChartData,
  type ChartOptions,
} from 'chart.js'
import { getScheduleForCycle } from '../schedule'
import type { CyclePuzzle, CycleRecord } from '../types'

ChartJS.register(CategoryScale, LinearScale, PointElement, LineElement, Filler, Legend, Tooltip)

interface TrainingProps {
  cycle: CycleRecord
  puzzles: CyclePuzzle[]
  onFinishCycle: () => void
  onJumpToCurrent: () => void
}

interface TrainingPuzzleListProps {
  cycle: CycleRecord
  puzzles: CyclePuzzle[]
  currentPuzzleRef: RefObject<HTMLLIElement | null>
  onCompletePuzzle: (puzzleId: string) => void
  onUncompletePuzzle: (puzzleId: string) => void
}

function toDateStr(date: Date): string {
  return date.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
}

export default function Training({
  cycle,
  puzzles,
  onFinishCycle,
  onJumpToCurrent,
}: TrainingProps) {
  const chartData = useMemo<ChartData<'line', (number | null)[], string> | null>(() => {
    if (puzzles.length === 0) {
      return null
    }

    const total = puzzles.length
    const schedule = getScheduleForCycle(cycle.cycle_number)
    const startDate = new Date(cycle.started_at)
    startDate.setHours(0, 0, 0, 0)

    const today = new Date()
    today.setHours(0, 0, 0, 0)

    const targetEnd = new Date(startDate)
    targetEnd.setDate(targetEnd.getDate() + schedule.days - 1)
    const endDate = today > targetEnd ? today : targetEnd

    const days: Date[] = []
    const cursor = new Date(startDate)
    while (cursor <= endDate) {
      days.push(new Date(cursor))
      cursor.setDate(cursor.getDate() + 1)
    }

    const dailyGoal = total / schedule.days
    const targetLine = days.map((_, index) => Math.min(total, Math.round(dailyGoal * (index + 1))))

    const completionsByDay: Record<string, number> = {}
    for (const puzzle of puzzles) {
      if (puzzle.completed_at) {
        const completedDate = new Date(puzzle.completed_at * 1000)
        const key = `${completedDate.getFullYear()}-${completedDate.getMonth()}-${completedDate.getDate()}`
        completionsByDay[key] = (completionsByDay[key] || 0) + 1
      }
    }

    let cumulative = 0
    const actualLine = days.map(day => {
      const key = `${day.getFullYear()}-${day.getMonth()}-${day.getDate()}`
      cumulative += completionsByDay[key] || 0
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

  const completed = puzzles.filter(puzzle => puzzle.completed).length
  const total = puzzles.length
  const hasCurrentPuzzle = puzzles.some(puzzle => !puzzle.completed)
  const schedule = getScheduleForCycle(cycle.cycle_number)
  const dailyGoal = Math.ceil(total / schedule.days)
  const startDate = new Date(cycle.started_at)
  const today = new Date()
  const daysElapsed = Math.max(1, Math.floor((today.getTime() - startDate.getTime()) / 86400000) + 1)
  const daysRemaining = Math.max(0, schedule.days - daysElapsed)
  const allDone = completed === total && total > 0

  const chartOptions: ChartOptions<'line'> = {
    responsive: true,
    plugins: {
      legend: { labels: { color: '#999' } },
      tooltip: {
        callbacks: {
          label: context => `${context.dataset.label ?? 'Value'}: ${context.parsed.y}`,
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
            <span style={{ color: 'var(--text-dim)' }}> #{cycle.cycle_number}</span>
          </div>
          <div style={{ display: 'flex', gap: 8 }}>
            {hasCurrentPuzzle && (
              <button
                className="secondary"
                onClick={onJumpToCurrent}
              >
                Jump to current
              </button>
            )}
            <button
              onClick={onFinishCycle}
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
    </div>
  )
}

export function TrainingPuzzleList({
  cycle,
  puzzles,
  currentPuzzleRef,
  onCompletePuzzle,
  onUncompletePuzzle,
}: TrainingPuzzleListProps) {
  const schedule = getScheduleForCycle(cycle.cycle_number)
  const dailyGoal = Math.ceil(puzzles.length / schedule.days)
  const firstUncompleted = puzzles.findIndex(puzzle => !puzzle.completed)

  return (
    <ul className="puzzle-list">
      {puzzles.map((puzzle, index) => {
        const showSeparator = index > 0 && index % dailyGoal === 0
        const dayNum = Math.floor(index / dailyGoal) + 1

        return (
          <li
            key={puzzle.puzzle_id}
            ref={index === firstUncompleted ? currentPuzzleRef : undefined}
          >
            {showSeparator && (
              <div className="day-separator">Day {dayNum}</div>
            )}
            <div className={`puzzle-item ${puzzle.completed ? 'completed' : ''}`}>
              <a
                className="puzzle-link"
                href={`https://lichess.org/training/${puzzle.puzzle_id}`}
                target="_blank"
                rel="noopener noreferrer"
                onClick={() => {
                  if (!puzzle.completed) {
                    onCompletePuzzle(puzzle.puzzle_id)
                  }
                }}
                onContextMenu={event => {
                  if (puzzle.completed) {
                    event.preventDefault()
                    onUncompletePuzzle(puzzle.puzzle_id)
                  }
                }}
              >
                <span className="check">{puzzle.completed ? '\u2713' : ''}</span>
                <span className="num">#{index + 1}</span>
                <span>{puzzle.puzzle_id}</span>
                {puzzle.completed && <span className="rating">{puzzle.rating}</span>}
              </a>
            </div>
          </li>
        )
      })}
    </ul>
  )
}
