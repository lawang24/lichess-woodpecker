import type { RefObject } from 'react'
import { useMemo, useState } from 'react'
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
  onCompletePuzzle: (puzzleId: string, solved: boolean) => void | Promise<void>
  onReplacePuzzle: (puzzleId: string) => void | Promise<void>
  onUncompletePuzzle: (puzzleId: string) => void | Promise<void>
}

type PuzzleResultAction = 'solved' | 'missed' | 'replace'

interface PuzzleResultActionConfig {
  id: PuzzleResultAction
  label: string
  solved?: boolean
}

const PUZZLE_RESULT_ACTIONS: PuzzleResultActionConfig[] = [
  { id: 'solved', label: 'Solved', solved: true },
  { id: 'missed', label: 'Missed', solved: false },
  { id: 'replace', label: 'Replace', solved: false },
]

function toDateStr(date: Date): string {
  return date.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
}

function PuzzleResultIcon({ action }: { action: PuzzleResultAction }) {
  if (action === 'solved') {
    return (
      <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">
        <path d="M20 6 9 17l-5-5" />
      </svg>
    )
  }

  if (action === 'missed') {
    return (
      <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">
        <path d="M18 6 6 18" />
        <path d="m6 6 12 12" />
      </svg>
    )
  }

  return (
    <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">
      <path d="M3 12a9 9 0 0 1 15.55-6.18" />
      <path d="M19 2v5h-5" />
      <path d="M21 12a9 9 0 0 1-15.55 6.18" />
      <path d="M5 22v-5h5" />
    </svg>
  )
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
  onReplacePuzzle,
  onUncompletePuzzle,
}: TrainingPuzzleListProps) {
  const schedule = getScheduleForCycle(cycle.cycle_number)
  const dailyGoal = Math.ceil(puzzles.length / schedule.days)
  const firstUncompleted = puzzles.findIndex(puzzle => !puzzle.completed)
  const [pendingResultPuzzleIds, setPendingResultPuzzleIds] = useState<Set<string>>(() => new Set())
  const [replacingPuzzleIds, setReplacingPuzzleIds] = useState<Set<string>>(() => new Set())

  function showPuzzleResultActions(puzzleId: string): void {
    setPendingResultPuzzleIds(prev => {
      if (prev.has(puzzleId)) {
        return prev
      }

      const next = new Set(prev)
      next.add(puzzleId)
      return next
    })
  }

  function clearPuzzleResultActions(puzzleId: string): void {
    setPendingResultPuzzleIds(prev => {
      if (!prev.has(puzzleId)) {
        return prev
      }

      const next = new Set(prev)
      next.delete(puzzleId)
      return next
    })
  }

  function setPuzzleReplacing(puzzleId: string, isReplacing: boolean): void {
    setReplacingPuzzleIds(prev => {
      if (prev.has(puzzleId) === isReplacing) {
        return prev
      }

      const next = new Set(prev)
      if (isReplacing) {
        next.add(puzzleId)
      } else {
        next.delete(puzzleId)
      }
      return next
    })
  }

  function completeWithResultAction(puzzleId: string, solved: boolean): void {
    try {
      const completion = onCompletePuzzle(puzzleId, solved)
      void Promise.resolve(completion)
        .then(() => clearPuzzleResultActions(puzzleId))
        .catch(() => undefined)
    } catch {
      // Keep the result buttons visible if completion fails synchronously.
    }
  }

  function replaceWithResultAction(puzzleId: string): void {
    setPuzzleReplacing(puzzleId, true)

    try {
      const replacement = onReplacePuzzle(puzzleId)
      void Promise.resolve(replacement)
        .then(() => clearPuzzleResultActions(puzzleId))
        .catch(() => undefined)
        .finally(() => setPuzzleReplacing(puzzleId, false))
    } catch {
      setPuzzleReplacing(puzzleId, false)
      // Keep the result buttons visible if replacement fails synchronously.
    }
  }

  return (
    <ul className="puzzle-list">
      {puzzles.map((puzzle, index) => {
        const showSeparator = index > 0 && index % dailyGoal === 0
        const dayNum = Math.floor(index / dailyGoal) + 1
        const isReplacing = replacingPuzzleIds.has(puzzle.puzzle_id)
        const showResultActions = !puzzle.completed && !isReplacing && pendingResultPuzzleIds.has(puzzle.puzzle_id)
        const hasPreviousResult = !puzzle.completed && !isReplacing && puzzle.previous_solved !== null
        const resultIndicator = isReplacing
          ? ''
          : puzzle.completed
          ? (puzzle.solved ? '\u2713' : '\u2715')
          : hasPreviousResult
            ? (puzzle.previous_solved ? '\u2713' : '\u2715')
            : ''
        const resultIndicatorClass = [
          'check',
          puzzle.completed && !puzzle.solved ? 'missed' : '',
          hasPreviousResult ? 'previous' : '',
          hasPreviousResult && !puzzle.previous_solved ? 'missed' : '',
        ].filter(Boolean).join(' ')
        const resultIndicatorLabel = puzzle.completed
          ? `${puzzle.solved ? 'Solved' : 'Missed'} in this cycle`
          : hasPreviousResult
            ? `${puzzle.previous_solved ? 'Solved' : 'Missed'} in previous cycle`
            : undefined

        return (
          <li
            key={puzzle.puzzle_id}
            ref={index === firstUncompleted ? currentPuzzleRef : undefined}
          >
            {showSeparator && (
              <div className="day-separator">Day {dayNum}</div>
            )}
            <div
              className={`puzzle-item ${puzzle.completed ? 'completed' : ''} ${isReplacing ? 'replacing' : ''}`}
              aria-busy={isReplacing}
            >
              <a
                className="puzzle-link"
                href={`https://lichess.org/training/${puzzle.puzzle_id}`}
                target="_blank"
                rel="noopener noreferrer"
                onClick={event => {
                  if (isReplacing) {
                    event.preventDefault()
                    return
                  }

                  if (!puzzle.completed) {
                    showPuzzleResultActions(puzzle.puzzle_id)
                  }
                }}
                onContextMenu={event => {
                  if (puzzle.completed) {
                    event.preventDefault()
                    onUncompletePuzzle(puzzle.puzzle_id)
                  }
                }}
              >
                <span
                  className={resultIndicatorClass}
                  aria-label={resultIndicatorLabel}
                  title={resultIndicatorLabel}
                >
                  {resultIndicator}
                </span>
                <span className="num">#{index + 1}</span>
                <span className={`puzzle-id ${isReplacing ? 'loading' : ''}`}>
                  {isReplacing ? 'Loading new puzzle...' : puzzle.puzzle_id}
                </span>
                {puzzle.completed && <span className="rating">{puzzle.rating}</span>}
              </a>
              {showResultActions && (
                <div className="puzzle-result-actions" aria-label={`Result actions for ${puzzle.puzzle_id}`}>
                  {PUZZLE_RESULT_ACTIONS.map(action => (
                    <button
                      key={action.id}
                      type="button"
                      className={`puzzle-result-button ${action.id}`}
                      aria-label={`${action.label} puzzle ${puzzle.puzzle_id}`}
                      title={action.label}
                      onClick={() => {
                        if (action.id === 'replace') {
                          replaceWithResultAction(puzzle.puzzle_id)
                          return
                        }

                        completeWithResultAction(puzzle.puzzle_id, action.solved ?? false)
                      }}
                    >
                      <PuzzleResultIcon action={action.id} />
                    </button>
                  ))}
                </div>
              )}
            </div>
          </li>
        )
      })}
    </ul>
  )
}
