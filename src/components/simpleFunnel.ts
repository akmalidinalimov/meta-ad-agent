// Pure funnel/rate/cost math for the simple single-page dashboard.
// Rates round to 1 decimal, money to 2 — matching the reference image exactly.

export interface FunnelInputs {
  linkClicks: number
  landingViews: number
  leads: number
  botStarts: number
  vslViews: number
  crmLeads: number
  spend: number
}

export interface FunnelBar {
  key: string
  label: string
  value: number
  pctOfPrev: number
  pctLabel: string
}

export interface SimpleFunnelOutput {
  rates: { visit: number; lead: number; start: number; vslView: number; crmFill: number }
  funnel: FunnelBar[]
  cost: { perVisit: number; perLead: number; perBotStart: number; perVslView: number; perCrmLead: number }
}

// Rate as a 1-decimal percent, capped at 100% — Meta cross-window attribution (and the
// account-wide bot-start denominator on a single campaign) can otherwise yield an
// impossible >100%. Matches the rest of the app, which also caps rates at 100.
function pct(numer: number, denom: number): number {
  return denom > 0 ? Math.min(100, Math.round((numer / denom) * 1000) / 10) : 0
}

function money(spend: number, count: number): number {
  return count > 0 ? Math.round((spend / count) * 100) / 100 : 0
}

export function computeSimpleFunnel(i: FunnelInputs): SimpleFunnelOutput {
  return {
    // Cards: each step over its natural denominator (CRM fill is vs bot starts).
    rates: {
      visit: pct(i.landingViews, i.linkClicks),
      lead: pct(i.leads, i.landingViews),
      start: pct(i.botStarts, i.leads),
      vslView: pct(i.vslViews, i.botStarts),
      crmFill: pct(i.crmLeads, i.botStarts),
    },
    // Funnel bars: each row's % is vs the stage directly above it.
    funnel: [
      { key: 'linkClicks', label: 'Link clicks', value: i.linkClicks, pctOfPrev: 100, pctLabel: '100%' },
      {
        key: 'landingViews',
        label: 'Landing views',
        value: i.landingViews,
        pctOfPrev: pct(i.landingViews, i.linkClicks),
        pctLabel: `${pct(i.landingViews, i.linkClicks)}% of clicks`,
      },
      {
        key: 'leads',
        label: 'Leads (CTA)',
        value: i.leads,
        pctOfPrev: pct(i.leads, i.landingViews),
        pctLabel: `${pct(i.leads, i.landingViews)}% of views`,
      },
      {
        key: 'botStarts',
        label: 'Bot starts',
        value: i.botStarts,
        pctOfPrev: pct(i.botStarts, i.leads),
        pctLabel: `${pct(i.botStarts, i.leads)}% of leads`,
      },
      {
        key: 'vslViews',
        label: 'VSL views (YT)',
        value: i.vslViews,
        pctOfPrev: pct(i.vslViews, i.botStarts),
        pctLabel: `${pct(i.vslViews, i.botStarts)}% of starts`,
      },
      {
        key: 'crmLeads',
        label: 'CRM leads (form)',
        value: i.crmLeads,
        pctOfPrev: pct(i.crmLeads, i.vslViews),
        pctLabel: `${pct(i.crmLeads, i.vslViews)}% of VSL views`,
      },
    ],
    // Spend ÷ each stage's volume.
    cost: {
      perVisit: money(i.spend, i.landingViews),
      perLead: money(i.spend, i.leads),
      perBotStart: money(i.spend, i.botStarts),
      perVslView: money(i.spend, i.vslViews),
      perCrmLead: money(i.spend, i.crmLeads),
    },
  }
}
