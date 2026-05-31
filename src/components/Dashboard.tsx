import { useEffect, useMemo, useState, type ChangeEvent, type ComponentType } from 'react'
import {
  AlertTriangle,
  BarChart3,
  BookOpen,
  Bot,
  Send,
  CheckCircle2,
  CircleDollarSign,
  ClipboardCheck,
  Eye,
  Film,
  FlaskConical,
  Gauge,
  LayoutDashboard,
  ListChecks,
  MousePointerClick,
  RadioTower,
  RefreshCcw,
  Settings,
  ShieldAlert,
  SlidersHorizontal,
  Target,
  TrendingDown as TrendingDownIcon,
  TrendingUp,
  Users,
  XCircle,
} from 'lucide-react'
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Line,
  LineChart,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import {
  deriveCreativeScores,
  deriveFunnel,
  derivePlacementScores,
  deriveRankingRows,
  deriveTrend,
  filterMetricsForDashboard,
  formatNumber,
  getCampaignOptions,
  getDateWindow,
} from '../lib/analytics'
import {
  buildEmptySegment,
  buildPlaybookDraft,
  parseCsvList,
  summarizePlaybookReadiness,
} from '../lib/playbookBuilder'
import { askAgent } from '../services/agentChatProvider'
import { createAgentTask, getAgentCommandCenter } from '../services/agentTaskProvider'
import { getMetaStatus, type MetaStatus } from '../services/metaStatusProvider'
import type {
  AgentSpec,
  AgentTask,
  CampaignPlaybook,
  CampaignPlaybookSegment,
  ApprovalRequest,
  Creative,
  DashboardData,
  DashboardFilters,
  DashboardKpi,
  DailyAdMetric,
  FunnelEventSummary,
  IconName,
  LaunchStrategy,
  MetaSnapshot,
  MetaSettingsAudit,
  Placement,
  RankingRow,
  TrackingHealthItem,
  Tone,
} from '../types/marketing'

const COLORS = ['#1f9d8a', '#3b82f6', '#f59e0b', '#ef4444', '#7c3aed', '#0f766e']

const iconMap: Record<IconName, ComponentType<{ size?: number }>> = {
  alert: AlertTriangle,
  bot: Bot,
  check: CheckCircle2,
  dollar: CircleDollarSign,
  target: Target,
  trendingDown: TrendingDownIcon,
  users: Users,
}

const navItems = [
  { id: 'overview', label: 'Overview', icon: LayoutDashboard },
  { id: 'commandCenter', label: 'Command Center', icon: Bot },
  { id: 'rankings', label: 'Rankings', icon: BarChart3 },
  { id: 'creatives', label: 'Creatives', icon: Film },
  { id: 'funnel', label: 'Funnel', icon: MousePointerClick },
  { id: 'audiences', label: 'Audiences', icon: Users },
  { id: 'placements', label: 'Placements', icon: RadioTower },
  { id: 'experiments', label: 'Experiments', icon: FlaskConical },
  { id: 'campaignBuilder', label: 'Campaign Builder', icon: ClipboardCheck },
  { id: 'strategy', label: 'Strategy', icon: Target },
  { id: 'settingsAudit', label: 'Settings Audit', icon: ClipboardCheck },
  { id: 'tracking', label: 'Tracking Health', icon: ShieldAlert },
  { id: 'alerts', label: 'Alerts', icon: AlertTriangle },
  { id: 'settings', label: 'Settings', icon: Settings },
] as const

type ViewId = (typeof navItems)[number]['id']

interface DashboardProps {
  data: DashboardData
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

export function Dashboard({ data }: DashboardProps) {
  const [activeView, setActiveView] = useState<ViewId>('overview')
  const [selectedCreativeId, setSelectedCreativeId] = useState(data.creatives[0]?.id ?? '')
  const [metaStatus, setMetaStatus] = useState<MetaStatus | null>(null)
  const [chatMessages, setChatMessages] = useState<ChatMessage[]>([
    {
      id: 'initial-agent-message',
      role: 'agent',
      content: 'Ask me about creatives, placements, audiences, funnel leaks, experiments, or Meta connection status.',
      sources: ['agent'],
    },
  ])
  const [chatInput, setChatInput] = useState('')
  const [isChatLoading, setIsChatLoading] = useState(false)
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
        campaignIds: filters.campaignIds,
        creativeFormat: filters.creativeFormat,
        placement: filters.placement,
        objective: filters.objective,
      },
    })
  }, [data, filters])
  const filteredCreatives = useMemo(
    () => filterCreatives(data.creatives, filteredMetrics, filters),
    [data.creatives, filteredMetrics, filters],
  )
  const creativeScores = useMemo(
    () => deriveCreativeScores(filteredMetrics, filteredCreatives, data.creativeAnalyses),
    [data.creativeAnalyses, filteredCreatives, filteredMetrics],
  )
  const filteredKpis = useMemo(
    () => deriveFilteredKpis(filteredMetrics, data.trackingHealth),
    [data.trackingHealth, filteredMetrics],
  )
  const funnel = useMemo(() => deriveFunnel(filteredMetrics), [filteredMetrics])
  const trend = useMemo(() => deriveTrend(filteredMetrics), [filteredMetrics])
  const placements = useMemo(
    () => (filters.placement === 'all' && data.dataSource?.kind === 'meta' ? data.placements : derivePlacementScores(filteredMetrics)),
    [data.dataSource?.kind, data.placements, filters.placement, filteredMetrics],
  )
  const selectedCreative = filteredCreatives.find((creative) => creative.id === selectedCreativeId) ?? filteredCreatives[0]

  const hasData = filteredMetrics.length > 0
  const dataSourceTone = data.dataSource?.kind === 'meta' ? 'good' : 'warning'

  const sendChatMessage = async (message: string) => {
    const cleanMessage = message.trim()
    if (!cleanMessage || isChatLoading) {
      return
    }

    setChatInput('')
    setIsChatLoading(true)
    setChatMessages((current) => [...current, { id: makeMessageId(), role: 'user', content: cleanMessage }])

    try {
      const response = await askAgent(cleanMessage)
      setChatMessages((current) => [
        ...current,
        {
          id: makeMessageId(),
          role: 'agent',
          content: response.answer,
          sources: response.sources,
          suggestedQuestions: response.suggestedQuestions,
          activeAgent: response.activeAgent ?? undefined,
          routeReason: response.routeReason ?? undefined,
        },
      ])
    } catch {
      setChatMessages((current) => [
        ...current,
        {
          id: makeMessageId(),
          role: 'agent',
          content: 'I could not reach the agent endpoint. Make sure the backend is running on port 8000.',
          sources: ['error'],
        },
      ])
    } finally {
      setIsChatLoading(false)
    }
  }

  useEffect(() => {
    void getMetaStatus()
      .then(setMetaStatus)
      .catch(() => {
        setMetaStatus(null)
      })
  }, [])

  return (
    <main className="app-shell">
      <header className="topbar">
        <div>
          <p className="eyebrow">Meta Ad Agent</p>
          <h1>Campaign Audit Dashboard</h1>
        </div>
        <div className={`status-pill ${dataSourceTone}`}>
          {data.dataSource?.kind === 'meta' ? <CheckCircle2 size={16} /> : <AlertTriangle size={16} />}
          {data.dataSource?.label ?? 'Dashboard data loaded'}
        </div>
      </header>

      <nav className="app-nav" aria-label="Dashboard sections">
        {navItems.map((item) => {
          const Icon = item.icon
          return (
            <button
              type="button"
              className={activeView === item.id ? 'active' : ''}
              onClick={() => setActiveView(item.id)}
              key={item.id}
            >
              <Icon size={16} />
              <span>{item.label}</span>
            </button>
          )
        })}
      </nav>

      <Filters data={data} filters={filters} onChange={setFilters} />

      {!hasData ? (
        <EmptyState onReset={() => setFilters(defaultFilters)} />
      ) : (
        <>
          {activeView === 'overview' && (
            <Overview
              data={data}
              kpis={filteredKpis}
              creativeScores={creativeScores}
              funnel={funnel}
              trend={trend}
              placements={placements}
            />
          )}
          {activeView === 'commandCenter' && <CommandCenterView data={data} />}
          {activeView === 'rankings' && <RankingsView data={data} metrics={filteredMetrics} />}
          {activeView === 'creatives' && (
            <CreativesView
              data={data}
              creativeScores={creativeScores}
              selectedCreative={selectedCreative}
              onSelectCreative={setSelectedCreativeId}
            />
          )}
          {activeView === 'funnel' && <FunnelView funnel={funnel} trend={trend} />}
          {activeView === 'audiences' && <AudiencesView data={data} />}
          {activeView === 'placements' && <PlacementsView placements={placements} />}
          {activeView === 'experiments' && <ExperimentsView data={data} />}
          {activeView === 'campaignBuilder' && <CampaignBuilderView />}
          {activeView === 'strategy' && <StrategyView />}
          {activeView === 'settingsAudit' && <SettingsAuditView />}
          {activeView === 'tracking' && <TrackingView data={data} />}
          {activeView === 'alerts' && <AlertsView data={data} />}
          {activeView === 'settings' && <SettingsView data={data} metaStatus={metaStatus} />}
        </>
      )}

      <AgentChatPanel
        messages={chatMessages}
        input={chatInput}
        isLoading={isChatLoading}
        onInputChange={setChatInput}
        onSend={sendChatMessage}
      />
    </main>
  )
}

interface ChatMessage {
  id: string
  role: 'user' | 'agent'
  content: string
  sources?: string[]
  suggestedQuestions?: string[]
  activeAgent?: string
  routeReason?: string
}

function makeMessageId() {
  return `${Date.now()}-${Math.random().toString(16).slice(2)}`
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

  const placements = Array.from(new Set(data.metrics.map((metric) => metric.placement)))
  const campaignOptions = getCampaignOptions({
    campaigns: data.campaigns,
    window: getDateWindow(filters.dateRange, getDashboardAnchorDate(data)),
    objective: filters.objective,
  })

  return (
    <section className="filter-bar" aria-label="Dashboard filters">
      <div className="filter-title">
        <SlidersHorizontal size={18} />
        <strong>Filters</strong>
      </div>
      <label>
        Date range
        <select value={filters.dateRange} onChange={(event) => update('dateRange', event.target.value as DashboardFilters['dateRange'])}>
          <option value="7d">Last 7 days</option>
          <option value="30d">Last 30 days</option>
          <option value="90d">Last 90 days</option>
        </select>
      </label>
      <label>
        Campaigns
        <select
          className="campaign-multi-select"
          value={filters.campaignIds}
          multiple
          size={Math.min(5, campaignOptions.length + 1)}
          onChange={handleCampaignSelectChange}
        >
          <option value="all">All campaigns</option>
          {campaignOptions.map((campaign) => (
            <option value={campaign.id} key={campaign.id}>
              {campaign.name}
            </option>
          ))}
        </select>
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
    </section>
  )
}

