// The primary Monitor headline: the simple per-campaign funnel dashboard — five rate
// cards (visit / lead / start / VSL-view / CRM-fill), the funnel, cost per stage, the
// CRM stage breakdown, and spend & volume. EVERYTHING auto-fetches on Refresh — there
// are no manual inputs: Meta volumes from /api/campaigns/kpis, bot starts from the
// first-party Telegram relay, CRM leads from /api/crm/stages (Bitrix), VSL views from
// /api/vsl (YouTube). Rates are recomputed client-side (capped at 100%); Start rate uses
// the backend's select_start_rate.
import { useEffect, useState } from 'react'
import {
  getCampaignKpis,
  getCrmStages,
  getVsl,
  type CampaignKpis,
  type CrmStages,
  type VslMetrics,
} from '../../../services/dashboardDataProvider'
import { formatNumber } from '../../../lib/analytics'
import { computeSimpleFunnel, type FunnelInputs } from '../../simpleFunnel'

interface LiveCampaignKpisProps {
  campaignId: string
  campaignName: string
  days: number
  refreshKey: number
}

function money(value: number): string {
  return `$${value.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
}

const RATE_CARDS = [
  { key: 'visit', label: 'Visit rate', color: '#2563eb', desc: '% of ad-clickers whose page loaded', sub: (i: FunnelInputs) => `${formatNumber(i.landingViews)} views ÷ ${formatNumber(i.linkClicks)} clicks` },
  { key: 'lead', label: 'Lead rate', color: '#0d9488', desc: '% of visitors who clicked the CTA', sub: (i: FunnelInputs) => `${formatNumber(i.leads)} leads ÷ ${formatNumber(i.landingViews)} views` },
  { key: 'start', label: 'Start rate', color: '#7c3aed', desc: '% of button-clickers who started the bot', sub: (i: FunnelInputs) => `${formatNumber(i.botStarts)} starts ÷ ${formatNumber(i.leads)} leads` },
  { key: 'vslView', label: 'VSL view rate', color: '#ea580c', desc: '% of bot-starters who watched the VSL', sub: (i: FunnelInputs) => `${formatNumber(i.vslViews)} VSL views ÷ ${formatNumber(i.botStarts)} starts` },
  { key: 'crmFill', label: 'CRM fill rate', color: '#db2777', desc: '% of bot-starters who filled the form', sub: (i: FunnelInputs) => `${formatNumber(i.crmLeads)} CRM leads ÷ ${formatNumber(i.botStarts)} starts` },
] as const

const FUNNEL_COLORS: Record<string, string> = { linkClicks: '#2563eb', landingViews: '#2563eb', leads: '#0d9488', botStarts: '#7c3aed', vslViews: '#ea580c', crmLeads: '#db2777' }
const COST_DEFS = [
  { key: 'perVisit', color: '#2563eb', label: 'per visit (landing view)' },
  { key: 'perLead', color: '#0d9488', label: 'per lead (CTA)' },
  { key: 'perBotStart', color: '#7c3aed', label: 'per bot start' },
  { key: 'perVslView', color: '#ea580c', label: 'per VSL view' },
  { key: 'perCrmLead', color: '#db2777', label: 'per CRM lead' },
] as const

const EMPTY_CRM: CrmStages = { ok: false, total: 0, paid: 0, paidStageIds: [], stages: [] }
const EMPTY_VSL: VslMetrics = { ok: false, configured: false, views: null, viewsWatched50: null, watchRate50: null, hasRetention: false }

export function LiveCampaignKpis({ campaignId, campaignName, days, refreshKey }: LiveCampaignKpisProps) {
  const currentKey = `${campaignId}|${days}|${refreshKey}`
  const [bundle, setBundle] = useState<{ kpis: CampaignKpis; crm: CrmStages; vsl: VslMetrics; loadedKey: string } | null>(null)

  useEffect(() => {
    if (typeof fetch !== 'function') return
    let active = true
    const key = `${campaignId}|${days}|${refreshKey}`
    // refreshKey>0 means the Refresh button was pressed → force a live, uncached pull on
    // every source (Meta insights, CRM stages, YouTube) and bust any browser cache.
    const force = refreshKey > 0
    void Promise.all([getCampaignKpis(campaignId, days, force), getCrmStages(days, force), getVsl(days, force)])
      .then(([kpis, crm, vsl]) => {
        if (active) setBundle({ kpis, crm, vsl, loadedKey: key })
      })
      .catch(() => {
        if (active) setBundle({ kpis: { ok: false }, crm: EMPTY_CRM, vsl: EMPTY_VSL, loadedKey: key })
      })
    return () => {
      active = false
    }
  }, [campaignId, days, refreshKey])

  const loading = bundle?.loadedKey !== currentKey
  const kpis = loading ? undefined : bundle?.kpis
  const crm = loading ? undefined : bundle?.crm
  const vsl = loading ? undefined : bundle?.vsl
  const live = Boolean(kpis?.ok && kpis?.hasData)

  // Every input is LIVE — no manual entry. Bot starts come from the first-party Telegram
  // relay (kpis.counts.botStarts), CRM leads from Bitrix (/api/crm/stages total), VSL
  // views from YouTube (/api/vsl). All refresh together when Refresh is pressed.
  const inputs: FunnelInputs = {
    linkClicks: kpis?.counts?.linkClicks ?? 0,
    landingViews: kpis?.counts?.landingPageViews ?? 0,
    leads: kpis?.counts?.leads ?? 0,
    botStarts: kpis?.counts?.botStarts ?? 0,
    vslViews: vsl?.views ?? 0,
    crmLeads: crm?.ok ? crm.total : 0,
    spend: kpis?.kpis?.spend ?? 0,
  }
  const out = computeSimpleFunnel(inputs)
  const maxBar = Math.max(inputs.linkClicks, 1)
  const vslNeedsConnect = Boolean(vsl && !vsl.configured)

  const freshness = loading
    ? 'Loading live data…'
    : live
      ? `Live from Meta · last ${days} days`
      : kpis?.ok
        ? 'Live · no delivery in this window yet'
        : 'Connect Meta to see live KPIs.'

  return (
    <section className="simple-dash" aria-label="Live campaign funnel">
      <div className="simple-toolbar">
        <h5>{campaignName}</h5>
        <span className="simple-note">{freshness}</span>
      </div>

      <div className="simple-cards">
        {RATE_CARDS.map((card) => {
          // START rate uses the backend's select_start_rate (first-party bot starts ÷
          // Telegram button clicks, scoped + capped) — the deliberate implementation —
          // rather than the client-side starts÷leads. The other four stay client-computed.
          let value: string
          let sub: string
          if (card.key === 'start') {
            value = loading ? '…' : kpis?.rates ? `${kpis.rates.startRate}%` : '—'
            const starts = formatNumber(kpis?.counts?.botStarts ?? 0)
            const denom =
              kpis?.startDenominatorSource === 'telegram_link_click'
                ? `${formatNumber(kpis?.counts?.telegramLinkClicks ?? 0)} button clicks`
                : `${formatNumber(kpis?.counts?.leads ?? 0)} leads`
            const scopeNote = kpis?.startScope === 'account' && campaignId !== 'all' ? ' · account-wide' : ''
            sub = `${starts} starts ÷ ${denom}${scopeNote}`
          } else if (card.key === 'vslView' && vslNeedsConnect) {
            value = loading ? '…' : '—'
            sub = 'Connect YouTube to populate'
          } else {
            value = loading ? '…' : `${out.rates[card.key as keyof typeof out.rates]}%`
            sub = card.sub(inputs)
          }
          return (
            <article className="simple-rate-card" key={card.key}>
              <p className="simple-rate-label" style={{ color: card.color }}>
                <span className="simple-dot" style={{ background: card.color }} />
                {card.label}
              </p>
              <strong style={{ color: card.color }}>{value}</strong>
              <span className="simple-rate-sub">{sub}</span>
              <small>{card.desc}</small>
            </article>
          )
        })}
      </div>

      <div className="simple-block">
        <h5>{campaignId === 'all' ? 'Funnel — all campaigns' : 'Funnel — this campaign'}</h5>
        <div className="simple-funnel">
          {out.funnel.map((row) => (
            <div className="simple-funnel-row" key={row.key}>
              <span className="simple-funnel-label">{row.label}</span>
              <div className="simple-funnel-track">
                <div className="simple-funnel-bar" style={{ width: `${Math.max(2, (row.value / maxBar) * 100)}%`, background: FUNNEL_COLORS[row.key] }}>
                  <em>{formatNumber(row.value)}</em>
                </div>
              </div>
              <span className="simple-funnel-pct">{row.pctLabel}</span>
            </div>
          ))}
        </div>
        <small className="simple-help">
          Each row’s % is that step’s conversion vs the stage above it. Everything auto-refreshes — Meta volumes from live
          insights, bot starts from the Telegram relay, CRM leads from Bitrix, VSL views from YouTube.
          {vslNeedsConnect ? ' VSL views read 0 until YouTube is connected (set YOUTUBE_VSL_VIDEO_ID + YOUTUBE_API_KEY).' : ''}
        </small>
      </div>

      <div className="simple-block">
        <h5>Cost per stage</h5>
        <div className="simple-cost">
          {COST_DEFS.map((c) => (
            <article className="simple-cost-item" key={c.key}>
              <strong style={{ color: c.color }}>{loading ? '…' : money(out.cost[c.key as keyof typeof out.cost])}</strong>
              <small>{c.label}</small>
            </article>
          ))}
        </div>
      </div>

      {crm && crm.ok && crm.total > 0 ? (
        <div className="simple-block">
          <h5>CRM stages — {crm.source ?? 'leads'}</h5>
          <p className="simple-help">
            {formatNumber(crm.total)} leads · Bitrix24 · {formatNumber(crm.paid)} paid
          </p>
          <div className="crm-stages">
            {crm.stages
              .filter((s) => s.count > 0)
              .map((s) => {
                const pct = Math.round((s.count / crm.total) * 100)
                const isPaid = crm.paidStageIds.includes(s.id)
                return (
                  <div className={`crm-stage-row${isPaid ? ' paid' : ''}`} key={s.id}>
                    <span className="crm-stage-name">{s.name}</span>
                    <div className="crm-stage-track">
                      <div className="crm-stage-bar" style={{ width: `${Math.max(2, pct)}%` }} />
                    </div>
                    <span className="crm-stage-count">
                      {formatNumber(s.count)} · {pct}%
                    </span>
                  </div>
                )
              })}
          </div>
        </div>
      ) : null}

      <div className="simple-block">
        <h5>Spend &amp; volume</h5>
        <div className="simple-spend">
          <article><strong>{money(inputs.spend)}</strong><small>Spend</small></article>
          <article><strong>{formatNumber(kpis?.kpis?.impressions ?? 0)}</strong><small>Impressions</small></article>
          <article><strong>{formatNumber(kpis?.kpis?.reach ?? 0)}</strong><small>Reach</small></article>
          <article><strong>{formatNumber(inputs.linkClicks)}</strong><small>Link clicks</small></article>
          <article><strong>{formatNumber(inputs.landingViews)}</strong><small>Landing views</small></article>
          <article><strong>{formatNumber(inputs.leads)}</strong><small>Website leads</small></article>
          <article><strong>{formatNumber(inputs.vslViews)}</strong><small>VSL views</small></article>
          <article><strong>{formatNumber(inputs.crmLeads)}</strong><small>CRM leads</small></article>
        </div>
      </div>
    </section>
  )
}
