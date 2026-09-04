import { describe, expect, it } from 'vitest'

import { computeSimpleFunnel, type FunnelInputs } from './simpleFunnel'

// Golden inputs taken straight from the reference dashboard image.
const REFERENCE: FunnelInputs = {
  linkClicks: 5080,
  landingViews: 3865,
  leads: 2801,
  botStarts: 1420,
  vslViews: 331,
  crmLeads: 178,
  spend: 321.22,
}

describe('computeSimpleFunnel — matches the reference image exactly', () => {
  const out = computeSimpleFunnel(REFERENCE)

  it('rate cards', () => {
    expect(out.rates.visit).toBe(76.1) // 3865 / 5080
    expect(out.rates.lead).toBe(72.5) // 2801 / 3865
    expect(out.rates.start).toBe(50.7) // 1420 / 2801
    expect(out.rates.vslView).toBe(23.3) // 331 / 1420
    expect(out.rates.crmFill).toBe(12.5) // 178 / 1420 (vs bot starts)
  })

  it('funnel bars use step-over-previous-step %', () => {
    const crm = out.funnel.find((f) => f.key === 'crmLeads')!
    expect(crm.value).toBe(178)
    expect(crm.pctOfPrev).toBe(53.8) // 178 / 331 VSL views (the row above)
    expect(out.funnel[0]).toMatchObject({ key: 'linkClicks', value: 5080, pctOfPrev: 100 })
  })

  it('cost per stage', () => {
    expect(out.cost.perVisit).toBe(0.08) // 321.22 / 3865
    expect(out.cost.perLead).toBe(0.11) // 321.22 / 2801
    expect(out.cost.perBotStart).toBe(0.23) // 321.22 / 1420
    expect(out.cost.perVslView).toBe(0.97) // 321.22 / 331
    expect(out.cost.perCrmLead).toBe(1.8) // 321.22 / 178
  })

  it('is zero-safe', () => {
    const zero = computeSimpleFunnel({ linkClicks: 0, landingViews: 0, leads: 0, botStarts: 0, vslViews: 0, crmLeads: 0, spend: 0 })
    expect(zero.rates.visit).toBe(0)
    expect(zero.cost.perLead).toBe(0)
  })

  it('caps rates at 100% (account-wide bot starts vs one campaign, or attribution overshoot)', () => {
    const out = computeSimpleFunnel({ linkClicks: 100, landingViews: 200, leads: 50, botStarts: 9999, vslViews: 0, crmLeads: 0, spend: 0 })
    expect(out.rates.visit).toBe(100) // 200/100 → capped
    expect(out.rates.start).toBe(100) // 9999/50 → capped
  })
})