function AgentChatPanel({
  messages,
  input,
  isLoading,
  onInputChange,
  onSend,
}: {
  messages: ChatMessage[]
  input: string
  isLoading: boolean
  onInputChange: (value: string) => void
  onSend: (message: string) => void
}) {
  const latestSuggestions = messages
    .slice()
    .reverse()
    .find((message) => message.suggestedQuestions?.length)?.suggestedQuestions

  return (
    <section className="agent-chat-shell" aria-label="Agent chat">
      <div className="agent-chat-header">
        <div>
          <p className="eyebrow">Agent Chat</p>
          <h2>Ask about your ads</h2>
        </div>
        <Bot size={20} />
      </div>

      <div className="agent-chat-messages">
        {messages.map((message) => (
          <div className={`chat-message ${message.role}`} key={message.id}>
            <p>{message.content}</p>
            {message.activeAgent && <small>Agent: {labelRawSetting(message.activeAgent)}{message.routeReason ? ` · ${message.routeReason}` : ''}</small>}
            {message.sources && message.sources.length > 0 && (
              <small>Sources: {message.sources.join(', ')}</small>
            )}
          </div>
        ))}
        {isLoading && (
          <div className="chat-message agent">
            <p>Thinking through the ad data...</p>
          </div>
        )}
      </div>

      {latestSuggestions && (
        <div className="chat-suggestions">
          {latestSuggestions.map((suggestion) => (
            <button type="button" onClick={() => onSend(suggestion)} disabled={isLoading} key={suggestion}>
              {suggestion}
            </button>
          ))}
        </div>
      )}

      <form
        className="chat-input-row"
        onSubmit={(event) => {
          event.preventDefault()
          onSend(input)
        }}
      >
        <input
          value={input}
          onChange={(event) => onInputChange(event.target.value)}
          placeholder="Ask: which creative should we scale?"
        />
        <button type="submit" disabled={isLoading || !input.trim()} aria-label="Send message">
          <Send size={17} />
        </button>
      </form>
    </section>
  )
}

function Overview({
  data,
  kpis,
  creativeScores,
  funnel,
  trend,
  placements,
}: {
  data: DashboardData
  kpis: DashboardKpi[]
  creativeScores: ReturnType<typeof deriveCreativeScores>
  funnel: ReturnType<typeof deriveFunnel>
  trend: ReturnType<typeof deriveTrend>
  placements: ReturnType<typeof derivePlacementScores>
}) {
  return (
    <>
      <KpiGrid kpis={kpis} />
      <section className="dashboard-grid">
        <FunnelPanel funnel={funnel} />
        <TrendPanel trend={trend} />
        <TopProblemsPanel data={data} />
        <CreativeTablePanel creativeScores={creativeScores} />
        <PlacementPanel placements={placements} />
        <AudiencePanel data={data} />
        <SpendPanel trend={trend} />
      </section>
      <section className="bottom-grid">
        <InsightsPanel data={data} />
        <ApprovalQueue data={data} />
      </section>
    </>
  )
}

function KpiGrid({ kpis }: { kpis: DashboardKpi[] }) {
  return (
    <section className="kpi-grid" aria-label="Campaign summary">
      {kpis.map((kpi) => {
        const Icon = iconMap[kpi.icon]
        return (
          <article className={`metric-card ${kpi.tone}`} key={kpi.label}>
            <div className="metric-icon">
              <Icon size={20} />
            </div>
            <div>
              <p>{kpi.label}</p>
              <strong>{kpi.value}</strong>
              <span>{kpi.change}</span>
              <small>{kpi.helper}</small>
            </div>
          </article>
        )
      })}
    </section>
  )
}

function FunnelPanel({ funnel }: { funnel: ReturnType<typeof deriveFunnel> }) {
  return (
    <article className="panel panel-wide">
      <PanelHeading eyebrow="Funnel" title="Meta click to course buyer path" icon={MousePointerClick} />
      <div className="funnel-list">
        {funnel.map((item, index) => (
          <div className="funnel-row" key={item.step}>
            <div>
              <span>{item.step}</span>
              <strong>{formatNumber(item.value)}</strong>
            </div>
            <div className="funnel-track">
              <div className="funnel-fill" style={{ width: `${Math.max(7, 100 - index * 13)}%` }} />
            </div>
            <em>{item.rate}</em>
          </div>
        ))}
      </div>
    </article>
  )
}

function TrendPanel({ trend }: { trend: ReturnType<typeof deriveTrend> }) {
  return (
    <article className="panel">
      <PanelHeading eyebrow="Trend" title="Spend, leads, buyers" icon={TrendingUp} />
      <div className="chart-box">
        <ResponsiveContainer width="100%" height="100%" minWidth={0} minHeight={0} initialDimension={{ width: 640, height: 268 }}>
          <LineChart data={trend}>
            <CartesianGrid strokeDasharray="3 3" vertical={false} />
            <XAxis dataKey="day" tickLine={false} axisLine={false} />
            <YAxis tickLine={false} axisLine={false} />
            <Tooltip />
            <Line type="monotone" dataKey="leads" stroke="#1f9d8a" strokeWidth={3} dot={false} />
            <Line type="monotone" dataKey="buyers" stroke="#ef4444" strokeWidth={3} dot={false} />
          </LineChart>
        </ResponsiveContainer>
      </div>
    </article>
  )
}

function TopProblemsPanel({ data }: { data: DashboardData }) {
  return (
    <article className="panel">
      <PanelHeading eyebrow="Top Problems Today" title="Priority watchlist" icon={AlertTriangle} />
      <div className="problem-list">
        {data.insights.map((insight) => {
          const Icon = iconMap[insight.icon]
          return (
            <div className={`problem-item ${insight.tone}`} key={insight.title}>
              <Icon size={18} />
              <div>
                <strong>{insight.title}</strong>
                <p>{insight.body}</p>
              </div>
            </div>
          )
        })}
      </div>
    </article>
  )
}

function CreativeTablePanel({ creativeScores }: { creativeScores: ReturnType<typeof deriveCreativeScores> }) {
  return (
    <article className="panel panel-wide">
      <PanelHeading eyebrow="Creative Intelligence" title="Top creatives by quality score" icon={Film} />
      <CreativeTable creativeScores={creativeScores} />
    </article>
  )
}

function CreativeTable({
  creativeScores,
  onSelect,
}: {
  creativeScores: ReturnType<typeof deriveCreativeScores>
  onSelect?: (id: string) => void
}) {
  return (
    <div className="creative-table">
      <div className="table-head">
        <span>Rank</span>
        <span>Creative</span>
        <span>Clicks</span>
        <span>Leads</span>
        <span>Buyers</span>
        <span>Viral</span>
        <span>Intent</span>
        <span>Quality</span>
        <span>Action</span>
      </div>
      {creativeScores.map((creative) => (
        <button className="table-row" type="button" onClick={() => onSelect?.(creative.id)} key={creative.id}>
          <span>#{creative.rank}</span>
          <div className="creative-cell">
            <MediaThumb assetUrl={creative.assetUrl} videoUrl={creative.videoUrl} videoId={creative.videoId} format={creative.format} />
            <div>
              <strong>{creative.name}</strong>
              <small>{creative.type} / {creative.format}</small>
            </div>
          </div>
          <span>{formatNumber(creative.clicks)}</span>
          <span>{formatNumber(creative.leads)}</span>
          <span>{creative.buyers}</span>
          <span>{creative.viral}</span>
          <span>{creative.intent}</span>
          <span>{creative.quality}</span>
          <em className={creative.tone}>{creative.action}</em>
        </button>
      ))}
    </div>
  )
}

function PlacementPanel({ placements }: { placements: ReturnType<typeof derivePlacementScores> }) {
  return (
    <article className="panel">
      <PanelHeading eyebrow="Placement" title="Spend share by channel" icon={RadioTower} />
      <div className="chart-box">
        <ResponsiveContainer width="100%" height="100%" minWidth={0} minHeight={0} initialDimension={{ width: 640, height: 268 }}>
          <PieChart>
            <Pie data={placements} dataKey="value" nameKey="name" innerRadius={58} outerRadius={88}>
              {placements.map((entry, index) => (
                <Cell key={entry.name} fill={COLORS[index % COLORS.length]} />
              ))}
            </Pie>
            <Tooltip />
          </PieChart>
        </ResponsiveContainer>
      </div>
      <ChartLegend placements={placements} />
    </article>
  )
}

function ChartLegend({ placements }: { placements: ReturnType<typeof derivePlacementScores> }) {
  return (
    <div className="legend-list">
      {placements.map((item, index) => (
        <span key={item.name}>
          <i style={{ background: COLORS[index % COLORS.length] }} />
          {item.name}: {item.value}%
        </span>
      ))}
    </div>
  )
}

function AudiencePanel({ data }: { data: DashboardData }) {
  return (
    <article className="panel panel-wide">
      <PanelHeading eyebrow="Audience Quality" title="Purchasing power by segment" icon={Users} />
      <div className="chart-box tall">
        <ResponsiveContainer width="100%" height="100%" minWidth={0} minHeight={0} initialDimension={{ width: 720, height: 318 }}>
          <BarChart data={data.audience}>
            <CartesianGrid strokeDasharray="3 3" vertical={false} />
            <XAxis dataKey="segment" tickLine={false} axisLine={false} />
            <YAxis tickLine={false} axisLine={false} />
            <Tooltip />
            <Bar dataKey="subs" fill="#3b82f6" radius={[5, 5, 0, 0]} />
            <Bar dataKey="buyers" fill="#1f9d8a" radius={[5, 5, 0, 0]} />
          </BarChart>
        </ResponsiveContainer>
      </div>
    </article>
  )
}

function SpendPanel({ trend }: { trend: ReturnType<typeof deriveTrend> }) {
  return (
    <article className="panel">
      <PanelHeading eyebrow="Spend Curve" title="Budget pressure" icon={CircleDollarSign} />
      <div className="chart-box">
        <ResponsiveContainer width="100%" height="100%" minWidth={0} minHeight={0} initialDimension={{ width: 640, height: 268 }}>
          <AreaChart data={trend}>
            <CartesianGrid strokeDasharray="3 3" vertical={false} />
            <XAxis dataKey="day" tickLine={false} axisLine={false} />
            <YAxis tickLine={false} axisLine={false} />
            <Tooltip />
            <Area type="monotone" dataKey="spend" stroke="#7c3aed" fill="#ddd6fe" strokeWidth={3} />
          </AreaChart>
        </ResponsiveContainer>
      </div>
    </article>
  )
}

function CreativesView({
  data,
  creativeScores,
  selectedCreative,
  onSelectCreative,
}: {
  data: DashboardData
  creativeScores: ReturnType<typeof deriveCreativeScores>
  selectedCreative?: Creative
  onSelectCreative: (id: string) => void
}) {
  const analysis = data.creativeAnalyses.find((item) => item.creativeId === selectedCreative?.id)
  const score = creativeScores.find((item) => item.id === selectedCreative?.id)

  return (
    <section className="detail-layout">
      <article className="panel panel-wide">
        <PanelHeading eyebrow="Creative Library" title="Creative performance and quality" icon={Film} />
        <CreativeTable creativeScores={creativeScores} onSelect={onSelectCreative} />
      </article>

      <article className="panel detail-panel">
        <PanelHeading eyebrow="Creative Detail" title={selectedCreative?.name ?? 'No creative selected'} icon={Eye} />
        {selectedCreative && score ? (
          <>
            <CreativePreview creative={selectedCreative} />
            <div className="score-grid">
              <Score label="Viral" value={analysis?.viralScore ?? score.viral} tone="neutral" />
              <Score label="Intent" value={analysis?.buyerIntentScore ?? score.intent} tone={score.intent >= 70 ? 'good' : 'warning'} />
              <Score label="Course fit" value={analysis?.courseFitScore ?? score.courseFit} tone="good" />
              <Score
                label="Purchasing power"
                value={analysis?.purchasingPowerScore ?? score.quality}
                tone={(analysis?.purchasingPowerScore ?? score.quality) >= 70 ? 'good' : 'warning'}
              />
              <Score
                label="Funnel quality"
                value={analysis?.funnelQualityScore ?? score.quality}
                tone={(analysis?.funnelQualityScore ?? score.quality) >= 70 ? 'good' : 'warning'}
              />
            </div>
            <div className="analysis-block">
              <strong>Why it worked</strong>
              <p>{analysis?.whyItWorked ?? 'This ranking is estimated from Meta performance data until deep video analysis is available.'}</p>
            </div>
            <div className="analysis-block">
              <strong>Why it did not convert</strong>
              <p>{analysis?.whyItDidNotConvert ?? 'Purchase tracking is missing or too sparse, so conversion quality needs downstream validation.'}</p>
            </div>
            <div className="scene-list">
              {(analysis?.sceneNotes ?? [
                'Use Gemini/video analysis next to inspect hook, pacing, offer clarity, and visual pattern.',
                'Compare this creative against landing-page leads, Telegram joins, webinar attendance, and purchases.',
              ]).map((note) => (
                <span key={note}>{note}</span>
              ))}
            </div>
          </>
        ) : (
          <EmptyState compact />
        )}
      </article>
    </section>
  )
}

