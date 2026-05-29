export type Tone = 'good' | 'warning' | 'danger' | 'neutral'

export type IconName =
  | 'alert'
  | 'bot'
  | 'check'
  | 'dollar'
  | 'target'
  | 'trendingDown'
  | 'users'

export type FunnelStage =
  | 'ad_impression'
  | 'ad_click'
  | 'landing_visit'
  | 'lead'
  | 'telegram_subscriber'
  | 'webinar_attendee'
  | 'buyer'

export type AdPlatform = 'meta' | 'youtube'

export type Placement =
  | 'instagram_reels'
  | 'instagram_stories'
  | 'instagram_feed'
  | 'facebook_feed'
  | 'facebook_reels'
  | 'audience_network'
  | 'messenger'

export interface Campaign {
  id: string
  platform: AdPlatform
  name: string
  objective: 'sales' | 'leads' | 'traffic' | 'engagement' | 'awareness'
  status: 'active' | 'paused' | 'completed'
  dailyBudgetUsd: number
  startedAt: string
  endedAt?: string
}

export interface AdSet {
  id: string
  campaignId: string
  name: string
  status: 'active' | 'paused' | 'completed'
  ageMin: number
  ageMax: number
  genders: Array<'female' | 'male' | 'all'>
  locations: string[]
  interests: string[]
  placements: Placement[]
  optimizationGoal: 'lead' | 'landing_page_view' | 'purchase' | 'conversion'
}

export interface Creative {
  id: string
  adId: string
  campaignId?: string
  adSetId?: string
  name: string
  format: 'video' | 'image' | 'gif' | 'carousel'
  theme: string
  hookType: string
  primaryPersona: string
  cta: string
  assetUrl?: string
  videoId?: string
  videoUrl?: string
}

export interface CreativeAnalysis {
  creativeId: string
  viralScore: number
  buyerIntentScore: number
  courseFitScore: number
  purchasingPowerScore: number
  funnelQualityScore: number
  hookSummary: string
  conversionRisk: string
  recommendedAction: string
  sceneNotes: string[]
  whyItWorked: string
  whyItDidNotConvert: string
}

export interface Ad {
  id: string
  adSetId: string
  creativeId: string
  name: string
  status: 'active' | 'paused' | 'completed'
}

export interface DailyAdMetric {
  date: string
  campaignId: string
  adSetId: string
  adId: string
  creativeId: string
  placement: Placement
  spendUsd: number
  impressions: number
  clicks: number
  landingPageViews: number
  leads: number
  telegramSubscribers: number
  webinarAttendees: number
  purchases: number
  purchaseRevenueUsd: number
}

export interface FunnelEvent {
  id: string
  stage: FunnelStage
  occurredAt: string
  campaignId?: string
  adSetId?: string
  adId?: string
  creativeId?: string
  telegramUserId?: string
  valueUsd?: number
}

export interface DashboardKpi {
  label: string
  value: string
  change: string
  helper: string
  tone: Tone
  icon: IconName
}

export interface FunnelSummary {
  step: string
  value: number
  rate: string
}

export interface TrendPoint {
  day: string
  spend: number
  leads: number
  buyers: number
}

export interface CreativeScore {
  id: string
  rank: number
  name: string
  type: string
  format: Creative['format']
  assetUrl?: string
  videoId?: string
  videoUrl?: string
  clicks: number
  leads: number
  buyers: number
  viral: number
  intent: number
  courseFit: number
  quality: number
  action: string
  tone: Tone
}

export interface PlacementScore {
  name: string
  value: number
  buyers: number
}

export interface RankingRow {
  id: string
  rank: number
  name: string
  category: 'segment' | 'campaign' | 'audience' | 'creative' | 'placement'
  spendUsd: number
  clicks: number
  leads: number
  telegramSubscribers: number
  purchases: number
  cpl: number
  costPerTelegramStart: number
  buyerRate: number
  qualityScore: number
  recommendedAction: string
  tone: Tone
}

