// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, render, screen, waitFor } from '@testing-library/react'
import { MonitorView } from './MonitorView'
import type { FunnelSummary, TrendPoint } from '../../../types/marketing'

const funnel: FunnelSummary[] = [{ step: 'Ad impressions', value: 100, rate: '100%' }]
const trend: TrendPoint[] = [{ day: '2026-06-10', spend: 10, leads: 2, buyers: 0 }]

function stubFetch() {
  vi.stubGlobal(
    'fetch',
    vi.fn((input: RequestInfo | URL) => {
      const url = String(input)
      if (url.includes('/api/campaigns/kpis')) {
        return Promise.resolve({
          ok: true,
          json: () =>
            Promise.resolve({
              ok: true,
              source: 'live',
              days: 7,
              campaignId: 'all',
              campaignName: 'All campaigns',
              hasData: true,
              kpis: {
                spend: 1234.5,
                leads: 42,
                cpl: 5,
                ctr: 2.2,
                leadRateFromClick: 30,
                purchases: 0,
                subscribes: 8,
                clicks: 100,
                impressions: 1000,
                costPerStart: 154.3,
              },
              rates: { visitRate: 60, leadRate: 14, startRate: 19 },
              counts: { linkClicks: 90, landingPageViews: 54, leads: 42, subscribes: 8 },
            }),
        } as Response)
      }
      if (url.includes('/api/agents/status')) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({ agents: [], events: [], updatedAt: '' }),
        } as Response)
      }
      return Promise.resolve({ ok: true, json: () => Promise.resolve({}) } as Response)
    }),
  )
}

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

describe('MonitorView', () => {
  it('shows the live campaign panel with KPIs and funnel rates', async () => {
    stubFetch()
    render(
      <MonitorView
        metrics={[]}
        trend={trend}
        funnel={funnel}
        days={7}
        campaignId="all"
        campaignName="All campaigns"
        refreshKey={0}
      />,
    )
    await waitFor(() => expect(screen.getByText('Spend')).toBeTruthy())
    expect(screen.getByText('All campaigns')).toBeTruthy()
    expect(screen.getByText('Visit rate')).toBeTruthy()
  })

  it('keeps the synced account history behind a disclosure', async () => {
    stubFetch()
    render(
      <MonitorView
        metrics={[]}
        trend={trend}
        funnel={funnel}
        days={7}
        campaignId="all"
        campaignName="All campaigns"
        refreshKey={0}
      />,
    )
    await waitFor(() => expect(screen.getByText('Account history · last sync')).toBeTruthy())
  })
})
