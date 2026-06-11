// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, render, screen, waitFor } from '@testing-library/react'
import { MonitorView } from './MonitorView'
import type { DailyAdMetric, FunnelSummary, TrendPoint } from '../../../types/marketing'

const funnel: FunnelSummary[] = [
  { step: 'Ad impressions', value: 128400, rate: '100%' },
  { step: 'Clicks', value: 3082, rate: '2.4%' },
  { step: 'Landing visits', value: 2100, rate: '68.1%' },
  { step: 'Leads', value: 312, rate: '14.9%' },
  { step: 'Telegram subs', value: 208, rate: '66.7%' },
  { step: 'Webinar attendees', value: 96, rate: '46.2%' },
  { step: 'Buyers', value: 0, rate: '0%' },
]

const trend: TrendPoint[] = [
  { day: '2026-06-09', spend: 170, leads: 44, buyers: 0 },
  { day: '2026-06-10', spend: 181, leads: 47, buyers: 0 },
]

const metrics: DailyAdMetric[] = []

function stubFetch() {
  vi.stubGlobal(
    'fetch',
    vi.fn((input: RequestInfo | URL) => {
      const url = String(input)
      if (url.includes('/api/targets')) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({ targets: { weeklyBudgetTargetUsd: 200 } }),
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
  it('renders the five KPI labels in rail order', async () => {
    stubFetch()
    render(<MonitorView metrics={metrics} trend={trend} funnel={funnel} />)
    await waitFor(() => expect(screen.getByText('Cost / Lead')).toBeTruthy())
    expect(screen.getByText('Spend · 7d')).toBeTruthy()
    expect(screen.getAllByText('Telegram STARTs').length >= 1).toBeTruthy()
    expect(screen.getByText('CTR')).toBeTruthy()
  })

  it('renders the five funnel stages with CTR on the clicks row, skipping visits and buyers', async () => {
    stubFetch()
    render(<MonitorView metrics={metrics} trend={trend} funnel={funnel} />)
    await waitFor(() => expect(screen.getByText(/Clicks · CTR 2.4%/)).toBeTruthy())
    expect(screen.getByText('Ad impressions')).toBeTruthy()
    expect(screen.getByText('Webinar attended')).toBeTruthy()
    expect(screen.queryByText('Landing visits')).toBeNull()
    expect(screen.queryByText('Buyers')).toBeNull()
  })

  it('renders the Agent Office panel', async () => {
    stubFetch()
    render(<MonitorView metrics={metrics} trend={trend} funnel={funnel} />)
    await waitFor(() => expect(screen.getByText('Agent Office')).toBeTruthy())
  })
})
