// The primary Monitor headline: the simple per-campaign funnel dashboard — five rate
// cards (visit / lead / start / VSL-view / CRM-fill), the funnel, cost per stage, the
// CRM stage breakdown, and spend & volume. Meta volumes come from /api/campaigns/kpis;
// CRM stages from /api/crm/stages (the configured order source); VSL from /api/vsl. Bot
// starts / CRM leads / VSL views are pre-filled from live data but stay editable and are
// remembered (localStorage). All rates are computed client-side so they match exactly.
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

const MANUAL_KEYS = { botStarts: 'vslDash.botStarts', crmLeads: 'vslDash.crmLeads', vslViews: 'vslDash.vslViews' } as const
type ManualField = keyof typeof MANUAL_KEYS

function readStoredManual(field: ManualField): string | null {
  if (typeof window === 'undefined') return null
  try {
    return window.localStorage.getItem(MANUAL_KEYS[field])
  } catch {
    return null
  }
}
function storeManual(field: ManualField, value: string) {
  if (typeof window === 'undefined') return
  try {
    window.localStorage.setItem(MANUAL_KEYS[field], value)
  } catch {
    /* ignore quota / privacy-mode errors */
  }
}
function toInt(value: string): number {
  const n = parseInt(value.replace(/[^0-9]/g, ''), 10)
  return Number.isFinite(n) ? n : 0
}
function money(value: number): string {
  return `$${value.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
}

const RATE_CARDS = [
  { key: 'visit', label: 'Visit rate', color: '#2563eb', desc: '% of ad-clickers whose page loaded', sub: (i: FunnelInputs) => `${formatNumber(i.landingViews)} views ÷ ${formatNumber(i.linkClicks)} clicks` },
  { key: 'lead', label: 'Lead rate', color: '#0d9488', desc: '% of visitors who clicked the CTA', sub: (i: FunnelInputs) => `${formatNumber(i.leads)} leads ÷ ${formatNumber(i.landingViews)} views` },
  { key: 'start', label: 'Start rate', color: '#7c3aed', desc: '% of leads who started the bot', sub: (i: FunnelInputs) => `${formatNumber(i.botStarts)} starts ÷ ${formatNumber(i.leads)} leads` },
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
  const [manual, setManual] = useState({ botStarts: '', crmLeads: '', vslViews: '' })

  useEffect(() => {
    if (typeof fetch !== 'function') return
    let active = true
    const key = `${campaignId}|${days}|${refreshKey}`
    const force = refreshKey > 0
    void Promise.all([getCampaignKpis(campaignId, days, force), getCrmStages(days, force), getVsl(days, force)])
      .then(([kpis, crm, vsl]) => {
        if (!active) return
        setBundle({ kpis, crm, vsl, loadedKey: key })
        // Refresh shows FRESH live values; a stored manual entry is only a fallback when
        // there is no live value (e.g. VSL views before YouTube is connected), so a stale
        // localStorage value can never shadow live bot-starts / CRM-leads on Refresh.
        const prefill = (field: ManualField, liveValue: number | null) => {
          if (liveValue != null) return String(liveValue)
          return readStoredManual(field) ?? ''
        }
        setManual({
          botStarts: prefill('botStarts', kpis.counts?.botStarts ?? null),
          crmLeads: prefill('crmLeads', crm.ok ? crm.total : null),
          vslViews: prefill('vslViews', vsl.views ?? null),
        })
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
  const live = Boolean(kpis?.ok && kpis?.hasData)

  const inputs: FunnelInputs = {
    linkClicks: kpis?.counts?.linkClicks ?? 0,
    landingViews: kpis?.counts?.landingPageViews ?? 0,
    leads: kpis?.counts?.leads ?? 0,
    botStarts: toInt(manual.botStarts),
    vslViews: toInt(manual.vslViews),
    crmLeads: toInt(manual.crmLeads),
    spend: kpis?.kpis?.spend ?? 0,
  }
  const out = computeSimpleFunnel(inputs)
  const maxBar = Math.max(inputs.linkClicks, 1)
  const onManual = (field: ManualField, value: string) => {
    setManual((m) => ({ ...m, [field]: value }))
    storeManual(field, value)
  }

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
        {RATE_CARDS.map((card) => (
          <article className="simple-rate-card" key={card.key}>
            <p className="simple-rate-label" style={{ color: card.color }}>
              <span className="simple-dot" style={{ background: card.color }} />
              {card.label}
            </p>
            <strong style={{ color: card.color }}>{loading ? '…' : `${out.rates[card.key as keyof typeof out.rates]}%`}</strong>
            <span className="simple-rate-sub">{card.sub(inputs)}</span>
            <small>{card.desc}</small>
          </article>
        ))}
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
        <div className="manual-inputs">
          <label>
            Bot starts
            <input inputMode="numeric" value={manual.botStarts} onChange={(e) => onManual('botStarts', e.target.value)} />
          </label>
          <label>
            CRM leads (Bitrix)
            <input inputMode="numeric" value={manual.crmLeads} onChange={(e) => onManual('crmLeads', e.target.value)} />
          </label>
          <label>
            VSL views (YouTube)
            <input inputMode="numeric" value={manual.vslViews} onChange={(e) => onManual('vslViews', e.target.value)} />
          </label>
        </div>
        <small className="simple-help">
          Each row’s % is that step’s conversion vs the stage above it. Bot starts / CRM leads / VSL views are pre-filled
          from live data but stay editable here and are remembered.
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
