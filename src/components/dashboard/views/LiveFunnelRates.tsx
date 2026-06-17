// Live ad-funnel rates (Visit / Lead / START) pulled straight from Meta insights
// via GET /api/funnel/rates. Rates are computed AND capped server-side in
// analysis_engine, so this panel only formats them. Falls back to a neutral
// "waiting for data" state when Meta is not connected or there's no spend yet.
import { useEffect, useState } from 'react'
import { Bot, MousePointerClick, RadioTower, Target } from 'lucide-react'
import { formatRate } from '../../../lib/format'

interface FunnelRatesPayload {
  ok: boolean
  hasData?: boolean
  days?: number
  counts?: {
    linkClicks: number
    landingPageViews: number
    leads: number
    botStarts: number
    telegramLinkClicks?: number
    subscribes: number
  }
  rates?: { visitRate: number; leadRate: number; startRate: number }
  startSource?: string
  startDenominatorSource?: string
  error?: string
}

const num = new Intl.NumberFormat('en')

export function LiveFunnelRates({ days = 30 }: { days?: number }) {
  const [payload, setPayload] = useState<FunnelRatesPayload | null>(null)
  // Which day-range the loaded payload reflects. When it doesn't match the requested
  // `days` (first load, or a range change still in flight) we show the loading state
  // instead of the previous window's numbers — derived, not a setState-in-effect, so a
  // range switch never flashes stale rates.
  const [loadedDays, setLoadedDays] = useState<number | null>(() => (typeof fetch === 'function' ? null : days))

  useEffect(() => {
    if (typeof fetch !== 'function') return
    let active = true
    void fetch(`/api/funnel/rates?days=${days}`)
      .then((response) => (response.ok ? response.json() : null))
      .then((data: FunnelRatesPayload | null) => {
        if (active) {
          setPayload(data)
          setLoadedDays(days)
        }
      })
      .catch(() => {
        if (active) {
          setPayload(null)
          setLoadedDays(days)
        }
      })
    return () => {
      active = false
    }
  }, [days])

  const loading = loadedDays !== days
  const rates = loading ? undefined : payload?.rates
  const counts = payload?.counts
  const live = !loading && Boolean(payload?.ok && payload?.hasData)

  const cards = [
    {
      label: 'Visit rate',
      Icon: MousePointerClick,
      value: rates ? formatRate(rates.visitRate) : loading ? '…' : '—',
      helper: live
        ? `${num.format(counts?.landingPageViews ?? 0)} landing views / ${num.format(counts?.linkClicks ?? 0)} link clicks`
        : 'Landing page views ÷ link clicks',
    },
    {
      label: 'Lead rate',
      Icon: Target,
      value: rates ? formatRate(rates.leadRate) : loading ? '…' : '—',
      helper: live
        ? `${num.format(counts?.leads ?? 0)} leads / ${num.format(counts?.landingPageViews ?? 0)} landing views`
        : 'Leads ÷ landing page views',
    },
    {
      label: 'START rate',
      Icon: Bot,
      value: rates ? formatRate(rates.startRate) : loading ? '…' : '—',
      helper: !live
        ? 'Telegram bot starts ÷ button clicks'
        : payload?.startDenominatorSource === 'telegram_link_click'
          ? `${num.format(counts?.botStarts ?? 0)} bot starts / ${num.format(counts?.telegramLinkClicks ?? 0)} button clicks`
          : `${num.format(counts?.botStarts ?? 0)} bot starts / ${num.format(counts?.leads ?? 0)} leads · add landing tracker for exact rate`,
    },
  ]

  const note = live
    ? `Live from Meta · last ${payload?.days ?? 30} days · deduplicated, capped at 100%`
    : payload && payload.ok === false
      ? payload.error ?? 'Connect Meta to populate live funnel rates.'
      : 'Waiting for ad spend — rates populate once the campaign runs.'

  return (
    <section className="monitor-funnel-rates" aria-label="Live funnel rates">
      <h5>Live funnel rates</h5>
      <div className="funnel-rate-cards">
        {cards.map(({ label, Icon, value, helper }) => (
          <article key={label} className={`funnel-rate-card ${live ? 'live' : ''}`}>
            <div className="frc-icon">
              <Icon size={18} />
            </div>
            <div>
              <p>{label}</p>
              <strong>{value}</strong>
              <small>{helper}</small>
            </div>
          </article>
        ))}
        <article className="funnel-rate-card source">
          <div className="frc-icon">
            <RadioTower size={18} />
          </div>
          <div>
            <p>Source</p>
            <strong>{live ? 'Meta live' : 'Standby'}</strong>
            <small>{note}</small>
          </div>
        </article>
      </div>
    </section>
  )
}
