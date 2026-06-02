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
  RankingRow,
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

export interface CreativeDecisionInsight {
  creativeId: string
  spendUsd: number
  clicks: number
  leads: number
  buyers: number
  cpc: number
  cpl: number
  leadRatePercent: number
  landingVisitRatePercent: number
  topAudience: string
  topPlacement: string
  diagnosis: string
  nextAction: string
  replicateSignals: string[]
  risks: string[]
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

export function filterMetricsForDashboard(args: {
  metrics: DailyAdMetric[]
  campaigns: Campaign[]
  ads: Ad[]
  creatives: Creative[]
  filters: {
    start: string
    campaignIds: string[]
    creativeFormat: 'all' | Creative['format']
    placement: 'all' | Placement
    objective: 'all' | Campaign['objective']
  }
}) {
  const campaignById = new Map(args.campaigns.map((campaign) => [campaign.id, campaign]))
  const adIds = new Set(args.ads.map((ad) => ad.id))
  const creativeById = new Map(args.creatives.map((creative) => [creative.id, creative]))

  return args.metrics.filter((metric) => {
    const creative = creativeById.get(metric.creativeId)
    const campaign = campaignById.get(metric.campaignId)

    return (
      metric.date >= args.filters.start &&
      (args.filters.campaignIds.includes('all') || args.filters.campaignIds.includes(metric.campaignId)) &&
      (args.filters.creativeFormat === 'all' || creative?.format === args.filters.creativeFormat) &&
      (args.filters.placement === 'all' || metric.placement === args.filters.placement) &&
      (args.filters.objective === 'all' || campaign?.objective === args.filters.objective) &&
      adIds.has(metric.adId)
    )
  })
}

export function getCampaignOptions(args: {
  campaigns: Campaign[]
  window: { start: string; end: string }
  objective: 'all' | Campaign['objective']
}) {
  return args.campaigns.filter(
    (campaign) =>
      campaignOverlapsWindow(campaign, args.window) &&
      (args.objective === 'all' || campaign.objective === args.objective),
  )
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
    const spendUsd = sumBy(rows, (row) => row.spendUsd)
    const leadRate = clicks === 0 ? 0 : Math.min(1, leads / clicks)

    return { creative, analysis, clicks, leads, buyers, spendUsd, leadRate }
  })

  const maxClicks = Math.max(1, ...rawScores.map((score) => score.clicks))
  const maxLeads = Math.max(1, ...rawScores.map((score) => score.leads))
  const maxBuyers = Math.max(1, ...rawScores.map((score) => score.buyers))
  // Best (lowest) CPL among creatives that actually produced leads, for normalization.
  const cplValues = rawScores.filter((s) => s.leads > 0).map((s) => s.spendUsd / s.leads)
  const bestCpl = cplValues.length ? Math.min(...cplValues) : 0

  return rawScores
    .map(({ creative, analysis, clicks, leads, buyers, spendUsd, leadRate }) => {
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

      const cpl = leads === 0 ? 0 : spendUsd / leads
      const leadRatePercent = Math.round(leadRate * 1000) / 10
      // Spend/sample confidence: enough clicks AND spend to trust the numbers.
      const spendConfidence: CreativeScore['spendConfidence'] =
        clicks >= 500 && spendUsd >= 50 ? 'high' : clicks >= 100 && spendUsd >= 10 ? 'medium' : 'low'
      const lowSample = clicks < 100 || spendUsd < 5
      // Viral/intent mismatch: attention without buyer intent is a quality risk.
      const mismatch = Math.max(0, viral - intent)

      // Composite rank: reward leads, lead rate, cheap CPL, sample confidence and
      // buyer intent; penalize viral/intent mismatch and thin samples.
      const cplScore = bestCpl > 0 && cpl > 0 ? Math.round(Math.min(1, bestCpl / cpl) * 100) : 0
      const confidenceScore = spendConfidence === 'high' ? 100 : spendConfidence === 'medium' ? 60 : 20
      const rankScore = Math.round(
        quality * 0.34 +
          intent * 0.18 +
          leadVolumeScore * 0.16 +
          leadRatePercent * 0.12 +
          cplScore * 0.1 +
          confidenceScore * 0.1 -
          mismatch * 0.4 -
          (lowSample ? 12 : 0),
      )

      const action =
        analysis?.recommendedAction ??
        (lowSample
          ? 'Gather data'
          : buyers > 0
            ? 'Scale'
            : mismatch >= 40
              ? 'Fix intent'
              : leads >= maxLeads * 0.5
                ? 'Audit quality'
                : leadRate >= 0.7
                  ? 'Test follow-up'
                  : 'Review')
      const tone: CreativeScore['tone'] = quality >= 70 ? 'good' : quality >= 45 ? 'warning' : 'danger'

      return {
        id: creative.id,
        rank: 0,
        rankScore,
        name: creative.name,
        type: creative.theme,
        format: creative.format,
        assetUrl: creative.assetUrl,
        videoId: creative.videoId,
        videoUrl: creative.videoUrl,
        clicks,
        leads,
        buyers,
        spendUsd,
        cpl,
        leadRate: leadRatePercent,
        spendConfidence,
        lowSample,
        mismatch,
        viral,
        intent,
        courseFit,
        quality,
        action,
        tone,
      }
    })
    .sort((a, b) => b.rankScore - a.rankScore || b.leads - a.leads || a.cpl - b.cpl || b.clicks - a.clicks)
    .map((score, index) => {
      const result: CreativeScore = { ...score, rank: index + 1 }
      delete (result as { rankScore?: number }).rankScore
      return result
    })
}