export interface AudienceScore {
  segment: string
  spend: number
  subs: number
  buyers: number
}

export interface AgentInsight {
  icon: IconName
  title: string
  body: string
  tone: Tone
}

export interface ExperimentRecommendation {
  title: string
  metric: string
  budget: string
}

export interface TrackingHealthItem {
  name: string
  status: 'healthy' | 'warning' | 'broken'
  matchRate: number
  lastEventAt: string
  note: string
}

export interface ApprovalAction {
  id: string
  title: string
  impact: string
  risk: 'low' | 'medium' | 'high'
  owner: 'agent' | 'human'
  status: 'ready' | 'needs_review' | 'blocked'
}

export interface MetricGlossaryItem {
  metric: string
  definition: string
  watchFor: string
}

export interface DashboardFilters {
  dateRange: '7d' | '30d' | '90d'
  campaignIds: string[]
  creativeFormat: 'all' | Creative['format']
  placement: 'all' | Placement
  audience: 'all' | string
  funnelStage: 'all' | FunnelStage
  objective: 'all' | Campaign['objective']
}

export interface DashboardData {
  campaigns: Campaign[]
  adSets: AdSet[]
  ads: Ad[]
  creatives: Creative[]
  creativeAnalyses: CreativeAnalysis[]
  metrics: DailyAdMetric[]
  kpis: DashboardKpi[]
  funnel: FunnelSummary[]
  trend: TrendPoint[]
  creativeScores: CreativeScore[]
  placements: PlacementScore[]
  audience: AudienceScore[]
  insights: AgentInsight[]
  experiments: ExperimentRecommendation[]
  trackingHealth: TrackingHealthItem[]
  approvalActions: ApprovalAction[]
  glossary: MetricGlossaryItem[]
  dataSource?: {
    kind: 'mock' | 'meta' | 'imported'
    label: string
    generatedAt?: string | null
    snapshotId?: string
    days?: number
    rawCounts?: Record<string, number>
    syncErrors?: Array<{ source: string; error: string }>
  }
}

export interface MetaSnapshot {
  id: string
  kind: 'meta'
  accountId: string
  days: number
  generatedAt: string
  rawCounts: Record<string, number>
  summary?: Record<string, number>
}

export interface CampaignPlaybookSegment {
  id: string
  name: string
  description?: string
  vslId?: string
  landingPageUrl?: string
  telegramBotUrl?: string
  targetAudienceNotes?: string
  painPoints?: string[]
  offerAngle?: string
  creativeCountTarget?: number
  startingBudgetUsd?: number
  guardrails?: string[]
  locations?: string[]
  placements?: string[]
  interests?: string[]
  ageRange?: string
  gender?: 'all' | 'female' | 'male'
}

export interface CampaignPlaybook {
  id: string
  name: string
  goal: string
  primarySuccessMetric: string
  secondarySuccessMetrics: string[]
  segments: CampaignPlaybookSegment[]
  rules: {
    startingBudgetUsd: number
    maxDailyBudgetUsd: number
    scalingStepPercent: number
    scalingFrequencyDays: number
    salesCapacityLeadsPerDay: number
    requiresApprovalForExecution: boolean
  }
  alertChannels: string[]
  approvalChannels: string[]
  createdAt?: string
  updatedAt?: string
}

export interface LaunchStrategySegment {
  id: string
  name: string
  budgetUsd: number
  audienceHypothesis: string
  offerAngle: string
  ageRange: string
  gender: string
  geoStrategy: {
    locations: string[]
    recommendation: string
    watchlist: string[]
  }
  recommendedPlacements: string[]
  interestStrategy: string[]
  creativeAngles: string[]
  funnelReadiness: {
    status: 'ready' | 'needs_links'
    missing: string[]
    trackingPlan: string
  }
  scaleRule: string
  stopRule: string
}

