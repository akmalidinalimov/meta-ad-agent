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
      return mockDashboardDataProvider.getDashboardData()
    }
  },
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
