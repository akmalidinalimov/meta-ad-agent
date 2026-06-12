import { useEffect, useMemo, useState, type ChangeEvent } from 'react'
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
import { EmptyState } from './dashboard/shared/EmptyState'
import {
  deriveFunnel,
  deriveTrend,
  filterMetricsForDashboard,
  getCampaignOptions,
  getDateWindow,
} from '../lib/analytics'
import {
  getDashboardAnchorDate,
  labelPlacement,
  labelRawSetting,
  shortCampaignLabel,
} from '../lib/format'
import { getMetaStatus, type MetaStatus } from '../services/metaStatusProvider'
import type { DashboardData, DashboardFilters } from '../types/marketing'

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

const defaultFilters: DashboardFilters = {
  dateRange: '90d',
  campaignIds: ['all'],
  creativeFormat: 'all',
  placement: 'all',
  audience: 'all',
  funnelStage: 'all',
  objective: 'all',
}

export function Dashboard({ data, isRefreshing = false, onRefresh, role = null }: DashboardProps) {
  // Viewers get a read-only console: no Team panel, no write controls.
  // A null role means auth is off (dev) → treat as full access.
  const isManager = role === 'owner' || role === 'admin' || role === null
  const visibleNavItems = visibleNavFor(role)
  const [activeView, setActiveView] = useState<ViewId>('overview')
  const [metaStatus, setMetaStatus] = useState<MetaStatus | null>(null)
  const [filters, setFilters] = useState<DashboardFilters>(defaultFilters)

  const filteredMetrics = useMemo(() => {
    const window = getDateWindow(filters.dateRange, getDashboardAnchorDate(data))
    return filterMetricsForDashboard({
      metrics: data.metrics,
      campaigns: data.campaigns,
      ads: data.ads,
      creatives: data.creatives,
      filters: {
        start: window.start,
        end: window.end,
        campaignIds: filters.campaignIds,
        creativeFormat: filters.creativeFormat,
        placement: filters.placement,
        objective: filters.objective,
      },
    })
  }, [data, filters])
  const funnel = useMemo(() => deriveFunnel(filteredMetrics), [filteredMetrics])
  const trend = useMemo(() => deriveTrend(filteredMetrics), [filteredMetrics])
  const hasData = filteredMetrics.length > 0
  const dataSourceTone = data.dataSource?.kind === 'meta' ? 'good' : 'warning'

  useEffect(() => {
    void getMetaStatus()
      .then(setMetaStatus)
      .catch(() => {
        setMetaStatus(null)
      })
  }, [])

  // Freshness stamp: when this data was loaded, and whether it is live. Keyed to
  // `data` so the timestamp re-stamps on every refresh (no effect → no cascading
  // render). The memo body doesn't read `data`, so exhaustive-deps flags it as
  // "unnecessary" — but that dependency IS the point: it drives the re-stamp.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  const loadedAt = useMemo(() => new Date(), [data])
  const isLive = data.dataSource?.kind === 'meta' && !data.dataSource?.backendUnreachable
  const freshness = `${isLive ? 'data as of' : 'snapshot ·'} ${loadedAt.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', hour12: false })}`

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
            <button className="sync-button secondary" type="button" onClick={() => void onRefresh()} disabled={isRefreshing}>
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

      <Filters data={data} filters={filters} onChange={setFilters} />

      {activeView === 'team' && isManager && <TeamPanel />}

      {/* Empty state is scoped to the data-driven Monitor only, so an over-narrow
          filter never hides Settings (reconnect) or Rankings. */}
      {activeView === 'overview' &&
        (hasData ? (
          <MonitorView metrics={filteredMetrics} trend={trend} funnel={funnel} />
        ) : (
          <EmptyState onReset={() => setFilters(defaultFilters)} />
        ))}
      {activeView === 'rankings' && <RankingsView data={data} metrics={filteredMetrics} />}
      {activeView === 'settings' && <SettingsView data={data} metaStatus={metaStatus} onDashboardRefresh={onRefresh} />}
    </main>
  )
}

