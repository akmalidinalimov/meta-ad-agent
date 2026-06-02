import { describe, expect, it, vi } from 'vitest'
import { createMetaAiCapture, getMetaAiCaptures } from './metaAiProvider'

const sampleCapture = {
  id: 'meta_ai_1',
  createdAt: '2026-06-01T10:00:00Z',
  capturedBy: 'operator',
  sourceText: 'Increase budget. CPL is $0.04.',
  screenshotText: '',
  analysis: {
    advisor: { recommendationSummary: ['Increase budget'], evidenceUsed: ['cpl'], whatItMissed: ['Telegram START quality'], trustLevel: 'medium' },
    strategist: {
      comparedAgainst: ['180-day Meta knowledge base'],
      scores: { specificity: 60, metricAccuracy: 45, actionability: 60, businessRealism: 34, riskAwareness: 15 },
      overallScore: 43,
      businessCounterpoints: ['Verify Telegram START quality.'],
      campaign: null,
    },
  },
}

describe('metaAiProvider', () => {
  it('lists saved captures', async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ captures: [sampleCapture] }) })
    vi.stubGlobal('fetch', fetchMock)

    const captures = await getMetaAiCaptures()

    expect(captures).toHaveLength(1)
    expect(captures[0].analysis.advisor.trustLevel).toBe('medium')
    expect(fetchMock).toHaveBeenCalledWith('/api/meta-ai/captures')
  })

  it('creates a capture and returns the analyzed record', async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ ok: true, capture: sampleCapture }) })
    vi.stubGlobal('fetch', fetchMock)

    const capture = await createMetaAiCapture({ sourceText: 'Increase budget. CPL is $0.04.', campaignName: 'VSL 2' })

    expect(capture.analysis.strategist.overallScore).toBe(43)
    expect(fetchMock).toHaveBeenCalledWith('/api/meta-ai/captures', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ sourceText: 'Increase budget. CPL is $0.04.', campaignName: 'VSL 2' }),
    })
  })

  it('surfaces the backend error detail on failure', async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: false, status: 400, json: async () => ({ detail: 'Paste the Meta AI text' }) })
    vi.stubGlobal('fetch', fetchMock)

    await expect(createMetaAiCapture({ sourceText: '' })).rejects.toThrow('Paste the Meta AI text')
  })
})
