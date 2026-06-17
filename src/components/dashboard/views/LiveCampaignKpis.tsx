// The primary, live headline of the Monitor screen: per-campaign (or account-wide)
// KPIs and funnel rates pulled straight from Meta via GET /api/campaigns/kpis.
// Numbers are computed AND capped server-side, so this panel only formats them.
import { useEffect, useState } from 'react'
import { Bot, MousePointerClick, Target } from 'lucide-react'
import { getCampaignKpis, type CampaignKpis } from '../../../services/dashboardDataProvider'
import { formatCurrency, formatRate } from '../../../lib/format'
import { formatNumber } from '../../../lib/analytics'

interface LiveCampaignKpisProps {
  campaignId: string
  campaignName: string
  days: number
  refreshKey: number
}

export function LiveCampaignKpis({ campaignId, campaignName, days, refreshKey }: LiveCampaignKpisProps) {
  // The scope this fetch belongs to. Loading is derived by comparing the key the
  // loaded payload was stamped with against the current key, so a campaign/range
  // switch never flashes the previous scope's numbers and we never call setState
  // synchronously inside the effect body (react-hooks/set-state-in-effect).
  const currentKey = `${campaignId}|${days}|${refreshKey}`
  const [bundle, setBundle] = useState<{ payload: CampaignKpis; loadedKey: string } | null>(null)

  useEffect(() => {
    if (typeof fetch !== 'function') return
    let active = true
    const key = `${campaignId}|${days}|${refreshKey}`
    void getCampaignKpis(campaignId, days, refreshKey > 0)
      .then((payload) => {
        if (active) setBundle({ payload, loadedKey: key })
      })
      .catch(() => {
        if (active) setBundle({ payload: { ok: false }, loadedKey: key })
      })
    return () => {
      active = false
    }
  }, [campaignId, days, refreshKey])

  const loading = bundle?.loadedKey !== currentKey
  const payload = loading ? undefined : bundle?.payload
  const ok = Boolean(payload?.ok)
  const hasData = Boolean(payload?.hasData)
  const kpis = payload?.kpis
  const rates = payload?.rates
  const counts = payload?.counts
  const live = ok && hasData

  const freshness = loading
    ? 'Loading live data…'
    : ok && hasData
      ? `Live from Meta · last ${days} days`
      : ok && !hasData
        ? 'Live · no delivery in this window yet'
        : 'Connect Meta to see live KPIs.'

  // KPI rail values. While loading we show '…'; once loaded we format whatever
  // the live payload carries (zeros included), never the previous scope's numbers.
  const railValue = (render: (k: NonNullable<typeof kpis>) => string) =>
    loading ? '…' : kpis ? render(kpis) : '—'

  const kpiItems = [
    { label: 'Spend', value: railValue((k) => formatCurrency(k.spend)) },
    { label: 'Leads', value: railValue((k) => formatNumber(k.leads)) },
    { label: 'Cost / Lead', value: railValue((k) => (k.cpl > 0 ? formatCurrency(k.cpl) : '—')) },
    { label: 'CTR', value: railValue((k) => `${k.ctr}%`) },
    { label: 'START rate', value: loading ? '…' : rates ? formatRate(rates.startRate) : '—' },
  ]

  const rateValue = (value?: number) => (loading ? '…' : value !== undefined ? formatRate(value) : '—')

  const rateCards = [
    {
      label: 'Visit rate',
      Icon: MousePointerClick,
      value: rateValue(rates?.visitRate),
      helper: live
        ? `${formatNumber(counts?.landingPageViews ?? 0)} landing views / ${formatNumber(counts?.linkClicks ?? 0)} link clicks`
        : 'Landing page views ÷ link clicks',
    },
    {
      label: 'Lead rate',
      Icon: Target,
      value: rateValue(rates?.leadRate),
      helper: live
        ? `${formatNumber(counts?.leads ?? 0)} leads / ${formatNumber(counts?.landingPageViews ?? 0)} landing views`
        : 'Leads ÷ landing page views',
    },
    {
      label: 'START rate',
      Icon: Bot,
      value: rateValue(rates?.startRate),
      helper: live
        ? `${formatNumber(counts?.botStarts ?? 0)} bot starts / ${
            payload?.startDenominatorSource === 'telegram_link_click'
              ? `${formatNumber(counts?.telegramLinkClicks ?? 0)} button clicks`
              : `${formatNumber(counts?.leads ?? 0)} leads`
          }${payload?.startScope === 'account' && campaignId !== 'all' ? ' · account-wide' : ''}`
        : 'Telegram bot starts ÷ button clicks',
    },
  ]

  return (
    <section className="monitor-funnel-rates" aria-label="Live campaign KPIs">
      <h5>{campaignName}</h5>
      <p className="monitor-live-freshness">{freshness}</p>

      <div className="monitor-kpis" aria-label="Key metrics">
        {kpiItems.map((kpi) => (
          <div key={kpi.label} className="monitor-kpi">
            <small>{kpi.label}</small>
            <strong>{kpi.value}</strong>
          </div>
        ))}
      </div>

      <div className="funnel-rate-cards">
        {rateCards.map(({ label, Icon, value, helper }) => (
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
      </div>
    </section>
  )
}