function Filters({
  data,
  filters,
  onChange,
}: {
  data: DashboardData
  filters: DashboardFilters
  onChange: (filters: DashboardFilters) => void
}) {
  const update = <K extends keyof DashboardFilters>(key: K, value: DashboardFilters[K]) => {
    const nextFilters = { ...filters, [key]: value }
    if (key === 'dateRange' || key === 'objective') {
      const dateWindow = getDateWindow(nextFilters.dateRange, getDashboardAnchorDate(data))
      const validCampaignIds = new Set(
        getCampaignOptions({
          campaigns: data.campaigns,
          window: dateWindow,
          objective: nextFilters.objective,
        }).map((campaign) => campaign.id),
      )
      const selectedCampaignIds = nextFilters.campaignIds.filter((campaignId) => campaignId !== 'all' && validCampaignIds.has(campaignId))
      nextFilters.campaignIds = selectedCampaignIds.length > 0 ? selectedCampaignIds : ['all']
    }
    onChange(nextFilters)
  }

  const updateCampaignSelection = (selectedValues: string[]) => {
    if (selectedValues.includes('all') || selectedValues.length === 0) {
      update('campaignIds', ['all'])
      return
    }

    update('campaignIds', selectedValues)
  }

  const toggleCampaign = (campaignId: string) => {
    if (campaignId === 'all') {
      update('campaignIds', ['all'])
      return
    }

    const current = filters.campaignIds.includes('all') ? [] : filters.campaignIds
    const next = current.includes(campaignId)
      ? current.filter((selectedId) => selectedId !== campaignId)
      : [...current, campaignId]

    update('campaignIds', next.length > 0 ? next : ['all'])
  }

  const campaignSummary =
    filters.campaignIds.includes('all')
      ? 'All campaigns'
      : `${filters.campaignIds.length} campaign${filters.campaignIds.length === 1 ? '' : 's'} selected`

  const isCampaignSelected = (campaignId: string) =>
    campaignId === 'all' ? filters.campaignIds.includes('all') : filters.campaignIds.includes(campaignId)

  const handleCampaignSelectChange = (event: ChangeEvent<HTMLSelectElement>) => {
    updateCampaignSelection(Array.from(event.target.selectedOptions, (option) => option.value))
  }

  const optionWindow = getDateWindow(filters.dateRange, getDashboardAnchorDate(data))
  // Placement options reflect the active date/campaign/objective context, but NOT the
  // placement selection itself (otherwise picking one placement would hide the others).
  const placementScopedMetrics = filterMetricsForDashboard({
    metrics: data.metrics,
    campaigns: data.campaigns,
    ads: data.ads,
    creatives: data.creatives,
    filters: {
      start: optionWindow.start,
      end: optionWindow.end,
      campaignIds: filters.campaignIds,
      creativeFormat: 'all',
      placement: 'all',
      objective: filters.objective,
    },
  })
  const placements = Array.from(
    new Set([
      ...placementScopedMetrics.map((metric) => metric.placement),
      ...(filters.placement !== 'all' ? [filters.placement] : []),
    ]),
  )
  const campaignOptions = getCampaignOptions({
    campaigns: data.campaigns,
    window: optionWindow,
    objective: filters.objective,
  })

  return (
    <details className="filter-bar" aria-label="Dashboard filters">
      <summary className="filter-summary">
        <SlidersHorizontal size={18} />
        <strong>Filters</strong>
        <span>{labelRawSetting(filters.dateRange)} · {campaignSummary}</span>
      </summary>
      <div className="filter-fields">
        <label>
          Date range
          <select value={filters.dateRange} onChange={(event) => update('dateRange', event.target.value as DashboardFilters['dateRange'])}>
            <option value="7d">Last 7 days</option>
            <option value="30d">Last 30 days</option>
            <option value="90d">Last 90 days</option>
          </select>
        </label>
        <label className="campaign-filter-field">
          Campaigns
          <div className="campaign-selection-summary">
            <span>{campaignSummary}</span>
            {!filters.campaignIds.includes('all') && (
              <button type="button" onClick={() => update('campaignIds', ['all'])}>
                Clear
              </button>
            )}
          </div>
          <div className="campaign-chip-list">
            <button
            type="button"
            className={isCampaignSelected('all') ? 'active' : ''}
            onClick={() => toggleCampaign('all')}
            >
              All
            </button>
            {campaignOptions.slice(0, 8).map((campaign) => (
              <button
                type="button"
                className={isCampaignSelected(campaign.id) ? 'active' : ''}
                onClick={() => toggleCampaign(campaign.id)}
                key={campaign.id}
                title={campaign.name}
              >
                {shortCampaignLabel(campaign.name)}
              </button>
            ))}
          </div>
          <select
            className="campaign-multi-select"
            value={filters.campaignIds}
            multiple
            size={Math.min(4, campaignOptions.length + 1)}
            onChange={handleCampaignSelectChange}
          >
            <option value="all">All campaigns</option>
            {campaignOptions.map((campaign) => (
              <option value={campaign.id} key={campaign.id}>
                {campaign.name}
              </option>
            ))}
          </select>
        </label>
        <label>
          Creative type
          <select value={filters.creativeFormat} onChange={(event) => update('creativeFormat', event.target.value as DashboardFilters['creativeFormat'])}>
            <option value="all">All types</option>
            <option value="video">Video</option>
            <option value="image">Image</option>
            <option value="gif">GIF</option>
            <option value="carousel">Carousel</option>
          </select>
        </label>
        <label>
          Placement
          <select value={filters.placement} onChange={(event) => update('placement', event.target.value as DashboardFilters['placement'])}>
            <option value="all">All placements</option>
            {placements.map((placement) => (
              <option value={placement} key={placement}>
                {labelPlacement(placement)}
              </option>
            ))}
          </select>
        </label>
        <label>
          Objective
          <select value={filters.objective} onChange={(event) => update('objective', event.target.value as DashboardFilters['objective'])}>
            <option value="all">All objectives</option>
            <option value="sales">Sales</option>
            <option value="leads">Leads</option>
            <option value="traffic">Traffic</option>
            <option value="engagement">Engagement</option>
            <option value="awareness">Awareness</option>
          </select>
        </label>
      </div>
    </details>
  )
}
