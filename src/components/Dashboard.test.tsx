// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { cleanup, render, screen, waitFor } from '@testing-library/react'
import { ApprovalQueue } from './Dashboard'
import type { ApprovalRequest, DashboardData } from '../types/marketing'

const baseApproval = {
  actionType: 'create_campaign',
  target: { level: 'campaign', id: 'c1', name: 'Launch' },
  reason: 'Recommended next launch.',
  risk: 'low' as const,
  expectedImpact: 'More qualified leads.',
  guardrailResult: 'pass' as const,
  guardrailChecks: [],
  executionMethod: 'mcp',
  requiresApproval: true,
  status: 'needs_review',
  createdAt: '2026-06-01T00:00:00Z',
  after: { campaign: { name: 'Launch', objective: 'leads', status: 'PAUSED' } },
}

const proactiveApproval: ApprovalRequest = {
  ...baseApproval,
  id: 'proactive-1',
  source: 'proactive',
  after: { campaign: { name: 'Proactive Launch', objective: 'leads', status: 'PAUSED' } },
  opportunity: {
    rationale: 'Your warm lookalikes are outperforming cold audiences this week.',
    audiences: [
      { label: 'Warm Lookalike 2%', qualityScore: 87, rationale: 'Best CPL last 7 days.' },
      { label: 'Interest: Online Courses', qualityScore: 74, rationale: 'High Telegram start rate.' },
      { label: 'Retargeting 30d', qualityScore: 69, rationale: 'Strong buyer intent.' },
      { label: 'Should Not Appear', qualityScore: 10, rationale: 'Fourth audience.' },
    ],
    creatives: [
      {
        segment: 'core',
        reuseExisting: [
          { creativeId: 'cr-1', name: 'Winning Testimonial Reel', qualityScore: 91, rationale: 'Top performer.' },
        ],
        newAngleBriefs: [
          { angle: 'Proof', hook: 'Watch how Sara replaced her salary in 60 days', whyItMightWork: 'Concrete proof.' },
        ],
      },
    ],
    sourceTemplate: {
      sourceCampaignId: 'src-1',
      sourceCampaignName: 'Spring Evergreen',
      config: { objective: 'leads', optimizationGoal: 'lead', bidStrategy: 'lowest_cost', budgetMode: 'daily', billingEvent: 'impressions' },
    },
  },
}

const normalApproval: ApprovalRequest = {
  ...baseApproval,
  id: 'normal-1',
}

const emptyDashboardData = { approvalActions: [] } as unknown as DashboardData

function mockFetch(approvals: ApprovalRequest[]) {
  return vi.fn((input: RequestInfo | URL) => {
    const url = String(input)
    if (url.includes('/api/approvals')) {
      return Promise.resolve({ ok: true, json: () => Promise.resolve({ approvals }) } as Response)
    }
    if (url.includes('/api/meta/status')) {
      return Promise.resolve({ ok: true, json: () => Promise.resolve({ liveWritesEnabled: false }) } as Response)
    }
    return Promise.resolve({ ok: true, json: () => Promise.resolve({}) } as Response)
  })
}

describe('ApprovalQueue proactive suggestions', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', mockFetch([proactiveApproval]))
  })

  afterEach(() => {
    cleanup()
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
  })

  it('renders a distinct proactive card with badge, audiences, mirrored config, and creative hooks', async () => {
    render(<ApprovalQueue data={emptyDashboardData} />)

    await waitFor(() => {
      expect(screen.getByText(/Suggested for you/i)).toBeTruthy()
    })

    // Rationale.
    expect(screen.getByText(/warm lookalikes are outperforming/i)).toBeTruthy()
    // An audience label + its quality score.
    expect(screen.getByText('Warm Lookalike 2%')).toBeTruthy()
    expect(screen.getByText(/Quality 87/i)).toBeTruthy()
    // Only top 3 audiences render.
    expect(screen.queryByText('Should Not Appear')).toBeNull()
    // Mirrored config from the source template.
    expect(screen.getByText(/Spring Evergreen/i)).toBeTruthy()
    // Reuse list name.
    expect(screen.getByText(/Winning Testimonial Reel/i)).toBeTruthy()
    // New angle brief hook.
    expect(screen.getByText(/Watch how Sara replaced her salary in 60 days/i)).toBeTruthy()
    // Existing controls still work for a needs_review approval.
    expect(screen.getByRole('button', { name: /Approve/i })).toBeTruthy()
  })

  it('renders a normal approval without any proactive extras', async () => {
    vi.stubGlobal('fetch', mockFetch([normalApproval]))
    render(<ApprovalQueue data={emptyDashboardData} />)

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /Approve/i })).toBeTruthy()
    })

    // The normal campaign name still renders.
    expect(screen.getAllByText('Launch').length).toBeGreaterThan(0)
    // No proactive badge or opportunity content.
    expect(screen.queryByText(/Suggested for you/i)).toBeNull()
    expect(screen.queryByText(/Top audiences/i)).toBeNull()
    expect(screen.queryByText(/Mirrors/i)).toBeNull()
    // Existing Approve button still present.
    expect(screen.getByRole('button', { name: /Approve/i })).toBeTruthy()
  })
})
