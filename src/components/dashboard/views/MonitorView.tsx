// The lean Monitor screen: KPI rail / one trend + funnel / Agent Office.
// Monitoring only — control lives in Telegram and the Claude connector.
import { useEffect, useMemo, useState } from 'react'
import { CartesianGrid, Legend, Line, LineChart, Tooltip, XAxis, YAxis } from 'recharts'
import { deriveMonitorKpis } from '../../../lib/monitorKpis'
import { chartTooltipFormatter, formatAxisCurrency } from '../../../lib/chartConfig'
import type { DailyAdMetric, FunnelSummary, TrendPoint } from '../../../types/marketing'
import { ChartFrame } from '../shared/ChartFrame'
import { AgentOffice } from './AgentOffice'
import { LiveFunnelRates } from './LiveFunnelRates'

// Spec §3.2: five stages; landing visits and buyers are intentionally omitted
// (buyers return when purchase tracking is activated).
const STAGE_LABELS: Array<{ step: string; label: (stage: FunnelSummary) => string }> = [
  { step: 'Ad impressions', label: () => 'Ad impressions' },
  { step: 'Clicks', label: (stage) => `Clicks · CTR ${stage.rate}` },
  { step: 'Leads', label: () => 'Leads' },
  { step: 'Telegram subs', label: () => 'Telegram STARTs' },
  { step: 'Webinar attendees', label: () => 'Webinar attended' },
]

const compact = new Intl.NumberFormat('en', { notation: 'compact', maximumFractionDigits: 1 })

interface MonitorViewProps {
  metrics: DailyAdMetric[]
  trend: TrendPoint[]
  funnel: FunnelSummary[]
  days?: number
}

export function MonitorView({ metrics, trend, funnel, days = 30 }: MonitorViewProps) {
  const [budgetTarget, setBudgetTarget] = useState<number | null>(null)

  useEffect(() => {
    if (typeof fetch !== 'function') return
    let cancelled = false
    void fetch('/api/targets')
      .then((response) => (response.ok ? response.json() : { targets: null }))
      .then((result: { targets?: Record<string, number | null> }) => {
        if (!cancelled) setBudgetTarget(result.targets?.weeklyBudgetTargetUsd ?? null)
      })
      .catch(() => undefined)
    return () => {
      cancelled = true
    }
  }, [])

  // Anchor KPI windows to the data's own calendar, not wall-clock today —
  // with snapshot/fallback data the latest data day acts as the partial "today",
  // keeping the KPI rail consistent with the trend/funnel below it.
  const anchorDate = useMemo(() => {
    if (metrics.length === 0) return undefined
    let latest = metrics[0].date
    for (const row of metrics) if (row.date > latest) latest = row.date
    return latest
  }, [metrics])

  const kpis = useMemo(
    () => deriveMonitorKpis(metrics, { weeklyBudgetTargetUsd: budgetTarget, today: anchorDate }),
    [metrics, budgetTarget, anchorDate],
  )

  const stages = STAGE_LABELS.map(({ step, label }) => {
    const stage = funnel.find((item) => item.step === step)
    return stage ? { label: label(stage), value: stage.value } : null
  }).filter((stage): stage is { label: string; value: number } => stage !== null)
  const stageMax = stages[0]?.value || 1

  const recentTrend = trend.slice(-14)

  // Collapsed by default on phones (spec §3.4); <details open> can't be CSS-driven.
  // Intentionally static (read once at mount) — resize/rotation re-open is out of scope.
  const [chartsOpen] = useState(
    () => typeof window === 'undefined' || window.innerWidth > 768,
  )

  return (
    <section className="monitor-screen">
      <LiveFunnelRates days={days} />

      <div className="monitor-kpis" aria-label="Key metrics">
        {kpis.map((kpi) => (
          <div key={kpi.id} className="monitor-kpi">
            <small>{kpi.label}</small>
            <strong>{kpi.value}</strong>
            <span className={`monitor-delta ${kpi.tone}`}>{kpi.delta}</span>
          </div>
        ))}
      </div>

      <details className="monitor-center" open={chartsOpen}>
        <summary>Trend &amp; funnel</summary>
        <div className="monitor-trend">
          <h5>Spend &amp; leads · last 14 days</h5>
          <ChartFrame summary="Daily spend and leads for the last 14 days">
            <LineChart data={recentTrend}>
              <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
              <XAxis dataKey="day" tick={{ fontSize: 11 }} tickLine={false} axisLine={false} tickFormatter={(value: string) => value.slice(5)} />
              <YAxis yAxisId="spend" tickFormatter={formatAxisCurrency} tick={{ fontSize: 11 }} tickLine={false} axisLine={false} />
              <YAxis yAxisId="leads" orientation="right" tick={{ fontSize: 11 }} tickLine={false} axisLine={false} />
              <Tooltip formatter={chartTooltipFormatter} />
              <Legend />
              <Line yAxisId="spend" type="monotone" dataKey="spend" stroke="var(--chart-1)" strokeWidth={2.5} dot={false} />
              <Line yAxisId="leads" type="monotone" dataKey="leads" stroke="var(--chart-2)" strokeWidth={2} dot={false} />
            </LineChart>
          </ChartFrame>
        </div>
        <div className="monitor-funnel">
          <h5>Funnel · filtered range</h5>
          {stages.map((stage) => (
            <div key={stage.label} className="monitor-funnel-row">
              <span>{stage.label}</span>
              <div className="bar-track">
                <div className="bar" style={{ width: `${Math.max((stage.value / stageMax) * 100, 1)}%` }} />
              </div>
              <b>{compact.format(stage.value)}</b>
            </div>
          ))}
        </div>
      </details>

      <AgentOffice />
    </section>
  )
}
