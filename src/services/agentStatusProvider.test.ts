import { afterEach, describe, expect, it, vi } from 'vitest'
import { getAgentStatus } from './agentStatusProvider'

const payload = {
  agents: [
    {
      id: 'monitor',
      name: 'Monitor',
      state: 'working',
      activity: 'scanning ad sets',
      sinceSeconds: 120,
      nextRunAt: null,
      lastActivity: null,
      lastActiveAt: null,
    },
  ],
  events: [{ agentId: 'monitor', summary: 'scan done', at: '2026-06-11T10:41:00Z' }],
  updatedAt: '2026-06-11T10:43:00Z',
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('getAgentStatus', () => {
  it('fetches and returns the status payload', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(() => Promise.resolve({ ok: true, json: () => Promise.resolve(payload) } as Response)),
    )
    const result = await getAgentStatus()
    expect(result.agents[0].state).toBe('working')
    expect(result.events.length).toBe(1)
  })

  it('throws on a non-ok response', async () => {
    vi.stubGlobal('fetch', vi.fn(() => Promise.resolve({ ok: false, status: 500 } as Response)))
    await expect(getAgentStatus()).rejects.toThrow()
  })
})
