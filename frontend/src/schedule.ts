import type { ScheduleEntry } from './types'

export const WOODPECKER_SCHEDULE: ScheduleEntry[] = [
  { label: '4 Weeks', days: 28, breakDays: 1 },
  { label: '2 Weeks', days: 14, breakDays: 1 },
  { label: '1 Week', days: 7, breakDays: 1 },
  { label: '4 Days', days: 4, breakDays: 1 },
  { label: '2 Days', days: 2, breakDays: 1 },
  { label: '1 Day', days: 1, breakDays: 0 },
]

export function getScheduleForCycle(cycleNumber: number): ScheduleEntry {
  const idx = Math.min(cycleNumber - 1, WOODPECKER_SCHEDULE.length - 1)
  return WOODPECKER_SCHEDULE[idx]!
}
