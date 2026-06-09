import { useCallback, useEffect, useState } from 'react'
import { Dashboard } from './components/Dashboard'
import { CreativesView } from './components/CreativesView'
import { Login } from './components/Login'
import { dashboardDataProvider, mockDashboardDataProvider } from './services/dashboardDataProvider'
import type { DashboardData } from './types/marketing'
import './App.css'

const LOAD_TIMEOUT_MS = 30000

type AuthState = 'checking' | 'authed' | 'login' | 'tg_error'

type TelegramWebApp = { initData?: string; ready?: () => void; expand?: () => void }

async function bootstrapAuth(): Promise<AuthState> {
  // Telegram Mini App: authenticate with the signed initData (no password).
  const tg = (window as unknown as { Telegram?: { WebApp?: TelegramWebApp } }).Telegram?.WebApp
  if (tg?.initData) {
    // Inside Telegram the operator must never see the password screen. If the
    // initData auth fails, surface a retryable error instead of falling through
    // to the browser session/password path.
    try {
      tg.ready?.()
      tg.expand?.()
      const response = await fetch('/api/telegram/webapp-auth', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ initData: tg.initData }),
      })
      return response.ok ? 'authed' : 'tg_error'
    } catch {
      return 'tg_error'
    }
  }
  try {
    const response = await fetch('/api/auth/session')
    const json = (await response.json()) as { authenticated?: boolean }
    return json.authenticated ? 'authed' : 'login'
  } catch {
    return 'login'
  }
}

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
  const [authState, setAuthState] = useState<AuthState>('checking')
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

  const runBootstrapAuth = useCallback(() => {
    setAuthState('checking')
    void bootstrapAuth().then((state) => {
      setAuthState(state)
    })
  }, [])

  useEffect(() => {
    let mounted = true
    void bootstrapAuth().then((state) => {
      if (mounted) {
        setAuthState(state)
      }
    })
    return () => {
      mounted = false
    }
  }, [])

  useEffect(() => {
    if (authState !== 'authed') {
      return
    }
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
  }, [authState])

  if (authState === 'checking') {
    return (
      <main className="app-shell">
        <div className="loading-panel">Loading…</div>
      </main>
    )
  }

  if (authState === 'tg_error') {
    return (
      <main className="app-shell login-shell">
        <div className="login-card">
          <h1>Meta Ad Agent</h1>
          <p>Couldn't verify your Telegram session.</p>
          <button type="button" onClick={runBootstrapAuth}>
            Retry
          </button>
        </div>
      </main>
    )
  }

  if (authState === 'login') {
    return <Login onSuccess={() => setAuthState('authed')} />
  }

  // Deep link from the Telegram ad-set drill-down: ?adset=<id> opens the rich
  // per-ad-set creatives view (thumbnails + lifetime stats) instead of the dashboard.
  const adsetParam = new URLSearchParams(window.location.search).get('adset')
  if (adsetParam) {
    return <CreativesView adsetId={adsetParam} />
  }

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
