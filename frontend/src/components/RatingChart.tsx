import { useState, useEffect, useMemo } from 'react'
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
import { api } from '../api'
import type { RatingPoint, RatingsResponse } from '../types'

ChartJS.register(CategoryScale, LinearScale, PointElement, LineElement, Filler, Legend, Tooltip)

interface RatingChartProps {
  startDate: Date
  endDate: Date
}

function toISO(date: Date): string {
  const year = date.getFullYear()
  const month = String(date.getMonth() + 1).padStart(2, '0')
  const day = String(date.getDate()).padStart(2, '0')
  return `${year}-${month}-${day}`
}

export default function RatingChart({ startDate, endDate }: RatingChartProps) {
  const [ratings, setRatings] = useState<RatingPoint[] | null>(null)

  useEffect(() => {
    let cancelled = false

    void api<RatingsResponse>(`/api/ratings?start_date=${toISO(startDate)}&end_date=${toISO(endDate)}`)
      .then(data => {
        if (!cancelled) {
          setRatings(data.ratings)
        }
      })
      .catch(() => {
        if (!cancelled) {
          setRatings([])
        }
      })

    return () => {
      cancelled = true
    }
  }, [startDate, endDate])

  const chartData = useMemo<{
    center: number
    data: ChartData<'line', (number | null)[], number>
  } | null>(() => {
    if (!ratings || ratings.length === 0) {
      return null
    }

    const days: Date[] = []
    const cursor = new Date(startDate)
    cursor.setHours(0, 0, 0, 0)
    const end = new Date(endDate)
    end.setHours(0, 0, 0, 0)

    while (cursor <= end) {
      days.push(new Date(cursor))
      cursor.setDate(cursor.getDate() + 1)
    }

    const ratingMap: Record<string, number> = {}
    for (const rating of ratings) {
      ratingMap[rating.date] = rating.rating
    }

    const center = Math.round(ratings[0].rating / 100) * 100
    const today = new Date()
    today.setHours(0, 0, 0, 0)

    const data = days.map(day => {
      if (day > today) {
        return null
      }

      return ratingMap[toISO(day)] ?? null
    })

    return {
      center,
      data: {
        labels: days.map((_, index) => index + 1),
        datasets: [
          {
            label: 'Chess.com Rating (Rapid)',
            data,
            borderColor: '#4fc3f7',
            backgroundColor: 'rgba(79, 195, 247, 0.1)',
            fill: true,
            tension: 0.2,
            spanGaps: true,
            pointRadius: 2,
          },
        ],
      },
    }
  }, [ratings, startDate, endDate])

  const chartOptions: ChartOptions<'line'> = {
    responsive: true,
    plugins: {
      legend: { labels: { color: '#999' } },
      tooltip: {
        callbacks: {
          label: context => `Rating: ${context.parsed.y}`,
        },
      },
    },
    scales: {
      y: {
        min: (chartData?.center ?? 0) - 300,
        max: (chartData?.center ?? 0) + 300,
        grid: { color: '#333' },
        ticks: { color: '#999' },
      },
      x: {
        title: { display: true, text: 'Day', color: '#999' },
        grid: { color: '#333' },
        ticks: {
          color: '#999',
          callback: value => {
            const numericValue = typeof value === 'number' ? value : Number(value)
            const label = numericValue + 1
            return label % 5 === 0 || label === 1 ? label : ''
          },
          maxRotation: 0,
        },
      },
    },
  }

  if (!ratings) {
    return <div className="card" style={{ color: 'var(--text-dim)', padding: 16 }}>Loading ratings...</div>
  }

  if (!chartData) {
    return null
  }

  return (
    <div className="card">
      <Line data={chartData.data} options={chartOptions} />
    </div>
  )
}
