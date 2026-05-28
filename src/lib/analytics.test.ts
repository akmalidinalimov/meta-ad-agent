import { describe, expect, it } from 'vitest'
import { campaignOverlapsWindow, deriveCreativeScores, getDateWindow } from './analytics'
import type { Campaign, Creative, CreativeAnalysis, DailyAdMetric } from '../types/marketing'

describe('getDateWindow', () => {
  it('builds an inclusive 30 day window anchored to the latest dashboard date', () => {
    expect(getDateWindow('30d', '2026-05-28')).toEqual({
      start: '2026-04-29',
      end: '2026-05-28',
    })
  })
})

describe('campaignOverlapsWindow', () => {
  const window = { start: '2026-04-29', end: '2026-05-28' }

  it('excludes campaigns that ended before the selected window', () => {
    const campaign: Campaign = {
      id: 'old',
      platform: 'meta',
      name: 'Old campaign',
      objective: 'leads',
      status: 'completed',
      dailyBudgetUsd: 10,
      startedAt: '2026-03-01',
      endedAt: '2026-03-20',
    }

    expect(campaignOverlapsWindow(campaign, window)).toBe(false)
  })

  it('includes active campaigns that started inside the selected window', () => {
    const campaign: Campaign = {
      id: 'active',
      platform: 'meta',
      name: 'Active campaign',
      objective: 'leads',
      status: 'active',
      dailyBudgetUsd: 10,
      startedAt: '2026-05-10',
    }

    expect(campaignOverlapsWindow(campaign, window)).toBe(true)
  })
})

describe('deriveCreativeScores', () => {
  const creatives: Creative[] = [
    {
      id: 'creative_a',
      adId: 'ad_a',
      name: 'Buyer proof',
      format: 'video',
      theme: 'proof',
      hookType: 'case study',
      primaryPersona: 'business owner',
      cta: 'Join webinar',
    },
    {
      id: 'creative_b',
      adId: 'ad_b',
      name: 'Viral curiosity',
      format: 'video',
      theme: 'viral',
      hookType: 'curiosity',
      primaryPersona: 'broad',
      cta: 'Watch',
    },
  ]

  const analyses: CreativeAnalysis[] = [
    {
      creativeId: 'creative_a',
      viralScore: 55,
      buyerIntentScore: 88,
      courseFitScore: 90,
      purchasingPowerScore: 86,
      funnelQualityScore: 84,
      hookSummary: 'Specific business proof',
      conversionRisk: 'low',
      recommendedAction: 'Scale',
      sceneNotes: [],
      whyItWorked: 'It qualifies buyers.',
      whyItDidNotConvert: 'No major issue.',
    },
    {
      creativeId: 'creative_b',
      viralScore: 98,
      buyerIntentScore: 25,
      courseFitScore: 30,
      purchasingPowerScore: 20,
      funnelQualityScore: 18,
      hookSummary: 'Curiosity hook',
      conversionRisk: 'high',
      recommendedAction: 'Rebuild',
      sceneNotes: [],
      whyItWorked: 'It gets clicks.',
      whyItDidNotConvert: 'Weak purchase intent.',
    },
  ]

  const metrics: DailyAdMetric[] = [
    {
      date: '2026-05-20',
      campaignId: 'campaign_1',
      adSetId: 'adset_1',
      adId: 'ad_a',
      creativeId: 'creative_a',
      placement: 'instagram_reels',
      spendUsd: 100,
      impressions: 10000,
      clicks: 500,
      landingPageViews: 420,
      leads: 120,
      telegramSubscribers: 80,
      webinarAttendees: 30,
      purchases: 6,
      purchaseRevenueUsd: 1200,
    },
    {
      date: '2026-05-20',
      campaignId: 'campaign_1',
      adSetId: 'adset_2',
      adId: 'ad_b',
      creativeId: 'creative_b',
      placement: 'instagram_reels',
      spendUsd: 100,
      impressions: 30000,
      clicks: 2000,
      landingPageViews: 1200,
      leads: 220,
      telegramSubscribers: 40,
      webinarAttendees: 4,
      purchases: 0,
      purchaseRevenueUsd: 0,
    },
  ]

  it('ranks buyer-quality creatives above viral low-intent creatives', () => {
    const scores = deriveCreativeScores(metrics, creatives, analyses)

    expect(scores[0].id).toBe('creative_a')
    expect(scores[0].rank).toBe(1)
    expect(scores[1].id).toBe('creative_b')
    expect(scores[1].rank).toBe(2)
  })
})
