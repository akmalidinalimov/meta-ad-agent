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
    const response = await fetch('/api/dashboard')

    if (!response.ok) {
      throw new Error(`Dashboard API failed with ${response.status}`)
    }

    return (await response.json()) as DashboardData
  },
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
