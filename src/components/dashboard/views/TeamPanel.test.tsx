// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { cleanup, render, screen, waitFor } from '@testing-library/react'
import { TeamPanel } from './TeamPanel'

afterEach(() => cleanup())

beforeEach(() => {
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init?: RequestInit) => {
      if (url === '/api/members' && (!init || init.method === undefined || init.method === 'GET')) {
        return new Response(
          JSON.stringify({
            members: [
              { userId: '42', username: null, role: 'owner' },
              { userId: '100', username: 'alice', role: 'viewer' },
            ],
          }),
          { status: 200 },
        )
      }
      return new Response(JSON.stringify({ ok: true }), { status: 200 })
    }),
  )
})

describe('TeamPanel', () => {
  it('lists members and marks the owner', async () => {
    render(<TeamPanel />)
    await waitFor(() => expect(screen.getByText(/@alice/i)).toBeTruthy())
    // owner row shows the owner role chip (exact text node)
    expect(screen.getByText('owner')).toBeTruthy()
  })

  it('exposes an add-member form', async () => {
    render(<TeamPanel />)
    await waitFor(() => expect(screen.getByPlaceholderText(/numeric Telegram ID/i)).toBeTruthy())
    expect(screen.getByRole('button', { name: /add member/i })).toBeTruthy()
  })
})