function CommandCenterView({ data }: { data: DashboardData }) {
  const [tasks, setTasks] = useState<AgentTask[]>([])
  const [agents, setAgents] = useState<AgentSpec[]>([])
  const [command, setCommand] = useState('Create a campaign with 3 VSLs: income, business automation, content creators. Use $100 each and optimize for Telegram START.')
  const [source, setSource] = useState<'dashboard' | 'telegram' | 'codex'>('dashboard')
  const [campaignGroupId, setCampaignGroupId] = useState('next-launch')
  const [segmentIds, setSegmentIds] = useState('income, business, creators')
  const [prepareApproval, setPrepareApproval] = useState(false)
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [isSendingTelegramTest, setIsSendingTelegramTest] = useState(false)
  const [message, setMessage] = useState<string | null>(null)

  const loadCommandCenter = async () => {
    const result = await getAgentCommandCenter()
    setTasks(result.tasks)
    setAgents(result.agents)
  }

  useEffect(() => {
    let cancelled = false
    void getAgentCommandCenter()
      .then((result) => {
        if (!cancelled) {
          setTasks(result.tasks)
          setAgents(result.agents)
        }
      })
      .catch(() => {
        if (!cancelled) {
          setMessage('Could not load the command center. Make sure the backend is running.')
        }
      })
    return () => {
      cancelled = true
    }
  }, [])

  const submitTask = async () => {
    if (!command.trim() || isSubmitting) {
      return
    }

    setIsSubmitting(true)
    setMessage('Sending command to the orchestrator...')
    try {
      const result = await createAgentTask({
        source,
        command,
        campaignGroupId: campaignGroupId.trim() || undefined,
        segmentIds: parseCsvList(segmentIds),
        prepareApproval,
      })
      setTasks((current) => [result.task, ...current.filter((task) => task.id !== result.task.id)])
      setMessage(
        result.task.approvalId
          ? 'Task planned and approval request created. It will still not publish or spend.'
          : 'Task planned. Review the plan before turning it into an approval request.',
      )
      await loadCommandCenter()
    } catch {
      setMessage('Could not create the task. Check the backend task endpoint.')
    } finally {
      setIsSubmitting(false)
    }
  }

  const recentCampaigns = data.campaigns.slice(0, 8)
  const approvalAgents = agents.filter((agent) => agent.requiresApproval).length
  const pendingTasks = tasks.filter((task) => task.status === 'planning' || task.status === 'needs_approval').length

  const sendTelegramTest = async () => {
    if (isSendingTelegramTest) {
      return
    }

    setIsSendingTelegramTest(true)
    setMessage('Sending Telegram test message...')
    try {
      const response = await fetch('/api/telegram/test-message', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: 'Meta Agent Telegram test: outbound messages are connected.' }),
      })
      const result = (await response.json()) as { telegram?: { ok?: boolean; error?: string } }
      setMessage(result.telegram?.ok ? 'Telegram test message sent.' : result.telegram?.error ?? `Telegram test failed with ${response.status}`)
    } catch {
      setMessage('Could not reach the Telegram test endpoint.')
    } finally {
      setIsSendingTelegramTest(false)
    }
  }

  return (
    <section className="dashboard-grid">
      <article className="panel panel-wide">
        <PanelHeading eyebrow="Command Center" title="Give work to the orchestrator" icon={Bot} />
        <div className="command-grid">
          <label className="command-field-wide">
            <span>Command</span>
            <textarea value={command} onChange={(event) => setCommand(event.target.value)} />
          </label>
          <label>
            <span>Input source</span>
            <select value={source} onChange={(event) => setSource(event.target.value as typeof source)}>
              <option value="dashboard">Dashboard</option>
              <option value="telegram">Telegram bot</option>
              <option value="codex">Codex chat</option>
            </select>
          </label>
          <label>
            <span>Campaign group ID</span>
            <input value={campaignGroupId} onChange={(event) => setCampaignGroupId(event.target.value)} />
          </label>
          <label>
            <span>Segment / VSL IDs</span>
            <input value={segmentIds} onChange={(event) => setSegmentIds(event.target.value)} />
          </label>
        </div>
        <div className="command-actions">
          <label className="approval-toggle">
            <input
              type="checkbox"
              checked={prepareApproval}
              onChange={(event) => setPrepareApproval(event.target.checked)}
            />
            <span>Create approval request if campaign plan is complete</span>
          </label>
          <button className="sync-button" type="button" onClick={submitTask} disabled={isSubmitting || !command.trim()}>
            <Send size={16} />
            {isSubmitting ? 'Planning...' : 'Send command'}
          </button>
          {message && <small className="sync-message">{message}</small>}
        </div>
      </article>

      <article className="panel">
        <PanelHeading eyebrow="Task Queue" title="Recent orchestrator work" icon={ListChecks} />
        <div className="builder-summary command-summary">
          <MiniMetric label="Tasks" value={tasks.length.toString()} />
          <MiniMetric label="Pending" value={pendingTasks.toString()} />
          <MiniMetric label="Agents" value={agents.length.toString()} />
          <MiniMetric label="Approval agents" value={approvalAgents.toString()} />
        </div>
        <div className="task-list">
          {tasks.length > 0 ? tasks.slice(0, 8).map((task) => (
            <div className={`task-item ${task.status}`} key={task.id}>
              <div>
                <strong>{task.requestedAction || 'Untitled task'}</strong>
                <p>{task.plan?.answer ? shortText(task.plan.answer, 180) : 'The orchestrator has captured this task.'}</p>
                <small>{task.source} / {task.activeAgent ?? 'orchestrator'} / {formatDateTime(task.updatedAt)}</small>
                {task.approvalId && <small>Approval: {task.approvalId}</small>}
                {task.approvalStatus && <small>Approval status: {labelRawSetting(task.approvalStatus)}</small>}
                {task.approvalDecision?.rejectionReason && <small>Rejected: {task.approvalDecision.rejectionReason}</small>}
                {task.approvalDecision?.changeRequestNote && <small>Needs changes: {task.approvalDecision.changeRequestNote}</small>}
              </div>
              <span>{labelRawSetting(task.status)}</span>
            </div>
          )) : (
            <EmptyState compact />
          )}
        </div>
      </article>

      <article className="panel">
        <PanelHeading eyebrow="Agent Availability" title="Specialists and execution safety" icon={ShieldAlert} />
        <div className="agent-status-grid">
          {agents.map((agent) => (
            <div className={`agent-status-card ${agentStatusTone(agent)}`} key={agent.id}>
              <div>
                <strong>{agent.name}</strong>
                <p>{agent.purpose}</p>
              </div>
              <span>{agent.requiresApproval ? 'Approval required' : 'Analysis ready'}</span>
            </div>
          ))}
          {agents.length === 0 && <EmptyState compact />}
        </div>
      </article>

      <article className="panel panel-wide">
        <PanelHeading eyebrow="Campaign Mapping" title="Connect Meta campaigns to reusable launch groups" icon={Target} />
        <div className="campaign-map-grid">
          <div className="mapping-note">
            <strong>Mapping rule</strong>
            <p>
              Use a stable campaign group ID plus segment/VSL IDs. The same structure works for one VSL, three VSLs, or five VSLs later.
            </p>
          </div>
          {recentCampaigns.map((campaign) => (
            <div className="campaign-map-row" key={campaign.id}>
              <strong>{campaign.name}</strong>
              <span>{campaign.id}</span>
              <small>{campaign.objective} / {campaign.status} / {formatCurrency(campaign.dailyBudgetUsd)}/day</small>
            </div>
          ))}
        </div>
      </article>

      <article className="panel panel-wide">
        <PanelHeading eyebrow="Telegram Control" title="Bot command wiring" icon={Bot} />
        <div className="telegram-command-grid">
          <div>
            <strong>Command webhook</strong>
            <code>POST /api/telegram/command</code>
            <p>Send Telegram message updates here to create orchestrator tasks from bot commands.</p>
          </div>
          <div>
            <strong>Shared secret</strong>
            <code>x-telegram-agent-secret</code>
            <p>Set `TELEGRAM_COMMAND_SECRET` in the backend and send the same value in this header.</p>
          </div>
          <div>
            <strong>Approval button data</strong>
            <code>approve:approval_id</code>
            <p>Approval buttons can approve a request, but publishing or spend still needs the execution endpoint and guardrails.</p>
          </div>
        </div>
        <div className="command-actions">
          <button className="sync-button secondary" type="button" onClick={sendTelegramTest} disabled={isSendingTelegramTest}>
            <Send size={16} />
            {isSendingTelegramTest ? 'Sending...' : 'Send test message'}
          </button>
        </div>
      </article>
    </section>
  )
}

function agentStatusTone(agent: AgentSpec) {
  if (agent.canExecuteLiveChanges) {
    return 'danger'
  }
  return agent.requiresApproval ? 'warning' : 'good'
}

function RankingsView({ data, metrics }: { data: DashboardData; metrics: DailyAdMetric[] }) {
  const campaignRankings = deriveRankingRows(
    metrics,
    data.campaigns.map((campaign) => ({
      id: campaign.id,
      name: campaign.name,
      category: 'campaign',
      metricIds: new Set([campaign.id]),
    })),
  )
  const creativeRankings = deriveRankingRows(
    metrics,
    data.creatives.map((creative) => ({
      id: creative.id,
      name: creative.name,
      category: 'creative',
      metricIds: new Set([creative.id]),
    })),
  )
  const audienceRankings = deriveRankingRows(
    metrics,
    data.adSets.map((adSet) => ({
      id: adSet.id,
      name: adSet.name,
      category: 'audience',
      metricIds: new Set([adSet.id]),
    })),
  )
  const placementRankings = deriveRankingRows(
    metrics,
    Array.from(new Set(metrics.map((metric) => metric.placement))).map((placement) => ({
      id: placement,
      name: labelPlacement(placement),
      category: 'placement',
      metricIds: new Set([placement]),
    })),
  )

  return (
    <section className="rankings-grid">
      <RankingPanel title="Campaign Ranking" rows={campaignRankings} />
      <RankingPanel title="Creative Ranking" rows={creativeRankings} />
      <RankingPanel title="Audience / Ad Set Ranking" rows={audienceRankings} />
      <RankingPanel title="Placement Ranking" rows={placementRankings} />
    </section>
  )
}

