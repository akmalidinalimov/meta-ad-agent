// KPI derivation for the Monitor rail. Delta integrity rules (see spec §3.1):
// complete days only — today's partial data would show false drops every
// morning — and spend pace renders only when a weekly budget target exists.
import type { DailyAdMetric } from '../types/marketing'
import { formatCurrency } from './format'

export type MonitorTone = 'neutral' | 'good' | 'bad'

export interface MonitorKpi {
  id: 'spend' | 'leads' | 'cpl' | 'starts' | 'ctr'
  label: string
  value: string
  delta: string
  tone: MonitorTone
}

export interface MonitorKpiOptions {
  weeklyBudgetTargetUsd?: number | null
  today?: string // ISO date treated as "today" (partial; excluded). Defaults to the current date.
}

interface Totals {
  spend: number
  leads: number
  clicks: number
  impressions: number
  starts: number
}

function isoDaysAgo(today: string, days: number): string {
  const date = new Date(`${today}T00:00:00Z`)
  date.setUTCDate(date.getUTCDate() - days)
  return date.toISOString().slice(0, 10)
}

function windowTotals(metrics: DailyAdMetric[], from: string, to: string): Totals {
  const rows = metrics.filter((m) => m.date >= from && m.date <= to)
  const sum = (pick: (m: DailyAdMetric) => number) => rows.reduce((acc, m) => acc + pick(m), 0)
  return {
    spend: sum((m) => m.spendUsd),
    leads: sum((m) => m.leads),
    clicks: sum((m) => m.clicks),
    impressions: sum((m) => m.impressions),
    starts: sum((m) => m.telegramSubscribers),
  }
}

function pctDelta(current: number, previous: number): number | null {
  if (previous <= 0) return null
  return ((current - previous) / previous) * 100
}

function pctDeltaText(
  delta: number | null,
  opts: { downIsGood?: boolean; neutral?: boolean } = {},
): { delta: string; tone: MonitorTone } {
  if (delta === null) return { delta: 'no prior data', tone: 'neutral' }
  const rounded = Math.round(Math.abs(delta))
  if (rounded === 0) return { delta: 'flat vs prev 7d', tone: 'neutral' }
  const up = delta > 0
  const arrow = up ? '▲' : '▼'
  if (opts.neutral) return { delta: `${arrow} ${rounded}% vs prev 7d`, tone: 'neutral' }
  const good = opts.downIsGood ? !up : up
  const suffix = opts.downIsGood && good ? ' — improving' : !good ? ' — watch' : ''
  return { delta: `${arrow} ${rounded}% vs prev 7d${suffix}`, tone: good ? 'good' : 'bad' }
}

export function deriveMonitorKpis(
  metrics: DailyAdMetric[],
  options: MonitorKpiOptions = {},
): MonitorKpi[] {
  const today = options.today ?? new Date().toISOString().slice(0, 10)
  const current = windowTotals(metrics, isoDaysAgo(today, 7), isoDaysAgo(today, 1))
  const previous = windowTotals(metrics, isoDaysAgo(today, 14), isoDaysAgo(today, 8))

  // Spend: pace vs budget only when a target is configured; never invent a pace claim.
  const target = options.weeklyBudgetTargetUsd
  let spendDelta: { delta: string; tone: MonitorTone }
  if (target && target > 0) {
    const pct = Math.round((current.spend / target) * 100)
    spendDelta = { delta: `${pct}% of weekly budget`, tone: pct > 105 ? 'bad' : 'neutral' }
  } else {
    spendDelta = pctDeltaText(pctDelta(current.spend, previous.spend), { neutral: true })
  }

  const leadsDelta = pctDeltaText(pctDelta(current.leads, previous.leads))
  const startsDelta = pctDeltaText(pctDelta(current.starts, previous.starts))

  const cplNow = current.leads > 0 ? current.spend / current.leads : null
  const cplPrev = previous.leads > 0 ? previous.spend / previous.leads : null
  const cplDelta =
    cplNow !== null && cplPrev !== null
      ? pctDeltaText(pctDelta(cplNow, cplPrev), { downIsGood: true })
      : { delta: 'no prior data' as const, tone: 'neutral' as const }

  const ctrNow = current.impressions > 0 ? (current.clicks / current.impressions) * 100 : null
  const ctrPrev = previous.impressions > 0 ? (previous.clicks / previous.impressions) * 100 : null
  let ctrDelta: { delta: string; tone: MonitorTone } = { delta: 'no prior data', tone: 'neutral' }
  if (ctrNow !== null && ctrPrev !== null) {
    const points = ctrNow - ctrPrev
    const rounded = Math.round(Math.abs(points) * 10) / 10
    if (rounded === 0) ctrDelta = { delta: 'flat vs prev 7d', tone: 'neutral' }
    else if (points > 0) ctrDelta = { delta: `▲ ${rounded}pt vs prev 7d`, tone: 'good' }
    else ctrDelta = { delta: `▼ ${rounded}pt — watch`, tone: 'bad' }
  }

  return [
    { id: 'spend', label: 'Spend · 7d', value: formatCurrency(current.spend), ...spendDelta },
    { id: 'leads', label: 'Leads', value: String(current.leads), ...leadsDelta },
    {
      id: 'cpl',
      label: 'Cost / Lead',
      value: cplNow !== null ? formatCurrency(cplNow) : '—',
      ...cplDelta,
    },
    { id: 'starts', label: 'Telegram STARTs', value: String(current.starts), ...startsDelta },
    {
      id: 'ctr',
      label: 'CTR',
      value: ctrNow !== null ? `${Math.round(ctrNow * 10) / 10}%` : '—',
      ...ctrDelta,
    },
  ]
}
