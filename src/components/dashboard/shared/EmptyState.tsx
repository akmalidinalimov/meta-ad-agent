import { AlertTriangle } from 'lucide-react'

export function EmptyState({
  compact = false,
  title = 'No matching data',
  body = 'Adjust filters to restore the current dashboard view.',
  onReset,
}: {
  compact?: boolean
  title?: string
  body?: string
  onReset?: () => void
}) {
  return (
    <div className={compact ? 'empty-state compact' : 'empty-state'}>
      <AlertTriangle size={22} />
      <strong>{title}</strong>
      <p>{body}</p>
      {onReset && (
        <button className="sync-button" type="button" onClick={onReset}>
          Reset filters
        </button>
      )}
    </div>
  )
}