function RankingPanel({ title, rows }: { title: string; rows: RankingRow[] }) {
  return (
    <article className="panel panel-wide">
      <PanelHeading eyebrow="Quality-adjusted" title={title} icon={BarChart3} />
      {rows.length > 0 ? <RankingTable rows={rows.slice(0, 12)} /> : <EmptyState compact />}
    </article>
  )
}

function RankingTable({ rows }: { rows: RankingRow[] }) {
  return (
    <div className="ranking-table">
      <div className="ranking-head">
        <span>Rank</span>
        <span>Name</span>
        <span>Spend</span>
        <span>Leads</span>
        <span>Bot starts</span>
        <span>Buyers</span>
        <span>Quality</span>
        <span>Action</span>
      </div>
      {rows.map((row) => (
        <div className="ranking-row" key={`${row.category}-${row.id}`}>
          <span>#{row.rank}</span>
          <strong title={row.name}>{row.name}</strong>
          <span>{formatCurrency(row.spendUsd)}</span>
          <span>{formatNumber(row.leads)}</span>
          <span>{formatNumber(row.telegramSubscribers)}</span>
          <span>{formatNumber(row.purchases)}</span>
          <em className={row.tone}>{row.qualityScore}</em>
          <small>{row.recommendedAction}</small>
        </div>
      ))}
    </div>
  )
}

function MediaThumb({
  assetUrl,
  videoUrl,
  videoId,
  format,
}: {
  assetUrl?: string
  videoUrl?: string
  videoId?: string
  format: Creative['format']
}) {
  const hasPlayableVideo = Boolean(videoUrl)

  return (
    <span className={`creative-thumb ${assetUrl ? 'has-image' : ''}`} aria-label={`${format} creative preview`}>
      {assetUrl ? <img src={assetUrl} alt="" loading="lazy" /> : <Film size={18} />}
      {hasPlayableVideo && <i aria-label="Playable video">▶</i>}
      {!hasPlayableVideo && videoId && <span title="Video ID exists, but source URL is unavailable">ID</span>}
      {!assetUrl && <small>{format}</small>}
    </span>
  )
}

function CreativePreview({ creative }: { creative: Creative }) {
  const [videoAsset, setVideoAsset] = useState<{ creativeId: string; videoUrl?: string; posterUrl?: string } | null>(null)
  const fetchedAsset = videoAsset?.creativeId === creative.id ? videoAsset : null
  const resolvedVideoUrl = creative.videoUrl ?? fetchedAsset?.videoUrl ?? ''
  const resolvedPosterUrl = creative.assetUrl ?? fetchedAsset?.posterUrl ?? ''

  useEffect(() => {
    if (!creative.videoId || creative.videoUrl) {
      return
    }

    let cancelled = false
    void fetch(`/api/meta/video/${creative.videoId}`)
      .then((response) => (response.ok ? response.json() : null))
      .then((payload: { videoUrl?: string; posterUrl?: string } | null) => {
        if (cancelled || !payload) {
          return
        }
        setVideoAsset({ creativeId: creative.id, videoUrl: payload.videoUrl, posterUrl: payload.posterUrl })
      })
      .catch(() => undefined)

    return () => {
      cancelled = true
    }
  }, [creative.assetUrl, creative.id, creative.videoId, creative.videoUrl])

  return (
    <div className={resolvedPosterUrl || resolvedVideoUrl ? 'creative-preview has-media' : 'creative-preview'}>
      {resolvedVideoUrl ? (
        <video controls poster={resolvedPosterUrl} src={resolvedVideoUrl} />
      ) : resolvedPosterUrl ? (
        <img src={resolvedPosterUrl} alt={creative.name} />
      ) : (
        <div>
          <Film size={24} />
          <strong>No media preview available</strong>
          <span>Meta returned metadata but no playable source URL.</span>
        </div>
      )}
      <div>
        <strong>{creative.format.toUpperCase()}</strong>
        <span>
          {resolvedVideoUrl
            ? creative.hookType
            : creative.videoId
              ? `${creative.hookType} / video source unavailable`
              : creative.hookType}
        </span>
      </div>
    </div>
  )
}

function FunnelView({ funnel, trend }: { funnel: ReturnType<typeof deriveFunnel>; trend: ReturnType<typeof deriveTrend> }) {
  return (
    <section className="dashboard-grid">
      <FunnelPanel funnel={funnel} />
      <TrendPanel trend={trend} />
      <article className="panel">
        <PanelHeading eyebrow="Leak Detector" title="Weakest funnel steps" icon={Gauge} />
        <div className="metric-list">
          {funnel.slice(1).map((item) => (
            <div key={item.step}>
              <strong>{item.step}</strong>
              <span>{item.rate}</span>
            </div>
          ))}
        </div>
      </article>
    </section>
  )
}

function AudiencesView({ data }: { data: DashboardData }) {
  return (
    <section className="dashboard-grid">
      <AudiencePanel data={data} />
      <article className="panel">
        <PanelHeading eyebrow="Audience Ranking" title="Buyer quality" icon={Target} />
        <div className="metric-list">
          {data.audience.map((item) => (
            <div key={item.segment}>
              <strong>{item.segment}</strong>
              <span>{item.buyers} buyers / {item.subs} subs</span>
            </div>
          ))}
        </div>
      </article>
    </section>
  )
}

