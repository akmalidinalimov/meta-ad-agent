// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, render, waitFor } from '@testing-library/react'
import { LiveFunnelRates } from './LiveFunnelRates'

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

function stubFetch() {
  const urls: string[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn((input: RequestInfo | URL) => {
      urls.push(String(input))
      return Promise.resolve({ ok: true, json: () => Promise.resolve({ ok: true, hasData: false }) } as Response)
    }),
  )
  return urls
}

describe('LiveFunnelRates', () => {
  it('requests funnel rates for the selected day range so the date filter drives the cards', async () => {
    const urls = stubFetch()
    render(<LiveFunnelRates days={7} />)
    await waitFor(() => expect(urls.length).toBeGreaterThan(0))
    expect(urls.some((url) => url.includes('/api/funnel/rates?days=7'))).toBe(true)
  })

  it('defaults to a 30-day window when no range is provided', async () => {
    const urls = stubFetch()
    render(<LiveFunnelRates />)
    await waitFor(() => expect(urls.length).toBeGreaterThan(0))
    expect(urls.some((url) => url.includes('days=30'))).toBe(true)
  })
})
