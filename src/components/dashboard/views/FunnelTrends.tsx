// Per-stage trend charts for the simple dashboard. Each funnel rate (visit / lead /
// start / VSL-view / CRM-fill) gets a daily line so the operator can see whether it is
// climbing or sliding. Collapsible (hidden until a rate is picked — by clicking a rate
// card above or the "Show trends" button), with a time-range selector (7/14/30/90 days
// or a custom date range). Each day's rate is derived from the endpoint's per-day COUNTS
// with the SAME computeSimpleFunnel the live cards use (Start rate comes straight from the
// backend), so the trend line and the headline number always agree. Renders identically
// in the browser and inside Telegram's Web App (same same-origin SPA).
import { useEffect, useMemo, useState } from 'react'
import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { getFunnelHistory, type FunnelHistory } from '../../../services/dashboardDataProvider'
import { computeSimpleFunnel } from '../../simpleFunnel'

export type TrendRateKey = 'visit' | 'lead' | 'start' | 'vslView' | 'crmFill'

const RATE_META: Record<TrendRateKey, { label: string; color: string }> = {
  visit: { label: 'Visit rate', color: '#2563eb' },
  lead: { label: 'Lead rate', color: '#0d9488' },
  start: { label: 'Start rate', color: '#7c3aed' },
  vslView: { label: 'VSL view rate', color: '#ea580c' },
  crmFill: { label: 'CRM fill rate', color: '#db2777' },
}
const RATE_KEYS = Object.keys(RATE_META) as TrendRateKey[]

const RANGES = [
  { key: '7', label: '7d', days: 7 },
  { key: '14', label: '14d', days: 14 },
  { key: '30', label: '30d', days: 30 },
  { key: '90', label: '90d', days: 90 },
] as const

type SeriesRow = {
  date: string
  incomplete: boolean
  visit: number
  lead: number
  start: number
  vslView: number | null
  crmFill: number
}

interface FunnelTrendsProps {
  campaignId: string
  days: number
  refreshKey: number
  selectedRate: TrendRateKey | null
  onSelectRate: (rate: TrendRateKey | null) => void
}

