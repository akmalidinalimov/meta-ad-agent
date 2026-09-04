import { dashboardData } from '../data/dashboardData'
import type { DashboardData } from '../types/marketing'

export interface DashboardDataProvider {
  getDashboardData(): Promise<DashboardData>
}

export const mockDashboardDataProvider: DashboardDataProvider = {
  async getDashboardData() {
    return dashboardData
  },
}

export const apiDashboardDataProvider: DashboardDataProvider = {
  async getDashboardData() {
    if (typeof fetch !== 'function') {
      return getDashboardDataFromScript()
    }

    const response = await fetch(apiUrl('/api/dashboard'))

    if (!response.ok) {
      throw new Error(`Dashboard API failed with ${response.status}`)
    }

    return (await response.json()) as DashboardData
  },
}

function getDashboardDataFromScript() {
  return new Promise<DashboardData>((resolve, reject) => {
    if (typeof document === 'undefined') {
      reject(new Error('Dashboard script fallback requires a browser document.'))
      return
    }

    const callbackName = `__metaAdAgentDashboard${Date.now()}${Math.random().toString(16).slice(2)}`
    const script = document.createElement('script')
    const cleanup = () => {
      delete (window as unknown as Record<string, unknown>)[callbackName]
      script.remove()
    }
    const timeoutId = window.setTimeout(() => {
      cleanup()
      reject(new Error('Dashboard script fallback timed out.'))
    }, 20000)

    ;(window as unknown as Record<string, (payload: DashboardData) => void>)[callbackName] = (payload) => {
      window.clearTimeout(timeoutId)
      cleanup()
      resolve(payload)
    }

    script.src = `${apiUrl('/api/dashboard.js')}?callback=${encodeURIComponent(callbackName)}`
    script.async = true
    script.onerror = () => {
      window.clearTimeout(timeoutId)
      cleanup()
      reject(new Error('Dashboard script fallback failed.'))
    }
    document.head.appendChild(script)
  })
}

export const dashboardDataProvider: DashboardDataProvider = {
  async getDashboardData() {
    try {
      return await apiDashboardDataProvider.getDashboardData()
    } catch (error) {
      console.warn('Falling back to local mock dashboard data.', error)
      const mock = await mockDashboardDataProvider.getDashboardData()
      // Tag the fallback so the UI can warn the operator they are NOT looking at live data.
      return {
        ...mock,
        dataSource: {
          ...(mock.dataSource ?? { kind: 'mock', label: 'Local sample data' }),
          backendUnreachable: true,
        },
      }
    }
  },
}

// Live Meta data fetched on demand, separate from the synced dashboard snapshot.
// The Monitor view uses these to show fresh per-campaign KPIs and funnel rates
// instead of the stale synced numbers.
export type LiveCampaign = {
  id: string
  name: string
  status: string | null
  effectiveStatus: string | null
  objective: string | null
  dailyBudgetUsd: number | null
  createdAt: string | null
  startedAt: string | null
  stoppedAt: string | null
}

export type CampaignKpis = {
  ok: boolean
  source?: string
  days?: number
  campaignId?: string
  campaignName?: string
  hasData?: boolean
  conversionEvent?: string
  conversionLabel?: string
  kpis?: {
    spend: number
    leads: number
    cpl: number
    ctr: number
    leadRateFromClick: number
    purchases: number
    subscribes: number
    clicks: number
    impressions: number
    reach: number
    costPerStart: number | null
  }
  rates?: { visitRate: number; leadRate: number; startRate: number }
  counts?: {
    linkClicks: number
    landingPageViews: number
    leads: number
    subscribes: number
    botStarts?: number
    telegramLinkClicks?: number
    formSubmits?: number
    vslPlays?: number
    vslKeyMessage?: number
  }
  startSource?: string
  startDenominatorSource?: string
  startScope?: string
  startHealth?: {
    stalled: boolean
    gapHours: number
    clicksDuringGap: number
    collectedStartRate: number | null
    message: string | null
  }
  syncErrors?: string[]
  error?: string
}

// Live campaigns created within the last `days`. On any failure we return a safe
// empty shape so callers never have to special-case rejections — the picker just
// shows "All campaigns" and the error text.
export async function getLiveCampaigns(
  days: number,
  force = false,
): Promise<{ ok: boolean; source?: string; campaigns: LiveCampaign[]; error?: string }> {
  try {
    const response = await fetch(
      apiUrl(`/api/campaigns/live?createdWithinDays=${days}&force=${force}`),
    )
    if (!response.ok) {
      return { ok: false, source: 'snapshot', campaigns: [] }
    }
    return (await response.json()) as {
      ok: boolean
      source?: string
      campaigns: LiveCampaign[]
      error?: string
    }
  } catch {
    return { ok: false, source: 'snapshot', campaigns: [] }
  }
}

// The date scope for a card fetch: an explicit since..until range (e.g. Today) wins,
// otherwise the last `days` days. `force` cache-busts on Refresh.
export type CardWindow = { days: number; since?: string; until?: string; force?: boolean }

