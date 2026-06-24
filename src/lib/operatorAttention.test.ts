import { describe, expect, it } from 'vitest'
import { buildOperatorAttention } from './operatorAttention'
import type { DashboardData } from '../types/marketing'

const baseData: DashboardData = {
  campaigns: [],
  adSets: [],
  ads: [],
  creatives: [],
  creativeAnalyses: [],
  metrics: [],
  kpis: [],
  funnel: [],
  trend: [],
  creativeScores: [],
  placements: [],
  audience: [],
  insights: [],
  experiments: [],
  trackingHealth: [],
  approvalActions: [],
  glossary: [],
}

describe('buildOperatorAttention', () => {
  it('prioritizes high monitoring alerts and campaign-watch danger decisions first', () => {
    const rows = buildOperatorAttention({
      ...baseData,
      monitoringAlerts: [
        {
          id: 'alert_1',
          severity: 'high',
          title: 'Spend and clicks but no leads',
          whyItMatters: 'Tracking or landing page may be broken.',
          recommendedActions: ['Check landing page button tracking.'],
          createdAt: '2026-06-01T00:00:00Z',
          status: 'open',
        },
      ],
      campaignWatch: [
        {
          campaignId: 'cmp_1',
          campaignName: 'Fresh VSL',
          status: 'active',
          currentDate: '2026-06-01',
          daysObserved: 2,
          spendUsd: 80,
          clicks: 260,
          leads: 0,
          telegramStarts: 0,
          cpc: 0.31,
          cpl: 0,
          leadRatePercent: 0,
          telegramStartRatePercent: 0,
          previousCpl: 0,
          previousLeadRatePercent: 0,
          decision: 'Fix tracking or landing page before scaling',
          reason: 'Spend and clicks are present, but no leads are recorded.',
          tone: 'danger',
          nextActions: ['Check tracking.'],
        },
      ],
    })

    expect(rows[0].tone).toBe('danger')
    expect(rows[0].source).toBe('Monitoring')
    expect(rows[1].source).toBe('Campaign Watch')
    expect(rows[1].action).toContain('Check tracking')
  })

  it('shows the authored whyItMatters reason even when metricDeltas is also present', () => {
    const rows = buildOperatorAttention({
      ...baseData,
      monitoringAlerts: [
        {
          id: 'alert_1',
          severity: 'high',
          title: 'CPL rose sharply',
          whyItMatters: 'Cheap clicks but lead quality is collapsing.',
          metricDeltas: { CPL: '2 -> 5' },
          recommendedActions: ['Pause the weakest ad set.'],
          createdAt: '2026-06-01T00:00:00Z',
          status: 'open',
        },
      ],
    })

    // Regression: an operator-precedence bug used to discard whyItMatters whenever
    // metricDeltas was truthy, replacing it with a generic placeholder.
    expect(rows[0].reason).toBe('Cheap clicks but lead quality is collapsing.')
  })

  it('falls back to a generic reason when no whyItMatters is authored', () => {
    const rows = buildOperatorAttention({
      ...baseData,
      monitoringAlerts: [
        {
          id: 'alert_2',
          severity: 'medium',
          title: 'CPC drifting up',
          metricDeltas: { CPC: '0.2 -> 0.4' },
          recommendedActions: ['Review creatives.'],
          createdAt: '2026-06-01T00:00:00Z',
          status: 'open',
        },
      ],
    })

    expect(rows[0].reason).toBe('Metric movement needs review.')
  })

  it('adds tracking and approval items when there are no alerts', () => {
    const rows = buildOperatorAttention({
      ...baseData,
      trackingHealth: [
        {
          name: 'Telegram START',
          status: 'broken',
          matchRate: 0,
          lastEventAt: 'Waiting',
          note: 'No START events received.',
        },
      ],
      approvalActions: [
        {
          id: 'approve-monitoring',
          title: 'Approve monitoring rules',
          impact: 'Monitor every four hours.',
          risk: 'low',
          owner: 'human',
          status: 'needs_review',
        },
      ],
    })

    expect(rows.map((row) => row.source)).toContain('Tracking')
    expect(rows.map((row) => row.source)).toContain('Approval')
  })
})
