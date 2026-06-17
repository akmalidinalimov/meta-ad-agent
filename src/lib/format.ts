import type { DashboardData, Placement } from '../types/marketing'

export function sumBy<T>(rows: T[], select: (row: T) => number): number {
  return rows.reduce((total, row) => total + select(row), 0)
}

export function formatCurrency(value: number): string {
  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: 'USD',
    maximumFractionDigits: value >= 100 ? 0 : 2,
  }).format(value)
}

export function formatPercent(value: number, base: number): string {
  return base === 0 ? '0%' : `${((value / base) * 100).toFixed(1)}%`
}

export function formatRate(value?: number): string {
  return typeof value === 'number' ? `${value.toFixed(value % 1 === 0 ? 0 : 1)}%` : '0%'
}

export function labelEventName(value: string): string {
  return value
    .split('_')
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(' ')
}

export function getDashboardAnchorDate(data: DashboardData): string {
  // Anchor the date-range window to the most recent day that actually has metric
  // data, so "last N days" always ends on a day with real numbers. A sync time
  // (generatedAt) that runs ahead of the data — or a brand-new campaign whose data
  // only just landed — no longer pushes the window past the latest results.
  const metricDates = data.metrics.map((metric) => metric.date).filter(Boolean)
  if (metricDates.length > 0) {
    return metricDates.reduce((max, value) => (value > max ? value : max))
  }

  const generatedAt = data.dataSource?.generatedAt?.slice(0, 10)
  if (generatedAt) {
    return generatedAt
  }

  const campaignDates = data.campaigns.flatMap((campaign) =>
    [campaign.startedAt, campaign.endedAt].filter((value): value is string => Boolean(value)),
  )
  if (campaignDates.length > 0) {
    return campaignDates.reduce((max, value) => (value > max ? value : max))
  }

  return new Date().toISOString().slice(0, 10)
}

export function labelPlacement(placement: Placement): string {
  return placement
    .split('_')
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(' ')
}

export function labelRawSetting(value: string): string {
  return value
    .split('_')
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(' ')
}

export function shortText(value: string, limit: number): string {
  return value.length <= limit ? value : `${value.slice(0, limit - 1)}...`
}

export function formatDateTime(value: string): string {
  return new Date(value).toLocaleString('en-US', {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}
