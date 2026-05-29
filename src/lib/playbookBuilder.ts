import type { CampaignPlaybook, CampaignPlaybookSegment } from '../types/marketing'

export type PlaybookDraftInput = {
  name: string
  startingBudgetUsd: number
  maxDailyBudgetUsd: number
  salesCapacityLeadsPerDay: number
  scalingStepPercent: number
  primarySuccessMetric: string
  segments: CampaignPlaybookSegment[]
}

export type PlaybookReadiness = {
  segmentCount: number
  readySegments: number
  missingLandingPages: number
  missingTelegramBots: number
  totalStartingBudgetUsd: number
}

export function slugifySegmentId(value: string) {
  const slug = value
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '_')
    .replace(/^_+|_+$/g, '')
    .replace(/_+/g, '_')
  return slug || 'segment'
}

export function parseCsvList(value: string) {
  return value
    .split(',')
    .map((item) => item.trim())
    .filter(Boolean)
}

export function buildEmptySegment(name = 'New segment'): CampaignPlaybookSegment {
  return {
    id: slugifySegmentId(name),
    name,
    description: '',
    vslId: '',
    landingPageUrl: '',
    telegramBotUrl: '',
    targetAudienceNotes: '',
    painPoints: [],
    offerAngle: '',
    creativeCountTarget: 8,
    startingBudgetUsd: undefined,
    guardrails: [],
    locations: ['Uzbekistan'],
    placements: ['instagram_reels', 'instagram_stories', 'instagram_feed'],
    interests: [],
    ageRange: 'Broad',
    gender: 'all',
  }
}

export function buildPlaybookDraft(input: PlaybookDraftInput): CampaignPlaybook {
  const now = new Date().toISOString()
  const rules = {
    startingBudgetUsd: numberOrDefault(input.startingBudgetUsd, 100),
    maxDailyBudgetUsd: numberOrDefault(input.maxDailyBudgetUsd, 500),
    scalingStepPercent: numberOrDefault(input.scalingStepPercent, 20),
    scalingFrequencyDays: 1,
    salesCapacityLeadsPerDay: numberOrDefault(input.salesCapacityLeadsPerDay, 200),
    requiresApprovalForExecution: true,
  }

  return {
    id: `pb_${slugifySegmentId(input.name)}_${Date.now()}`,
    name: input.name.trim() || 'Configurable campaign playbook',
    goal: 'Launch controlled Meta campaign tests and optimize toward downstream buyer quality.',
    primarySuccessMetric: input.primarySuccessMetric.trim() || 'bot_start',
    secondarySuccessMetrics: ['form_button_click', 'qualified_lead', 'full_payment'],
    segments: input.segments
      .filter((segment) => segment.name.trim())
      .map((segment) => ({
        ...segment,
        id: slugifySegmentId(segment.id || segment.name),
        creativeCountTarget: numberOrDefault(segment.creativeCountTarget, 8),
        startingBudgetUsd: numberOrDefault(segment.startingBudgetUsd, rules.startingBudgetUsd),
        locations: segment.locations?.length ? segment.locations : ['Uzbekistan'],
        placements: segment.placements?.length
          ? segment.placements
          : ['instagram_reels', 'instagram_stories', 'instagram_feed'],
        interests: segment.interests ?? [],
        guardrails: segment.guardrails ?? [],
      })),
    rules,
    alertChannels: ['dashboard'],
    approvalChannels: ['dashboard', 'telegram'],
    createdAt: now,
    updatedAt: now,
  }
}

export function summarizePlaybookReadiness(playbook: CampaignPlaybook): PlaybookReadiness {
  const missingLandingPages = playbook.segments.filter((segment) => !segment.landingPageUrl?.trim()).length
  const missingTelegramBots = playbook.segments.filter((segment) => !segment.telegramBotUrl?.trim()).length
  const readySegments = playbook.segments.filter(
    (segment) => Boolean(segment.landingPageUrl?.trim()) && Boolean(segment.telegramBotUrl?.trim()),
  ).length
  return {
    segmentCount: playbook.segments.length,
    readySegments,
    missingLandingPages,
    missingTelegramBots,
    totalStartingBudgetUsd: playbook.segments.reduce(
      (total, segment) => total + numberOrDefault(segment.startingBudgetUsd, playbook.rules.startingBudgetUsd),
      0,
    ),
  }
}

function numberOrDefault(value: number | undefined, fallback: number) {
  return Number.isFinite(value) && value !== undefined && value > 0 ? value : fallback
}
