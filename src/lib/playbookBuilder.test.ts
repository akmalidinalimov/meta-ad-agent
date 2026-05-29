import { describe, expect, it } from 'vitest'
import {
  buildEmptySegment,
  buildPlaybookDraft,
  parseCsvList,
  slugifySegmentId,
  summarizePlaybookReadiness,
} from './playbookBuilder'

describe('playbook builder', () => {
  it('slugifies segment ids without hardcoding campaign categories', () => {
    expect(slugifySegmentId('Business Automation / Agents')).toBe('business_automation_agents')
    expect(slugifySegmentId('')).toBe('segment')
  })

  it('builds arbitrary segment drafts with inherited budget and defaults', () => {
    const draft = buildPlaybookDraft({
      name: 'June AI launch',
      startingBudgetUsd: 120,
      maxDailyBudgetUsd: 600,
      salesCapacityLeadsPerDay: 220,
      scalingStepPercent: 20,
      primarySuccessMetric: 'qualified_telegram_start',
      segments: [
        buildEmptySegment('Income'),
        {
          ...buildEmptySegment('Business owners'),
          startingBudgetUsd: 200,
          locations: ['Tashkent', 'Samarkand'],
          placements: ['instagram_reels', 'instagram_stories'],
        },
      ],
    })

    expect(draft.segments).toHaveLength(2)
    expect(draft.segments[0]).toMatchObject({
      id: 'income',
      name: 'Income',
      startingBudgetUsd: 120,
      creativeCountTarget: 8,
    })
    expect(draft.segments[1]).toMatchObject({
      id: 'business_owners',
      startingBudgetUsd: 200,
      locations: ['Tashkent', 'Samarkand'],
      placements: ['instagram_reels', 'instagram_stories'],
    })
  })

  it('summarizes readiness without requiring landing pages or bots', () => {
    const draft = buildPlaybookDraft({
      name: 'Flexible launch',
      startingBudgetUsd: 100,
      maxDailyBudgetUsd: 500,
      salesCapacityLeadsPerDay: 200,
      scalingStepPercent: 20,
      primarySuccessMetric: 'bot_start',
      segments: [
        { ...buildEmptySegment('Income'), landingPageUrl: '', telegramBotUrl: '' },
        { ...buildEmptySegment('Creator'), landingPageUrl: 'https://example.com', telegramBotUrl: 'https://t.me/bot' },
      ],
    })

    expect(summarizePlaybookReadiness(draft)).toEqual({
      segmentCount: 2,
      readySegments: 1,
      missingLandingPages: 1,
      missingTelegramBots: 1,
      totalStartingBudgetUsd: 200,
    })
  })

  it('only marks a segment ready when both landing page and Telegram bot are present', () => {
    const draft = buildPlaybookDraft({
      name: 'Mixed readiness',
      startingBudgetUsd: 100,
      maxDailyBudgetUsd: 500,
      salesCapacityLeadsPerDay: 200,
      scalingStepPercent: 20,
      primarySuccessMetric: 'bot_start',
      segments: [
        { ...buildEmptySegment('Landing only'), landingPageUrl: 'https://example.com', telegramBotUrl: '' },
        { ...buildEmptySegment('Bot only'), landingPageUrl: '', telegramBotUrl: 'https://t.me/bot' },
      ],
    })

    expect(summarizePlaybookReadiness(draft).readySegments).toBe(0)
  })

  it('parses comma-separated inputs into clean lists', () => {
    expect(parseCsvList('Uzbekistan, Tashkent,, Samarkand')).toEqual(['Uzbekistan', 'Tashkent', 'Samarkand'])
  })
})
