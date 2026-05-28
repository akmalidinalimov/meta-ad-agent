import { useEffect, useState } from 'react'
import { Dashboard } from './components/Dashboard'
import { dashboardDataProvider, mockDashboardDataProvider } from './services/dashboardDataProvider'
import type { DashboardData } from './types/marketing'
import './App.css'

const LOAD_TIMEOUT_MS = 12000

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

  return <Dashboard data={data} key={`${data.dataSource?.kind ?? 'local'}-${data.dataSource?.generatedAt ?? 'initial'}`} />
}

export default App