function windowParams(w: CardWindow): URLSearchParams {
  const params = new URLSearchParams()
  if (w.since && w.until) {
    params.set('since', w.since)
    params.set('until', w.until)
  } else {
    params.set('days', String(w.days))
  }
  if (w.force) params.set('force', 'true')
  return params
}

// Live KPIs + funnel rates for one campaign (or the whole account when 'all').
// The campaignId param is omitted for 'all' so the backend scopes account-wide.
export async function getCampaignKpis(campaignId: string, w: CardWindow): Promise<CampaignKpis> {
  try {
    const params = windowParams(w)
    if (campaignId && campaignId !== 'all') params.set('campaignId', campaignId)
    const response = await fetch(apiUrl(`/api/campaigns/kpis?${params.toString()}`))
    if (!response.ok) {
      return { ok: false }
    }
    return (await response.json()) as CampaignKpis
  } catch {
    return { ok: false }
  }
}

// Bitrix CRM stage distribution for the configured order/source. Safe empty shape on failure.
// `cell` selects origin: 'B' = Telegram-bot VSL form only, 'A' = same form elsewhere, 'all' = both.
export type CrmStageRow = { id: string; name: string; count: number }
export type CrmStages = {
  ok: boolean
  source?: string
  total: number
  paid: number
  paidStageIds: string[]
  stages: CrmStageRow[]
  days?: number
  since?: string
  until?: string
  cell?: string
  cellCounts?: { A: number; B: number; all: number }
  spend?: number
  leadsAll?: number
  paidAll?: number
  costPerLead?: number | null
  costPerSale?: number | null
  error?: string
}
export async function getCrmStages(w: CardWindow & { cell?: 'A' | 'B' | 'all' }): Promise<CrmStages> {
  const empty: CrmStages = { ok: false, total: 0, paid: 0, paidStageIds: [], stages: [] }
  try {
    const params = windowParams(w)
    if (w.cell) params.set('cell', w.cell)
    const response = await fetch(apiUrl(`/api/crm/stages?${params.toString()}`))
    if (!response.ok) return empty
    return (await response.json()) as CrmStages
  } catch {
    return empty
  }
}

// YouTube VSL watch-through. Safe "unconfigured" shape on failure. When the window is a
// bounded range, `periodViews` is the views inside that range (lifetime `views` still set).
export type VslMetrics = {
  ok: boolean
  configured: boolean
  views: number | null
  viewsWatched50: number | null
  watchRate50: number | null
  hasRetention: boolean
  scoped?: boolean
  periodViews?: number | null
  since?: string
  until?: string
  error?: string
}
export async function getVsl(w: CardWindow): Promise<VslMetrics> {
  const empty: VslMetrics = { ok: false, configured: false, views: null, viewsWatched50: null, watchRate50: null, hasRetention: false }
  try {
    const response = await fetch(apiUrl(`/api/vsl?${windowParams(w).toString()}`))
    if (!response.ok) return empty
    return (await response.json()) as VslMetrics
  } catch {
    return empty
  }
}

// Per-day funnel history (the trend charts). Each point carries the day's COUNTS — the
// UI derives visit/lead/VSL-view/CRM-fill with the same computeSimpleFunnel as the live
// cards, and uses the backend startRate — so the trend line and the headline card agree.
export type FunnelHistoryPoint = {
  date: string
  incomplete?: boolean
  spend: number
  startRate: number
  startDenominatorSource?: string
  counts: {
    linkClicks: number
    landingViews: number
    leads: number
    botStarts: number
    telegramLinkClicks: number
    subscribes: number
    crmLeads: number
    vslViews: number | null
  }
}
export type FunnelHistory = {
  ok: boolean
  days?: number
  since?: string
  until?: string
  campaignId?: string
  vslConfigured?: boolean
  points: FunnelHistoryPoint[]
  notes?: Record<string, string>
  error?: string
}

export async function getFunnelHistory(
  campaignId: string,
  opts: { days?: number; since?: string; until?: string; force?: boolean } = {},
): Promise<FunnelHistory> {
  const empty: FunnelHistory = { ok: false, points: [] }
  try {
    const params = new URLSearchParams()
    if (campaignId && campaignId !== 'all') params.set('campaignId', campaignId)
    if (opts.since && opts.until) {
      params.set('since', opts.since)
      params.set('until', opts.until)
    } else if (opts.days) {
      params.set('days', String(opts.days))
    }
    if (opts.force) params.set('force', 'true')
    const response = await fetch(apiUrl(`/api/funnel/history?${params.toString()}`))
    if (!response.ok) return empty
    return (await response.json()) as FunnelHistory
  } catch {
    return empty
  }
}

function apiUrl(path: string) {
  const configuredBaseUrl = import.meta.env.VITE_API_BASE_URL as string | undefined
  if (configuredBaseUrl) {
    return `${configuredBaseUrl.replace(/\/$/, '')}${path}`
  }

  if (typeof window !== 'undefined' && ['127.0.0.1', 'localhost'].includes(window.location.hostname)) {
    return `http://127.0.0.1:8000${path}`
  }

  return path
}
