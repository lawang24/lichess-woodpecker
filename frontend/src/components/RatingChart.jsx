import { useState, useEffect, useMemo } from 'react'
import { Line } from 'react-chartjs-2'
import { api } from '../api.js'

function toDateStr(d) {
  return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
}

function toISO(d) {
  const y = d.getFullYear()
  const m = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return `${y}-${m}-${day}`
}

export default function RatingChart({ startDate, endDate }) {
  const [ratings, setRatings] = useState(null)

  useEffect(() => {
    api(`/api/ratings?start_date=${toISO(startDate)}&end_date=${toISO(endDate)}`)
      .then(data => setRatings(data.ratings))
      .catch(() => setRatings([]))
  }, [startDate, endDate])

  const chartData = useMemo(() => {
    if (!ratings || ratings.length === 0) return null

    // Build daily labels from start to end
    const days = []
    const d = new Date(startDate)
    d.setHours(0, 0, 0, 0)
    const end = new Date(endDate)
    end.setHours(0, 0, 0, 0)
    while (d <= end) {
      days.push(new Date(d))
      d.setDate(d.getDate() + 1)
    }

    // Index ratings by date for fast lookup
    const ratingMap = {}
    for (const r of ratings) {
      ratingMap[r.date] = r.rating
    }

    const firstRating = ratings[0].rating
    const center = Math.round(firstRating / 100) * 100

    const today = new Date()
    today.setHours(0, 0, 0, 0)

    const data = days.map(day => {
      if (day > today) return null
      const key = toISO(day)
      return ratingMap[key] ?? null
    })

    return {
      center,
      labels: days.map((_, i) => i + 1),
      datasets: [{
        label: 'Chess.com Rating (Rapid)',
        data,
        borderColor: '#4fc3f7',
        backgroundColor: 'rgba(79, 195, 247, 0.1)',
        fill: true,
        tension: 0.2,
        spanGaps: true,
        pointRadius: 2,
      }],
    }
  }, [ratings, startDate, endDate])

  const chartOptions = {
    responsive: true,
    plugins: { legend: { labels: { color: '#999' } } },
    scales: {
      y: {
        min: chartData?.center - 300,
        max: chartData?.center + 300,
        grid: { color: '#333' },
        ticks: { color: '#999' },
      },
      x: {
        title: { display: true, text: 'Day', color: '#999' },
        grid: { color: '#333' },
        ticks: {
          color: '#999',
          callback: (val) => (val + 1) % 5 === 0 || val === 0 ? val + 1 : '',
          maxRotation: 0,
        },
      },
    },
  }

  if (!ratings) return <div className="card" style={{ color: 'var(--text-dim)', padding: 16 }}>Loading ratings...</div>
  if (!chartData) return null

  return (
    <div className="card">
      <Line data={chartData} options={chartOptions} />
    </div>
  )
}
