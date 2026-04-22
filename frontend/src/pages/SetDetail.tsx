import type { RefObject } from 'react'
import { useState, useEffect, useCallback, useRef } from 'react'
import { useParams, Link } from 'react-router-dom'
import { api } from '../api'
import { computeTimeline } from '../timeline'
import Dashboard from '../components/Dashboard'
import TimelineBar from '../components/TimelineBar'
import Training, { TrainingPuzzleList } from '../components/Training'
import type {
  CycleDetailResponse,
  CyclePuzzle,
  CycleRecord,
  PuzzleSet,
  SetHistoryResponse,
  SetOverviewResponse,
  StartCycleResponse,
} from '../types'

type CurrentCycleSummary = Pick<CycleRecord, 'id' | 'cycle_number' | 'completed_at'>

interface SetDetailsSectionProps {
  setInfo: PuzzleSet
  puzzleCount: number
  onReset: () => void
}

interface SetTimelinesSectionProps {
  history: SetHistoryResponse
}

interface ActiveCycleSectionProps {
  currentCycle: CurrentCycleSummary | null
  currentCycleDetails: CycleDetailResponse | null
  onStartCycle: () => void
  onFinishCycle: () => void
  onJumpToCurrentPuzzle: () => void
}

interface CompletedCycleInformationSectionProps {
  history: SetHistoryResponse
}

interface PuzzleListSectionProps {
  currentCycleDetails: CycleDetailResponse | null
  currentPuzzleRef: RefObject<HTMLLIElement | null>
  onCompletePuzzle: (puzzleId: string) => void
  onUncompletePuzzle: (puzzleId: string) => void
}

function getPendingPuzzleKey(cycleId: number, puzzleId: string): string {
  return `${cycleId}:${puzzleId}`
}

function findCurrentCycle(cycles: readonly CurrentCycleSummary[]): CurrentCycleSummary | null {
  return cycles.find(cycle => cycle.completed_at === null) ?? null
}

