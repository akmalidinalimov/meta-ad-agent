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
import { askAgent } from '../services/agentChatProvider'
import { getMetaStatus, type MetaStatus } from '../services/metaStatusProvider'
import type {
  CampaignPlaybook,
  Creative,
  DashboardData,
  DashboardFilters,
  DashboardKpi,
  DailyAdMetric,
  FunnelEventSummary,
  IconName,
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
  { id: 'rankings', label: 'Rankings', icon: BarChart3 },
  { id: 'creatives', label: 'Creatives', icon: Film },
  { id: 'funnel', label: 'Funnel', icon: MousePointerClick },
  { id: 'audiences', label: 'Audiences', icon: Users },
  { id: 'placements', label: 'Placements', icon: RadioTower },
  { id: 'experiments', label: 'Experiments', icon: FlaskConical },
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
        <ResponsiveContainer width="100%" height="100%">
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
        <ResponsiveContainer width="100%" height="100%">
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
        <ResponsiveContainer width="100%" height="100%">
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
        <ResponsiveContainer width="100%" height="100%">
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
          <ResponsiveContainer width="100%" height="100%">
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
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (typeof fetch !== 'function') {
      setError('Settings audit API cannot be loaded in this browser sandbox.')
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
      <TopProblemsPanel data={data} />
      <InsightsPanel data={data} />
    </section>
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
  return (
    <article className="panel">
      <PanelHeading eyebrow="Recommended Actions" title="Approval queue" icon={ClipboardCheck} />
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
