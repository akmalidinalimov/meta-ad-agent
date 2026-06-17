import { describe, expect, it } from 'vitest'

import { buildAudienceRows, type CrmFunnelPayload } from './crmFunnel'

const payload: CrmFunnelPayload = {
  ok: true,
  stages: ['NEW', 'PAID'],
  stageLabels: { NEW: 'New', PAID: "To'lov" },
  paidStageIds: ['PAID'],
  matchRate: 0.5,
  audiences: {
    ai: { NEW: 1, PAID: 1, submits: 2, paid: 1, botStarts: 4, paidRate: 0.5, paidRatePerStart: 0.25 },
    unattributed: { NEW: 3, PAID: 0, submits: 3, paid: 0, botStarts: 0, paidRate: 0, paidRatePerStart: 0 },
  },
}

describe('buildAudienceRows', () => {
  it('orders known audiences first, unattributed last, and carries paid metrics', () => {
    const rows = buildAudienceRows(payload)
    expect(rows[0].audience).toBe('ai')
    expect(rows[rows.length - 1].audience).toBe('unattributed')
    expect(rows[0].cells.map((c) => c.count)).toEqual([1, 1])
    expect(rows[0].paidRatePct).toBe('50%')
    expect(rows[0].botStarts).toBe(4)
  })

  it('returns [] when payload has no audiences', () => {
    expect(buildAudienceRows({ ...payload, audiences: {} })).toEqual([])
  })
})