function SetDetailsSection({ setInfo, puzzleCount, onReset }: SetDetailsSectionProps) {
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

function SetTimelinesSection({ history }: SetTimelinesSectionProps) {
  return <TimelineBar history={history} />
}

function ActiveCycleSection({
  currentCycle,
  currentCycleDetails,
  onStartCycle,
  onFinishCycle,
  onJumpToCurrentPuzzle,
}: ActiveCycleSectionProps) {
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

function CompletedCycleInformationSection({ history }: CompletedCycleInformationSectionProps) {
  return <Dashboard history={history} />
}

function PuzzleListSection({
  currentCycleDetails,
  currentPuzzleRef,
  onCompletePuzzle,
  onUncompletePuzzle,
}: PuzzleListSectionProps) {
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
  const { setId } = useParams<{ setId: string }>()
  const [setOverview, setSetOverview] = useState<SetOverviewResponse | null>(null)
  const [setHistory, setSetHistory] = useState<SetHistoryResponse | null>(null)
  const [currentCycle, setCurrentCycle] = useState<CurrentCycleSummary | null>(null)
  const [currentCycleDetails, setCurrentCycleDetails] = useState<CycleDetailResponse | null>(null)
  const currentPuzzleRef = useRef<HTMLLIElement | null>(null)
  const latestCycleIdRef = useRef<number | null>(null)
  const pendingPuzzleKeysRef = useRef<Set<string>>(new Set())

  const applyCurrentCycleDetails = useCallback(
    (
      next:
        | CycleDetailResponse
        | null
        | ((prev: CycleDetailResponse | null) => CycleDetailResponse | null),
    ): void => {
      setCurrentCycleDetails(next)
    },
    [],
  )

  const updatePuzzleInCurrentCycle = useCallback(
    (
      cycleId: number,
      puzzleId: string,
      updater: (puzzle: CyclePuzzle) => CyclePuzzle,
    ): CyclePuzzle | null => {
      if (!currentCycleDetails || currentCycleDetails.cycle.id !== cycleId) {
        return null
      }

      const existingPuzzle = currentCycleDetails.puzzles.find(puzzle => puzzle.puzzle_id === puzzleId) ?? null

      if (!existingPuzzle) {
        return null
      }

      applyCurrentCycleDetails(prev => {
        if (!prev || prev.cycle.id !== cycleId) {
          return prev
        }

        let didUpdate = false
        const puzzles = prev.puzzles.map(puzzle => {
          if (puzzle.puzzle_id !== puzzleId) {
            return puzzle
          }

          didUpdate = true
          return updater(puzzle)
        })

        if (!didUpdate) {
          return prev
        }

        return {
          ...prev,
          puzzles,
        }
      })

      return existingPuzzle
    },
    [applyCurrentCycleDetails, currentCycleDetails],
  )

  const fetchSetDetailData = useCallback(async (): Promise<{
    overviewResponse: SetOverviewResponse
    historyResponse: SetHistoryResponse
    nextCurrentCycle: CurrentCycleSummary | null
    cycleDetails: CycleDetailResponse | null
  }> => {
    if (!setId) {
      throw new Error('Set id is required')
    }

    const [overviewResponse, historyResponse] = await Promise.all([
      api<SetOverviewResponse>(`/api/sets/${setId}`),
      api<SetHistoryResponse>(`/api/sets/${setId}/history`),
    ])
    const nextCurrentCycle = findCurrentCycle(historyResponse.cycles)
    const cycleDetails = nextCurrentCycle
      ? await api<CycleDetailResponse>(`/api/cycles/${nextCurrentCycle.id}`)
      : null

    return {
      overviewResponse,
      historyResponse,
      nextCurrentCycle,
      cycleDetails,
    }
  }, [setId])

  useEffect(() => {
    let cancelled = false

    void fetchSetDetailData()
      .then(data => {
        if (cancelled) {
          return
        }

        latestCycleIdRef.current = data.nextCurrentCycle?.id ?? null
        setSetOverview(data.overviewResponse)
        setSetHistory(data.historyResponse)
        setCurrentCycle(data.nextCurrentCycle)
        applyCurrentCycleDetails(data.cycleDetails)
      })
      .catch(error => {
        if (!cancelled) {
          console.error(error)
        }
      })

    return () => {
      cancelled = true
    }
  }, [applyCurrentCycleDetails, fetchSetDetailData])

  async function refreshSetDetail(): Promise<void> {
    const data = await fetchSetDetailData()
    latestCycleIdRef.current = data.nextCurrentCycle?.id ?? null
    setSetOverview(data.overviewResponse)
    setSetHistory(data.historyResponse)
    setCurrentCycle(data.nextCurrentCycle)
    applyCurrentCycleDetails(data.cycleDetails)
  }

  async function refreshCurrentCycleDetails(
    cycleId: number | null = currentCycle?.id ?? null,
  ): Promise<void> {
    if (!cycleId) {
      return
    }

    const cycleDetails = await api<CycleDetailResponse>(`/api/cycles/${cycleId}`)
    applyCurrentCycleDetails(prev => (latestCycleIdRef.current === cycleId ? cycleDetails : prev))
  }

  async function startCycle(): Promise<void> {
    if (!setId) {
      return
    }

    const cycle = await api<StartCycleResponse>(`/api/sets/${setId}/cycles`, { method: 'POST' })
    const nextCurrentCycle: CurrentCycleSummary = {
      id: cycle.id,
      cycle_number: cycle.cycle_number,
      completed_at: null,
    }
    latestCycleIdRef.current = cycle.id
    setCurrentCycle(nextCurrentCycle)
    await refreshCurrentCycleDetails(cycle.id)
  }

  async function resetSet(): Promise<void> {
    if (!setId) {
      return
    }

    if (!confirm('Reset this set? All cycle history will be deleted.')) {
      return
    }

    await api(`/api/sets/${setId}/reset`, { method: 'POST' })
    await refreshSetDetail()
  }

  async function finishCurrentCycle(): Promise<void> {
    if (!currentCycle) {
      return
    }

    await api(`/api/cycles/${currentCycle.id}/finish`, { method: 'PATCH' })
    await refreshSetDetail()
  }

  async function completePuzzle(puzzleId: string): Promise<void> {
    if (!currentCycle) {
      return
    }

    const cycleId = currentCycle.id
    const pendingPuzzleKey = getPendingPuzzleKey(cycleId, puzzleId)
    if (pendingPuzzleKeysRef.current.has(pendingPuzzleKey)) {
      return
    }

    const previousPuzzle = updatePuzzleInCurrentCycle(cycleId, puzzleId, puzzle => ({
      ...puzzle,
      completed: true,
      completed_at: Date.now() / 1000,
    }))

    if (!previousPuzzle || previousPuzzle.completed) {
      return
    }

    pendingPuzzleKeysRef.current.add(pendingPuzzleKey)

    try {
      await api(`/api/cycles/${cycleId}/complete/${puzzleId}`, { method: 'POST' })
    } catch (error) {
      updatePuzzleInCurrentCycle(cycleId, puzzleId, () => previousPuzzle)
      throw error
    } finally {
      pendingPuzzleKeysRef.current.delete(pendingPuzzleKey)
    }
  }

  async function uncompletePuzzle(puzzleId: string): Promise<void> {
    if (!currentCycle) {
      return
    }

    const cycleId = currentCycle.id
    const pendingPuzzleKey = getPendingPuzzleKey(cycleId, puzzleId)
    if (pendingPuzzleKeysRef.current.has(pendingPuzzleKey)) {
      return
    }

    const previousPuzzle = updatePuzzleInCurrentCycle(cycleId, puzzleId, puzzle => ({
      ...puzzle,
      completed: false,
      completed_at: null,
    }))

    if (!previousPuzzle || !previousPuzzle.completed) {
      return
    }

    pendingPuzzleKeysRef.current.add(pendingPuzzleKey)

    try {
      await api(`/api/cycles/${cycleId}/complete/${puzzleId}`, { method: 'DELETE' })
    } catch (error) {
      updatePuzzleInCurrentCycle(cycleId, puzzleId, () => previousPuzzle)
      throw error
    } finally {
      pendingPuzzleKeysRef.current.delete(pendingPuzzleKey)
    }
  }

  function jumpToCurrentPuzzle(): void {
    currentPuzzleRef.current?.scrollIntoView({ behavior: 'smooth', block: 'center' })
  }

  if (!setId || !setOverview || !setHistory) {
    return null
  }

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

      <PuzzleListSection
        currentCycleDetails={currentCycleDetails}
        currentPuzzleRef={currentPuzzleRef}
        onCompletePuzzle={completePuzzle}
        onUncompletePuzzle={uncompletePuzzle}
      />
    </>
  )
}
