import { getScheduleForCycle } from '../schedule'
import type { CycleRecord, SetHistoryResponse } from '../types'

interface DashboardProps {
  history: SetHistoryResponse
}

function hasDuration(cycle: CycleRecord): cycle is CycleRecord & { duration_days: number } {
  return cycle.duration_days !== null
}

export default function Dashboard({ history }: DashboardProps) {
  const completedCycles = history.cycles.filter(hasDuration)

  return (
    <>
      {completedCycles.length === 0 ? (
        <div className="card" style={{ color: 'var(--text-dim)' }}>No completed cycles yet.</div>
      ) : (
        <div className="table-wrap">
          <table style={{ width: '100%', borderCollapse: 'collapse' }}>
            <thead>
              <tr style={{ color: 'var(--text-dim)', fontSize: '0.85rem', textAlign: 'left' }}>
                <th style={{ padding: 8 }}>Cycle</th>
                <th style={{ padding: 8 }}>Target</th>
                <th style={{ padding: 8 }}>Duration</th>
                <th style={{ padding: 8 }}>Completed</th>
                <th style={{ padding: 8 }}>Date</th>
              </tr>
            </thead>
            <tbody>
              {completedCycles.map(cycle => {
                const schedule = getScheduleForCycle(cycle.cycle_number)
                const hitTarget = cycle.duration_days <= schedule.days

                return (
                  <tr key={cycle.id} style={{ borderTop: '1px solid var(--border)' }}>
                    <td style={{ padding: 8 }}>#{cycle.cycle_number}</td>
                    <td style={{ padding: 8 }}>{schedule.label}</td>
                    <td style={{ padding: 8, color: hitTarget ? 'var(--success)' : 'var(--accent)' }}>
                      {cycle.duration_days}d
                    </td>
                    <td style={{ padding: 8 }}>
                      {cycle.completed_count || 0}
                    </td>
                    <td style={{ padding: 8, color: 'var(--text-dim)', fontSize: '0.85rem' }}>
                      {new Date(cycle.started_at).toLocaleDateString()}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
    </>
  )
}
