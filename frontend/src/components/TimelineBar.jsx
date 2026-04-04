import { computeTimeline, formatDate } from '../timeline.js'

export default function TimelineBar({ history }) {
  const timeline = computeTimeline(history.cycles)

  if (timeline.state === 'not-started') return null

  const finishColor = timeline.state === 'complete'
    ? 'var(--success)'
    : timeline.behindSchedule
      ? 'var(--accent)'
      : 'var(--text)'

  return (
    <div style={{
      display: 'grid',
      gridTemplateColumns: 'repeat(3, 1fr)',
      gap: 12,
      background: 'var(--surface)',
      borderRadius: 8,
      padding: '12px 16px',
      marginBottom: 12,
      textAlign: 'center',
    }}>
      <div>
        <div style={{ fontSize: '0.95rem', fontWeight: 'bold' }}>
          {formatDate(timeline.startDate)}
        </div>
        <div style={{ fontSize: '0.75rem', color: 'var(--text-dim)' }}>Started</div>
      </div>
      <div>
        <div style={{ fontSize: '0.95rem', fontWeight: 'bold' }}>
          Day {timeline.dayN}
        </div>
        <div style={{ fontSize: '0.75rem', color: 'var(--text-dim)' }}>Current</div>
      </div>
      <div>
        <div style={{
          fontSize: '0.95rem',
          fontWeight: 'bold',
          color: finishColor,
        }}>
          {timeline.state === 'complete'
            ? formatDate(timeline.finishDate)
            : formatDate(timeline.projectedFinish)}
        </div>
        <div style={{ fontSize: '0.75rem', color: 'var(--text-dim)' }}>
          {timeline.state === 'complete' ? 'Completed' : 'Projected Finish'}
        </div>
      </div>
    </div>
  )
}
