import { useCallback, useEffect, useState } from 'react'
import { Dashboard } from './components/Dashboard'
import { dashboardDataProvider, mockDashboardDataProvider } from './services/dashboardDataProvider'
import type { DashboardData } from './types/marketing'
import './App.css'

const LOAD_TIMEOUT_MS = 30000

async function getDashboardDataWithTimeout() {
  let timeoutId: ReturnType<typeof setTimeout> | undefined

  try {
    return await Promise.race([
      dashboardDataProvider.getDashboardData(),
      new Promise<DashboardData>((resolve) => {
        timeoutId = setTimeout(async () => {
          console.warn('Dashboard API did not respond in time. Showing local dashboard data.')
          resolve(await mockDashboardDataProvider.getDashboardData())
        }, LOAD_TIMEOUT_MS)
      }),
    ])
  } finally {
    if (timeoutId) {
      clearTimeout(timeoutId)
    }
  }
}

function App() {
  const [data, setData] = useState<DashboardData | null>(null)
  const [isRefreshing, setIsRefreshing] = useState(false)

  const refreshDashboardData = useCallback(async () => {
    setIsRefreshing(true)
    try {
      const nextData = await getDashboardDataWithTimeout()
      setData(nextData)
      return nextData
    } catch (error) {
      console.error('Dashboard data refresh failed. Keeping current dashboard data.', error)
      throw error
    } finally {
      setIsRefreshing(false)
    }
  }, [])

  useEffect(() => {
    let isMounted = true

    void getDashboardDataWithTimeout()
      .catch((error) => {
        console.error('Dashboard data load failed. Showing local dashboard data.', error)
        return mockDashboardDataProvider.getDashboardData()
      })
      .then((nextData) => {
        if (isMounted) {
          setData(nextData)
        }
      })

    return () => {
      isMounted = false
    }
  }, [])

  if (!data) {
    return (
      <main className="app-shell">
        <div className="loading-panel">Loading campaign audit...</div>
      </main>
    )
  }

  return (
    <Dashboard
      data={data}
      isRefreshing={isRefreshing}
      onRefresh={refreshDashboardData}
      key={`${data.dataSource?.kind ?? 'local'}-${data.dataSource?.generatedAt ?? 'initial'}`}
    />
  )
}

export default App
