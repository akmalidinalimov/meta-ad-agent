import { describe, expect, it } from 'vitest'
import { getDashboardAnchorDate } from './format'
import type { DashboardData } from '../types/marketing'

// getDashboardAnchorDate only reads metrics / dataSource / campaigns, so a partial
// object cast keeps these focused on the anchoring logic.
function makeData(partial: Partial<DashboardData>): DashboardData {
  return { campaigns: [], metrics: [], ...partial } as unknown as DashboardData
}

describe('getDashboardAnchorDate', () => {
  it('anchors to the latest metric date, even when generatedAt runs ahead of the data', () => {
    const data = makeData({
      metrics: [{ date: '2026-06-10' }, { date: '2026-06-16' }, { date: '2026-06-02' }] as DashboardData['metrics'],
      dataSource: { kind: 'meta', generatedAt: '2026-06-20T09:00:00Z' } as DashboardData['dataSource'],
    })
    // The window should end on the freshest day that actually has data, not the
    // sync timestamp — otherwise "last 7 days" could miss the latest results.
    expect(getDashboardAnchorDate(data)).toBe('2026-06-16')
  })

  it('falls back to the generatedAt date when there are no metrics yet', () => {
    const data = makeData({
      metrics: [],
      dataSource: { kind: 'meta', generatedAt: '2026-06-20T09:00:00Z' } as DashboardData['dataSource'],
    })
    expect(getDashboardAnchorDate(data)).toBe('2026-06-20')
  })

  it('falls back to the latest campaign date when there is no data or generatedAt', () => {
    const data = makeData({
      metrics: [],
      campaigns: [{ startedAt: '2026-05-01', endedAt: '2026-05-20' }] as DashboardData['campaigns'],
    })
    expect(getDashboardAnchorDate(data)).toBe('2026-05-20')
  })
})
