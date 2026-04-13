import { WOODPECKER_SCHEDULE, getScheduleForCycle } from './schedule'
import type { CycleSummary, Timeline } from './types'

function hasCompletedAt(cycle: CycleSummary): cycle is CycleSummary & { completed_at: string } {
  return cycle.completed_at !== null
}

export function computeTimeline(cycles: readonly CycleSummary[]): Timeline {
  const totalCycles = WOODPECKER_SCHEDULE.length
  const sorted = [...cycles].sort((a, b) => a.cycle_number - b.cycle_number)

  if (sorted.length === 0) return { state: 'not-started' }

  const startDate = new Date(sorted[0].started_at)

  const today = new Date()
  today.setHours(0, 0, 0, 0)
  const startDay = new Date(startDate)
  startDay.setHours(0, 0, 0, 0)
  const dayN = Math.floor((today.getTime() - startDay.getTime()) / 86400000) + 1

  const activeCycle = sorted.find(c => c.completed_at === null)
  const completedCycles = sorted.filter(hasCompletedAt)

  // All done
  if (!activeCycle && completedCycles.length >= totalCycles) {
    const lastCompleted = completedCycles[completedCycles.length - 1]
    return {
      state: 'complete',
      startDate,
      dayN,
      finishDate: new Date(lastCompleted.completed_at),
    }
  }

  let remainingDays = 0

  if (activeCycle) {
    const activeStart = new Date(activeCycle.started_at)
    activeStart.setHours(0, 0, 0, 0)
    const elapsed = Math.floor((today.getTime() - activeStart.getTime()) / 86400000) + 1
    const schedule = getScheduleForCycle(activeCycle.cycle_number)
    remainingDays += Math.max(0, schedule.days - elapsed)
    remainingDays += schedule.breakDays

    for (let n = activeCycle.cycle_number + 1; n <= totalCycles; n++) {
      const s = getScheduleForCycle(n)
      remainingDays += s.days + s.breakDays
    }
  } else {
    const lastCompleted = completedCycles[completedCycles.length - 1]
    const lastSchedule = getScheduleForCycle(lastCompleted.cycle_number)
    const completedAt = new Date(lastCompleted.completed_at)
    completedAt.setHours(0, 0, 0, 0)
    const daysSinceCompleted = Math.floor((today.getTime() - completedAt.getTime()) / 86400000)
    const remainingBreak = Math.max(0, lastSchedule.breakDays - daysSinceCompleted)
    remainingDays += remainingBreak

    for (let n = lastCompleted.cycle_number + 1; n <= totalCycles; n++) {
      const s = getScheduleForCycle(n)
      remainingDays += s.days + s.breakDays
    }
  }

  const projectedFinish = new Date(today)
  projectedFinish.setDate(projectedFinish.getDate() + remainingDays)

  let behindSchedule = false
  if (activeCycle) {
    const activeStart = new Date(activeCycle.started_at)
    activeStart.setHours(0, 0, 0, 0)
    const elapsed = Math.floor((today.getTime() - activeStart.getTime()) / 86400000) + 1
    behindSchedule = elapsed > getScheduleForCycle(activeCycle.cycle_number).days
  }

  return { state: 'in-progress', startDate, dayN, projectedFinish, behindSchedule }
}

export const formatDate = (date: Date): string =>
  date.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })
