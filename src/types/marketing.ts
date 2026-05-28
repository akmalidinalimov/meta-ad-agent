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
    kind: 'mock' | 'meta'
    label: string
    generatedAt?: string | null
    rawCounts?: Record<string, number>
    syncErrors?: Array<{ source: string; error: string }>
  }
}
