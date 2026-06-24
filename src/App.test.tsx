/** @vitest-environment jsdom */
import '@testing-library/jest-dom/vitest'
import { cleanup, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import App from './App'

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
  delete (window as unknown as { Telegram?: unknown }).Telegram
})

describe('App Telegram auth', () => {
  beforeEach(() => {
    ;(window as unknown as { Telegram?: { WebApp?: { initData?: string } } }).Telegram = {
      WebApp: { initData: 'auth_date=1&hash=deadbeef' },
    }
  })

  it('shows the retry panel and never the password form when webapp-auth fails inside Telegram', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => ({ ok: false, json: async () => ({}) }) as Response),
    )

    render(<App />)

    await waitFor(() => expect(screen.getByText(/couldn't verify your telegram session/i)).toBeInTheDocument())
    expect(screen.getByRole('button', { name: /retry/i })).toBeInTheDocument()
    // The password screen must NOT render for a Telegram user.
    expect(screen.queryByPlaceholderText('Password')).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /sign in/i })).not.toBeInTheDocument()
  })
})
