import { BarChart3 } from 'lucide-react'
import { deriveRankingRows, formatNumber } from '../../../lib/analytics'
import { formatCurrency, labelPlacement } from '../../../lib/format'
import type { DailyAdMetric, DashboardData, RankingRow } from '../../../types/marketing'
import { EmptyState } from '../shared/EmptyState'
import { PanelHeading } from '../shared/PanelHeading'

export function RankingsView({ data, metrics }: { data: DashboardData; metrics: DailyAdMetric[] }) {
  const campaignRankings = deriveRankingRows(
    metrics,
    data.campaigns.map((campaign) => ({
      id: campaign.id,
      name: campaign.name,
      category: 'campaign',
      metricIds: new Set([campaign.id]),
    })),
  )
  const creativeRankings = deriveRankingRows(
    metrics,
    data.creatives.map((creative) => ({
      id: creative.id,
      name: creative.name,
      category: 'creative',
      metricIds: new Set([creative.id]),
    })),
  )
  const audienceRankings = deriveRankingRows(
    metrics,
    data.adSets.map((adSet) => ({
      id: adSet.id,
      name: adSet.name,
      category: 'audience',
      metricIds: new Set([adSet.id]),
    })),
  )
  const placementRankings = deriveRankingRows(
    metrics,
    Array.from(new Set(metrics.map((metric) => metric.placement))).map((placement) => ({
      id: placement,
      name: labelPlacement(placement),
      category: 'placement',
      metricIds: new Set([placement]),
    })),
  )

  return (
    <section className="rankings-grid">
      <RankingPanel title="Campaign Ranking" rows={campaignRankings} />
      <RankingPanel title="Creative Ranking" rows={creativeRankings} />
      <RankingPanel title="Audience / Ad Set Ranking" rows={audienceRankings} />
      <RankingPanel title="Placement Ranking" rows={placementRankings} />
    </section>
  )
}

function RankingPanel({ title, rows }: { title: string; rows: RankingRow[] }) {
  return (
    <article className="panel panel-wide">
      <PanelHeading eyebrow="Quality-adjusted" title={title} icon={BarChart3} />
      {rows.length > 0 ? <RankingTable rows={rows.slice(0, 12)} /> : <EmptyState compact />}
    </article>
  )
}

function RankingTable({ rows }: { rows: RankingRow[] }) {
  return (
    <div className="ranking-table">
      <div className="ranking-head">
        <span>Rank</span>
        <span>Name</span>
        <span>Spend</span>
        <span>CPC</span>
        <span>CPL</span>
        <span>Lead rate</span>
        <span>START rate</span>
        <span>Leads</span>
        <span>Buyers</span>
        <span>Quality</span>
        <span>Action</span>
      </div>
      {rows.map((row) => (
        <div className="ranking-row" key={`${row.category}-${row.id}`}>
          <span>#{row.rank}</span>
          <strong title={row.name}>{row.name}</strong>
          <span>{formatCurrency(row.spendUsd)}</span>
          <span>{formatCurrency(row.cpc)}</span>
          <span>{row.cpl ? formatCurrency(row.cpl) : '—'}</span>
          <span>{row.leadRatePercent.toFixed(1)}%</span>
          <span>{row.telegramStartRatePercent.toFixed(1)}%</span>
          <span>{formatNumber(row.leads)}</span>
          <span>{formatNumber(row.purchases)}</span>
          <em className={row.tone}>{row.qualityScore}</em>
          <small>{row.recommendedAction}</small>
        </div>
      ))}
    </div>
  )
}
