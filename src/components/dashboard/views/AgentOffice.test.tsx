// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, render, screen, waitFor } from '@testing-library/react'
import { AgentOffice } from './AgentOffice'
import type { AgentStatusPayload } from '../../../services/agentStatusProvider'

const payload: AgentStatusPayload = {
  agents: [
    {
      id: 'monitor',
      name: 'Monitor',
      state: 'working',
      activity: 'scanning 14 ad sets',
      sinceSeconds: 120,
      nextRunAt: null,
      lastActivity: null,
      lastActiveAt: null,
    },
    {
      id: 'analyst',
      name: 'Analyst',
      state: 'idle',
      activity: null,
      sinceSeconds: null,
      nextRunAt: null,
      lastActivity: 'KPI digest sent to Telegram',
      lastActiveAt: '2026-06-11T08:41:00Z',
    },
    {
      id: 'planner',
      name: 'Planner',
      state: 'scheduled',
      activity: null,
      sinceSeconds: null,
      nextRunAt: '2026-06-11T14:00:00Z',
      lastActivity: 'opportunity review completed',
      lastActiveAt: '2026-06-10T14:00:00Z',
    },
    {
      id: 'creative',
      name: 'Creative',
      state: 'idle',
      activity: null,
      sinceSeconds: null,
      nextRunAt: null,
      lastActivity: null,
      lastActiveAt: null,
    },
  ],
  events: [
    { agentId: 'monitor', summary: 'scan done — 14 ad sets healthy', at: '2026-06-11T10:41:00Z' },
    { agentId: 'analyst', summary: 'KPI digest sent to Telegram', at: '2026-06-11T08:41:00Z' },
  ],
  updatedAt: '2026-06-11T10:43:00Z',
}

function stubFetch(data: AgentStatusPayload | null) {
  vi.stubGlobal(
    'fetch',
    vi.fn(() =>
      data
        ? Promise.resolve({ ok: true, json: () => Promise.resolve(data) } as Response)
        : Promise.reject(new Error('offline')),
    ),
  )
}

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

describe('AgentOffice', () => {
  it('summarizes working vs idle and shows activity sentences', async () => {
    stubFetch(payload)
    render(<AgentOffice />)
    await waitFor(() => {
      expect(screen.getByText(/1 working · 3 idle/)).toBeTruthy()
    })
    expect(screen.getByText(/working — scanning 14 ad sets/)).toBeTruthy()
    // Idle agent shows its last real activity, not a bare "idle"
    expect(screen.getByText(/last: KPI digest sent to Telegram/)).toBeTruthy()
  })

  it('renders the recent activity feed', async () => {
    stubFetch(payload)
    render(<AgentOffice />)
    await waitFor(() => {
      expect(screen.getByText(/scan done — 14 ad sets healthy/)).toBeTruthy()
    })
  })

  it('marks working agents in the office scene', async () => {
    stubFetch(payload)
    const { container } = render(<AgentOffice />)
    await waitFor(() => {
      expect(container.querySelector('.office-desk.working')).toBeTruthy()
    })
    expect(container.querySelectorAll('.office-desk').length).toBe(4)
  })

  it('shows a connecting state before data arrives and survives fetch failure', async () => {
    stubFetch(null)
    render(<AgentOffice />)
    await waitFor(() => {
      expect(screen.getByText(/unavailable/i)).toBeTruthy()
    })
  })
})
