export function MiniMetric({ label, value }: { label: string; value: string }) {
  return (
    <div className="mini-metric">
      <small>{label}</small>
      <strong>{value}</strong>
    </div>
  )
}