export interface LaunchStrategy {
  id: string
  playbookId: string
  playbookName: string
  generatedAt: string
  summary: string
  execution: {
    mode: string
    requiresApproval: boolean
    approvalChannels: string[]
  }
  budget: {
    totalDailyBudgetUsd: number
    maxDailyBudgetUsd: number
    scalingStepPercent: number
    scalingFrequencyDays: number
    salesCapacityLeadsPerDay: number
    estimatedDailyLeadLoad: number
    split: Array<{
      segmentId: string
      segmentName: string
      dailyBudgetUsd: number
      sharePercent: number
    }>
  }
  segments: LaunchStrategySegment[]
  testMatrix: Array<{
    day: string
    test: string
    decisionMetric: string
    action: string
  }>
  approvalActions: ApprovalAction[]
  risks: string[]
  knowledgeUsed: {
    bestPlacements: string[]
    bestInterests: string[]
    bestRegions: string[]
    lessons: string[]
    recommendations: Array<{ area?: string; title?: string; reason?: string }>
  }
  assumptions: string[]
}

export interface ApprovalRequest {
  id: string
  actionType: string
  target: {
    level: string
    id: string
    name: string
  }
  after: {
    campaign?: {
      name: string
      objective: string
      status: string
    }
    adsets?: Array<{
      name: string
      status: string
      daily_budget: number
      optimization_goal: string
      targeting: {
        publisher_platforms?: string[]
        instagram_positions?: string[]
        flexible_spec?: Array<{
          interests?: Array<{ name: string }>
        }>
      }
    }>
  }
  reason: string
  risk: 'low' | 'medium' | 'high' | string
  expectedImpact: string
  guardrailResult: 'pass' | 'warn' | 'fail' | string
  guardrailChecks: Array<{
    result: 'pass' | 'warn' | 'fail' | string
    message: string
  }>
  executionMethod: string
  requiresApproval: boolean
  status: string
  createdAt: string
  updatedAt?: string
  approvedBy?: string
  approvedAt?: string
  lastExecutionResult?: {
    ok?: boolean
    dryRun?: boolean
    note?: string
  }
}

export interface MetaSettingsAudit {
  summary: {
    campaigns: number
    adsets: number
    ads: number
    advantageAudienceAdsets: number
    instagramOnlyAdsets: number
    facebookMixedAdsets: number
    countryTargetedAdsets: number
    regionTargetedAdsets: number
  }
  campaigns: Array<{
    id: string
    name: string
    status: string
    objective: string
    dailyBudgetUsd: number
    lifetimeBudgetUsd: number
    startTime?: string
    stopTime?: string
  }>
  adsets: Array<{
    id: string
    campaignId: string
    name: string
    status: string
    optimizationGoal: string
    dailyBudgetUsd: number
    ageMin: number
    ageMax: number
    genders: string[]
    locations: string[]
    geoStrategy: string
    interests: string[]
    advantageAudience: boolean
    placements: string[]
    platformStrategy: string
    recommendedUse: string
  }>
  placementMix: Array<{ placement: string; adsetCount: number }>
  objectiveMix: Array<{ objective: string; campaignCount: number }>
  risks: Array<{
    severity: 'info' | 'warning' | 'danger'
    area: string
    title: string
    detail: string
  }>
  policy: {
    executionMode: string
    primaryInterface: string
    browserFallback: string
  }
}

export interface FunnelEventSummary {
  totalEvents: number
  eventsByName: Record<string, number>
  eventsBySegment: Record<string, Record<string, number>>
  uniqueVisitors: number
  uniqueTelegramUsers: number
  latestEventAt?: string | null
  eventSteps?: Array<{
    eventName: string
    count: number
    uniqueVisitors: number
    rateFromPrevious: number | null
  }>
  rates?: {
    telegramStartRate: number
    keyMessageReachRate: number
    formClickRate: number
    qualifiedLeadRate: number
    fullPaymentRate: number
  }
}
