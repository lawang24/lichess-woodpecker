import { useState, useEffect, useCallback, useRef } from 'react'
import { useParams, Link } from 'react-router-dom'
import { api } from '../api.js'
import { computeTimeline } from '../timeline.js'
import Dashboard from '../components/Dashboard.jsx'
import RatingChart from '../components/RatingChart.jsx'
import TimelineBar from '../components/TimelineBar.jsx'
import Training, { TrainingPuzzleList } from '../components/Training.jsx'

function findCurrentCycle(cycles) {
  return cycles.find(cycle => cycle.completed_at === null) ?? null
}

function getRatingHistoryWindow(cycles) {
  const timeline = computeTimeline(cycles)

  if (timeline.state === 'not-started') {
    return null
  }

  return {
    startDate: timeline.startDate,
    endDate: timeline.state === 'complete' ? timeline.finishDate : timeline.projectedFinish,
  }
}

function SetDetailsSection({ setInfo, puzzleCount, onReset }) {
  return (
    <div className="card-row" style={{ marginBottom: 12 }}>
      <h2 style={{ marginBottom: 0 }}>
        {setInfo.name}
        <span style={{ color: 'var(--text-dim)', fontSize: '0.85rem', marginLeft: 8 }}>
          {puzzleCount} puzzles
          {setInfo.target_rating && ` / ${setInfo.target_rating} elo`}
        </span>
      </h2>
      <button className="secondary" onClick={onReset}>Reset</button>
    </div>
  )
}

function SetTimelinesSection({ history }) {
  return <TimelineBar history={history} />
}

function ActiveCycleSection({
  currentCycle,
  currentCycleDetails,
  onStartCycle,
  onFinishCycle,
  onJumpToCurrentPuzzle,
}) {
  if (!currentCycle) {
    return (
      <div style={{ marginTop: 16 }}>
        <button onClick={onStartCycle}>Start New Cycle</button>
      </div>
    )
  }

  if (!currentCycleDetails) {
    return null
  }

  return (
    <Training
      cycle={currentCycleDetails.cycle}
      puzzles={currentCycleDetails.puzzles}
      onFinishCycle={onFinishCycle}
      onJumpToCurrent={onJumpToCurrentPuzzle}
    />
  )
}

function RatingChartSection({ history }) {
  const ratingHistoryWindow = getRatingHistoryWindow(history.cycles)

  if (!ratingHistoryWindow) {
    return null
  }

  return <RatingChart {...ratingHistoryWindow} />
}

function CompletedCycleInformationSection({ history }) {
  return <Dashboard history={history} />
}

function PuzzleListSection({
  currentCycleDetails,
  currentPuzzleRef,
  onCompletePuzzle,
  onUncompletePuzzle,
}) {
  if (!currentCycleDetails) {
    return null
  }

  return (
    <TrainingPuzzleList
      cycle={currentCycleDetails.cycle}
      puzzles={currentCycleDetails.puzzles}
      currentPuzzleRef={currentPuzzleRef}
      onCompletePuzzle={onCompletePuzzle}
      onUncompletePuzzle={onUncompletePuzzle}
    />
  )
}

export default function SetDetail() {
  const { setId } = useParams()
  const [setOverview, setSetOverview] = useState(null)
  const [setHistory, setSetHistory] = useState(null)
  const [currentCycle, setCurrentCycle] = useState(null)
  const [currentCycleDetails, setCurrentCycleDetails] = useState(null)
  const currentPuzzleRef = useRef(null)
  const latestCycleIdRef = useRef(null)

  const fetchSetDetailData = useCallback(async () => {
    const [overviewResponse, historyResponse] = await Promise.all([
      api(`/api/sets/${setId}`),
      api(`/api/sets/${setId}/history`),
    ])
    const nextCurrentCycle = findCurrentCycle(historyResponse.cycles)
    const cycleDetails = nextCurrentCycle ? await api(`/api/cycles/${nextCurrentCycle.id}`) : null

    return {
      overviewResponse,
      historyResponse,
      nextCurrentCycle,
      cycleDetails,
    }
  }, [setId])

  useEffect(() => {
    let cancelled = false

    void fetchSetDetailData().then(data => {
      if (cancelled) {
        return
      }

      latestCycleIdRef.current = data.nextCurrentCycle?.id ?? null
      setSetOverview(data.overviewResponse)
      setSetHistory(data.historyResponse)
      setCurrentCycle(data.nextCurrentCycle)
      setCurrentCycleDetails(data.cycleDetails)
    })

    return () => {
      cancelled = true
    }
  }, [fetchSetDetailData])

  async function refreshSetDetail() {
    const data = await fetchSetDetailData()
    latestCycleIdRef.current = data.nextCurrentCycle?.id ?? null
    setSetOverview(data.overviewResponse)
    setSetHistory(data.historyResponse)
    setCurrentCycle(data.nextCurrentCycle)
    setCurrentCycleDetails(data.cycleDetails)
  }

  async function refreshCurrentCycleDetails(cycleId = currentCycle?.id) {
    if (!cycleId) return

    const cycleDetails = await api(`/api/cycles/${cycleId}`)
    setCurrentCycleDetails(prev => (latestCycleIdRef.current === cycleId ? cycleDetails : prev))
  }

  async function startCycle() {
    const cycle = await api(`/api/sets/${setId}/cycles`, { method: 'POST' })
    const nextCurrentCycle = { id: cycle.id, cycle_number: cycle.cycle_number, completed_at: null }
    latestCycleIdRef.current = cycle.id
    setCurrentCycle(nextCurrentCycle)
    await refreshCurrentCycleDetails(cycle.id)
  }

  async function resetSet() {
    if (!confirm('Reset this set? All cycle history will be deleted.')) return
    await api(`/api/sets/${setId}/reset`, { method: 'POST' })
    await refreshSetDetail()
  }

  async function finishCurrentCycle() {
    if (!currentCycle) return

    await api(`/api/cycles/${currentCycle.id}/finish`, { method: 'PATCH' })
    await refreshSetDetail()
  }

  async function completePuzzle(puzzleId) {
    if (!currentCycle) return

    await api(`/api/cycles/${currentCycle.id}/complete/${puzzleId}`, { method: 'POST' })
    await refreshCurrentCycleDetails()
  }

  async function uncompletePuzzle(puzzleId) {
    if (!currentCycle) return

    await api(`/api/cycles/${currentCycle.id}/complete/${puzzleId}`, { method: 'DELETE' })
    await refreshCurrentCycleDetails()
  }

  function jumpToCurrentPuzzle() {
    currentPuzzleRef.current?.scrollIntoView({ behavior: 'smooth', block: 'center' })
  }

  if (!setOverview || !setHistory) return null

  const { set: setInfo, puzzles } = setOverview

  return (
    <>
      <Link to="/" className="back-link">&larr; Back to sets</Link>
      <SetDetailsSection setInfo={setInfo} puzzleCount={puzzles.length} onReset={resetSet} />

      <SetTimelinesSection history={setHistory} />

      <ActiveCycleSection
        currentCycle={currentCycle}
        currentCycleDetails={currentCycleDetails}
        onStartCycle={startCycle}
        onFinishCycle={finishCurrentCycle}
        onJumpToCurrentPuzzle={jumpToCurrentPuzzle}
      />

      <CompletedCycleInformationSection history={setHistory} />
      
      <RatingChartSection history={setHistory} />

      <PuzzleListSection
        currentCycleDetails={currentCycleDetails}
        currentPuzzleRef={currentPuzzleRef}
        onCompletePuzzle={completePuzzle}
        onUncompletePuzzle={uncompletePuzzle}
      />
    </>
  )
}
