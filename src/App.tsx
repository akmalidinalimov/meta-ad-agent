import { useEffect, useState } from 'react'
import { Dashboard } from './components/Dashboard'
import { dashboardDataProvider } from './services/dashboardDataProvider'
import type { DashboardData } from './types/marketing'
import './App.css'

function App() {
  const [data, setData] = useState<DashboardData | null>(null)

  useEffect(() => {
    void dashboardDataProvider.getDashboardData().then(setData)
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
