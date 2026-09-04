import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  AlertTriangle,
  BarChart3,
  CheckCircle2,
  LayoutDashboard,
  RefreshCcw,
  Settings,
  ShieldAlert,
  SlidersHorizontal,
  Users,
} from 'lucide-react'
import { RankingsView } from './dashboard/views/RankingsView'
import { SettingsView } from './dashboard/views/SettingsView'
import { TeamPanel } from './dashboard/views/TeamPanel'
import { MonitorView } from './dashboard/views/MonitorView'
import {
  deriveFunnel,
  deriveTrend,
  filterMetricsForDashboard,
  getDateWindow,
  type DateRange,
} from '../lib/analytics'
import { getDashboardAnchorDate } from '../lib/format'
import { getMetaStatus, type MetaStatus } from '../services/metaStatusProvider'
import { getLiveCampaigns, type LiveCampaign } from '../services/dashboardDataProvider'
import type { DashboardData } from '../types/marketing'

const navItems = [
  { id: 'overview', label: 'Monitor', icon: LayoutDashboard },
  { id: 'rankings', label: 'Rankings', icon: BarChart3 },
  { id: 'settings', label: 'Settings', icon: Settings },
  { id: 'team', label: 'Team', icon: Users, managerOnly: true },
] as const

type ViewId = (typeof navItems)[number]['id']

// Exported for unit testing the role-gated nav; co-located with navItems on purpose.
// eslint-disable-next-line react-refresh/only-export-components
export function visibleNavFor(role: string | null) {
  const isManager = role === null || role === 'owner' || role === 'admin'
  return navItems.filter((item) => !('managerOnly' in item && item.managerOnly) || isManager)
}

// The single <h1> must describe the current view so screen-reader users (and
// the document outline) reflect where they are, not a fixed title.
function viewHeading(view: ViewId): string {
  switch (view) {
    case 'team':
      return 'Team & Access'
    case 'rankings':
      return 'Performance Rankings'
    case 'settings':
      return 'Settings & Data Sources'
    case 'overview':
    default:
      return 'Campaign Monitor'
  }
}

interface DashboardProps {
  data: DashboardData
  isRefreshing?: boolean
  onRefresh?: () => Promise<DashboardData>
  role?: string | null
}

// The campaign picker lists campaigns CREATED within this window, independent of the stat
// period — so a "Today" period never empties the campaign list.
const CAMPAIGN_LIST_DAYS = 90

type PeriodKind = 'today' | 'yesterday' | '7d' | '14d' | '30d' | 'custom'
type Period = { kind: PeriodKind; since?: string; until?: string }

// Format a Date's UTC wall-clock as YYYY-MM-DD.
function ymd(d: Date): string {
  return `${d.getUTCFullYear()}-${String(d.getUTCMonth() + 1).padStart(2, '0')}-${String(d.getUTCDate()).padStart(2, '0')}`
}

// Tashkent (UTC+5, no DST) is the operator's business day. Shift the current instant +5h and
// read its UTC fields to get the Tashkent calendar date — so "today" is the Tashkent day no
// matter which timezone the dashboard is opened in (phone, laptop, or the server).
const TASHKENT_OFFSET_MS = 5 * 60 * 60 * 1000
function tashkentDay(daysAgo = 0): Date {
  return new Date(Date.now() + TASHKENT_OFFSET_MS - daysAgo * 86_400_000)
}

// Resolve a period to the live-card window: an explicit since..until (every preset now sends
// one) on Tashkent (UTC+5) day boundaries, so the dashboard's day matches how leads are
// counted in Bitrix.
function resolvePeriod(p: Period): { days: number; since?: string; until?: string; label: string } {
  if (p.kind === 'today') {
    const t = ymd(tashkentDay(0))
    return { days: 1, since: t, until: t, label: 'Today' }
  }
  if (p.kind === 'yesterday') {
    const s = ymd(tashkentDay(1))
    return { days: 2, since: s, until: s, label: 'Yesterday' }
  }
  if (p.kind === 'custom' && p.since && p.until) {
    return { days: 30, since: p.since, until: p.until, label: `${p.since} → ${p.until}` }
  }
  const days = p.kind === '7d' ? 7 : p.kind === '14d' ? 14 : 30
  return { days, since: ymd(tashkentDay(days - 1)), until: ymd(tashkentDay(0)), label: `Last ${days} days` }
}

// The synced account-history disclosure still uses the coarse DateRange; map the period to it.
function periodToDateRange(p: Period): DateRange {
  if (p.kind === '14d') return '14d'
  if (p.kind === '7d' || p.kind === 'today' || p.kind === 'yesterday') return '7d'
  return '30d'
}