function PlacementsView({ placements }: { placements: ReturnType<typeof derivePlacementScores> }) {
  return (
    <section className="dashboard-grid">
      <PlacementPanel placements={placements} />
      <article className="panel panel-wide">
        <PanelHeading eyebrow="Placement Efficiency" title="Spend share vs buyers" icon={BarChart3} />
        <div className="chart-box tall">
          <ResponsiveContainer width="100%" height="100%" minWidth={0} minHeight={0} initialDimension={{ width: 720, height: 318 }}>
            <BarChart data={placements}>
              <CartesianGrid strokeDasharray="3 3" vertical={false} />
              <XAxis dataKey="name" tickLine={false} axisLine={false} />
              <YAxis tickLine={false} axisLine={false} />
              <Tooltip />
              <Bar dataKey="value" fill="#3b82f6" radius={[5, 5, 0, 0]} />
              <Bar dataKey="buyers" fill="#1f9d8a" radius={[5, 5, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </article>
    </section>
  )
}

function ExperimentsView({ data }: { data: DashboardData }) {
  return (
    <section className="bottom-grid">
      <article className="panel">
        <PanelHeading eyebrow="Experiment Queue" title="Next controlled tests" icon={FlaskConical} />
        <div className="experiment-list">
          {data.experiments.map((experiment, index) => (
            <div className="experiment-item" key={experiment.title}>
              <span>{index + 1}</span>
              <div>
                <strong>{experiment.title}</strong>
                <p>{experiment.metric}</p>
                <small>{experiment.budget}</small>
              </div>
            </div>
          ))}
        </div>
      </article>
      <ApprovalQueue data={data} />
    </section>
  )
}

function SettingsAuditView() {
  const [audit, setAudit] = useState<MetaSettingsAudit | null>(null)
  const [error, setError] = useState<string | null>(() =>
    typeof fetch !== 'function' ? 'Settings audit API cannot be loaded in this browser sandbox.' : null,
  )

  useEffect(() => {
    if (typeof fetch !== 'function') {
      return
    }

    void fetch('/api/meta/settings-audit')
      .then((response) => response.ok ? response.json() : Promise.reject(new Error(`HTTP ${response.status}`)))
      .then((result: { available?: boolean; audit?: MetaSettingsAudit; error?: string }) => {
        if (!result.available || !result.audit) {
          setError(result.error ?? 'No saved Meta settings audit yet.')
          return
        }
        setAudit(result.audit)
      })
      .catch((requestError) => setError(requestError instanceof Error ? requestError.message : 'Could not load settings audit.'))
  }, [])

  if (error && !audit) {
    return (
      <section className="dashboard-grid">
        <article className="panel panel-wide empty-state">
          <AlertTriangle size={24} />
          <strong>Settings audit unavailable</strong>
          <p>{error}</p>
        </article>
      </section>
    )
  }

  if (!audit) {
    return (
      <section className="dashboard-grid">
        <article className="panel panel-wide empty-state">
          <RefreshCcw size={24} />
          <strong>Loading settings audit</strong>
          <p>Reading campaign, ad set, placement, and targeting settings from the saved Meta snapshot.</p>
        </article>
      </section>
    )
  }

  return (
    <section className="dashboard-grid">
      <article className="panel panel-wide">
        <PanelHeading eyebrow="Execution Safety" title="Agent control baseline" icon={ShieldAlert} />
        <div className="settings-summary-grid">
          <MiniMetric label="Mode" value={audit.policy.executionMode.replaceAll('_', ' ')} />
          <MiniMetric label="Primary interface" value={audit.policy.primaryInterface.replaceAll('_', ' ')} />
          <MiniMetric label="Browser fallback" value={audit.policy.browserFallback.replaceAll('_', ' ')} />
        </div>
      </article>
      <article className="panel panel-wide">
        <PanelHeading eyebrow="Settings Extractor" title="Meta setup summary" icon={ClipboardCheck} />
        <div className="settings-summary-grid">
          <MiniMetric label="Campaigns" value={audit.summary.campaigns.toLocaleString()} />
          <MiniMetric label="Ad sets" value={audit.summary.adsets.toLocaleString()} />
          <MiniMetric label="Ads" value={audit.summary.ads.toLocaleString()} />
          <MiniMetric label="Advantage+ audience" value={audit.summary.advantageAudienceAdsets.toLocaleString()} />
          <MiniMetric label="IG-only ad sets" value={audit.summary.instagramOnlyAdsets.toLocaleString()} />
          <MiniMetric label="Mixed FB/IG ad sets" value={audit.summary.facebookMixedAdsets.toLocaleString()} />
          <MiniMetric label="Country targeting" value={audit.summary.countryTargetedAdsets.toLocaleString()} />
          <MiniMetric label="Region/city targeting" value={audit.summary.regionTargetedAdsets.toLocaleString()} />
        </div>
      </article>
      <article className="panel">
        <PanelHeading eyebrow="Risk Watchlist" title="Settings to review" icon={AlertTriangle} />
        <div className="insight-list">
          {audit.risks.length > 0 ? audit.risks.map((risk) => (
            <div className={`insight ${risk.severity === 'warning' ? 'warning' : risk.severity === 'danger' ? 'danger' : 'neutral'}`} key={`${risk.area}-${risk.title}`}>
              <strong>{risk.title}</strong>
              <p>{risk.detail}</p>
              <small>{risk.area}</small>
            </div>
          )) : (
            <div className="insight good">
              <strong>No settings risk detected yet</strong>
              <p>The saved Meta settings do not show obvious guardrail conflicts.</p>
            </div>
          )}
        </div>
      </article>
      <article className="panel">
        <PanelHeading eyebrow="Placement Mix" title="Where ad sets can deliver" icon={RadioTower} />
        <div className="metric-list">
          {audit.placementMix.slice(0, 10).map((item) => (
            <div key={item.placement}>
              <strong>{labelRawSetting(item.placement)}</strong>
              <span>{item.adsetCount} ad sets</span>
            </div>
          ))}
        </div>
      </article>
      <article className="panel panel-wide">
        <PanelHeading eyebrow="Ad Set Settings" title="Top extracted controls" icon={SlidersHorizontal} />
        <div className="settings-table">
          <div className="settings-row settings-head">
            <span>Ad set</span>
            <span>Age / gender</span>
            <span>Geo</span>
            <span>Audience</span>
            <span>Placements</span>
            <span>Use</span>
          </div>
          {audit.adsets.slice(0, 14).map((adset) => (
            <div className="settings-row" key={adset.id}>
              <span><strong>{adset.name}</strong><small>{shortText(adset.id, 18)}</small></span>
              <span>{adset.ageMin}-{adset.ageMax} / {adset.genders.join(', ')}</span>
              <span>{adset.locations.slice(0, 3).join(', ')}<small>{adset.geoStrategy}</small></span>
              <span>{adset.advantageAudience ? 'Advantage+ audience' : adset.interests.slice(0, 2).join(', ')}</span>
              <span>{labelRawSetting(adset.platformStrategy)}</span>
              <span>{adset.recommendedUse}</span>
            </div>
          ))}
        </div>
      </article>
    </section>
  )
}

function MiniMetric({ label, value }: { label: string; value: string }) {
  return (
    <div className="mini-metric">
      <small>{label}</small>
      <strong>{value}</strong>
    </div>
  )
}

function CampaignBuilderView() {
  const [name, setName] = useState('Next AI course launch')
  const [primarySuccessMetric, setPrimarySuccessMetric] = useState('bot_start')
  const [startingBudgetUsd, setStartingBudgetUsd] = useState(100)
  const [maxDailyBudgetUsd, setMaxDailyBudgetUsd] = useState(500)
  const [salesCapacityLeadsPerDay, setSalesCapacityLeadsPerDay] = useState(200)
  const [scalingStepPercent, setScalingStepPercent] = useState(20)
  const [segments, setSegments] = useState<CampaignPlaybookSegment[]>([
    {
      ...buildEmptySegment('New segment'),
      targetAudienceNotes: 'Describe who should see this VSL.',
      offerAngle: 'Describe the promise or hook for this segment.',
    },
  ])
  const [savedPlaybook, setSavedPlaybook] = useState<CampaignPlaybook | null>(null)
  const [saveMessage, setSaveMessage] = useState<string | null>(null)
  const [isSaving, setIsSaving] = useState(false)

  const draft = useMemo(
    () =>
      buildPlaybookDraft({
        name,
        startingBudgetUsd,
        maxDailyBudgetUsd,
        salesCapacityLeadsPerDay,
        scalingStepPercent,
        primarySuccessMetric,
        segments,
      }),
    [maxDailyBudgetUsd, name, primarySuccessMetric, salesCapacityLeadsPerDay, scalingStepPercent, segments, startingBudgetUsd],
  )
  const readiness = useMemo(() => summarizePlaybookReadiness(draft), [draft])

  const updateSegment = (index: number, patch: Partial<CampaignPlaybookSegment>) => {
    setSegments((current) => current.map((segment, segmentIndex) => (segmentIndex === index ? { ...segment, ...patch } : segment)))
  }

  const addSegment = () => {
    setSegments((current) => [...current, buildEmptySegment(`Segment ${current.length + 1}`)])
  }

  const removeSegment = (index: number) => {
    setSegments((current) => current.filter((_, segmentIndex) => segmentIndex !== index))
  }

  const savePlaybook = async () => {
    if (isSaving) {
      return
    }
    setIsSaving(true)
    setSaveMessage('Saving campaign playbook...')
    try {
      const response = await fetch('/api/playbooks', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ playbook: draft }),
      })
      const result = (await response.json()) as { playbook?: CampaignPlaybook; error?: string }
      if (!response.ok || !result.playbook) {
        setSaveMessage(result.error ?? `Save failed with ${response.status}`)
        return
      }
      setSavedPlaybook(result.playbook)
      setSaveMessage('Playbook saved. It can be used later for approval-based launch planning.')
    } catch {
      setSaveMessage('Could not reach the playbook API.')
    } finally {
      setIsSaving(false)
    }
  }

  return (
    <section className="dashboard-grid">
      <article className="panel panel-wide">
        <PanelHeading eyebrow="Campaign Builder" title="Configurable launch playbook" icon={ClipboardCheck} />
        <div className="builder-grid">
          <label>
            <span>Playbook name</span>
            <input value={name} onChange={(event) => setName(event.target.value)} />
          </label>
          <label>
            <span>Primary success metric</span>
            <select value={primarySuccessMetric} onChange={(event) => setPrimarySuccessMetric(event.target.value)}>
              <option value="bot_start">Telegram START</option>
              <option value="form_button_click">Form button click</option>
              <option value="qualified_lead">Qualified lead</option>
              <option value="full_payment">Full payment</option>
            </select>
          </label>
          <label>
            <span>Starting budget / segment</span>
            <input type="number" min={1} value={startingBudgetUsd} onChange={(event) => setStartingBudgetUsd(Number(event.target.value))} />
          </label>
          <label>
            <span>Max daily budget</span>
            <input type="number" min={1} value={maxDailyBudgetUsd} onChange={(event) => setMaxDailyBudgetUsd(Number(event.target.value))} />
          </label>
          <label>
            <span>Sales capacity leads/day</span>
            <input type="number" min={1} value={salesCapacityLeadsPerDay} onChange={(event) => setSalesCapacityLeadsPerDay(Number(event.target.value))} />
          </label>
          <label>
            <span>Scale step percent</span>
            <input type="number" min={1} value={scalingStepPercent} onChange={(event) => setScalingStepPercent(Number(event.target.value))} />
          </label>
        </div>
      </article>

      <article className="panel panel-wide">
        <PanelHeading eyebrow="Segments" title="VSL and audience test groups" icon={Target} />
        <div className="builder-summary">
          <MiniMetric label="Segments" value={readiness.segmentCount.toString()} />
          <MiniMetric label="Ready with links" value={readiness.readySegments.toString()} />
          <MiniMetric label="Missing landing pages" value={readiness.missingLandingPages.toString()} />
          <MiniMetric label="Starting budget total" value={formatCurrency(readiness.totalStartingBudgetUsd)} />
        </div>
        <div className="segment-builder-list">
          {segments.map((segment, index) => (
            <div className="segment-builder-card" key={`${segment.id}-${index}`}>
              <div className="segment-builder-head">
                <strong>Segment {index + 1}</strong>
                <button type="button" onClick={() => removeSegment(index)} disabled={segments.length === 1}>
                  Remove
                </button>
              </div>
              <div className="builder-grid">
                <label>
                  <span>Name</span>
                  <input value={segment.name} onChange={(event) => updateSegment(index, { name: event.target.value })} />
                </label>
                <label>
                  <span>VSL ID</span>
                  <input value={segment.vslId ?? ''} onChange={(event) => updateSegment(index, { vslId: event.target.value })} placeholder="Optional for now" />
                </label>
                <label>
                  <span>Landing page URL</span>
                  <input value={segment.landingPageUrl ?? ''} onChange={(event) => updateSegment(index, { landingPageUrl: event.target.value })} placeholder="Add later" />
                </label>
                <label>
                  <span>Telegram bot URL</span>
                  <input value={segment.telegramBotUrl ?? ''} onChange={(event) => updateSegment(index, { telegramBotUrl: event.target.value })} placeholder="Add later" />
                </label>
                <label>
                  <span>Locations</span>
                  <input value={(segment.locations ?? []).join(', ')} onChange={(event) => updateSegment(index, { locations: parseCsvList(event.target.value) })} />
                </label>
                <label>
                  <span>Placements</span>
                  <input value={(segment.placements ?? []).join(', ')} onChange={(event) => updateSegment(index, { placements: parseCsvList(event.target.value) })} />
                </label>
                <label>
                  <span>Interests</span>
                  <input value={(segment.interests ?? []).join(', ')} onChange={(event) => updateSegment(index, { interests: parseCsvList(event.target.value) })} />
                </label>
                <label>
                  <span>Segment budget</span>
                  <input
                    type="number"
                    min={1}
                    value={segment.startingBudgetUsd ?? startingBudgetUsd}
                    onChange={(event) => updateSegment(index, { startingBudgetUsd: Number(event.target.value) })}
                  />
                </label>
                <label>
                  <span>Creative count target</span>
                  <input
                    type="number"
                    min={1}
                    value={segment.creativeCountTarget ?? 8}
                    onChange={(event) => updateSegment(index, { creativeCountTarget: Number(event.target.value) })}
                  />
                </label>
                <label>
                  <span>Age range</span>
                  <input value={segment.ageRange ?? 'Broad'} onChange={(event) => updateSegment(index, { ageRange: event.target.value })} />
                </label>
                <label className="builder-field-wide">
                  <span>Audience hypothesis</span>
                  <textarea value={segment.targetAudienceNotes ?? ''} onChange={(event) => updateSegment(index, { targetAudienceNotes: event.target.value })} />
                </label>
                <label className="builder-field-wide">
                  <span>Offer angle</span>
                  <textarea value={segment.offerAngle ?? ''} onChange={(event) => updateSegment(index, { offerAngle: event.target.value })} />
                </label>
              </div>
            </div>
          ))}
        </div>
        <div className="builder-actions">
          <button className="sync-button" type="button" onClick={addSegment}>
            <ListChecks size={16} />
            Add segment
          </button>
          <button className="sync-button" type="button" onClick={savePlaybook} disabled={isSaving}>
            <CheckCircle2 size={16} />
            {isSaving ? 'Saving...' : 'Save playbook'}
          </button>
          {saveMessage && <small className="sync-message">{saveMessage}</small>}
        </div>
      </article>

      <article className="panel panel-wide">
        <PanelHeading eyebrow="Draft Preview" title="Approval-safe launch structure" icon={ShieldAlert} />
        <div className="metric-list">
          <div><strong>Execution mode</strong><span>{draft.rules.requiresApprovalForExecution ? 'Approval required' : 'Autonomous'}</span></div>
          <div><strong>Scale rule</strong><span>{draft.rules.scalingStepPercent}% every {draft.rules.scalingFrequencyDays} day</span></div>
          <div><strong>Approval channels</strong><span>{draft.approvalChannels.join(', ')}</span></div>
          <div><strong>Saved playbook</strong><span>{savedPlaybook ? savedPlaybook.name : 'Not saved this session'}</span></div>
        </div>
      </article>
    </section>
  )
}

