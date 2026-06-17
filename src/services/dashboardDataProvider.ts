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
    costPerStart: number | null
  }
  rates?: { visitRate: number; leadRate: number; startRate: number }
  counts?: {
    linkClicks: number
    landingPageViews: number
    leads: number
    subscribes: number
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

// Live KPIs + funnel rates for one campaign (or the whole account when 'all').
// The campaignId param is omitted for 'all' so the backend scopes account-wide.
export async function getCampaignKpis(
  campaignId: string,
  days: number,
  force = false,
): Promise<CampaignKpis> {
  try {
    const scope = campaignId === 'all' ? '' : `campaignId=${encodeURIComponent(campaignId)}&`
    const response = await fetch(apiUrl(`/api/campaigns/kpis?${scope}days=${days}&force=${force}`))
    if (!response.ok) {
      return { ok: false }
    }
    return (await response.json()) as CampaignKpis
  } catch {
    return { ok: false }
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