export function FunnelTrends({ campaignId, days, refreshKey, selectedRate, onSelectRate }: FunnelTrendsProps) {
  const [rangeDays, setRangeDays] = useState<number>(() => clampRange(days))
  const [custom, setCustom] = useState<{ since: string; until: string } | null>(null)
  const [history, setHistory] = useState<FunnelHistory | null>(null)
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    if (selectedRate === null) return // collapsed → don't fetch
    if (typeof fetch !== 'function') return
    let active = true
    setLoading(true)
    const opts =
      custom && custom.since && custom.until
        ? { since: custom.since, until: custom.until, force: refreshKey > 0 }
        : { days: rangeDays, force: refreshKey > 0 }
    void getFunnelHistory(campaignId, opts).then((h) => {
      if (active) {
        setHistory(h)
        setLoading(false)
      }
    })
    return () => {
      active = false
    }
  }, [campaignId, rangeDays, custom, refreshKey, selectedRate])

  const series = useMemo(() => buildSeries(history), [history])

  // Collapsed state: just a slim toggle to reveal the trends (defaults to Visit rate).
  if (selectedRate === null) {
    return (
      <div className="simple-trends-toggle">
        <button type="button" className="simple-trend-btn" onClick={() => onSelectRate('visit')}>
          📈 Show trends over time
        </button>
      </div>
    )
  }

  const meta = RATE_META[selectedRate]
  const chartData = series.map((row) => ({ date: row.date.slice(5), value: row[selectedRate], incomplete: row.incomplete }))
  const hasData = chartData.some((d) => d.value != null)
  const hasIncomplete = series.some((row) => row.incomplete)

  // Distinguish the in-progress (provisional) day with a hollow dot so its still-settling
  // conversion rate isn't read as a real dip.
  const renderDot = (props: { cx?: number; cy?: number; index?: number; payload?: { incomplete?: boolean } }) => {
    const { cx, cy, index, payload } = props
    if (typeof cx !== 'number' || typeof cy !== 'number' || Number.isNaN(cy)) return <g key={index} />
    const provisional = payload?.incomplete
    return (
      <circle
        key={index}
        cx={cx}
        cy={cy}
        r={provisional ? 4 : 2}
        fill={provisional ? '#ffffff' : meta.color}
        stroke={meta.color}
        strokeWidth={provisional ? 2 : 1}
      />
    )
  }

  return (
    <div className="simple-block simple-trends">
      <div className="simple-trends-head">
        <h5 style={{ color: meta.color }}>📈 Trend — {meta.label}</h5>
        <button type="button" className="simple-trend-hide" onClick={() => onSelectRate(null)}>
          Hide ✕
        </button>
      </div>

      <div className="simple-chip-row" role="tablist" aria-label="Choose a rate">
        {RATE_KEYS.map((key) => {
          const active = key === selectedRate
          return (
            <button
              key={key}
              type="button"
              role="tab"
              aria-selected={active}
              className={`simple-chip${active ? ' is-active' : ''}`}
              style={active ? { background: RATE_META[key].color, borderColor: RATE_META[key].color, color: '#fff' } : { color: RATE_META[key].color }}
              onClick={() => onSelectRate(key)}
            >
              {RATE_META[key].label}
            </button>
          )
        })}
      </div>

      <div className="simple-chip-row">
        {RANGES.map((r) => (
          <button
            key={r.key}
            type="button"
            className={`simple-chip${!custom && rangeDays === r.days ? ' is-active' : ''}`}
            onClick={() => {
              setCustom(null)
              setRangeDays(r.days)
            }}
          >
            {r.label}
          </button>
        ))}
        <span className="simple-date-range">
          <input
            type="date"
            aria-label="From date"
            value={custom?.since ?? ''}
            max={custom?.until || undefined}
            onChange={(e) => setCustom((c) => ({ since: e.target.value, until: c?.until || e.target.value }))}
          />
          <span aria-hidden>→</span>
          <input
            type="date"
            aria-label="To date"
            value={custom?.until ?? ''}
            min={custom?.since || undefined}
            onChange={(e) => setCustom((c) => ({ since: c?.since || e.target.value, until: e.target.value }))}
          />
        </span>
      </div>

      {loading ? (
        <p className="simple-help">Loading trend…</p>
      ) : !hasData ? (
        <div className="simple-trend-empty">
          {selectedRate === 'vslView' ? (
            <>
              <strong>No daily VSL trend yet.</strong>
              <span>
                YouTube reports only a running total, so the VSL line builds from the daily view-count we record — it
                needs 2+ days and starts drawing tomorrow.
              </span>
            </>
          ) : (
            <>
              <strong>No data for this rate in the selected range yet.</strong>
              <span>Once this campaign has delivery on these days, the line appears here.</span>
            </>
          )}
        </div>
      ) : (
        <div style={{ width: '100%', height: 240 }}>
          <ResponsiveContainer>
            <LineChart data={chartData} margin={{ top: 8, right: 12, bottom: 0, left: -10 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#eef2f7" />
              <XAxis dataKey="date" tick={{ fontSize: 11, fill: '#94a3b8' }} tickMargin={6} />
              <YAxis domain={[0, 100]} tickFormatter={(v: number) => `${v}%`} tick={{ fontSize: 11, fill: '#94a3b8' }} width={42} />
              <Tooltip
                formatter={(value) => {
                  const v = value as number | null
                  return [v == null ? '—' : `${v}%`, meta.label]
                }}
                labelFormatter={(label) => `Day ${String(label)}`}
                contentStyle={{ borderRadius: 12, border: '1px solid #e7edf4', fontSize: 12 }}
              />
              <Line
                type="monotone"
                dataKey="value"
                stroke={meta.color}
                strokeWidth={2.5}
                dot={renderDot}
                activeDot={{ r: 4 }}
                connectNulls={false}
                isAnimationActive={false}
                name={meta.label}
              />
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}

      <small className="simple-help">
        {history?.since && history?.until ? `${history.since} → ${history.until} · daily` : 'daily'} · same math as the
        cards above.
        {hasIncomplete
          ? ' The hollow last point is today (in progress) — its lead/start/CRM rate is still settling and rises as the day finishes and Meta attributes late conversions.'
          : ''}
      </small>
    </div>
  )
}

function clampRange(days: number): number {
  if (days >= 90) return 90
  if (days >= 30) return 30
  if (days >= 14) return 14
  return 7
}

// Derive each day's five rates from its counts — identical math to the live cards
// (computeSimpleFunnel for four, the backend startRate for Start). VSL is null on days
// with no snapshot delta so the line shows a gap rather than a misleading 0.
function buildSeries(history: FunnelHistory | null): SeriesRow[] {
  if (!history?.points?.length) return []
  return history.points.map((p) => {
    const out = computeSimpleFunnel({
      linkClicks: p.counts.linkClicks,
      landingViews: p.counts.landingViews,
      leads: p.counts.leads,
      botStarts: p.counts.botStarts,
      vslViews: p.counts.vslViews ?? 0,
      crmLeads: p.counts.crmLeads,
      spend: p.spend,
    })
    return {
      date: p.date,
      incomplete: Boolean(p.incomplete),
      visit: out.rates.visit,
      lead: out.rates.lead,
      start: p.startRate,
      vslView: p.counts.vslViews == null ? null : out.rates.vslView,
      crmFill: out.rates.crmFill,
    }
  })
}