function StrategyView() {
  const [playbooks, setPlaybooks] = useState<CampaignPlaybook[]>([])
  const [selectedPlaybookId, setSelectedPlaybookId] = useState('')
  const [strategy, setStrategy] = useState<LaunchStrategy | null>(null)
  const [knowledgeAvailable, setKnowledgeAvailable] = useState(false)
  const [isGenerating, setIsGenerating] = useState(false)
  const [isPreparing, setIsPreparing] = useState(false)
  const [message, setMessage] = useState<string | null>(null)

  useEffect(() => {
    if (typeof fetch !== 'function') {
      return
    }

    void fetch('/api/playbooks')
      .then((response) => response.ok ? response.json() : { playbooks: [] })
      .then((result: { playbooks?: CampaignPlaybook[] }) => {
        const nextPlaybooks = result.playbooks ?? []
        setPlaybooks(nextPlaybooks)
        setSelectedPlaybookId((current) => current || nextPlaybooks[0]?.id || '')
      })
      .catch(() => {
        setPlaybooks([])
        setMessage('Could not load saved playbooks.')
      })
  }, [])

  const selectedPlaybook = playbooks.find((playbook) => playbook.id === selectedPlaybookId) ?? playbooks[0]
  const selectedPlaybookHasSegments = Boolean(selectedPlaybook?.segments?.length)

  const generateStrategy = async () => {
    if (isGenerating) {
      return
    }
    if (!selectedPlaybookHasSegments) {
      setMessage('Add at least one segment in Campaign Builder before generating a launch strategy.')
      return
    }

    setIsGenerating(true)
    setMessage('Generating approval-ready strategy...')
    try {
      const response = await fetch('/api/strategy/generate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ playbook: selectedPlaybook ?? null }),
      })
      const result = (await response.json()) as { ok?: boolean; strategy?: LaunchStrategy; knowledgeAvailable?: boolean; error?: string }
      if (!response.ok || !result.ok || !result.strategy) {
        setMessage(result.error ?? `Strategy generation failed with ${response.status}`)
        return
      }
      setStrategy(result.strategy)
      setKnowledgeAvailable(Boolean(result.knowledgeAvailable))
      setMessage(result.knowledgeAvailable ? 'Strategy generated from saved Meta knowledge.' : 'Strategy generated from playbook defaults; sync Meta for stronger evidence.')
    } catch {
      setMessage('Could not reach the strategy endpoint.')
    } finally {
      setIsGenerating(false)
    }
  }

  const prepareExecutionApproval = async () => {
    if (isPreparing || !selectedPlaybookHasSegments) {
      return
    }

    setIsPreparing(true)
    setMessage('Preparing paused Meta campaign approval...')
    try {
      const response = await fetch('/api/execution/prepare-campaign', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          playbook: selectedPlaybook ?? null,
          reason: 'Prepare a paused campaign shell from this playbook. Do not spend until approved.',
        }),
      })
      const result = (await response.json()) as { ok?: boolean; approval?: ApprovalRequest; detail?: string; error?: string }
      if (!response.ok || !result.ok || !result.approval) {
        setMessage(result.detail ?? result.error ?? `Approval preparation failed with ${response.status}`)
        return
      }
      setMessage(`Approval request created: ${result.approval.id}. Review it in the approval queue before dry-run execution.`)
    } catch {
      setMessage('Could not reach the execution approval endpoint.')
    } finally {
      setIsPreparing(false)
    }
  }

  return (
    <section className="dashboard-grid">
      <article className="panel panel-wide">
        <PanelHeading eyebrow="Agent Strategy" title="Approval-ready launch plan" icon={Target} />
        <div className="strategy-command-row">
          <label>
            <span>Playbook</span>
            <select value={selectedPlaybook?.id ?? ''} onChange={(event) => setSelectedPlaybookId(event.target.value)}>
              {playbooks.map((playbook) => (
                <option value={playbook.id} key={playbook.id}>
                  {playbook.name}
                </option>
              ))}
            </select>
          </label>
          <button className="sync-button" type="button" onClick={generateStrategy} disabled={isGenerating || !selectedPlaybookHasSegments}>
            <TrendingUp size={16} />
            {isGenerating ? 'Generating...' : 'Generate strategy'}
          </button>
          <button className="sync-button secondary" type="button" onClick={prepareExecutionApproval} disabled={isPreparing || !selectedPlaybookHasSegments}>
            <ShieldAlert size={16} />
            {isPreparing ? 'Preparing...' : 'Prepare approval'}
          </button>
          {message && <small className="sync-message">{message}</small>}
        </div>
      </article>

      {strategy ? (
        <>
          <article className="panel panel-wide">
            <PanelHeading eyebrow="Launch Summary" title={strategy.playbookName} icon={Gauge} />
            <p className="strategy-summary">{strategy.summary}</p>
            <div className="builder-summary">
              <MiniMetric label="Daily budget" value={formatCurrency(strategy.budget.totalDailyBudgetUsd)} />
              <MiniMetric label="Max daily budget" value={formatCurrency(strategy.budget.maxDailyBudgetUsd)} />
              <MiniMetric label="Lead load estimate" value={strategy.budget.estimatedDailyLeadLoad.toLocaleString()} />
              <MiniMetric label="Approval mode" value={strategy.execution.requiresApproval ? 'Required' : 'Optional'} />
            </div>
          </article>

          <article className="panel panel-wide">
            <PanelHeading eyebrow="Budget Split" title="Segment allocation" icon={CircleDollarSign} />
            <div className="strategy-budget-list">
              {strategy.budget.split.map((item) => (
                <div className="strategy-budget-row" key={item.segmentId}>
                  <div>
                    <strong>{item.segmentName}</strong>
                    <span>{formatCurrency(item.dailyBudgetUsd)} / day</span>
                  </div>
                  <div className="funnel-track">
                    <div className="funnel-fill" style={{ width: `${Math.max(4, item.sharePercent)}%` }} />
                  </div>
                  <em>{item.sharePercent.toFixed(1)}%</em>
                </div>
              ))}
            </div>
          </article>

          <section className="strategy-segment-grid">
            {strategy.segments.map((segment) => (
              <article className="panel" key={segment.id}>
                <PanelHeading eyebrow="Segment Strategy" title={segment.name} icon={Users} />
                <div className="metric-list">
                  <div><strong>Budget</strong><span>{formatCurrency(segment.budgetUsd)} / day</span></div>
                  <div><strong>Audience</strong><span>{segment.audienceHypothesis}</span></div>
                  <div><strong>Age / gender</strong><span>{segment.ageRange} / {segment.gender}</span></div>
                  <div><strong>Geo</strong><span>{segment.geoStrategy.recommendation}</span></div>
                  <div><strong>Placements</strong><span>{segment.recommendedPlacements.map(labelRawSetting).join(', ')}</span></div>
                  <div><strong>Interests</strong><span>{segment.interestStrategy.slice(0, 4).join(', ')}</span></div>
                  <div><strong>Funnel</strong><span>{segment.funnelReadiness.status === 'ready' ? 'Ready' : `Missing ${segment.funnelReadiness.missing.join(', ')}`}</span></div>
                </div>
                <div className="strategy-angle-list">
                  {segment.creativeAngles.map((angle) => <span key={angle}>{angle}</span>)}
                </div>
              </article>
            ))}
          </section>

          <article className="panel panel-wide">
            <PanelHeading eyebrow="Testing Plan" title="First review window" icon={FlaskConical} />
            <div className="settings-table strategy-table">
              <div className="settings-row settings-head">
                <span>Window</span>
                <span>Test</span>
                <span>Decision metric</span>
                <span>Action</span>
              </div>
              {strategy.testMatrix.map((item) => (
                <div className="settings-row" key={`${item.day}-${item.test}`}>
                  <span>{item.day}</span>
                  <span>{item.test}</span>
                  <span>{labelEventName(item.decisionMetric)}</span>
                  <span>{item.action}</span>
                </div>
              ))}
            </div>
          </article>

          <article className="panel">
            <PanelHeading eyebrow="Risks" title="What can break the launch" icon={AlertTriangle} />
            <div className="insight-list">
              {(strategy.risks.length ? strategy.risks : ['No major launch risks detected from the current playbook.']).map((risk) => (
                <div className="insight-item warning" key={risk}>
                  <AlertTriangle size={18} />
                  <div>
                    <strong>Watchpoint</strong>
                    <p>{risk}</p>
                  </div>
                </div>
              ))}
            </div>
          </article>

          <article className="panel">
            <PanelHeading eyebrow="Approval Queue" title="Human-controlled actions" icon={ShieldAlert} />
            <div className="action-list">
              {strategy.approvalActions.map((action) => (
                <div className={`action-item ${action.risk}`} key={action.id}>
                  <strong>{action.title}</strong>
                  <p>{action.impact}</p>
                  <span>{labelRawSetting(action.status)} · {action.owner}</span>
                </div>
              ))}
            </div>
          </article>

          <article className="panel panel-wide">
            <PanelHeading eyebrow="Knowledge Used" title={knowledgeAvailable ? 'Saved Meta evidence' : 'Playbook defaults'} icon={BookOpen} />
            <div className="strategy-knowledge-grid">
              <KnowledgeList title="Placements" items={strategy.knowledgeUsed.bestPlacements} />
              <KnowledgeList title="Interests" items={strategy.knowledgeUsed.bestInterests} />
              <KnowledgeList title="Regions" items={strategy.knowledgeUsed.bestRegions} />
              <KnowledgeList title="Lessons" items={strategy.knowledgeUsed.lessons} />
            </div>
          </article>
        </>
      ) : (
        <article className="panel panel-wide empty-panel">
          <Bot size={28} />
          <strong>No strategy generated yet</strong>
          <p>{selectedPlaybookHasSegments ? 'Choose a saved playbook and generate the first approval-ready campaign strategy.' : 'Add configurable segments in Campaign Builder, save the playbook, then generate the launch strategy.'}</p>
        </article>
      )}
    </section>
  )
}

function KnowledgeList({ title, items }: { title: string; items: string[] }) {
  return (
    <div className="knowledge-list">
      <strong>{title}</strong>
      {(items.length ? items : ['Waiting for more saved evidence.']).map((item) => (
        <span key={item}>{item}</span>
      ))}
    </div>
  )
}

function TrackingView({ data }: { data: DashboardData }) {
  const [funnelEvents, setFunnelEvents] = useState<FunnelEventSummary | null>(null)

  useEffect(() => {
    if (typeof fetch !== 'function') {
      return
    }

    void fetch('/api/funnel/summary')
      .then((response) => response.ok ? response.json() : null)
      .then((summary: FunnelEventSummary | null) => setFunnelEvents(summary))
      .catch(() => setFunnelEvents(null))
  }, [])

  return (
    <section className="dashboard-grid">
      <article className="panel panel-wide">
        <PanelHeading eyebrow="Funnel Event Stream" title="Landing and Telegram tracking" icon={Bot} />
        <div className="settings-summary-grid">
          <MiniMetric label="Events received" value={(funnelEvents?.totalEvents ?? 0).toLocaleString()} />
          <MiniMetric label="Unique visitors" value={(funnelEvents?.uniqueVisitors ?? 0).toLocaleString()} />
          <MiniMetric label="Telegram users" value={(funnelEvents?.uniqueTelegramUsers ?? 0).toLocaleString()} />
          <MiniMetric label="Latest event" value={funnelEvents?.latestEventAt ? formatDateTime(funnelEvents.latestEventAt) : 'Waiting'} />
          <MiniMetric label="Telegram START rate" value={formatRate(funnelEvents?.rates?.telegramStartRate)} />
          <MiniMetric label="Key message reach" value={formatRate(funnelEvents?.rates?.keyMessageReachRate)} />
          <MiniMetric label="Form click rate" value={formatRate(funnelEvents?.rates?.formClickRate)} />
          <MiniMetric label="Qualified lead rate" value={formatRate(funnelEvents?.rates?.qualifiedLeadRate)} />
          <MiniMetric label="CRM attributed lead rate" value={formatRate(funnelEvents?.rates?.crmAttributedLeadRate)} />
        </div>
      </article>
      <article className="panel">
        <PanelHeading eyebrow="CRM Join" title="Bitrix lead attribution" icon={Users} />
        <div className="settings-summary-grid">
          <MiniMetric label="CRM leads" value={(funnelEvents?.crm?.totalLeads ?? 0).toLocaleString()} />
          <MiniMetric label="Joined leads" value={(funnelEvents?.crm?.attributedLeads ?? 0).toLocaleString()} />
          <MiniMetric label="Tracked stages" value={Object.keys(funnelEvents?.crm?.stages ?? {}).length.toLocaleString()} />
        </div>
        <div className="insight-list compact">
          {Object.entries(funnelEvents?.crm?.stages ?? {}).length > 0 ? (
            Object.entries(funnelEvents?.crm?.stages ?? {}).map(([stage, count]) => (
              <div className="insight-item neutral" key={stage}>
                <Users size={18} />
                <div>
                  <strong>{stage}</strong>
                  <p>{count.toLocaleString()} leads in this CRM stage.</p>
                </div>
              </div>
            ))
          ) : (
            <div className="insight-item warning">
              <AlertTriangle size={18} />
              <div>
                <strong>Waiting for CRM imports</strong>
                <p>Import Bitrix leads with visitor or Telegram IDs to connect sales stages to ad traffic.</p>
              </div>
            </div>
          )}
        </div>
      </article>
      <article className="panel panel-wide">
        <PanelHeading eyebrow="Observed Bot Funnel" title="Tracked Telegram steps" icon={ListChecks} />
        <div className="table-list">
          <div className="ranking-head event-steps-grid">
            <span>Step</span>
            <span>Events</span>
            <span>Visitors</span>
            <span>From previous</span>
          </div>
          {(funnelEvents?.eventSteps?.length ? funnelEvents.eventSteps : [{ eventName: 'waiting_for_events', count: 0, uniqueVisitors: 0, rateFromPrevious: null }]).map((step) => (
            <div className="ranking-row event-steps-grid" key={step.eventName}>
              <strong>{labelEventName(step.eventName)}</strong>
              <span>{step.count.toLocaleString()}</span>
              <span>{step.uniqueVisitors.toLocaleString()}</span>
              <em>{step.rateFromPrevious === null ? 'First step' : formatRate(step.rateFromPrevious)}</em>
            </div>
          ))}
        </div>
      </article>
      {data.trackingHealth.map((item) => (
        <article className={`panel tracking-card ${item.status}`} key={item.name}>
          <div className="tracking-head">
            {item.status === 'healthy' ? <CheckCircle2 size={20} /> : item.status === 'warning' ? <AlertTriangle size={20} /> : <XCircle size={20} />}
            <div>
              <h2>{item.name}</h2>
              <p>{item.lastEventAt}</p>
            </div>
          </div>
          <strong>{item.matchRate}% match</strong>
          <div className="funnel-track">
            <div className="funnel-fill" style={{ width: `${item.matchRate}%` }} />
          </div>
          <p>{item.note}</p>
        </article>
      ))}
    </section>
  )
}