export function deriveCreativeDecisionInsight(args: {
  creativeId: string
  metrics: DailyAdMetric[]
  adSets: AdSet[]
  score?: CreativeScore
}): CreativeDecisionInsight {
  const rows = args.metrics.filter((row) => row.creativeId === args.creativeId)
  const spendUsd = sumBy(rows, (row) => row.spendUsd)
  const clicks = sumBy(rows, (row) => row.clicks)
  const landingPageViews = sumBy(rows, (row) => row.landingPageViews)
  const leads = sumBy(rows, (row) => row.leads)
  const buyers = sumBy(rows, (row) => row.purchases)
  const cpc = clicks === 0 ? 0 : spendUsd / clicks
  const cpl = leads === 0 ? 0 : spendUsd / leads
  const leadRatePercent = clicks === 0 ? 0 : (leads / clicks) * 100
  const rawLandingVisitRatePercent = clicks === 0 ? 0 : (landingPageViews / clicks) * 100
  const landingVisitRatePercent = Math.min(100, rawLandingVisitRatePercent)
  const topPlacement = topMetricLabel(rows, (row) => placementLabels[row.placement], (row) => row.leads)
  const adSetById = new Map(args.adSets.map((adSet) => [adSet.id, adSet]))
  const topAudience = topMetricLabel(
    rows,
    (row) => adSetById.get(row.adSetId)?.name ?? row.adSetId,
    (row) => row.leads,
  )
  const quality = args.score?.quality ?? 0
  const intent = args.score?.intent ?? leadRatePercent

  const replicateSignals = [
    leads > 0 ? `${formatNumber(leads)} leads captured` : 'No lead volume yet',
    clicks > 0 ? `${formatNumber(clicks)} clicks generated` : 'No click volume yet',
    topAudience !== 'Not enough data' ? `Strongest audience: ${topAudience}` : 'Audience winner not proven yet',
    topPlacement !== 'Not enough data' ? `Strongest placement: ${topPlacement}` : 'Placement winner not proven yet',
  ]

  const risks = [
    buyers === 0 ? 'No attributed buyers yet, so quality must be validated with Telegram/CRM data.' : '',
    leadRatePercent >= 70 && buyers === 0
      ? 'Very high lead rate with no buyers can indicate curiosity traffic or low purchasing power.'
      : '',
    landingVisitRatePercent > 0 && landingVisitRatePercent < 70
      ? 'Landing visit rate is weak; page speed, load quality, or click intent may be leaking traffic.'
      : '',
    rawLandingVisitRatePercent > 110
      ? 'Meta landing visits exceed clicks; verify action attribution before treating visit rate as exact.'
      : '',
    spendUsd > 0 && leads === 0 ? 'Spend is present but lead capture is missing.' : '',
  ].filter(Boolean)

  const diagnosis =
    buyers > 0 && quality >= 70
      ? 'Scale candidate: this creative has downstream buyer proof and strong quality.'
      : leads >= 100 && buyers === 0
        ? 'Traffic magnet: this creative attracts attention and registrations, but buyer quality is unproven.'
        : intent >= 70 && quality >= 55
          ? 'Lead-quality candidate: keep testing, but verify payment intent before scaling.'
          : clicks < 50
            ? 'Insufficient data: give it controlled spend before judging the hook.'
            : 'Review candidate: performance exists, but the creative needs clearer offer or audience matching.'

  const nextAction =
    buyers > 0 && quality >= 70
      ? 'Replicate the hook and audience, then test one new visual variation against it.'
      : leads >= 100 && buyers === 0
        ? 'Audit lead quality before scaling; pair it with higher purchasing-power audiences.'
        : clicks < 50
          ? 'Keep it in rotation until it reaches enough clicks for a fair read.'
          : 'Retest with stronger proof, clearer AI income outcome, or a narrower audience.'

  return {
    creativeId: args.creativeId,
    spendUsd,
    clicks,
    leads,
    buyers,
    cpc,
    cpl,
    leadRatePercent,
    landingVisitRatePercent,
    topAudience,
    topPlacement,
    diagnosis,
    nextAction,
    replicateSignals,
    risks,
  }
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

export function deriveRankingRows(
  metrics: DailyAdMetric[],
  groups: Array<{ id: string; name: string; category: RankingRow['category']; metricIds: Set<string> }>,
): RankingRow[] {
  return groups
    .map((group) => {
      const rows = metrics.filter(
        (metric) =>
          group.metricIds.has(metric.adId) ||
          group.metricIds.has(metric.creativeId) ||
          group.metricIds.has(metric.campaignId) ||
          group.metricIds.has(metric.adSetId) ||
          group.metricIds.has(metric.placement),
      )
      const spendUsd = sumBy(rows, (row) => row.spendUsd)
      const clicks = sumBy(rows, (row) => row.clicks)
      const leads = sumBy(rows, (row) => row.leads)
      const telegramSubscribers = sumBy(rows, (row) => row.telegramSubscribers)
      const purchases = sumBy(rows, (row) => row.purchases)
      const cpc = clicks === 0 ? 0 : spendUsd / clicks
      const cpl = leads === 0 ? 0 : spendUsd / leads
      const costPerTelegramStart = telegramSubscribers === 0 ? 0 : spendUsd / telegramSubscribers
      const buyerRate = leads === 0 ? 0 : purchases / leads
      const telegramRate = clicks === 0 ? 0 : telegramSubscribers / clicks
      const leadRate = clicks === 0 ? 0 : leads / clicks
      const qualityScore = Math.round(
        Math.min(45, buyerRate * 1000) + Math.min(35, telegramRate * 100) + Math.min(20, leadRate * 50),
      )
      const tone: RankingRow['tone'] = qualityScore >= 70 ? 'good' : qualityScore >= 40 ? 'warning' : 'danger'
      const recommendedAction =
        purchases > 0 || qualityScore >= 70
          ? 'Scale carefully'
          : clicks > 0 && telegramSubscribers === 0
            ? 'Audit funnel'
            : 'Review'

      return {
        id: group.id,
        rank: 0,
        name: group.name,
        category: group.category,
        spendUsd,
        clicks,
        leads,
        telegramSubscribers,
        purchases,
        cpc,
        cpl,
        costPerTelegramStart,
        leadRatePercent: leadRate * 100,
        telegramStartRatePercent: telegramRate * 100,
        buyerRate,
        qualityScore,
        recommendedAction,
        tone,
      }
    })
    .filter((row) => row.spendUsd > 0 || row.clicks > 0 || row.leads > 0)
    .sort((a, b) => b.qualityScore - a.qualityScore || b.purchases - a.purchases || b.telegramSubscribers - a.telegramSubscribers)
    .map((row, index) => ({ ...row, rank: index + 1 }))
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

function topMetricLabel<T>(rows: T[], labelFor: (row: T) => string, valueFor: (row: T) => number) {
  const totals = new Map<string, number>()
  rows.forEach((row) => {
    const label = labelFor(row) || 'Unknown'
    totals.set(label, (totals.get(label) ?? 0) + valueFor(row))
  })

  const top = Array.from(totals.entries()).sort((a, b) => b[1] - a[1])[0]
  return top && top[1] > 0 ? top[0] : 'Not enough data'
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
