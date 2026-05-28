import type {
  AudienceScore,
  Ad,
  AdSet,
  AgentInsight,
  ApprovalAction,
  Campaign,
  Creative,
  CreativeAnalysis,
  CreativeScore,
  DailyAdMetric,
  DashboardData,
  DashboardKpi,
  ExperimentRecommendation,
  FunnelSummary,
  MetricGlossaryItem,
  Placement,
  PlacementScore,
  TrackingHealthItem,
  TrendPoint,
} from '../types/marketing'

const placementLabels: Record<Placement, string> = {
  instagram_reels: 'IG Reels',
  instagram_stories: 'IG Stories',
  instagram_feed: 'IG Feed',
  facebook_feed: 'FB Feed',
  facebook_reels: 'FB Reels',
  audience_network: 'Audience Network',
  messenger: 'Messenger',
}

export type DateRange = '7d' | '30d' | '90d'

export function getDateWindow(range: DateRange, anchorDate: string) {
  const days = range === '7d' ? 7 : range === '30d' ? 30 : 90
  const date = new Date(`${anchorDate}T00:00:00`)
  date.setDate(date.getDate() - days + 1)
  return { start: formatDateKey(date), end: anchorDate }
}

export function campaignOverlapsWindow(
  campaign: Pick<Campaign, 'startedAt' | 'endedAt' | 'status'>,
  window: { start: string; end: string },
) {
  const campaignStart = campaign.startedAt || window.start
  const campaignEnd = campaign.endedAt || (campaign.status === 'active' ? window.end : campaignStart)
  return campaignStart <= window.end && campaignEnd >= window.start
}

export function formatNumber(value: number) {
  return new Intl.NumberFormat('en-US').format(value)
}

export function deriveFunnel(metrics: DailyAdMetric[]): FunnelSummary[] {
  const totals = metrics.reduce(
    (acc, row) => {
      acc.impressions += row.impressions
      acc.clicks += row.clicks
      acc.landingPageViews += row.landingPageViews
      acc.leads += row.leads
      acc.telegramSubscribers += row.telegramSubscribers
      acc.webinarAttendees += row.webinarAttendees
      acc.purchases += row.purchases
      return acc
    },
    {
      impressions: 0,
      clicks: 0,
      landingPageViews: 0,
      leads: 0,
      telegramSubscribers: 0,
      webinarAttendees: 0,
      purchases: 0,
    },
  )

  const rate = (value: number, previous: number) =>
    previous === 0 ? '0%' : `${((value / previous) * 100).toFixed(1)}%`

  return [
    { step: 'Ad impressions', value: totals.impressions, rate: '100%' },
    { step: 'Clicks', value: totals.clicks, rate: rate(totals.clicks, totals.impressions) },
    {
      step: 'Landing visits',
      value: totals.landingPageViews,
      rate: rate(totals.landingPageViews, totals.clicks),
    },
    { step: 'Leads', value: totals.leads, rate: rate(totals.leads, totals.landingPageViews) },
    {
      step: 'Telegram subs',
      value: totals.telegramSubscribers,
      rate: rate(totals.telegramSubscribers, totals.leads),
    },
    {
      step: 'Webinar attendees',
      value: totals.webinarAttendees,
      rate: rate(totals.webinarAttendees, totals.telegramSubscribers),
    },
    { step: 'Buyers', value: totals.purchases, rate: rate(totals.purchases, totals.webinarAttendees) },
  ]
}

export function deriveTrend(metrics: DailyAdMetric[]): TrendPoint[] {
  const byDate = new Map<string, TrendPoint>()

  metrics.forEach((row) => {
    const current = byDate.get(row.date) ?? {
      day: formatTrendDate(row.date),
      spend: 0,
      leads: 0,
      buyers: 0,
    }

    current.spend += row.spendUsd
    current.leads += row.leads
    current.buyers += row.purchases
    byDate.set(row.date, current)
  })

  return Array.from(byDate.entries())
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([, value]) => value)
}