function AlertsView({ data }: { data: DashboardData }) {
  return (
    <section className="bottom-grid">
      <MonitoringAlertsPanel data={data} />
      <TopProblemsPanel data={data} />
      <InsightsPanel data={data} />
    </section>
  )
}

function MonitoringAlertsPanel({ data }: { data: DashboardData }) {
  const alerts = data.monitoringAlerts ?? []
  return (
    <article className="panel">
      <PanelHeading eyebrow="Monitoring Alerts" title="Latest campaign health warnings" icon={AlertTriangle} />
      <div className="insight-list">
        {alerts.length === 0 ? (
          <div className="insight-item good">
            <CheckCircle2 size={18} />
            <div>
              <strong>No monitoring alerts</strong>
              <p>Run the monitoring check to detect rising costs, falling Telegram START quality, or creative fatigue.</p>
            </div>
          </div>
        ) : (
          alerts.slice(0, 5).map((alert) => (
            <div className={`insight-item ${alert.severity === 'high' ? 'danger' : alert.severity === 'medium' ? 'warning' : 'neutral'}`} key={alert.id}>
              <AlertTriangle size={18} />
              <div>
                <strong>{alert.title}</strong>
                <p>{alert.recommendedActions.slice(0, 2).join(' ')}</p>
              </div>
            </div>
          ))
        )}
      </div>
    </article>
  )
}

function SettingsView({ data, metaStatus }: { data: DashboardData; metaStatus: MetaStatus | null }) {
  const [isSyncing, setIsSyncing] = useState(false)
  const [syncMessage, setSyncMessage] = useState<string | null>(null)
  const [syncDays, setSyncDays] = useState<90 | 180>(90)
  const [snapshots, setSnapshots] = useState<MetaSnapshot[]>([])
  const [playbooks, setPlaybooks] = useState<CampaignPlaybook[]>([])
  const syncErrors = data.dataSource?.syncErrors ?? []
  const rawCounts = data.dataSource?.rawCounts ?? {}

  useEffect(() => {
    if (typeof fetch !== 'function') {
      return
    }

    void fetch('/api/meta/snapshots')
      .then((response) => response.ok ? response.json() : { snapshots: [] })
      .then((result: { snapshots?: MetaSnapshot[] }) => setSnapshots(result.snapshots ?? []))
      .catch(() => setSnapshots([]))

    void fetch('/api/playbooks')
      .then((response) => response.ok ? response.json() : { playbooks: [] })
      .then((result: { playbooks?: CampaignPlaybook[] }) => setPlaybooks(result.playbooks ?? []))
      .catch(() => setPlaybooks([]))
  }, [])

  const runSync = async () => {
    if (isSyncing) {
      return
    }

    setIsSyncing(true)
    setSyncMessage(`Syncing the last ${syncDays} days from Meta...`)

    try {
      const response = await fetch('/api/meta/sync', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ days: syncDays }),
      })
      const result = (await response.json()) as {
        ok?: boolean
        error?: string
        llmEnabled?: boolean
        snapshot?: MetaSnapshot
      }

      if (!response.ok || !result.ok) {
        setSyncMessage(result.error ?? `Sync failed with ${response.status}`)
        return
      }

      if (result.snapshot) {
        setSnapshots((current) => [result.snapshot as MetaSnapshot, ...current.filter((item) => item.id !== result.snapshot?.id)])
      }
      setSyncMessage(result.llmEnabled ? 'Sync complete. LLM analysis saved.' : 'Sync complete. Rule-based analysis saved.')
      window.setTimeout(() => window.location.reload(), 900)
    } catch {
      setSyncMessage('Could not reach the backend sync endpoint.')
    } finally {
      setIsSyncing(false)
    }
  }

  return (
    <section className="dashboard-grid">
      <article className="panel">
        <PanelHeading eyebrow="Meta Connection" title="Marketing API status" icon={Settings} />
        <div className={`connection-card ${metaStatus?.connected ? 'good' : metaStatus?.configured ? 'warning' : 'danger'}`}>
          <strong>
            {metaStatus?.connected
              ? 'Connected'
              : metaStatus?.configured
                ? 'Configured, needs validation'
                : 'Not configured'}
          </strong>
          <p>{metaStatus?.error ?? metaStatus?.account?.name ?? 'Add local credentials to connect Meta.'}</p>
          <div className="metric-list">
            <div><strong>Ad account</strong><span>{metaStatus?.adAccountId || 'Missing'}</span></div>
            <div><strong>Business ID</strong><span>{metaStatus?.businessId || 'Missing'}</span></div>
            <div><strong>App ID</strong><span>{metaStatus?.appId || 'Missing'}</span></div>
            <div><strong>API version</strong><span>{metaStatus?.apiVersion || 'Missing'}</span></div>
            <div><strong>Token</strong><span>{metaStatus?.tokenConfigured ? metaStatus.tokenPreview : 'Missing'}</span></div>
            <div><strong>Pixel</strong><span>{metaStatus?.pixelConfigured ? 'Configured' : 'Not set'}</span></div>
          </div>
        </div>
      </article>
      <article className="panel">
        <PanelHeading eyebrow="Dashboard Source" title="Real data status" icon={RefreshCcw} />
        <div className={`connection-card ${data.dataSource?.kind === 'meta' ? 'good' : 'warning'}`}>
          <strong>{data.dataSource?.label ?? 'Dashboard data'}</strong>
          <p>
            {data.dataSource?.generatedAt
              ? `Last analysis: ${formatDateTime(data.dataSource.generatedAt)}${data.dataSource.snapshotId ? ` (${data.dataSource.days ?? 90}d snapshot)` : ''}`
              : 'No saved Meta analysis timestamp yet.'}
          </p>
          <div className="segmented-control compact">
            {[90, 180].map((days) => (
              <button
                className={syncDays === days ? 'active' : ''}
                key={days}
                type="button"
                onClick={() => setSyncDays(days as 90 | 180)}
              >
                {days} days
              </button>
            ))}
          </div>
          <button className="sync-button" type="button" onClick={runSync} disabled={isSyncing || !metaStatus?.connected}>
            <RefreshCcw size={16} />
            {isSyncing ? 'Syncing...' : `Run ${syncDays}-day sync`}
          </button>
          {syncMessage && <small className="sync-message">{syncMessage}</small>}
          <div className="metric-list">
            <div><strong>Campaigns</strong><span>{rawCounts.campaigns ?? data.campaigns.length}</span></div>
            <div><strong>Ad sets</strong><span>{rawCounts.adsets ?? data.adSets.length}</span></div>
            <div><strong>Ads</strong><span>{rawCounts.ads ?? data.ads.length}</span></div>
            <div><strong>Insight rows</strong><span>{rawCounts.placementRows ?? data.metrics.length}</span></div>
            <div><strong>Snapshot ID</strong><span>{data.dataSource?.snapshotId ? shortText(data.dataSource.snapshotId, 28) : 'Not saved yet'}</span></div>
            <div><strong>Sync warnings</strong><span>{syncErrors.length}</span></div>
          </div>
        </div>
      </article>
      <article className="panel">
        <PanelHeading eyebrow="Import Memory" title="Saved snapshots" icon={BookOpen} />
        <div className="metric-list">
          {snapshots.length > 0 ? snapshots.slice(0, 5).map((snapshot) => (
            <div key={snapshot.id}>
              <strong>{snapshot.days} days</strong>
              <span>{formatDateTime(snapshot.generatedAt)}</span>
            </div>
          )) : (
            <div><strong>No snapshots yet</strong><span>Run a Meta sync to create one.</span></div>
          )}
        </div>
      </article>
      <article className="panel">
        <PanelHeading eyebrow="Campaign Playbooks" title="Configurable launch strategy" icon={ClipboardCheck} />
        <div className="metric-list">
          {playbooks.slice(0, 3).map((playbook) => (
            <div key={playbook.id}>
              <strong>{playbook.name}</strong>
              <span>{playbook.segments.length} segments · {playbook.primarySuccessMetric}</span>
            </div>
          ))}
        </div>
      </article>
      <article className="panel panel-wide">
        <PanelHeading eyebrow="Metric Glossary" title="Definitions and watch points" icon={BookOpen} />
        <div className="glossary-grid">
          {data.glossary.map((item) => (
            <div className="glossary-item" key={item.metric}>
              <strong>{item.metric}</strong>
              <p>{item.definition}</p>
              <small>{item.watchFor}</small>
            </div>
          ))}
        </div>
      </article>
      <article className="panel">
        <PanelHeading eyebrow="Data Sources" title="Connector targets" icon={Settings} />
        <div className="metric-list">
          <div><strong>Meta Marketing API</strong><span>{data.dataSource?.kind === 'meta' ? 'Connected' : 'Pending'}</span></div>
          <div><strong>Landing Page</strong><span>Pixel and CAPI next</span></div>
          <div><strong>Telegram Bot</strong><span>Subscriber events next</span></div>
          <div><strong>YouTube VSL</strong><span>Retention events next</span></div>
          <div><strong>Gemini</strong><span>Creative video analysis next</span></div>
        </div>
      </article>
      {syncErrors.length > 0 && (
        <article className="panel panel-wide">
          <PanelHeading eyebrow="Sync Warnings" title="Meta data to retry in smaller slices" icon={AlertTriangle} />
          <div className="metric-list">
            {syncErrors.map((item) => (
              <div key={`${item.source}-${item.error}`}>
                <strong>{item.source}</strong>
                <span>{item.error}</span>
              </div>
            ))}
          </div>
        </article>
      )}
    </section>
  )
}

