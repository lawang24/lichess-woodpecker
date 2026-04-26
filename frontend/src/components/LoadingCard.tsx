interface LoadingCardProps {
  children: string
}

export default function LoadingCard({ children }: LoadingCardProps) {
  return (
    <div className="card loading-card" role="status" aria-live="polite">
      <span className="loading-spinner" aria-hidden="true" />
      <span>{children}</span>
    </div>
  )
}
