/**
 * Shared recharts presentation helpers so every chart formats currency and
 * counts identically (tooltips, axis ticks, legends) instead of showing raw
 * numbers. Centralizing this keeps Trend, Placement, Audience and Spend panels
 * in sync.
 */

const currencyFormatter = new Intl.NumberFormat('en-US', {
  style: 'currency',
  currency: 'USD',
  maximumFractionDigits: 0,
})

const compactCurrencyFormatter = new Intl.NumberFormat('en-US', {
  style: 'currency',
  currency: 'USD',
  notation: 'compact',
  maximumFractionDigits: 1,
})

const numberFormatter = new Intl.NumberFormat('en-US')

/** Currency for tooltips/labels: whole-dollar for readability. */
export function formatChartCurrency(value: number): string {
  return currencyFormatter.format(value)
}

/** Compact currency for dense axis ticks (e.g. $1.2K). */
export function formatAxisCurrency(value: number | string): string {
  const numeric = typeof value === 'number' ? value : Number(value)
  if (!Number.isFinite(numeric)) {
    return String(value)
  }
  return compactCurrencyFormatter.format(numeric)
}

/** Plain integer count for tooltips/labels. */
export function formatChartNumber(value: number): string {
  return numberFormatter.format(value)
}

/**
 * recharts <Tooltip> formatter. Series whose key looks monetary (spend) format
 * as currency; everything else (leads, buyers, subs) formats as a count.
 *
 * Typed loosely (value/name may be undefined or arrays) to match recharts'
 * `Formatter<ValueType, NameType>` contract.
 */
export function chartTooltipFormatter(
  value: number | string | ReadonlyArray<number | string> | undefined,
  name: number | string | undefined,
): [string, string] {
  const raw = Array.isArray(value) ? value[0] : value
  const numeric = typeof raw === 'number' ? raw : Number(raw)
  const safe = Number.isFinite(numeric) ? numeric : 0
  const label = name == null ? '' : String(name)
  const isCurrency = /spend|budget|cost|cpa|cpl|cpc|usd/i.test(label)
  return [isCurrency ? formatChartCurrency(safe) : formatChartNumber(safe), label]
}