function InsightsPanel({ data }: { data: DashboardData }) {
  return (
    <article className="panel">
      <PanelHeading eyebrow="Agent Diagnosis" title="What needs attention" icon={AlertTriangle} />
      <div className="insight-list">
        {data.insights.map((insight) => {
          const Icon = iconMap[insight.icon]
          return (
            <div className={`insight-item ${insight.tone}`} key={insight.title}>
              <Icon size={18} />
              <div>
                <strong>{insight.title}</strong>
                <p>{insight.body}</p>
              </div>
            </div>
          )
        })}
      </div>
    </article>
  )
}

function ApprovalQueue({ data }: { data: DashboardData }) {
  const [approvals, setApprovals] = useState<ApprovalRequest[]>([])
  const [message, setMessage] = useState<string | null>(null)

  const fetchApprovals = async () => {
    const response = await fetch('/api/approvals')
    const result = (await response.json()) as { approvals?: ApprovalRequest[] }
    return result.approvals ?? []
  }

  useEffect(() => {
    if (typeof fetch !== 'function') {
      return
    }
    let cancelled = false
    void fetchApprovals()
      .then((nextApprovals) => {
        if (!cancelled) {
          setApprovals(nextApprovals)
        }
      })
      .catch(() => {
        if (!cancelled) {
          setMessage('Could not load execution approvals.')
        }
      })
    return () => {
      cancelled = true
    }
  }, [])

  const approve = async (approvalId: string) => {
    setMessage('Approving request...')
    try {
      const response = await fetch(`/api/approvals/${approvalId}/approve`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ approvedBy: 'dashboard' }),
      })
      if (!response.ok) {
        const result = (await response.json()) as { detail?: string }
        setMessage(result.detail ?? `Approval failed with ${response.status}`)
        return
      }
      setMessage('Approved. You can now run a dry-run preview.')
      setApprovals(await fetchApprovals())
    } catch {
      setMessage('Could not approve the request.')
    }
  }

  const reject = async (approvalId: string) => {
    setMessage('Rejecting request...')
    try {
      const response = await fetch(`/api/approvals/${approvalId}/reject`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ rejectedBy: 'dashboard', reason: 'Rejected in dashboard.' }),
      })
      if (!response.ok) {
        const result = (await response.json()) as { detail?: string }
        setMessage(result.detail ?? `Reject failed with ${response.status}`)
        return
      }
      setMessage('Rejected. No execution can run from this approval.')
      setApprovals(await fetchApprovals())
    } catch {
      setMessage('Could not reject the request.')
    }
  }

  const requestChanges = async (approvalId: string) => {
    setMessage('Marking request as needs changes...')
    try {
      const response = await fetch(`/api/approvals/${approvalId}/changes`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ requestedBy: 'dashboard', note: 'Needs changes in dashboard.' }),
      })
      if (!response.ok) {
        const result = (await response.json()) as { detail?: string }
        setMessage(result.detail ?? `Needs changes failed with ${response.status}`)
        return
      }
      setMessage('Marked as needs changes. Revise the plan before approving.')
      setApprovals(await fetchApprovals())
    } catch {
      setMessage('Could not mark the request as needs changes.')
    }
  }

  const dryRun = async (approvalId: string) => {
    setMessage('Running dry-run preview...')
    try {
      const response = await fetch(`/api/approvals/${approvalId}/execute`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ dryRun: true }),
      })
      const result = (await response.json()) as { result?: { note?: string }; detail?: string }
      if (!response.ok) {
        setMessage(result.detail ?? `Dry run failed with ${response.status}`)
        return
      }
      setMessage(result.result?.note ?? 'Dry-run completed without sending a request to Meta.')
      setApprovals(await fetchApprovals())
    } catch {
      setMessage('Could not run the dry-run preview.')
    }
  }

  return (
    <article className="panel">
      <PanelHeading eyebrow="Recommended Actions" title="Approval queue" icon={ClipboardCheck} />
      {approvals.length > 0 && (
        <div className="action-list execution-approval-list">
          {approvals.map((approval) => (
            <div className={`action-item ${approval.risk}`} key={approval.id}>
              <div>
                <strong>{approval.after.campaign?.name ?? approval.actionType}</strong>
                <p>{approval.reason}</p>
                <small>
                  {approval.status} / {approval.guardrailResult} / {approval.executionMethod}
                </small>
                <small>
                  {(approval.after.adsets ?? []).length} paused ad set(s), budget {formatCurrency((approval.after.adsets ?? []).reduce((total, adset) => total + adset.daily_budget / 100, 0))}/day
                </small>
                {approval.rejectionReason && <small>Rejected reason: {approval.rejectionReason}</small>}
                {approval.changeRequestNote && <small>Change request: {approval.changeRequestNote}</small>}
              </div>
              <div className="approval-button-stack">
                {approval.status === 'needs_review' && (
                  <>
                    <button className="sync-button secondary" type="button" onClick={() => void approve(approval.id)}>
                      Approve
                    </button>
                    <button className="sync-button secondary danger-button" type="button" onClick={() => void reject(approval.id)}>
                      Reject
                    </button>
                    <button className="sync-button secondary" type="button" onClick={() => void requestChanges(approval.id)}>
                      Needs changes
                    </button>
                  </>
                )}
                {approval.status === 'approved' && (
                  <button className="sync-button" type="button" onClick={() => void dryRun(approval.id)}>
                    Dry run
                  </button>
                )}
                <span>{approval.risk}</span>
              </div>
            </div>
          ))}
        </div>
      )}
      {message && <small className="sync-message">{message}</small>}
      <div className="action-list">
        {data.approvalActions.map((action) => (
          <div className={`action-item ${action.risk}`} key={action.id}>
            <div>
              <strong>{action.title}</strong>
              <p>{action.impact}</p>
              <small>{action.owner} / {action.status}</small>
            </div>
            <span>{action.risk}</span>
          </div>
        ))}
      </div>
    </article>
  )
}

function PanelHeading({
  eyebrow,
  title,
  icon: Icon,
}: {
  eyebrow: string
  title: string
  icon: ComponentType<{ size?: number }>
}) {
  return (
    <div className="panel-heading">
      <div>
        <p className="eyebrow">{eyebrow}</p>
        <h2>{title}</h2>
      </div>
      <Icon size={20} />
    </div>
  )
}

function Score({ label, value, tone }: { label: string; value: number; tone: Tone }) {
  return (
    <div className={`score-card ${tone}`}>
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  )
}

function EmptyState({ compact = false, onReset }: { compact?: boolean; onReset?: () => void }) {
  return (
    <div className={compact ? 'empty-state compact' : 'empty-state'}>
      <AlertTriangle size={22} />
      <strong>No matching data</strong>
      <p>Adjust filters to restore the current dashboard view.</p>
      {onReset && (
        <button className="sync-button" type="button" onClick={onReset}>
          Reset filters
        </button>
      )}
    </div>
  )
}

function filterCreatives(creatives: Creative[], metrics: DailyAdMetric[], filters: DashboardFilters) {
  const visibleCreativeIds = new Set(metrics.map((metric) => metric.creativeId))

  return creatives.filter((creative) => {
    return (
      (filters.creativeFormat === 'all' || creative.format === filters.creativeFormat) &&
      visibleCreativeIds.has(creative.id)
    )
  })
}

function deriveFilteredKpis(metrics: DailyAdMetric[], trackingHealth: TrackingHealthItem[]): DashboardKpi[] {
  const spend = sumBy(metrics, (metric) => metric.spendUsd)
  const clicks = sumBy(metrics, (metric) => metric.clicks)
  const landingPageViews = sumBy(metrics, (metric) => metric.landingPageViews)
  const leads = sumBy(metrics, (metric) => metric.leads)
  const buyers = sumBy(metrics, (metric) => metric.purchases)
  const averageTrackingHealth = Math.round(
    sumBy(trackingHealth, (item) => item.matchRate) / Math.max(1, trackingHealth.length),
  )

  return [
    {
      label: 'Filtered Spend',
      value: formatCurrency(spend),
      change: `${metrics.length} metric rows`,
      helper: 'Based on active filters',
      tone: 'neutral',
      icon: 'dollar',
    },
    {
      label: 'Visit Rate',
      value: formatPercent(landingPageViews, clicks),
      change: `${formatNumber(landingPageViews)} landing visits`,
      helper: 'Landing visits / clicks',
      tone: landingPageViews > 0 ? 'good' : 'warning',
      icon: 'bot',
    },
    {
      label: 'LP Lead Rate',
      value: formatPercent(leads, landingPageViews),
      change: `${formatNumber(leads)} leads`,
      helper: 'Leads / landing visits',
      tone: leads > 0 ? 'good' : 'warning',
      icon: 'target',
    },
    {
      label: 'Buyers',
      value: formatNumber(buyers),
      change: buyers > 0 ? `${formatCurrency(spend / buyers)} CPA` : 'No buyers',
      helper: 'Filtered course purchases',
      tone: buyers > 0 ? 'good' : 'warning',
      icon: 'users',
    },
    {
      label: 'Tracking Health',
      value: `${averageTrackingHealth}%`,
      change: averageTrackingHealth >= 85 ? 'Stable' : 'Needs review',
      helper: 'Pixel, API, purchase, Telegram, webinar',
      tone: averageTrackingHealth >= 85 ? 'good' : 'warning',
      icon: 'check',
    },
  ]
}

function sumBy<T>(rows: T[], select: (row: T) => number) {
  return rows.reduce((total, row) => total + select(row), 0)
}

function formatCurrency(value: number) {
  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: 'USD',
    maximumFractionDigits: value >= 100 ? 0 : 2,
  }).format(value)
}

function formatPercent(value: number, base: number) {
  return base === 0 ? '0%' : `${((value / base) * 100).toFixed(1)}%`
}

function formatRate(value?: number) {
  return typeof value === 'number' ? `${value.toFixed(value % 1 === 0 ? 0 : 1)}%` : '0%'
}

function labelEventName(value: string) {
  return value
    .split('_')
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(' ')
}

function getDashboardAnchorDate(data: DashboardData): string {
  const generatedAt = data.dataSource?.generatedAt?.slice(0, 10)
  if (generatedAt) {
    return generatedAt
  }

  const campaignDates = data.campaigns.flatMap((campaign) =>
    [campaign.startedAt, campaign.endedAt].filter((value): value is string => Boolean(value)),
  )
  const metricDates = data.metrics.map((metric) => metric.date)
  const dates: string[] = [...campaignDates, ...metricDates]
  return dates.reduce((max, value) => (value > max ? value : max), '2026-05-21')
}

function labelPlacement(placement: Placement) {
  return placement
    .split('_')
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(' ')
}

function labelRawSetting(value: string) {
  return value
    .split('_')
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(' ')
}

function shortCampaignLabel(name: string) {
  const cleanName = name.replace(/^DA\s*-\s*/i, '').trim()
  return cleanName.length <= 28 ? cleanName : `${cleanName.slice(0, 27)}...`
}

function shortText(value: string, limit: number) {
  return value.length <= limit ? value : `${value.slice(0, limit - 1)}...`
}

function formatDateTime(value: string) {
  return new Date(value).toLocaleString('en-US', {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}
