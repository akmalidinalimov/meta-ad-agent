// The primary Monitor headline: the simple per-campaign funnel dashboard — five rate
// cards (visit / lead / start / VSL-view / CRM-fill), the funnel, cost per stage, the
// CRM stage breakdown, and spend & volume. EVERYTHING auto-fetches on Refresh — there
// are no manual inputs: Meta volumes from /api/campaigns/kpis, bot starts from the
// first-party Telegram relay, CRM leads from /api/crm/stages (Bitrix), VSL views from
// /api/vsl (YouTube). Rates are recomputed client-side (capped at 100%) — EXCEPT VSL reach,
// which is an uncapped YouTube-views ÷ bot-starts PROXY (not a true watch rate; see below).
// Start rate uses the backend's select_start_rate.
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
import { FunnelTrends, type TrendRateKey } from './FunnelTrends'

interface LiveCampaignKpisProps {
  campaignId: string
  campaignName: string
  days: number
  since?: string
  until?: string
  periodLabel?: string
  refreshKey: number
}

function money(value: number): string {
  return `$${value.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
}

const RATE_CARDS = [
  { key: 'visit', label: 'Visit rate', color: '#2563eb', desc: '% of ad-clickers whose page loaded', sub: (i: FunnelInputs) => `${formatNumber(i.landingViews)} views ÷ ${formatNumber(i.linkClicks)} clicks` },
  { key: 'lead', label: 'Lead rate', color: '#0d9488', desc: '% of visitors who clicked the CTA', sub: (i: FunnelInputs) => `${formatNumber(i.leads)} leads ÷ ${formatNumber(i.landingViews)} views` },
  { key: 'start', label: 'Start rate', color: '#7c3aed', desc: '% of button-clickers who started the bot', sub: (i: FunnelInputs) => `${formatNumber(i.botStarts)} starts ÷ ${formatNumber(i.leads)} leads` },
  { key: 'vslView', label: 'VSL reach (YT)', color: '#ea580c', desc: 'YouTube views ÷ bot-starts — a directional reach PROXY (the VSL is watched mostly inside Telegram, so YouTube undercounts); NOT a true watch rate', sub: (i: FunnelInputs) => `${formatNumber(i.vslViews)} YouTube views ÷ ${formatNumber(i.botStarts)} starts` },
  { key: 'crmFill', label: 'CRM fill rate', color: '#db2777', desc: '% of bot-starters who filled the in-bot form', sub: (i: FunnelInputs) => `${formatNumber(i.crmLeads)} form submits ÷ ${formatNumber(i.botStarts)} starts` },
] as const

const FUNNEL_COLORS: Record<string, string> = { linkClicks: '#2563eb', landingViews: '#2563eb', leads: '#0d9488', botStarts: '#7c3aed', vslViews: '#ea580c', crmLeads: '#db2777' }
const COST_DEFS = [
  { key: 'perVisit', color: '#2563eb', label: 'per visit (landing view)' },
  { key: 'perLead', color: '#0d9488', label: 'per lead (CTA)' },
  { key: 'perBotStart', color: '#7c3aed', label: 'per bot start' },
  { key: 'perVslView', color: '#ea580c', label: 'per VSL view (YouTube)' },
  { key: 'perCrmLead', color: '#db2777', label: 'per CRM lead' },
] as const

const EMPTY_CRM: CrmStages = { ok: false, total: 0, paid: 0, paidStageIds: [], stages: [] }
const EMPTY_VSL: VslMetrics = { ok: false, configured: false, views: null, viewsWatched50: null, watchRate50: null, hasRetention: false }

export function LiveCampaignKpis({ campaignId, campaignName, days, since, until, periodLabel, refreshKey }: LiveCampaignKpisProps) {
  const scoped = Boolean(since && until)
  const currentKey = `${campaignId}|${days}|${since ?? ''}|${until ?? ''}|${refreshKey}`
  const [bundle, setBundle] = useState<{ kpis: CampaignKpis; crm: CrmStages; vsl: VslMetrics; loadedKey: string } | null>(null)
  // Which rate's trend chart is open (null = trends hidden). Set by clicking a rate card
  // below or the "Show trends" button inside FunnelTrends.
  const [trendRate, setTrendRate] = useState<TrendRateKey | null>(null)

  useEffect(() => {
    if (typeof fetch !== 'function') return
    let active = true
    const key = `${campaignId}|${days}|${since ?? ''}|${until ?? ''}|${refreshKey}`
    // refreshKey>0 means the Refresh button was pressed → force a live, uncached pull on
    // every source (Meta insights, CRM stages, YouTube) and bust any browser cache.
    const force = refreshKey > 0
    const win = { days, since, until, force }
    // CRM stages cover ALL leads that landed in Bitrix for the window (cell 'all'). NOTE:
    // cell 'B' = "Landing B / the no-bot direct form" — a tiny/empty bucket; the real bot +
    // alikhanova.cloud form leads land in cell A, so 'all' is what the orders count and the
    // cost-per-CRM-lead use. (The CRM-fill RATE uses the first-party crm_form_submit relay,
    // not these Bitrix stages.)
    void Promise.all([
      getCampaignKpis(campaignId, win),
      getCrmStages({ ...win, cell: 'all' }),
      getVsl(win),
    ])
      .then(([kpis, crm, vsl]) => {
        if (active) setBundle({ kpis, crm, vsl, loadedKey: key })
      })
      .catch(() => {
        if (active) setBundle({ kpis: { ok: false }, crm: EMPTY_CRM, vsl: EMPTY_VSL, loadedKey: key })
      })
    return () => {
      active = false
    }
  }, [campaignId, days, since, until, refreshKey])

  const loading = bundle?.loadedKey !== currentKey
  const kpis = loading ? undefined : bundle?.kpis
  const crm = loading ? undefined : bundle?.crm
  const vsl = loading ? undefined : bundle?.vsl
  const live = Boolean(kpis?.ok && kpis?.hasData)

  // VSL views for the active window: a bounded range uses the period delta (periodViews),
  // an open "last N days" window uses YouTube's lifetime cumulative.
  const vslViewsValue = scoped ? (vsl?.periodViews ?? null) : (vsl?.views ?? null)

  // Every input is LIVE — no manual entry. Bot starts come from the first-party Telegram
  // relay (kpis.counts.botStarts), CRM leads from Bitrix bot-only (Cell B), VSL views from
  // YouTube. All refresh together when Refresh is pressed.
  // CRM fill = people who filled the form INSIDE the Telegram bot, measured by the
  // first-party crm_form_submit event (a ChatPlace relay, like bot_start) — NOT the Bitrix
  // "Cell B" tag, which is the no-bot direct-landing form. formSubmits is account-wide.
  const formSubmits = kpis?.counts?.formSubmits ?? 0
  const crmNotTracked = Boolean(kpis?.ok && formSubmits === 0)
  const inputs: FunnelInputs = {
    linkClicks: kpis?.counts?.linkClicks ?? 0,
    landingViews: kpis?.counts?.landingPageViews ?? 0,
    leads: kpis?.counts?.leads ?? 0,
    botStarts: kpis?.counts?.botStarts ?? 0,
    vslViews: vslViewsValue ?? 0,
    crmLeads: formSubmits,
    spend: kpis?.kpis?.spend ?? 0,
  }
  const out = computeSimpleFunnel(inputs)
  const maxBar = Math.max(inputs.linkClicks, 1)
  const vslNeedsConnect = Boolean(vsl && !vsl.configured)
  // Configured, but a bounded range with no baseline snapshot yet → daily VSL still accruing.
  const vslAccruing = Boolean(vsl?.configured && scoped && vslViewsValue == null)

  // VSL reach rate: YouTube views ÷ bot-starts. Uses period views when scoped, lifetime
  // otherwise. Can exceed 100% (public YouTube includes rewatches + non-bot viewers; YouTube
  // Studio data lags ~48 h so there is also an API lag effect).
  const reachViews = vsl?.periodViews ?? vsl?.views ?? null
  const botStartsForReach = kpis?.counts?.botStarts ?? 0
  const reachRate: number | null =
    botStartsForReach > 0 && reachViews != null ? (reachViews / botStartsForReach) * 100 : null

  const periodText = periodLabel ?? (scoped ? `${since} → ${until}` : `last ${days} days`)
  const freshness = loading
    ? 'Loading live data…'
    : live
      ? `Live · ${periodText}`
      : kpis?.ok
        ? `Live · no delivery · ${periodText}`
        : 'Connect Meta to see live KPIs.'

  return (
    <section className="simple-dash" aria-label="Live campaign funnel">
      <div className="simple-toolbar">
        <h5>{campaignName}</h5>
        <span className="simple-note">
          {freshness}
          {kpis?.conversionEvent ? ` · 🎯 optimizing for ${kpis.conversionEvent}` : ''}
        </span>
      </div>

      <div className="simple-cards">
        {RATE_CARDS.map((card) => {
          // START rate uses the backend's select_start_rate (first-party bot starts ÷
          // Telegram button clicks, scoped + capped) — the deliberate implementation —
          // rather than the client-side starts÷leads. The other four stay client-computed.
          let value: string
          let sub: string
          // startHealthWarning: non-null when the backend signals a bot_start collection
          // gap. 'stalled' = relay currently down (red); 'gap' = gap in history but
          // collecting again now (amber). We do NOT change the displayed rate — flag only.
          let startHealthWarning: 'stalled' | 'gap' | null = null
          let startHealthMessage: string | null = null
          if (card.key === 'start') {
            value = loading ? '…' : kpis?.rates ? `${kpis.rates.startRate}%` : '—'
            const starts = formatNumber(kpis?.counts?.botStarts ?? 0)
            const denom =
              kpis?.startDenominatorSource === 'telegram_link_click'
                ? `${formatNumber(kpis?.counts?.telegramLinkClicks ?? 0)} button clicks`
                : `${formatNumber(kpis?.counts?.leads ?? 0)} leads`
            const scopeNote = kpis?.startScope === 'account' && campaignId !== 'all' ? ' · account-wide' : ''
            sub = `${starts} starts ÷ ${denom}${scopeNote}`
            if (!loading && kpis?.startHealth?.message) {
              startHealthWarning = kpis.startHealth.stalled ? 'stalled' : 'gap'
              startHealthMessage = kpis.startHealth.message
            }
          } else if (card.key === 'vslView' && vslNeedsConnect) {
            value = loading ? '…' : '—'
            sub = 'Connect YouTube to populate'
          } else if (card.key === 'vslView' && vslAccruing) {
            value = loading ? '…' : '—'
            sub = 'VSL daily accrues — check back tomorrow'
          } else if (card.key === 'vslView') {
            // Reach proxy: uncapped YouTube-views ÷ bot-starts (can exceed 100% — public
            // YouTube counts rewatches + non-bot viewers). For short windows, YouTube's
            // ~48h reporting lag starves the numerator, so the number reads artificially low.
            value = loading ? '…' : reachRate != null ? `${reachRate.toFixed(1)}%` : '—'
            sub = card.sub(inputs) + (days <= 2 ? ' · YouTube lags ~48h, so today/recent read low' : '')
          } else if (card.key === 'crmFill' && crmNotTracked) {
            value = loading ? '…' : '—'
            sub = 'In-bot form-submit relay not connected — add it in ChatPlace to populate this.'
          } else {
            value = loading ? '…' : `${out.rates[card.key as keyof typeof out.rates]}%`
            sub = card.sub(inputs)
          }
          const selected = trendRate === card.key
          const toggle = () => setTrendRate((prev) => (prev === card.key ? null : (card.key as TrendRateKey)))
          // The conversion card relabels to the campaign's OWN optimized event (Lead /
          // Registration / View rate) so a registration/view campaign isn't mislabelled.
          const cardLabel = card.key === 'lead' && kpis?.conversionLabel ? kpis.conversionLabel : card.label
          return (
            <article
              className={`simple-rate-card simple-rate-clickable${selected ? ' is-selected' : ''}`}
              key={card.key}
              role="button"
              tabIndex={0}
              aria-pressed={selected}
              title="Click to see this rate's trend over time"
              onClick={toggle}
              onKeyDown={(e) => {
                if (e.key === 'Enter' || e.key === ' ') {
                  e.preventDefault()
                  toggle()
                }
              }}
            >
              <p className="simple-rate-label" style={{ color: card.color }}>
                <span className="simple-dot" style={{ background: card.color }} />
                {cardLabel}
              </p>
              <strong style={{ color: card.color }}>
                {value}
                {startHealthWarning && (
                  <span
                    aria-label="Data incomplete"
                    style={{
                      marginLeft: '0.35em',
                      fontSize: '0.85em',
                      color: startHealthWarning === 'stalled' ? 'var(--color-danger, #dc2626)' : 'var(--color-warning, #d97706)',
                    }}
                  >
                    ⚠️
                  </span>
                )}
              </strong>
              <span
                className="simple-rate-sub"
                style={
                  startHealthWarning
                    ? {
                        color: startHealthWarning === 'stalled' ? 'var(--color-danger, #dc2626)' : 'var(--color-warning, #d97706)',
                        fontStyle: 'italic',
                      }
                    : undefined
                }
              >
                {startHealthWarning && startHealthMessage ? startHealthMessage : sub}
              </span>
              <small>{card.desc}</small>
              <span className="simple-rate-trend-hint">📈 {selected ? 'trend shown' : 'view trend'}</span>
            </article>
          )
        })}
      </div>

      <FunnelTrends
        campaignId={campaignId}
        days={days}
        refreshKey={refreshKey}
        selectedRate={trendRate}
        onSelectRate={setTrendRate}
      />

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
          insights, bot starts + in-bot form submits from the Telegram relay, VSL views from YouTube.
          {vslNeedsConnect ? ' VSL views read 0 until YouTube is connected (set YOUTUBE_VSL_VIDEO_ID + YOUTUBE_API_KEY).' : ''}
        </small>
      </div>

      <div className="simple-block">
        <h5>Cost per stage</h5>
        <div className="simple-cost">
          {COST_DEFS.map((c) => (
            <article className="simple-cost-item" key={c.key}>
              <strong style={{ color: c.color }}>
                {loading
                  ? '…'
                  : c.key === 'perCrmLead'
                    ? // The cost ladder's CRM-lead step uses the REAL Bitrix lead count (same as
                      // the CRM block below), NOT the first-party crm_form_submit count (≈0 until
                      // that relay is wired) — otherwise it divides by ~0 and reads $0.00.
                      crm?.costPerLead != null
                      ? money(crm.costPerLead)
                      : '—'
                    : money(out.cost[c.key as keyof typeof out.cost])}
              </strong>
              <small>{c.label}</small>
            </article>
          ))}
        </div>
      </div>

      {crm && crm.ok ? (
        <div className="simple-block">
          <h5>CRM order stages — Bitrix24 (all leads)</h5>
          <p className="simple-help">
            <strong>{formatNumber(crm.total)}</strong> orders · Bitrix24 · {formatNumber(crm.paid)} paid
            {crm.cellCounts ? ` · Cell A ${formatNumber(crm.cellCounts.A)} · Cell B ${formatNumber(crm.cellCounts.B)} (no-bot form)` : ''}
          </p>
          {crm.total > 0 ? (
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
          ) : (
            <p className="simple-help">No Bitrix orders for this form in this period yet.</p>
          )}
          <div className="simple-cost" style={{ marginTop: '0.75rem' }}>
            <article className="simple-cost-item">
              <strong style={{ color: '#db2777' }}>
                {loading ? '…' : crm.costPerLead != null ? money(crm.costPerLead) : '—'}
              </strong>
              <small>Cost per CRM lead</small>
              <small className="simple-rate-sub">
                {loading ? '' : crm.spend != null && crm.leadsAll != null
                  ? `${money(crm.spend)} spend ÷ ${formatNumber(crm.leadsAll)} leads · account-level`
                  : 'account-level'}
              </small>
            </article>
            <article className="simple-cost-item">
              <strong style={{ color: '#be185d' }}>
                {loading ? '…' : crm.costPerSale != null ? money(crm.costPerSale) : '—'}
              </strong>
              <small>Cost per sale</small>
              <small className="simple-rate-sub">
                {loading ? '' : crm.spend != null && crm.paidAll != null
                  ? `${money(crm.spend)} spend ÷ ${formatNumber(crm.paidAll)} paid · account-level`
                  : 'account-level'}
              </small>
            </article>
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
