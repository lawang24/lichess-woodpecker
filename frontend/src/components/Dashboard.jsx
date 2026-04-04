import { getScheduleForCycle } from '../schedule.js'

export default function Dashboard({ history, targetRating }) {
  const completedCycles = history.cycles.filter(c => c.duration_days !== null)

  return (
    <>
      {completedCycles.length === 0 ? (
        <div className="card" style={{ color: 'var(--text-dim)' }}>No completed cycles yet.</div>
      ) : (
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
            {completedCycles.map(c => {
              const schedule = getScheduleForCycle(c.cycle_number)
              const hitTarget = c.duration_days <= schedule.days
              return (
                <tr key={c.id} style={{ borderTop: '1px solid var(--border)' }}>
                  <td style={{ padding: 8 }}>#{c.cycle_number}</td>
                  <td style={{ padding: 8 }}>{schedule.label}</td>
                  <td style={{ padding: 8, color: hitTarget ? 'var(--success)' : 'var(--accent)' }}>
                    {c.duration_days}d
                  </td>
                  <td style={{ padding: 8 }}>
                    {c.completed_count || 0}
                  </td>
                  <td style={{ padding: 8, color: 'var(--text-dim)', fontSize: '0.85rem' }}>
                    {new Date(c.started_at).toLocaleDateString()}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      )}
    </>
  )
}
