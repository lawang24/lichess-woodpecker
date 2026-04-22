export interface User {
  id: number
  provider: string
  provider_user_id: string
  provider_username: string
}

export interface PuzzleSet {
  id: number
  name: string
  target_rating: number | null
  created_at: string
}

export interface PuzzleSetItem {
  id: number
  set_id: number
  puzzle_id: string
  rating: number
  position: number
}

export interface CycleSummary {
  id: number
  set_id: number
  cycle_number: number
  started_at: string
  completed_at: string | null
}

export interface CycleRecord extends CycleSummary {
  completed_count: number | null
  duration_days: number | null
}

export interface CyclePuzzle extends PuzzleSetItem {
  completed: boolean
  completed_at: number | null
}

export interface SetListItem extends PuzzleSet {
  puzzle_count: number
  cycles: CycleSummary[]
}

export interface SetOverviewResponse {
  set: PuzzleSet
  puzzles: PuzzleSetItem[]
}

export interface SetHistoryResponse {
  cycles: CycleRecord[]
  total_puzzles: number
}

export interface CycleDetailResponse {
  cycle: CycleRecord
  puzzles: CyclePuzzle[]
}

export interface StartCycleResponse {
  id: number
  cycle_number: number
}

export interface ScheduleEntry {
  label: string
  days: number
  breakDays: number
}

export type Timeline =
  | { state: 'not-started' }
  | {
      state: 'complete'
      startDate: Date
      dayN: number
      finishDate: Date
    }
  | {
      state: 'in-progress'
      startDate: Date
      dayN: number
      projectedFinish: Date
      behindSchedule: boolean
    }
