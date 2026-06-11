// src/lib/monitorKpis.test.ts
import { describe, expect, it } from 'vitest'
import { deriveMonitorKpis } from './monitorKpis'
import type { DailyAdMetric } from '../types/marketing'

function metric(date: string, overrides: Partial<DailyAdMetric> = {}): DailyAdMetric {
  return {
    date,
    campaignId: 'c1',
    adSetId: 'as1',
    adId: 'a1',
    creativeId: 'cr1',
    placement: 'instagram_reels' as DailyAdMetric['placement'],
    spendUsd: 10,
    impressions: 1000,
    clicks: 25,
    landingPageViews: 20,
    leads: 5,
    telegramSubscribers: 3,
    webinarAttendees: 1,
    purchases: 0,
    purchaseRevenueUsd: 0,
    ...overrides,
  }
}

const TODAY = '2026-06-11'

// 7 complete current days (06-04..06-10) + 7 previous (05-28..06-03)
function fortnight(currentSpend = 10, previousSpend = 10): DailyAdMetric[] {
  const rows: DailyAdMetric[] = []
  for (let i = 1; i <= 7; i++) rows.push(metric(`2026-06-${String(11 - i).padStart(2, '0')}`, { spendUsd: currentSpend }))
  rows.push(metric('2026-06-03', { spendUsd: previousSpend }))
  rows.push(metric('2026-06-02', { spendUsd: previousSpend }))
  rows.push(metric('2026-06-01', { spendUsd: previousSpend }))
  rows.push(metric('2026-05-31', { spendUsd: previousSpend }))
  rows.push(metric('2026-05-30', { spendUsd: previousSpend }))
  rows.push(metric('2026-05-29', { spendUsd: previousSpend }))
  rows.push(metric('2026-05-28', { spendUsd: previousSpend }))
  return rows
}

describe('deriveMonitorKpis', () => {
  it('returns the five KPIs in rail order', () => {
    const kpis = deriveMonitorKpis(fortnight(), { today: TODAY })
    expect(kpis.map((k) => k.id)).toEqual(['spend', 'leads', 'cpl', 'starts', 'ctr'])
  })

  it("excludes today's partial data from totals and deltas", () => {
    const rows = [...fortnight(), metric(TODAY, { spendUsd: 9999 })]
    const kpis = deriveMonitorKpis(rows, { today: TODAY })
    expect(kpis[0].value).toBe('$70.00') // 7 complete days x $10, today's 9999 ignored
  })

  it('shows budget pace only when a target is configured', () => {
    const withTarget = deriveMonitorKpis(fortnight(), { today: TODAY, weeklyBudgetTargetUsd: 140 })
    expect(withTarget[0].delta).toBe('50% of weekly budget')

    const withoutTarget = deriveMonitorKpis(fortnight(), { today: TODAY })
    expect(withoutTarget[0].delta).toContain('vs prev 7d') // plain delta, no pace claim
  })

  it('words a CPL drop as improving', () => {
    // current spend 10/day, previous 20/day, same leads -> CPL halved
    const kpis = deriveMonitorKpis(fortnight(10, 20), { today: TODAY })
    const cpl = kpis.find((k) => k.id === 'cpl')!
    expect(cpl.delta).toContain('▼')
    expect(cpl.delta).toContain('improving')
    expect(cpl.tone).toBe('good')
  })

  it('reports CTR delta in points', () => {
    const rows = fortnight()
    // halve current clicks: CTR 2.5% -> 1.25%, a -1.3pt move
    for (const row of rows) if (row.date >= '2026-06-04') row.clicks = 12
    const kpis = deriveMonitorKpis(rows, { today: TODAY })
    const ctr = kpis.find((k) => k.id === 'ctr')!
    expect(ctr.delta).toContain('pt')
    expect(ctr.tone).toBe('bad')
  })

  it('handles an empty previous window without a pace claim', () => {
    const rows = fortnight().filter((r) => r.date >= '2026-06-04')
    const kpis = deriveMonitorKpis(rows, { today: TODAY })
    expect(kpis[1].delta).toBe('no prior data')
    expect(kpis[1].tone).toBe('neutral')
  })
})