export function deriveCreativeScores(
  metrics: DailyAdMetric[],
  creatives: Creative[],
  analyses: CreativeAnalysis[],
): CreativeScore[] {
  const rawScores = creatives.map((creative) => {
    const rows = metrics.filter((row) => row.creativeId === creative.id)
    const analysis = analyses.find((item) => item.creativeId === creative.id)

    const clicks = sumBy(rows, (row) => row.clicks)
    const leads = sumBy(rows, (row) => row.leads)
    const buyers = sumBy(rows, (row) => row.purchases)
    const leadRate = clicks === 0 ? 0 : Math.min(1, leads / clicks)

    return { creative, analysis, clicks, leads, buyers, leadRate }
  })

  const maxClicks = Math.max(1, ...rawScores.map((score) => score.clicks))
  const maxLeads = Math.max(1, ...rawScores.map((score) => score.leads))
  const maxBuyers = Math.max(1, ...rawScores.map((score) => score.buyers))

  return rawScores
    .map(({ creative, analysis, clicks, leads, buyers, leadRate }) => {
      const viral = analysis?.viralScore ?? Math.round((clicks / maxClicks) * 100)
      const intent = analysis?.buyerIntentScore ?? Math.round(leadRate * 100)
      const leadVolumeScore = Math.round((leads / maxLeads) * 100)
      const buyerScore = Math.round((buyers / maxBuyers) * 100)
      const courseFit = analysis?.courseFitScore ?? Math.round(leadVolumeScore * 0.7 + buyerScore * 0.3)
      const quality =
        analysis === undefined
          ? Math.round(viral * 0.25 + intent * 0.3 + courseFit * 0.3 + buyerScore * 0.15)
          : Math.round(
              (analysis.buyerIntentScore +
                analysis.courseFitScore +
                analysis.purchasingPowerScore +
                analysis.funnelQualityScore) /
                4,
            )

      const action =
        analysis?.recommendedAction ??
        (buyers > 0
          ? 'Scale'
          : leads >= maxLeads * 0.5
            ? 'Audit quality'
            : leadRate >= 0.7
              ? 'Test follow-up'
              : 'Review')
      const tone: CreativeScore['tone'] = quality >= 70 ? 'good' : quality >= 45 ? 'warning' : 'danger'

      return {
        id: creative.id,
        rank: 0,
        name: creative.name,
        type: creative.theme,
        format: creative.format,
        assetUrl: creative.assetUrl,
        videoId: creative.videoId,
        videoUrl: creative.videoUrl,
        clicks,
        leads,
        buyers,
        viral,
        intent,
        courseFit,
        quality,
        action,
        tone,
      }
    })
    .sort((a, b) => b.quality - a.quality || b.buyers - a.buyers || b.leads - a.leads || b.clicks - a.clicks)
    .map((score, index) => ({ ...score, rank: index + 1 }))
}

export function derivePlacementScores(metrics: DailyAdMetric[]): PlacementScore[] {
  const totalSpend = sumBy(metrics, (row) => row.spendUsd)
  const byPlacement = new Map<Placement, { spend: number; buyers: number }>()

  metrics.forEach((row) => {
    const current = byPlacement.get(row.placement) ?? { spend: 0, buyers: 0 }
    current.spend += row.spendUsd
    current.buyers += row.purchases
    byPlacement.set(row.placement, current)
  })

  return Array.from(byPlacement.entries()).map(([placement, value]) => ({
    name: placementLabels[placement],
    value: totalSpend === 0 ? 0 : Math.round((value.spend / totalSpend) * 100),
    buyers: value.buyers,
  }))
}

export function composeDashboardData(args: {
  campaigns: Campaign[]
  adSets: AdSet[]
  ads: Ad[]
  metrics: DailyAdMetric[]
  creatives: Creative[]
  analyses: CreativeAnalysis[]
  kpis: DashboardKpi[]
  audience: AudienceScore[]
  insights: AgentInsight[]
  experiments: ExperimentRecommendation[]
  trackingHealth: TrackingHealthItem[]
  approvalActions: ApprovalAction[]
  glossary: MetricGlossaryItem[]
}): DashboardData {
  return {
    campaigns: args.campaigns,
    adSets: args.adSets,
    ads: args.ads,
    creatives: args.creatives,
    creativeAnalyses: args.analyses,
    metrics: args.metrics,
    kpis: args.kpis,
    funnel: deriveFunnel(args.metrics),
    trend: deriveTrend(args.metrics),
    creativeScores: deriveCreativeScores(args.metrics, args.creatives, args.analyses),
    placements: derivePlacementScores(args.metrics),
    audience: args.audience,
    insights: args.insights,
    experiments: args.experiments,
    trackingHealth: args.trackingHealth,
    approvalActions: args.approvalActions,
    glossary: args.glossary,
  }
}

function sumBy<T>(rows: T[], select: (row: T) => number) {
  return rows.reduce((total, row) => total + select(row), 0)
}

function formatTrendDate(date: string) {
  const parsed = new Date(`${date}T00:00:00`)
  return parsed.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
}

function formatDateKey(date: Date) {
  const year = date.getFullYear()
  const month = String(date.getMonth() + 1).padStart(2, '0')
  const day = String(date.getDate()).padStart(2, '0')
  return `${year}-${month}-${day}`
}