export function Dashboard({ data, isRefreshing = false, onRefresh, role = null }: DashboardProps) {
  // Viewers get a read-only console: no Team panel, no write controls.
  // A null role means auth is off (dev) → treat as full access.
  const isManager = role === 'owner' || role === 'admin' || role === null
  const visibleNavItems = visibleNavFor(role)
  const [activeView, setActiveView] = useState<ViewId>('overview')
  const [metaStatus, setMetaStatus] = useState<MetaStatus | null>(null)
  const [period, setPeriod] = useState<Period>({ kind: '30d' })
  const [selectedCampaignId, setSelectedCampaignId] = useState('all')
  const [liveCampaigns, setLiveCampaigns] = useState<LiveCampaign[]>([])
  const [liveError, setLiveError] = useState<string | null>(null)
  const [refreshKey, setRefreshKey] = useState(0)
  // The live cards use the precise period window (since/until/days); the synced history
  // disclosure uses the coarse DateRange derived from it.
  const live = resolvePeriod(period)
  const dateRange = periodToDateRange(period)

  // Account-history window (synced snapshot) drives the disclosure charts only —
  // it is account-wide (no campaign/creative filter); the live panel above it owns
  // the per-campaign scope.
  const filteredMetrics = useMemo(() => {
    const window = getDateWindow(dateRange, getDashboardAnchorDate(data))
    return filterMetricsForDashboard({
      metrics: data.metrics,
      campaigns: data.campaigns,
      ads: data.ads,
      creatives: data.creatives,
      filters: {
        start: window.start,
        end: window.end,
        campaignIds: ['all'],
        creativeFormat: 'all',
      },
    })
  }, [data, dateRange])
  const funnel = useMemo(() => deriveFunnel(filteredMetrics), [filteredMetrics])
  const trend = useMemo(() => deriveTrend(filteredMetrics), [filteredMetrics])
  const hasHistory = filteredMetrics.length > 0
  const dataSourceTone = data.dataSource?.kind === 'meta' ? 'good' : 'warning'

  useEffect(() => {
    void getMetaStatus()
      .then(setMetaStatus)
      .catch(() => {
        setMetaStatus(null)
      })
  }, [])

  // Load the live campaign list for the picker, scoped to those CREATED within the
  // selected window. A range change re-fetches; Refresh forces a live pull. We never
  // setState synchronously in the effect body (react-hooks/set-state-in-effect) and
  // reset the selection only if the current pick is no longer in range.
  useEffect(() => {
    let active = true
    void getLiveCampaigns(CAMPAIGN_LIST_DAYS, refreshKey > 0)
      .then((result) => {
        if (!active) return
        setLiveCampaigns(result.campaigns)
        setLiveError(result.ok ? null : result.error ?? 'Connect Meta to list live campaigns.')
        setSelectedCampaignId((current) =>
          current === 'all' || result.campaigns.some((campaign) => campaign.id === current)
            ? current
            : 'all',
        )
      })
      .catch(() => {
        if (!active) return
        setLiveCampaigns([])
        setLiveError('Connect Meta to list live campaigns.')
      })
    return () => {
      active = false
    }
  }, [refreshKey])

  // Refresh bumps refreshKey (forces live re-fetch in the picker + KPI panels) and
  // re-runs the snapshot refresh so the account-history disclosure updates too.
  const handleRefresh = useCallback(() => {
    setRefreshKey((key) => key + 1)
    if (onRefresh) void onRefresh()
  }, [onRefresh])

  // Freshness stamp: when this data was loaded, and whether it is live. Keyed to
  // `data` so the timestamp re-stamps on every refresh (no effect → no cascading
  // render). The memo body doesn't read `data`, so exhaustive-deps flags it as
  // "unnecessary" — but that dependency IS the point: it drives the re-stamp.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  const loadedAt = useMemo(() => new Date(), [data])
  const isLive = data.dataSource?.kind === 'meta' && !data.dataSource?.backendUnreachable
  const freshness = `${isLive ? 'data as of' : 'snapshot ·'} ${loadedAt.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', hour12: false })}`

  const selectedCampaignName =
    liveCampaigns.find((campaign) => campaign.id === selectedCampaignId)?.name ??
    (selectedCampaignId === 'all' ? 'All campaigns' : selectedCampaignId)

  return (
    <main className="app-shell">
      <header className="topbar">
        <div>
          <p className="eyebrow">Meta Ad Agent</p>
          <h1>{viewHeading(activeView)}</h1>
        </div>
        <div className="topbar-actions">
          {role === 'viewer' && (
            <div className="status-pill neutral" title="Read-only access">
              <ShieldAlert size={16} />
              Viewer · read-only
            </div>
          )}
          <div className={`status-pill ${dataSourceTone}`}>
            {data.dataSource?.kind === 'meta' ? <CheckCircle2 size={16} /> : <AlertTriangle size={16} />}
            {data.dataSource?.label ?? 'Dashboard data loaded'}
          </div>
          <div className="status-pill neutral">{freshness}</div>
          {onRefresh && (
            <button className="sync-button secondary" type="button" onClick={handleRefresh} disabled={isRefreshing}>
              <RefreshCcw size={16} />
              {isRefreshing ? 'Refreshing...' : 'Refresh data'}
            </button>
          )}
        </div>
      </header>

      <nav className="app-nav" aria-label="Dashboard sections">
        {visibleNavItems.map((item) => {
          const Icon = item.icon
          return (
            <button
              type="button"
              className={activeView === item.id ? 'active' : ''}
              aria-current={activeView === item.id ? 'page' : undefined}
              onClick={() => setActiveView(item.id)}
              key={item.id}
            >
              <Icon size={16} />
              <span>{item.label}</span>
            </button>
          )
        })}
      </nav>

      {data.dataSource?.backendUnreachable && (
        <div className="data-banner danger" role="status">
          <AlertTriangle size={16} />
          <span>Backend not reachable — showing local sample data. These numbers are NOT live; connect the backend before making decisions.</span>
        </div>
      )}

      {activeView === 'overview' && <PeriodSelector period={period} onChange={setPeriod} />}

      <Filters
        campaigns={liveCampaigns}
        selectedCampaignId={selectedCampaignId}
        onCampaignChange={setSelectedCampaignId}
        error={liveError}
      />

      {activeView === 'team' && isManager && <TeamPanel />}

      {/* The live panel owns its own empty state, so the Monitor renders
          unconditionally — an empty snapshot no longer hides live KPIs. */}
      {activeView === 'overview' && (
        <MonitorView
          metrics={filteredMetrics}
          trend={trend}
          funnel={funnel}
          days={live.days}
          since={live.since}
          until={live.until}
          periodLabel={live.label}
          campaignId={selectedCampaignId}
          campaignName={selectedCampaignName}
          refreshKey={refreshKey}
          hasHistory={hasHistory}
        />
      )}
      {activeView === 'rankings' && <RankingsView data={data} metrics={filteredMetrics} />}
      {activeView === 'settings' && <SettingsView data={data} metaStatus={metaStatus} onDashboardRefresh={onRefresh} />}
    </main>
  )
}

