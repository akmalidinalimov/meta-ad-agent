// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, render, screen, waitFor } from '@testing-library/react'
import { LiveCampaignKpis } from './LiveCampaignKpis'

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

describe('LiveCampaignKpis', () => {
  it('requests live KPIs scoped to the selected campaign and day range', async () => {
    const urls: string[] = []
    vi.stubGlobal(
      'fetch',
      vi.fn((input: RequestInfo | URL) => {
        urls.push(String(input))
        return Promise.resolve({
          ok: true,
          json: () =>
            Promise.resolve({
              ok: true,
              hasData: true,
              campaignName: 'Alpha',
              days: 7,
              kpis: {
                spend: 100,
                leads: 20,
                cpl: 5,
                ctr: 2,
                leadRateFromClick: 20,
                purchases: 0,
                subscribes: 8,
                clicks: 50,
                impressions: 500,
                costPerStart: 12.5,
              },
              rates: { visitRate: 50, leadRate: 40, startRate: 40 },
              counts: {},
            }),
        } as Response)
      }),
    )

    render(<LiveCampaignKpis campaignId="c1" campaignName="Alpha" days={7} refreshKey={0} />)

    await waitFor(() => expect(urls.length).toBeGreaterThan(0))
    expect(urls.some((url) => url.includes('/api/campaigns/kpis'))).toBe(true)
    expect(urls.some((url) => url.includes('campaignId=c1'))).toBe(true)
    expect(urls.some((url) => url.includes('days=7'))).toBe(true)
    expect(screen.getByText('Alpha')).toBeTruthy()
  })
})
