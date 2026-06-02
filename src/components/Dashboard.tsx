import { useEffect, useMemo, useState, type ChangeEvent, type ComponentType, type CSSProperties } from 'react'
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
  Play,
  RadioTower,
  RefreshCcw,
  Settings,
  ShieldAlert,
  SlidersHorizontal,
  Sparkles,
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
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { ChartFrame } from './dashboard/shared/ChartFrame'
import { MediaThumb } from './dashboard/shared/MediaThumb'
import { MetaAiCaptureView } from './dashboard/sections/MetaAiCaptureView'
import { PanelHeading } from './dashboard/shared/PanelHeading'
import {
  deriveCreativeScores,
  deriveCreativeDecisionInsight,
  deriveFunnel,
  derivePlacementScores,
  deriveRankingRows,
  deriveTrend,
  filterMetricsForDashboard,
  formatNumber,
  getCampaignOptions,
  getDateWindow,
} from '../lib/analytics'
import { buildOperatorAttention } from '../lib/operatorAttention'
import {
  buildEmptySegment,
  buildPlaybookDraft,
  parseCsvList,
  summarizePlaybookReadiness,
} from '../lib/playbookBuilder'
import { askAgent, runAgentCouncil } from '../services/agentChatProvider'
import { createAgentTask, getAgentCommandCenter } from '../services/agentTaskProvider'
import { getMetaStatus, type MetaStatus } from '../services/metaStatusProvider'
import type {
  AgentSpec,
  AgentCouncilSession,
  AgentTask,
  CampaignPlaybook,
  CampaignPlaybookSegment,
  ApprovalRequest,
  CampaignWatchItem,
  Creative,
  DashboardData,
  DashboardFilters,
  DashboardKpi,
  DailyAdMetric,
  DraftCampaignProposal,
  FunnelEventSummary,
  IconName,
  LaunchStrategy,
  MetaSnapshot,
  MetaSettingsAudit,
  Placement,
  RankingRow,
  SystemChecklist,
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
  { id: 'agentOffice', label: 'Agent Office', icon: Users },
  { id: 'rankings', label: 'Rankings', icon: BarChart3 },
  { id: 'creatives', label: 'Creatives', icon: Film },
  { id: 'funnel', label: 'Funnel', icon: MousePointerClick },
  { id: 'audiences', label: 'Audiences', icon: Users },
  { id: 'placements', label: 'Placements', icon: RadioTower },
  { id: 'experiments', label: 'Experiments', icon: FlaskConical },
  { id: 'metaAi', label: 'Meta AI', icon: Sparkles },
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
  isRefreshing?: boolean
  onRefresh?: () => Promise<DashboardData>
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

export function Dashboard({ data, isRefreshing = false, onRefresh }: DashboardProps) {
  const [activeView, setActiveView] = useState<ViewId>('overview')
  const [selectedCreativeId, setSelectedCreativeId] = useState('')
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
  const [latestCouncil, setLatestCouncil] = useState<AgentCouncilSession | null>(null)

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
  const selectedCreative =
    filteredCreatives.find((creative) => creative.id === selectedCreativeId) ??
    filteredCreatives.find((creative) => creative.id === creativeScores[0]?.id) ??
    filteredCreatives[0]

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
      if (response.agentCouncil) {
        setLatestCouncil(response.agentCouncil)
      }
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
          agentHandoffs: response.agentHandoffs,
          quality: response.quality ?? undefined,
          agentCouncil: response.agentCouncil ?? undefined,
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
        <div className="topbar-actions">
          <div className={`status-pill ${dataSourceTone}`}>
            {data.dataSource?.kind === 'meta' ? <CheckCircle2 size={16} /> : <AlertTriangle size={16} />}
            {data.dataSource?.label ?? 'Dashboard data loaded'}
          </div>
          {onRefresh && (
            <button className="sync-button secondary" type="button" onClick={() => void onRefresh()} disabled={isRefreshing}>
              <RefreshCcw size={16} />
              {isRefreshing ? 'Refreshing...' : 'Refresh data'}
            </button>
          )}
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
          {activeView === 'agentOffice' && (
            <AgentOfficeView latestCouncil={latestCouncil} onCouncilReady={setLatestCouncil} />
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
          {activeView === 'metaAi' && <MetaAiCaptureView />}
          {activeView === 'campaignBuilder' && <CampaignBuilderView />}
          {activeView === 'strategy' && <StrategyView />}
          {activeView === 'settingsAudit' && <SettingsAuditView />}
          {activeView === 'tracking' && <TrackingView data={data} />}
          {activeView === 'alerts' && <AlertsView data={data} />}
          {activeView === 'settings' && <SettingsView data={data} metaStatus={metaStatus} onDashboardRefresh={onRefresh} />}
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
  agentHandoffs?: Array<{
    fromAgent: string
    toAgent: string
    reason: string
    inputsNeeded: string[]
    expectedOutput: string
    confidence: string
  }>
  quality?: {
    score: number
    status: string
    issues: string[]
  }
  agentCouncil?: AgentCouncilSession | null
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
            {message.quality && <small>Quality: {message.quality.score}/100 · {labelRawSetting(message.quality.status)}</small>}
            {message.agentCouncil && (
              <small>
                Council: {message.agentCouncil.events.length} exchanges · {message.agentCouncil.averageScoreOutOf10.toFixed(1)}/10
              </small>
            )}
            {message.agentHandoffs && message.agentHandoffs.length > 0 && (
              <small>
                Handoff: {message.agentHandoffs.slice(0, 2).map((handoff) => `${labelRawSetting(handoff.fromAgent)} → ${labelRawSetting(handoff.toAgent)}`).join(', ')}
              </small>
            )}
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
      <ChartFrame>
        <LineChart data={trend}>
          <CartesianGrid strokeDasharray="3 3" vertical={false} />
          <XAxis dataKey="day" tickLine={false} axisLine={false} />
          <YAxis tickLine={false} axisLine={false} />
          <Tooltip />
          <Line type="monotone" dataKey="leads" stroke="#1f9d8a" strokeWidth={3} dot={false} />
          <Line type="monotone" dataKey="buyers" stroke="#ef4444" strokeWidth={3} dot={false} />
        </LineChart>
      </ChartFrame>
    </article>
  )
}

function TopProblemsPanel({ data }: { data: DashboardData }) {
  const attentionItems = buildOperatorAttention(data)
  return (
    <article className="panel">
      <PanelHeading eyebrow="What Needs Attention Now" title="Operator priority queue" icon={AlertTriangle} />
      <div className="problem-list">
        {attentionItems.map((item, index) => {
          const Icon = item.tone === 'good' ? CheckCircle2 : item.tone === 'danger' ? XCircle : AlertTriangle
          return (
            <div className={`problem-item ${item.tone}`} key={item.id}>
              <Icon size={18} />
              <div>
                <small>{index + 1}. {item.source}</small>
                <strong>{item.title}</strong>
                <p>{item.reason}</p>
                <em>{item.action}</em>
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
        <span>Leads</span>
        <span>CPL</span>
        <span>Lead rate</span>
        <span>Confidence</span>
        <span>Intent</span>
        <span>Quality</span>
        <span>Action</span>
        <span>Watch</span>
      </div>
      {creativeScores.map((creative) => {
        const interactive = Boolean(onSelect)
        return (
          <div
            className="table-row"
            key={creative.id}
            role={interactive ? 'button' : undefined}
            tabIndex={interactive ? 0 : undefined}
            onClick={interactive ? () => onSelect?.(creative.id) : undefined}
            onKeyDown={
              interactive
                ? (event) => {
                    if (event.key === 'Enter' || event.key === ' ') {
                      event.preventDefault()
                      onSelect?.(creative.id)
                    }
                  }
                : undefined
            }
          >
            <span>#{creative.rank}</span>
            <div className="creative-cell">
              <MediaThumb assetUrl={creative.assetUrl} videoUrl={creative.videoUrl} videoId={creative.videoId} format={creative.format} />
              <div>
                <strong>{creative.name}</strong>
                <small>
                  {creative.type} / {creative.format}
                  {creative.lowSample && <span className="creative-flag low-sample">Low sample</span>}
                  {creative.mismatch >= 40 && <span className="creative-flag mismatch">Viral≫intent</span>}
                </small>
              </div>
            </div>
            <span>{formatNumber(creative.leads)}</span>
            <span>{creative.cpl > 0 ? `$${creative.cpl.toFixed(2)}` : '—'}</span>
            <span>{creative.leadRate.toFixed(1)}%</span>
            <span className={`confidence ${creative.spendConfidence}`}>{creative.spendConfidence}</span>
            <span>{creative.intent}</span>
            <span>{creative.quality}</span>
            <em className={creative.tone}>{creative.action}</em>
            <WatchAction creative={creative} onSelect={onSelect} />
          </div>
        )
      })}
    </div>
  )
}

function WatchAction({
  creative,
  onSelect,
}: {
  creative: ReturnType<typeof deriveCreativeScores>[number]
  onSelect?: (id: string) => void
}) {
  if (creative.videoUrl) {
    return (
      <a
        className="watch-action"
        href={creative.videoUrl}
        target="_blank"
        rel="noreferrer"
        onClick={(event) => event.stopPropagation()}
      >
        <Play size={13} /> Watch
      </a>
    )
  }
  if (creative.videoId && onSelect) {
    return (
      <button
        type="button"
        className="watch-action"
        onClick={(event) => {
          event.stopPropagation()
          onSelect(creative.id)
        }}
      >
        <Play size={13} /> Load
      </button>
    )
  }
  return <span className="watch-action disabled">—</span>
}

function PlacementPanel({ placements }: { placements: ReturnType<typeof derivePlacementScores> }) {
  return (
    <article className="panel">
      <PanelHeading eyebrow="Placement" title="Spend share by channel" icon={RadioTower} />
      <ChartFrame>
        <PieChart>
          <Pie data={placements} dataKey="value" nameKey="name" innerRadius={58} outerRadius={88}>
            {placements.map((entry, index) => (
              <Cell key={entry.name} fill={COLORS[index % COLORS.length]} />
            ))}
          </Pie>
          <Tooltip />
        </PieChart>
      </ChartFrame>
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
      <ChartFrame tall>
        <BarChart data={data.audience}>
          <CartesianGrid strokeDasharray="3 3" vertical={false} />
          <XAxis dataKey="segment" tickLine={false} axisLine={false} />
          <YAxis tickLine={false} axisLine={false} />
          <Tooltip />
          <Bar dataKey="subs" fill="#3b82f6" radius={[5, 5, 0, 0]} />
          <Bar dataKey="buyers" fill="#1f9d8a" radius={[5, 5, 0, 0]} />
        </BarChart>
      </ChartFrame>
    </article>
  )
}

function SpendPanel({ trend }: { trend: ReturnType<typeof deriveTrend> }) {
  return (
    <article className="panel">
      <PanelHeading eyebrow="Spend Curve" title="Budget pressure" icon={CircleDollarSign} />
      <ChartFrame>
        <AreaChart data={trend}>
          <CartesianGrid strokeDasharray="3 3" vertical={false} />
          <XAxis dataKey="day" tickLine={false} axisLine={false} />
          <YAxis tickLine={false} axisLine={false} />
          <Tooltip />
          <Area type="monotone" dataKey="spend" stroke="#7c3aed" fill="#ddd6fe" strokeWidth={3} />
        </AreaChart>
      </ChartFrame>
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
  const decisionInsight = selectedCreative
    ? deriveCreativeDecisionInsight({
        creativeId: selectedCreative.id,
        metrics: data.metrics,
        adSets: data.adSets,
        score,
      })
    : null

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
            <CreativeMetrics score={score} />
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
            {decisionInsight && <CreativeDecisionPanel insight={decisionInsight} />}
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

function CreativeMetrics({ score }: { score: ReturnType<typeof deriveCreativeScores>[number] }) {
  const stats: { label: string; value: string; tone?: string }[] = [
    { label: 'Spend', value: `$${score.spendUsd.toFixed(2)}` },
    { label: 'CPL', value: score.cpl > 0 ? `$${score.cpl.toFixed(2)}` : '—' },
    { label: 'Lead rate', value: `${score.leadRate.toFixed(1)}%` },
    { label: 'Leads', value: formatNumber(score.leads) },
    { label: 'Clicks', value: formatNumber(score.clicks) },
    { label: 'Confidence', value: score.spendConfidence, tone: score.spendConfidence },
  ]

  return (
    <div className="creative-metrics">
      <div className="metric-stats">
        {stats.map((stat) => (
          <div className="metric-stat" key={stat.label}>
            <small>{stat.label}</small>
            <strong className={stat.tone ? `confidence ${stat.tone}` : undefined}>{stat.value}</strong>
          </div>
        ))}
      </div>
      {(score.lowSample || score.mismatch >= 40) && (
        <div className="metric-notes">
          {score.lowSample && <span className="creative-flag low-sample">Low sample — ranking is provisional</span>}
          {score.mismatch >= 40 && (
            <span className="creative-flag mismatch">Viral≫intent — attention without buyer intent</span>
          )}
        </div>
      )}
    </div>
  )
}


function CreativeDecisionPanel({ insight }: { insight: ReturnType<typeof deriveCreativeDecisionInsight> }) {
  return (
    <div className="creative-decision">
      <div className="creative-decision__summary">
        <strong>Specialist read</strong>
        <p>{insight.diagnosis}</p>
      </div>
      <div className="creative-metric-strip">
        <span>
          <small>CPC</small>
          <strong>{formatCurrency(insight.cpc)}</strong>
        </span>
        <span>
          <small>CPL</small>
          <strong>{insight.cpl ? formatCurrency(insight.cpl) : '—'}</strong>
        </span>
        <span>
          <small>Lead rate</small>
          <strong>{formatRate(insight.leadRatePercent)}</strong>
        </span>
        <span>
          <small>Visit rate</small>
          <strong>{formatRate(insight.landingVisitRatePercent)}</strong>
        </span>
      </div>
      <div className="creative-decision-grid">
        <div>
          <strong>Replicate signals</strong>
          {insight.replicateSignals.map((signal) => (
            <span key={signal}>{signal}</span>
          ))}
        </div>
        <div>
          <strong>Watch risks</strong>
          {(insight.risks.length ? insight.risks : ['No major risk detected from the filtered metric window.']).map((risk) => (
            <span key={risk}>{risk}</span>
          ))}
        </div>
      </div>
      <div className="creative-next-action">
        <strong>Next action</strong>
        <p>{insight.nextAction}</p>
      </div>
    </div>
  )
}

function CommandCenterView({ data }: { data: DashboardData }) {
  const [tasks, setTasks] = useState<AgentTask[]>([])
  const [agents, setAgents] = useState<AgentSpec[]>([])
  const [systemChecklist, setSystemChecklist] = useState<SystemChecklist | null>(null)
  const [command, setCommand] = useState('Create a campaign with 3 VSLs: income, business automation, content creators. Use $100 each and optimize for Telegram START.')
  const [source, setSource] = useState<'dashboard' | 'telegram' | 'codex'>('dashboard')
  const [campaignGroupId, setCampaignGroupId] = useState('next-launch')
  const [segmentIds, setSegmentIds] = useState('income, business, creators')
  const [prepareApproval, setPrepareApproval] = useState(false)
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [isSendingTelegramTest, setIsSendingTelegramTest] = useState(false)
  const [message, setMessage] = useState<string | null>(null)

  const loadCommandCenter = async () => {
    const [result, checklist] = await Promise.all([
      getAgentCommandCenter(),
      fetch('/api/system/checklist')
        .then((response) => response.ok ? response.json() : null)
        .catch(() => null),
    ])
    setTasks(result.tasks)
    setAgents(result.agents)
    setSystemChecklist(checklist as SystemChecklist | null)
  }

  useEffect(() => {
    let cancelled = false
    void Promise.all([
      getAgentCommandCenter(),
      fetch('/api/system/checklist')
        .then((response) => response.ok ? response.json() : null)
        .catch(() => null),
    ])
      .then(([result, checklist]) => {
        if (!cancelled) {
          setTasks(result.tasks)
          setAgents(result.agents)
          setSystemChecklist(checklist as SystemChecklist | null)
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
              <span>{agent.readinessStatus ? labelRawSetting(agent.readinessStatus) : agent.requiresApproval ? 'Approval required' : 'Analysis ready'}</span>
              {agent.blockedReasons && agent.blockedReasons.length > 0 && (
                <small>{agent.blockedReasons.map(labelRawSetting).join(', ')}</small>
              )}
            </div>
          ))}
          {agents.length === 0 && <EmptyState compact />}
        </div>
      </article>

      <article className="panel">
        <PanelHeading eyebrow="Regression Checklist" title="Completion readiness" icon={CheckCircle2} />
        {systemChecklist ? (
          <>
            <div className="builder-summary command-summary">
              <MiniMetric label="Ready" value={`${systemChecklist.summary.ready}/${systemChecklist.summary.total}`} />
              <MiniMetric label="Partial" value={systemChecklist.summary.partial.toString()} />
              <MiniMetric label="Needs work" value={systemChecklist.summary.needs_attention.toString()} />
            </div>
            <div className="task-list">
              {systemChecklist.items.slice(0, 10).map((item) => (
                <div className={`task-item ${item.status}`} key={item.id}>
                  <div>
                    <strong>{item.title}</strong>
                    <p>{item.evidence}</p>
                  </div>
                  <span>{labelRawSetting(item.status)}</span>
                </div>
              ))}
            </div>
          </>
        ) : (
          <EmptyState compact />
        )}
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

function AgentOfficeView({
  latestCouncil,
  onCouncilReady,
}: {
  latestCouncil: AgentCouncilSession | null
  onCouncilReady: (council: AgentCouncilSession) => void
}) {
  const [command, setCommand] = useState(
    'Run strategy council: agents talk to each other, challenge weak assumptions, and create the best paused VSL campaign plan from the last 180 days.',
  )
  const [isRunning, setIsRunning] = useState(false)
  const [isPlaying, setIsPlaying] = useState(false)
  const [isImplementing, setIsImplementing] = useState(false)
  const [activeEventIndex, setActiveEventIndex] = useState(0)
  const [message, setMessage] = useState<string | null>(null)
  const [implementationResult, setImplementationResult] = useState<{
    approvalId: string
    status: string
    guardrail: string
  } | null>(null)
  const agents = latestCouncil?.agents ?? fallbackCouncilAgents()
  const events = latestCouncil?.events ?? []
  const safeActiveEventIndex = events.length ? Math.min(activeEventIndex, events.length - 1) : 0
  const activeEvent = events[safeActiveEventIndex]
  const activeRound = latestCouncil?.rounds.find((round) => activeEvent && round.events.some((event) => event.id === activeEvent.id))
  const fromPosition = getAgentDeskPosition(activeEvent?.fromAgent)
  const toPosition = getAgentApproachPosition(activeEvent?.fromAgent, activeEvent?.toAgent)
  const activeAgentIds = new Set(activeEvent ? [activeEvent.fromAgent, activeEvent.toAgent] : ['orchestrator'])
  const movingAgentName = activeEvent ? agentNameForId(agents, activeEvent.fromAgent) : 'Orchestrator'
  const progressLabel = latestCouncil
    ? `${Math.min(safeActiveEventIndex + 1, events.length)} of ${events.length} exchanges`
    : 'Waiting for a council session'

  useEffect(() => {
    if (!isPlaying || events.length <= 1) {
      return undefined
    }

    const timer = window.setInterval(() => {
      setActiveEventIndex((current) => {
        if (current >= events.length - 1) {
          window.clearInterval(timer)
          setIsPlaying(false)
          return current
        }
        return current + 1
      })
    }, 2200)

    return () => window.clearInterval(timer)
  }, [events.length, isPlaying])

  const startCouncil = async () => {
    if (!command.trim() || isRunning) {
      return
    }

    setIsRunning(true)
    setMessage('Running the strategy council...')
    try {
      const council = await runAgentCouncil(command)
      onCouncilReady(council)
      setActiveEventIndex(0)
      setIsPlaying(true)
      setMessage('Council session generated. Review the plan before creating any paused campaign draft.')
    } catch {
      setMessage('Could not run the council endpoint. Make sure the backend is running on port 8000.')
    } finally {
      setIsRunning(false)
    }
  }

  const implementCouncilPlan = async () => {
    if (!latestCouncil || isImplementing) {
      return
    }

    setIsImplementing(true)
    setImplementationResult(null)
    setMessage('Creating paused Meta campaign approval from the council plan...')
    try {
      const response = await fetch('/api/execution/prepare-campaign', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          playbook: latestCouncil.generatedPlaybook ?? null,
          reason: `Implemented from Agent Office council ${latestCouncil.id}. Create only a paused Meta campaign structure from the final council recommendations.`,
        }),
      })
      const result = (await response.json()) as { ok?: boolean; approval?: ApprovalRequest; detail?: string; error?: string }
      if (!response.ok || !result.ok || !result.approval) {
        setMessage(result.detail ?? result.error ?? `Implementation failed with ${response.status}`)
        return
      }
      setImplementationResult({
        approvalId: result.approval.id,
        status: result.approval.status,
        guardrail: result.approval.guardrailResult,
      })
      setMessage(`Paused campaign approval created: ${result.approval.id}. It remains review-gated and cannot publish or spend.`)
    } catch {
      setMessage('Could not reach the paused campaign implementation endpoint.')
    } finally {
      setIsImplementing(false)
    }
  }

  const stepEvent = (direction: -1 | 1) => {
    setIsPlaying(false)
    setActiveEventIndex((current) => Math.min(Math.max(current + direction, 0), Math.max(events.length - 1, 0)))
  }

  return (
    <section className="agent-office-view">
      <article className="panel panel-wide agent-office-brief">
        <PanelHeading eyebrow="Agent Office" title="Multi-agent strategy council" icon={Users} />
        <div className="agent-office-controls">
          <label>
            <span>Council task</span>
            <textarea value={command} onChange={(event) => setCommand(event.target.value)} />
          </label>
          <div className="agent-office-actions">
            <button className="sync-button" type="button" onClick={startCouncil} disabled={isRunning || !command.trim()}>
              <Bot size={16} />
              {isRunning ? 'Agents debating...' : 'Run council'}
            </button>
            {message && <small className="sync-message">{message}</small>}
          </div>
        </div>
        <div className="builder-summary command-summary">
          <MiniMetric label="Agents" value={agents.length.toString()} />
          <MiniMetric label="Rounds" value={(latestCouncil?.rounds.length ?? 0).toString()} />
          <MiniMetric label="Exchanges" value={(latestCouncil?.events.length ?? 0).toString()} />
          <MiniMetric
            label="Quality"
            value={latestCouncil ? `${latestCouncil.averageScoreOutOf10.toFixed(1)}/10` : 'Waiting'}
          />
        </div>
      </article>

      <article className="panel panel-wide agent-office-map-panel agent-office-main">
        <PanelHeading eyebrow="Top-View Office" title="Watch agents debate the campaign" icon={Bot} />
        <div className="office-status-strip">
          <div>
            <small>What is happening now</small>
            <strong>
              {activeEvent
                ? `${agentNameForId(agents, activeEvent.fromAgent)} is talking to ${agentNameForId(agents, activeEvent.toAgent)}`
                : 'Run the council to start the agent conversation'}
            </strong>
            <span>{activeRound ? `${activeRound.title}: ${activeRound.purpose}` : 'Agents will move between desks as they critique the plan.'}</span>
          </div>
          <div className="office-playback">
            <button type="button" onClick={() => stepEvent(-1)} disabled={!events.length || safeActiveEventIndex === 0}>
              Back
            </button>
            <button type="button" onClick={() => setIsPlaying((current) => !current)} disabled={!events.length}>
              {isPlaying ? 'Pause' : 'Play'}
            </button>
            <button type="button" onClick={() => stepEvent(1)} disabled={!events.length || safeActiveEventIndex >= events.length - 1}>
              Next
            </button>
            <span>{progressLabel}</span>
          </div>
        </div>
        <div className="agent-office-scene">
          <div className="agent-office-map" aria-label="Top-view animated agent office">
            <div className="office-floor-rug" />
            <div className="office-center-table">
              <strong>Strategy table</strong>
              <span>Final plan forms here after critique rounds</span>
            </div>
            {activeEvent && (
              <div
                className="moving-agent"
                style={
                  {
                    '--from-x': `${fromPosition.x}%`,
                    '--from-y': `${fromPosition.y}%`,
                    '--to-x': `${toPosition.x}%`,
                    '--to-y': `${toPosition.y}%`,
                  } as CSSProperties
                }
              >
                <Bot size={17} />
                <span>{movingAgentName}</span>
              </div>
            )}
          {agents.map((agent) => {
            const position = getAgentDeskPosition(agent.id)
            const visual = getAgentVisual(agent.id)
            const isActive = activeAgentIds.has(agent.id)
            const isSpeaker = activeEvent?.fromAgent === agent.id
            const isReceiver = activeEvent?.toAgent === agent.id
            return (
              <div
                className={`agent-desk ${agent.id === 'orchestrator' ? 'orchestrator' : ''} ${isActive ? 'active' : ''} ${isSpeaker ? 'speaker' : ''} ${isReceiver ? 'receiver' : ''}`}
                data-agent-id={agent.id}
                style={{ left: `${position.x}%`, top: `${position.y}%`, '--agent-color': visual.color } as CSSProperties}
                key={agent.id}
              >
                <div className="agent-circle">
                  <Bot size={20} />
                  <i />
                </div>
                <div className="agent-label-card">
                  <strong>{agent.name}</strong>
                  <span>{visual.shortRole}</span>
                  <small>{councilScoreForAgent(latestCouncil, agent.id)}</small>
                </div>
              </div>
            )
          })}
          </div>
          <div className="active-exchange-card">
            <small>{activeRound?.title ?? 'Waiting'}</small>
            <strong>{activeEvent?.question ?? 'No exchange selected yet'}</strong>
            <p>{activeEvent?.answer ?? 'Run the council to see each agent question, critique, and refine the setup.'}</p>
          </div>
        </div>
      </article>

      <article className="panel">
        <PanelHeading eyebrow="Timeline Replay" title="Every agent exchange" icon={RadioTower} />
        <div className="council-event-list timeline-replay">
          {events.length > 0 ? (
            events.map((event, index) => (
              <button
                className={index === safeActiveEventIndex ? 'council-event active' : 'council-event'}
                type="button"
                onClick={() => {
                  setIsPlaying(false)
                  setActiveEventIndex(index)
                }}
                key={event.id}
              >
                <CouncilEventCard event={event} />
              </button>
            ))
          ) : (
            <EmptyState compact />
          )}
        </div>
      </article>

      <article className="panel">
        <PanelHeading eyebrow="Agent Scores" title="Council quality checks" icon={Gauge} />
        <div className="agent-score-list">
          {latestCouncil?.scores.length ? (
            latestCouncil.scores.map((score) => (
              <div className="agent-score-row" key={score.agentId}>
                <strong>{labelRawSetting(score.agentId)}</strong>
                <span>{score.scoreOutOf10.toFixed(1)}/10</span>
                <p>{score.reason}</p>
              </div>
            ))
          ) : (
            <EmptyState compact />
          )}
        </div>
      </article>

      <article className="panel panel-wide">
        <PanelHeading eyebrow="Critique Rounds" title="How the plan improved" icon={ListChecks} />
        <div className="council-round-grid">
          {latestCouncil?.rounds.length ? (
            latestCouncil.rounds.map((round) => (
              <div className="council-round" key={round.id}>
                <strong>{round.title}</strong>
                <p>{round.purpose}</p>
                <small>{round.events.length} exchanges</small>
                {round.events.slice(0, 3).map((event) => (
                  <span key={event.id}>{labelRawSetting(event.fromAgent)} asked {labelRawSetting(event.toAgent)}</span>
                ))}
              </div>
            ))
          ) : (
            <EmptyState compact />
          )}
        </div>
      </article>

      <article className="panel panel-wide">
        <PanelHeading eyebrow="Final Plan" title="Council output before approval" icon={ClipboardCheck} />
        {latestCouncil ? (
          <CouncilFinalPlan
            council={latestCouncil}
            isImplementing={isImplementing}
            implementationResult={implementationResult}
            onImplement={implementCouncilPlan}
          />
        ) : (
          <EmptyState compact />
        )}
      </article>
    </section>
  )
}

function CouncilEventCard({ event }: { event: AgentCouncilSession['events'][number] }) {
  return (
    <>
      <div className="council-event-flow">
        <span>{labelRawSetting(event.fromAgent)}</span>
        <i />
        <span>{labelRawSetting(event.toAgent)}</span>
      </div>
      <strong>{event.question}</strong>
      <p>{event.answer}</p>
      <small>{labelRawSetting(event.state)}</small>
    </>
  )
}

function CouncilFinalPlan({
  council,
  isImplementing,
  implementationResult,
  onImplement,
}: {
  council: AgentCouncilSession
  isImplementing: boolean
  implementationResult: { approvalId: string; status: string; guardrail: string } | null
  onImplement: () => void
}) {
  const finalPlan = council.finalPlan
  const canImplement = finalPlan.executionDecision.canCreatePausedDraft && !isImplementing
  return (
    <div className="council-final-plan">
      <div className="council-plan-summary">
        <strong>{finalPlan.summary}</strong>
        <p>{finalPlan.campaignNamingRule}</p>
      </div>
      <div className="council-plan-grid">
        <div>
          <span>Audience</span>
          <strong>{finalPlan.audienceDecision.primary}</strong>
          {finalPlan.audienceDecision.segments.slice(0, 4).map((segment) => (
            <small key={segment.name}>
              {segment.name}: {formatCurrency(segment.budgetUsd)}/day · {segment.locations.join(', ')}
            </small>
          ))}
        </div>
        <div>
          <span>Creative</span>
          <strong>{finalPlan.creativeDecision.topCreative}</strong>
          <small>{finalPlan.creativeDecision.rule}</small>
          <small>{finalPlan.creativeDecision.topCreativePool.join(', ')}</small>
        </div>
        <div>
          <span>Placement</span>
          <strong>{finalPlan.placementDecision.primary}</strong>
          <small>{finalPlan.placementDecision.rule}</small>
        </div>
        <div>
          <span>Funnel</span>
          <strong>{finalPlan.funnelDecision.requiredEvents.join(', ')}</strong>
          <small>{finalPlan.funnelDecision.rule}</small>
        </div>
        <div>
          <span>Monitoring</span>
          <strong>Every {finalPlan.monitoringDecision.cadenceHours} hours</strong>
          <small>{finalPlan.monitoringDecision.watchMetrics.join(', ')}</small>
          <small>{finalPlan.monitoringDecision.rule}</small>
        </div>
        <div>
          <span>Safety</span>
          <strong>{finalPlan.executionDecision.canCreatePausedDraft ? 'Paused draft allowed' : 'Draft blocked'}</strong>
          <small>Publish: {finalPlan.executionDecision.canPublish ? 'allowed' : 'blocked'}</small>
          <small>Approval: {finalPlan.executionDecision.approvalRequired ? 'required' : 'not required'}</small>
        </div>
      </div>
      <div className="council-experiment-list">
        {finalPlan.experimentDecision.map((experiment) => (
          <div key={`${experiment.day}-${experiment.test}`}>
            <strong>{experiment.day}</strong>
            <span>{experiment.test}</span>
            <small>{experiment.decisionMetric}: {experiment.action}</small>
          </div>
        ))}
      </div>
      <div className="council-implementation-actions">
        <div>
          <strong>Turn this council output into an executable paused campaign packet</strong>
          <p>
            This uses the generated playbook, creates a Meta approval request, and keeps every campaign/ad set paused until a guarded execution step is approved.
          </p>
        </div>
        <button className="sync-button" type="button" onClick={onImplement} disabled={!canImplement}>
          <ClipboardCheck size={16} />
          {isImplementing ? 'Implementing...' : 'Implemented'}
        </button>
      </div>
      {implementationResult && (
        <div className="implementation-result" role="status">
          <strong>Paused campaign approval created</strong>
          <span>{implementationResult.approvalId}</span>
          <small>Status: {labelRawSetting(implementationResult.status)} · Guardrail: {labelRawSetting(implementationResult.guardrail)}</small>
        </div>
      )}
    </div>
  )
}

function councilScoreForAgent(council: AgentCouncilSession | null, agentId: string) {
  const score = council?.scores.find((item) => item.agentId === agentId)
  return score ? `${score.scoreOutOf10.toFixed(1)}/10` : 'not scored'
}

function agentNameForId(agents: AgentCouncilSession['agents'], agentId?: string) {
  return agents.find((agent) => agent.id === agentId)?.name ?? labelRawSetting(agentId ?? 'agent')
}

function getAgentApproachPosition(fromAgentId?: string, toAgentId?: string) {
  const target = getAgentDeskPosition(toAgentId)
  const source = getAgentDeskPosition(fromAgentId)
  const deltaX = target.x - source.x
  const deltaY = target.y - source.y
  const distance = Math.max(Math.sqrt(deltaX * deltaX + deltaY * deltaY), 1)
  return {
    x: target.x - (deltaX / distance) * 16,
    y: target.y - (deltaY / distance) * 16,
  }
}

function getAgentDeskPosition(agentId?: string) {
  const positions: Record<string, { x: number; y: number }> = {
    orchestrator: { x: 50, y: 13 },
    audit: { x: 24, y: 18 },
    meta_ai_strategist: { x: 76, y: 18 },
    audience: { x: 19, y: 42 },
    creative: { x: 81, y: 42 },
    placement: { x: 24, y: 73 },
    funnel: { x: 50, y: 84 },
    experiment: { x: 76, y: 73 },
    monitoring: { x: 38, y: 30 },
    execution: { x: 62, y: 30 },
  }
  return positions[agentId ?? 'orchestrator'] ?? { x: 50, y: 50 }
}

function getAgentVisual(agentId: string) {
  const visuals: Record<string, { color: string; shortRole: string }> = {
    orchestrator: { color: '#0f766e', shortRole: 'coordinates' },
    audit: { color: '#2563eb', shortRole: 'audits data' },
    meta_ai_strategist: { color: '#7c3aed', shortRole: 'Meta AI read' },
    audience: { color: '#db2777', shortRole: 'audience' },
    creative: { color: '#ea580c', shortRole: 'creative' },
    placement: { color: '#0891b2', shortRole: 'placements' },
    funnel: { color: '#16a34a', shortRole: 'tracking' },
    experiment: { color: '#ca8a04', shortRole: 'testing' },
    monitoring: { color: '#475569', shortRole: 'monitors' },
    execution: { color: '#dc2626', shortRole: 'paused drafts' },
  }
  return visuals[agentId] ?? { color: '#64748b', shortRole: labelRawSetting(agentId) }
}

function fallbackCouncilAgents(): AgentCouncilSession['agents'] {
  return [
    { id: 'orchestrator', name: 'Orchestrator', role: 'routes work and asks follow-up questions', state: 'waiting', requiresApproval: true },
    { id: 'audit', name: 'Performance Auditor', role: 'checks 180-day evidence', state: 'waiting', requiresApproval: false },
    { id: 'meta_ai_strategist', name: 'Meta AI Strategist', role: 'captures Meta AI recommendations', state: 'waiting', requiresApproval: false },
    { id: 'audience', name: 'Audience Specialist', role: 'ranks interests, age, gender, geo', state: 'waiting', requiresApproval: false },
    { id: 'creative', name: 'Creative Analyst', role: 'ranks videos and hooks', state: 'waiting', requiresApproval: false },
    { id: 'placement', name: 'Placement Optimizer', role: 'guards Instagram placement mix', state: 'waiting', requiresApproval: false },
    { id: 'funnel', name: 'Funnel Tracking Agent', role: 'tracks landing page and Telegram starts', state: 'waiting', requiresApproval: false },
    { id: 'experiment', name: 'Experiment Agent', role: 'designs A/B tests and stop rules', state: 'waiting', requiresApproval: false },
    { id: 'monitoring', name: 'Monitoring Agent', role: 'checks campaigns every four hours', state: 'waiting', requiresApproval: false },
    { id: 'execution', name: 'Execution Agent', role: 'creates paused drafts only', state: 'waiting', requiresApproval: true },
  ]
}

function agentStatusTone(agent: AgentSpec) {
  if (agent.readinessStatus === 'blocked') {
    return 'danger'
  }
  if (agent.readinessStatus === 'needs_data') {
    return 'warning'
  }
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
        <span>CPC</span>
        <span>CPL</span>
        <span>Lead rate</span>
        <span>START rate</span>
        <span>Leads</span>
        <span>Buyers</span>
        <span>Quality</span>
        <span>Action</span>
      </div>
      {rows.map((row) => (
        <div className="ranking-row" key={`${row.category}-${row.id}`}>
          <span>#{row.rank}</span>
          <strong title={row.name}>{row.name}</strong>
          <span>{formatCurrency(row.spendUsd)}</span>
          <span>{formatCurrency(row.cpc)}</span>
          <span>{row.cpl ? formatCurrency(row.cpl) : '—'}</span>
          <span>{row.leadRatePercent.toFixed(1)}%</span>
          <span>{row.telegramStartRatePercent.toFixed(1)}%</span>
          <span>{formatNumber(row.leads)}</span>
          <span>{formatNumber(row.purchases)}</span>
          <em className={row.tone}>{row.qualityScore}</em>
          <small>{row.recommendedAction}</small>
        </div>
      ))}
    </div>
  )
}

function CreativePreview({ creative }: { creative: Creative }) {
  const [videoAsset, setVideoAsset] = useState<{
    creativeId: string
    videoUrl?: string
    posterUrl?: string
    permalinkUrl?: string
  } | null>(null)
  const fetchedAsset = videoAsset?.creativeId === creative.id ? videoAsset : null
  const resolvedVideoUrl = creative.videoUrl ?? fetchedAsset?.videoUrl ?? ''
  const resolvedPosterUrl = creative.assetUrl ?? fetchedAsset?.posterUrl ?? ''
  const resolvedPermalinkUrl = normalizeMetaPermalink(fetchedAsset?.permalinkUrl)

  useEffect(() => {
    if (!creative.videoId || creative.videoUrl) {
      return
    }

    let cancelled = false
    void fetch(`/api/meta/video/${creative.videoId}`)
      .then((response) => (response.ok ? response.json() : null))
      .then((payload: { videoUrl?: string; posterUrl?: string; permalinkUrl?: string } | null) => {
        if (cancelled || !payload) {
          return
        }
        setVideoAsset({
          creativeId: creative.id,
          videoUrl: payload.videoUrl,
          posterUrl: payload.posterUrl,
          permalinkUrl: payload.permalinkUrl,
        })
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
              ? `${creative.hookType} / Meta video ID ${creative.videoId}`
              : creative.hookType}
        </span>
        {!resolvedVideoUrl && resolvedPermalinkUrl && (
          <a href={resolvedPermalinkUrl} target="_blank" rel="noreferrer">
            Open Meta video
          </a>
        )}
      </div>
    </div>
  )
}

function normalizeMetaPermalink(permalinkUrl?: string) {
  if (!permalinkUrl) {
    return ''
  }
  if (/^https?:\/\//i.test(permalinkUrl)) {
    return permalinkUrl
  }
  return `https://www.facebook.com${permalinkUrl.startsWith('/') ? permalinkUrl : `/${permalinkUrl}`}`
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
        <ChartFrame tall>
          <BarChart data={placements}>
            <CartesianGrid strokeDasharray="3 3" vertical={false} />
            <XAxis dataKey="name" tickLine={false} axisLine={false} />
            <YAxis tickLine={false} axisLine={false} />
            <Tooltip />
            <Bar dataKey="value" fill="#3b82f6" radius={[5, 5, 0, 0]} />
            <Bar dataKey="buyers" fill="#1f9d8a" radius={[5, 5, 0, 0]} />
          </BarChart>
        </ChartFrame>
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
  const [proposal, setProposal] = useState<DraftCampaignProposal | null>(null)
  const [knowledgeAvailable, setKnowledgeAvailable] = useState(false)
  const [isGenerating, setIsGenerating] = useState(false)
  const [isPreparing, setIsPreparing] = useState(false)
  const [isGeneratingProposal, setIsGeneratingProposal] = useState(false)
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

  const generateDraftProposal = async () => {
    if (isGeneratingProposal || !selectedPlaybookHasSegments) {
      return
    }

    setIsGeneratingProposal(true)
    setMessage('Generating review-only draft proposal...')
    try {
      const response = await fetch('/api/campaign-proposals/draft', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ playbook: selectedPlaybook ?? null }),
      })
      const result = (await response.json()) as { ok?: boolean; proposal?: DraftCampaignProposal; detail?: string; error?: string }
      if (!response.ok || !result.ok || !result.proposal) {
        setMessage(result.detail ?? result.error ?? `Draft proposal failed with ${response.status}`)
        return
      }
      setProposal(result.proposal)
      setMessage('Review-only draft proposal generated. Nothing was created in Meta.')
    } catch {
      setMessage('Could not reach the draft proposal endpoint.')
    } finally {
      setIsGeneratingProposal(false)
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
          <button className="sync-button secondary" type="button" onClick={generateDraftProposal} disabled={isGeneratingProposal || !selectedPlaybookHasSegments}>
            <ClipboardCheck size={16} />
            {isGeneratingProposal ? 'Generating...' : 'Generate draft proposal'}
          </button>
          {message && <small className="sync-message">{message}</small>}
        </div>
      </article>

      <article className="panel panel-wide">
        <PanelHeading eyebrow="Review-Only Draft Proposal" title="Paused campaign packet" icon={ClipboardCheck} />
        {proposal ? (
          <div className="proposal-layout">
            <div className="proposal-summary">
              <MiniMetric label="Campaign status" value={proposal.draftCampaign.status} />
              <MiniMetric label="Draft ad sets" value={proposal.draftAdSets.length.toString()} />
              <MiniMetric label="Daily budget" value={formatCurrency(proposal.budgetPlan.totalDailyBudgetUsd)} />
              <MiniMetric label="Tracking" value={labelRawSetting(proposal.trackingReadiness.status)} />
            </div>
            <div className="metric-list">
              <div><strong>Campaign</strong><span>{proposal.draftCampaign.name}</span></div>
              <div><strong>Recommended placements</strong><span>{proposal.recommendedPlacements.map(labelRawSetting).join(', ')}</span></div>
              <div><strong>Avoid placements</strong><span>{proposal.avoidPlacements.map(labelRawSetting).join(', ')}</span></div>
              <div><strong>Approval packet</strong><span>{proposal.approvalPacket.status} / {proposal.approvalPacket.guardrailResult}</span></div>
            </div>
            <div className="proposal-checklist">
              {proposal.operatorChecklist.slice(0, 5).map((item) => (
                <span key={item}>{item}</span>
              ))}
            </div>
          </div>
        ) : (
          <div className="empty-panel compact">
            <ClipboardCheck size={24} />
            <strong>No proposal generated yet</strong>
            <p>Generate a review-only packet to inspect paused campaign/ad set payloads before creating anything in Meta.</p>
          </div>
        )}
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

          {strategy.launchPacket && (
            <article className="panel panel-wide">
              <PanelHeading eyebrow="Launch Packet" title="Operator-ready decision brief" icon={ListChecks} />
              <div className="builder-summary">
                <MiniMetric label="Decision" value={labelRawSetting(strategy.launchPacket.decision)} />
                <MiniMetric label="Primary goal" value={labelEventName(strategy.launchPacket.primaryGoal)} />
                <MiniMetric label="Monitor every" value={`${strategy.launchPacket.monitoringPlan.cadenceHours}h`} />
                <MiniMetric label="Publish" value={strategy.launchPacket.approvalPlan.publishBlocked ? 'Blocked' : 'Allowed'} />
              </div>
              <div className="strategy-knowledge-grid">
                <KnowledgeList title="Use placements" items={strategy.launchPacket.placementPlan.use.map(labelRawSetting)} />
                <KnowledgeList title="Avoid / isolate" items={strategy.launchPacket.placementPlan.avoid.map(labelRawSetting)} />
                <KnowledgeList title="Required funnel events" items={strategy.launchPacket.funnelPlan.requiredEvents.map(labelEventName)} />
                <KnowledgeList title="Watch metrics" items={strategy.launchPacket.monitoringPlan.watchMetrics} />
              </div>
              <div className="proposal-checklist">
                {strategy.launchPacket.regressionChecklist.slice(0, 6).map((item) => (
                  <span key={item}>{item}</span>
                ))}
              </div>
            </article>
          )}

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
      <CampaignWatchPanel items={data.campaignWatch ?? []} />
      <MonitoringAlertsPanel data={data} />
      <TopProblemsPanel data={data} />
      <InsightsPanel data={data} />
    </section>
  )
}

function CampaignWatchPanel({ items }: { items: CampaignWatchItem[] }) {
  return (
    <article className="panel panel-wide">
      <PanelHeading eyebrow="New Campaign Watch" title="Current campaign decisions" icon={Gauge} />
      {items.length === 0 ? (
        <EmptyState
          compact
          title="No current campaigns to watch"
          body="Sync recent Meta data or refresh the dashboard after a new campaign is created."
        />
      ) : (
        <div className="campaign-watch-list">
          {items.slice(0, 6).map((item) => (
            <div className={`campaign-watch-card ${item.tone}`} key={item.campaignId}>
              <div>
                <small>{item.currentDate} | {item.status} | {item.daysObserved} observed days</small>
                <strong>{item.campaignName}</strong>
                <p>{item.reason}</p>
              </div>
              <div className="campaign-watch-metrics">
                <MiniMetric label="Spend" value={formatCurrency(item.spendUsd)} />
                <MiniMetric label="CPC" value={formatCurrency(item.cpc)} />
                <MiniMetric label="CPL" value={item.cpl > 0 ? formatCurrency(item.cpl) : '-'} />
                <MiniMetric label="Lead rate" value={`${item.leadRatePercent.toFixed(1)}%`} />
                <MiniMetric label="START rate" value={`${item.telegramStartRatePercent.toFixed(1)}%`} />
              </div>
              <div className="campaign-watch-actions">
                <em>{item.decision}</em>
                <ul>
                  {item.nextActions.slice(0, 3).map((action) => (
                    <li key={action}>{action}</li>
                  ))}
                </ul>
              </div>
            </div>
          ))}
        </div>
      )}
    </article>
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
                {alert.whyItMatters ? <p>{alert.whyItMatters}</p> : null}
                <p>{alert.recommendedActions.slice(0, 2).join(' ')}</p>
              </div>
            </div>
          ))
        )}
      </div>
    </article>
  )
}

function SettingsView({
  data,
  metaStatus,
  onDashboardRefresh,
}: {
  data: DashboardData
  metaStatus: MetaStatus | null
  onDashboardRefresh?: () => Promise<DashboardData>
}) {
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
      setSyncMessage(
        result.llmEnabled
          ? 'Sync complete. LLM analysis saved. Refreshing dashboard data...'
          : 'Sync complete. Rule-based analysis saved. Refreshing dashboard data...',
      )
      if (onDashboardRefresh) {
        await onDashboardRefresh()
      }
      setSyncMessage(result.llmEnabled ? 'Sync complete. Dashboard is updated.' : 'Sync complete. Dashboard is updated.')
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

function Score({ label, value, tone }: { label: string; value: number; tone: Tone }) {
  return (
    <div className={`score-card ${tone}`}>
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  )
}

function EmptyState({
  compact = false,
  title = 'No matching data',
  body = 'Adjust filters to restore the current dashboard view.',
  onReset,
}: {
  compact?: boolean
  title?: string
  body?: string
  onReset?: () => void
}) {
  return (
    <div className={compact ? 'empty-state compact' : 'empty-state'}>
      <AlertTriangle size={22} />
      <strong>{title}</strong>
      <p>{body}</p>
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