// Prominent period control for the live cards — Today / Yesterday / 7d / 14d / 30d /
// Custom. Sits directly above the KPI cards so the operator can scope every number
// (including "today's leads so far") in one tap.
const PERIOD_PRESETS: Array<{ kind: PeriodKind; label: string }> = [
  { kind: 'today', label: 'Today' },
  { kind: 'yesterday', label: 'Yesterday' },
  { kind: '7d', label: 'Last 7d' },
  { kind: '14d', label: 'Last 14d' },
  { kind: '30d', label: 'Last 30d' },
]

function PeriodSelector({ period, onChange }: { period: Period; onChange: (p: Period) => void }) {
  return (
    <div className="period-bar" role="group" aria-label="Date period">
      <span className="period-bar-label">📅 Period</span>
      <div className="period-chips">
        {PERIOD_PRESETS.map((preset) => (
          <button
            key={preset.kind}
            type="button"
            className={`period-chip${period.kind === preset.kind ? ' is-active' : ''}`}
            aria-pressed={period.kind === preset.kind}
            onClick={() => onChange({ kind: preset.kind })}
          >
            {preset.label}
          </button>
        ))}
        <button
          type="button"
          className={`period-chip${period.kind === 'custom' ? ' is-active' : ''}`}
          aria-pressed={period.kind === 'custom'}
          onClick={() => onChange({ kind: 'custom', since: period.since, until: period.until })}
        >
          Custom
        </button>
        {period.kind === 'custom' && (
          <span className="period-custom">
            <input
              type="date"
              aria-label="From date"
              value={period.since ?? ''}
              max={period.until || undefined}
              onChange={(e) => onChange({ kind: 'custom', since: e.target.value, until: period.until || e.target.value })}
            />
            <span aria-hidden>→</span>
            <input
              type="date"
              aria-label="To date"
              value={period.until ?? ''}
              min={period.since || undefined}
              onChange={(e) => onChange({ kind: 'custom', since: period.since || e.target.value, until: e.target.value })}
            />
          </span>
        )}
      </div>
    </div>
  )
}

function Filters({
  campaigns,
  selectedCampaignId,
  onCampaignChange,
  error,
}: {
  campaigns: LiveCampaign[]
  selectedCampaignId: string
  onCampaignChange: (campaignId: string) => void
  error: string | null
}) {
  const campaignSummary =
    selectedCampaignId === 'all'
      ? 'All campaigns'
      : campaigns.find((campaign) => campaign.id === selectedCampaignId)?.name ?? '1 campaign'

  return (
    <details className="filter-bar" aria-label="Dashboard filters">
      <summary className="filter-summary">
        <SlidersHorizontal size={18} />
        <strong>Campaign</strong>
        <span>{campaignSummary}</span>
      </summary>
      <div className="filter-fields">
        <label>
          Campaign
          <select value={selectedCampaignId} onChange={(event) => onCampaignChange(event.target.value)}>
            <option value="all">All campaigns</option>
            {campaigns.map((campaign) => (
              <option value={campaign.id} key={campaign.id}>
                {campaign.name}
              </option>
            ))}
          </select>
        </label>
      </div>
      {error && <p className="filter-error">{error}</p>}
    </details>
  )
}
