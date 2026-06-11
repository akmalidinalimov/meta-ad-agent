// src/components/Dashboard.test.tsx
import { describe, expect, it } from 'vitest'
import { visibleNavFor } from './Dashboard'

describe('visibleNavFor', () => {
  it('has no chat tab for anyone — control lives in Telegram', () => {
    for (const role of [null, 'owner', 'admin', 'viewer']) {
      expect(visibleNavFor(role).map((item) => item.id)).not.toContain('chat')
    }
  })

  it('shows monitor, rankings, settings to viewers', () => {
    expect(visibleNavFor('viewer').map((item) => item.id)).toEqual([
      'overview',
      'rankings',
      'settings',
    ])
  })

  it('adds team for managers and defaults (dev mode)', () => {
    expect(visibleNavFor('admin').map((item) => item.id)).toContain('team')
    expect(visibleNavFor(null).map((item) => item.id)).toContain('team')
  })
})
