import { useEffect, useMemo, useState, type ChangeEvent } from 'react'
import {
  AlertTriangle,
  BarChart3,
  Bot,
  Send,
  CheckCircle2,
  CircleDollarSign,
  ClipboardCheck,
  Film,
  LayoutDashboard,
  ListChecks,
  MousePointerClick,
  RadioTower,
  RefreshCcw,
  Settings,
  ShieldAlert,
  SlidersHorizontal,
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
  Legend,
  Line,
  LineChart,
  Pie,
  PieChart,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { COLORS, iconMap } from './dashboard/constants'
import { RankingsView } from './dashboard/views/RankingsView'
import { SettingsView } from './dashboard/views/SettingsView'
import { ChartFrame } from './dashboard/shared/ChartFrame'
import { ChatMessageContent } from './dashboard/shared/ChatMessageContent'
import { EmptyState } from './dashboard/shared/EmptyState'
import { MediaThumb } from './dashboard/shared/MediaThumb'
import { MiniMetric } from './dashboard/shared/MiniMetric'
import { PanelHeading } from './dashboard/shared/PanelHeading'
import {
  deriveCreativeScores,
  deriveFunnel,
  derivePlacementScores,
  deriveTrend,
  filterMetricsForDashboard,
  formatNumber,
  getCampaignOptions,
  getDateWindow,
} from '../lib/analytics'
import {
  chartTooltipFormatter,
  formatAxisCurrency,
  formatChartCurrency,
  formatChartNumber,
} from '../lib/chartConfig'
import {
  formatCurrency,
  formatDateTime,
  formatPercent,
  formatRate,
  getDashboardAnchorDate,
  labelPlacement,
  labelRawSetting,
  shortCampaignLabel,
  shortText,
  sumBy,
} from '../lib/format'
import { buildOperatorAttention } from '../lib/operatorAttention'
import { askAgent } from '../services/agentChatProvider'
import { getAgentCommandCenter } from '../services/agentTaskProvider'
import { getMetaStatus, type MetaStatus } from '../services/metaStatusProvider'
import type {
  AgentSpec,
  AgentCouncilSession,
  AgentTask,
  ApprovalRequest,
  ProactiveOpportunity,
  Creative,
  DashboardData,
  DashboardFilters,
  DashboardKpi,
  DailyAdMetric,
  Tone,
  TrackingHealthItem,
} from '../types/marketing'

const navItems = [
  { id: 'chat', label: 'Chat', icon: Send },
  { id: 'overview', label: 'Monitor', icon: LayoutDashboard },
  { id: 'rankings', label: 'Rankings', icon: BarChart3 },
  { id: 'settings', label: 'Settings', icon: Settings },
] as const

type ViewId = (typeof navItems)[number]['id']

// The single <h1> must describe the current view so screen-reader users (and
// the document outline) reflect where they are, not a fixed title.
function viewHeading(view: ViewId): string {
  switch (view) {
    case 'chat':
      return 'Set up a campaign by chatting'
    case 'rankings':
      return 'Performance Rankings'
    case 'settings':
      return 'Settings & Data Sources'
    case 'overview':
    default:
      return 'Campaign Audit Dashboard'
  }
}

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
  const [activeView, setActiveView] = useState<ViewId>('chat')
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
        end: window.end,
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

  // Jump from the decision surface into the agent chat, pre-seeded with the question.
  const askAgentsAbout = (message: string) => {
    setActiveView('chat')
    void sendChatMessage(message)
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
          <h1>{viewHeading(activeView)}</h1>
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

      {activeView !== 'chat' && <Filters data={data} filters={filters} onChange={setFilters} />}

      {/* Chat-first front door: set up a campaign by chatting; the agent drafts a
          paused packet and the approval cards execute it — all on one screen. */}
      {activeView === 'chat' && (
        <CampaignChatView
          data={data}
          chatMessages={chatMessages}
          chatInput={chatInput}
          isChatLoading={isChatLoading}
          onChatInputChange={setChatInput}
          onChatSend={sendChatMessage}
        />
      )}

      {/* Empty state is scoped to the data-driven Overview only, so an over-narrow
          filter never hides Settings (reconnect) or Command Center (ask the agent). */}
      {activeView === 'overview' &&
        (hasData ? (
          <Overview
            data={data}
            kpis={filteredKpis}
            creativeScores={creativeScores}
            funnel={funnel}
            trend={trend}
            placements={placements}
            onAskWhy={askAgentsAbout}
          />
        ) : (
          <EmptyState onReset={() => setFilters(defaultFilters)} />
        ))}
      {activeView === 'rankings' && <RankingsView data={data} metrics={filteredMetrics} />}
      {activeView === 'settings' && <SettingsView data={data} metaStatus={metaStatus} onDashboardRefresh={onRefresh} />}
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

const CHAT_STARTER_PROMPTS = [
  'Draft a paused campaign using my best audiences and creatives',
  'Plan a 3-VSL launch at $100/day optimized for Telegram START',
  'Which audience should I scale next, and why?',
  'What are my best creatives right now?',
]

function CampaignChatView({
  data,
  chatMessages,
  chatInput,
  isChatLoading,
  onChatInputChange,
  onChatSend,
}: {
  data: DashboardData
  chatMessages: ChatMessage[]
  chatInput: string
  isChatLoading: boolean
  onChatInputChange: (value: string) => void
  onChatSend: (message: string) => void
}) {
  const [tasks, setTasks] = useState<AgentTask[]>([])
  const [agents, setAgents] = useState<AgentSpec[]>([])

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
          setTasks([])
          setAgents([])
        }
      })
    return () => {
      cancelled = true
    }
  }, [])

  const approvalAgents = agents.filter((agent) => agent.requiresApproval).length
  const pendingTasks = tasks.filter((task) => task.status === 'planning' || task.status === 'needs_approval').length

  return (
    <section className="campaign-chat-view">
      <section className="panel campaign-chat-intro">
        <PanelHeading eyebrow="Front door" title="Set up a campaign by chatting" icon={Send} />
        {typeof data.funnelSummary?.rates?.telegramStartRate === 'number' && (
          <span className="provenance-chip rule funnel-context-chip">
            Live funnel · Telegram START rate {formatRate(data.funnelSummary.rates.telegramStartRate)}
          </span>
        )}
        <p>
          Describe what you want and the agent drafts an approval-safe, paused campaign — reusing your
          best audiences and winning creatives. Review it in the approval card below, then create it in
          Meta. Nothing goes live without your explicit approval.
        </p>
        <div className="campaign-chat-starters">
          {CHAT_STARTER_PROMPTS.map((prompt) => (
            <button
              key={prompt}
              type="button"
              className="sync-button secondary"
              disabled={isChatLoading}
              onClick={() => onChatSend(prompt)}
            >
              {prompt}
            </button>
          ))}
        </div>
      </section>

      <AgentChatPanel
        messages={chatMessages}
        input={chatInput}
        isLoading={isChatLoading}
        onInputChange={onChatInputChange}
        onSend={onChatSend}
      />

      <ApprovalQueue data={data} />

      <details className="overview-details">
        <summary>Agent activity</summary>
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
      </details>
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
            {message.role === 'agent' && message.sources && message.sources.length > 0 && (
              <span
                className={`provenance-chip ${
                  message.sources.includes('openai') ? 'llm' : message.sources.includes('error') ? 'error' : 'rule'
                }`}
              >
                {message.sources.includes('openai')
                  ? 'Live + LLM'
                  : message.sources.includes('error')
                    ? 'Unavailable'
                    : 'Rule-based'}
              </span>
            )}
            <ChatMessageContent content={message.content} />
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
  onAskWhy,
}: {
  data: DashboardData
  kpis: DashboardKpi[]
  creativeScores: ReturnType<typeof deriveCreativeScores>
  funnel: ReturnType<typeof deriveFunnel>
  trend: ReturnType<typeof deriveTrend>
  placements: ReturnType<typeof derivePlacementScores>
  onAskWhy: (message: string) => void
}) {
  return (
    <>
      {/* DECIDE: hero, KPIs, and the "what's wrong" diagnosis row */}
      <DecisionHero data={data} onAskWhy={onAskWhy} />
      <KpiGrid kpis={kpis} />
      <section className="overview-command-grid">
        <FunnelPanel funnel={funnel} />
        <TopProblemsPanel data={data} />
      </section>

      {/* TRENDS: primary charts, lifted directly under the KPIs */}
      <section className="overview-primary-grid">
        <TrendPanel trend={trend} />
        <SpendPanel trend={trend} />
      </section>

      {/* REVIEW: approvals surfaced high — acting on suggestions is the point */}
      <section className="overview-review-grid">
        <ApprovalQueue data={data} />
        <InsightsPanel data={data} />
      </section>

      {/* DETAIL: dense breakdowns deferred, collapsed by default */}
      <details className="overview-details">
        <summary>Show detailed breakdowns</summary>
        <section className="dashboard-grid">
          <CreativeTablePanel creativeScores={creativeScores} />
          <PlacementPanel placements={placements} />
          <AudiencePanel data={data} />
        </section>
      </details>
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
        {funnel.map((item) => {
          // Width must reflect the actual data (share of the top-of-funnel
          // value), not the row index. A small floor keeps tiny stages legible.
          const topValue = funnel[0]?.value ?? 0
          const widthPercent = topValue > 0 ? Math.max(7, (item.value / topValue) * 100) : 7
          return (
            <div className="funnel-row" key={item.step}>
              <div>
                <span>{item.step}</span>
                <strong>{formatNumber(item.value)}</strong>
              </div>
              <div className="funnel-track">
                <div className="funnel-fill" style={{ width: `${widthPercent}%` }} />
              </div>
              <em>{item.rate}</em>
            </div>
          )
        })}
      </div>
    </article>
  )
}

function TrendPanel({ trend }: { trend: ReturnType<typeof deriveTrend> }) {
  const totalLeads = sumBy(trend, (point) => point.leads)
  const totalBuyers = sumBy(trend, (point) => point.buyers)
  const summary = `Daily trend over ${trend.length} days: ${formatChartNumber(totalLeads)} leads and ${formatChartNumber(totalBuyers)} buyers total.`
  return (
    <article className="panel">
      <PanelHeading eyebrow="Trend" title="Spend, leads, buyers" icon={TrendingUp} />
      <ChartFrame summary={summary}>
        <LineChart data={trend}>
          <CartesianGrid strokeDasharray="3 3" vertical={false} />
          <XAxis dataKey="day" tickLine={false} axisLine={false} />
          <YAxis tickLine={false} axisLine={false} tickFormatter={formatChartNumber} />
          <Tooltip formatter={chartTooltipFormatter} />
          <Legend />
          <Line type="monotone" dataKey="leads" name="Leads" stroke={COLORS[0]} strokeWidth={3} dot={false} />
          <Line type="monotone" dataKey="buyers" name="Buyers" stroke={COLORS[3]} strokeWidth={3} dot={false} />
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

function DecisionHero({ data, onAskWhy }: { data: DashboardData; onAskWhy: (message: string) => void }) {
  const attentionItems = buildOperatorAttention(data)
  const topItem = attentionItems[0]
  const hasDanger = attentionItems.some((item) => item.tone === 'danger')
  const hasWarning = attentionItems.some((item) => item.tone === 'warning')
  const status = hasDanger ? 'Action needed' : hasWarning ? 'Watch closely' : 'Healthy'
  const tone = hasDanger ? 'danger' : hasWarning ? 'warning' : 'good'
  const reason = topItem?.reason ?? 'No urgent campaign issue is visible in the current data window.'
  const action = topItem?.action ?? 'Keep monitoring the strongest campaigns and protect tracking quality.'
  const risk = hasDanger
    ? 'Costs or funnel leakage may compound if ignored.'
    : hasWarning
      ? 'Performance may drift if the warning is not watched.'
      : 'Main risk is missing new shifts if data is not refreshed.'

  return (
    <section className={`decision-hero ${tone}`}>
      <div>
        <span className="decision-hero-status">{status}</span>
        <h2>{topItem?.title ?? 'Campaign system is stable'}</h2>
        <p>{reason}</p>
      </div>
      <div className="decision-block-grid">
        <div>
          <small>Best next action</small>
          <strong>{action}</strong>
        </div>
        <div>
          <small>Risk if ignored</small>
          <strong>{risk}</strong>
        </div>
        <button
          className="sync-button secondary"
          type="button"
          onClick={() =>
            onAskWhy(
              topItem
                ? `Why is "${topItem.title}" the top priority right now, and what exactly should I do about it?`
                : 'What is the most important thing to do with my campaigns right now, and why?',
            )
          }
        >
          <Bot size={16} />
          Ask agents why
        </button>
      </div>
    </section>
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
  const topPlacement = placements[0]
  const summary = topPlacement
    ? `Spend share across ${placements.length} placements; ${topPlacement.name} leads at ${topPlacement.value}%.`
    : 'Spend share by placement channel.'
  return (
    <article className="panel">
      <PanelHeading eyebrow="Placement" title="Spend share by channel" icon={RadioTower} />
      <ChartFrame summary={summary}>
        <PieChart>
          <Pie data={placements} dataKey="value" nameKey="name" innerRadius={58} outerRadius={88}>
            {placements.map((entry, index) => (
              <Cell key={entry.name} fill={COLORS[index % COLORS.length]} />
            ))}
          </Pie>
          <Tooltip formatter={(value, name) => [`${Array.isArray(value) ? value[0] : value}% spend`, String(name ?? '')]} />
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
  const totalSubs = sumBy(data.audience, (segment) => segment.subs)
  const totalBuyers = sumBy(data.audience, (segment) => segment.buyers)
  const summary = `Subscribers vs buyers across ${data.audience.length} audience segments: ${formatChartNumber(totalSubs)} subscribers and ${formatChartNumber(totalBuyers)} buyers total.`
  return (
    <article className="panel panel-wide">
      <PanelHeading eyebrow="Audience Quality" title="Purchasing power by segment" icon={Users} />
      <ChartFrame tall summary={summary}>
        <BarChart data={data.audience}>
          <CartesianGrid strokeDasharray="3 3" vertical={false} />
          <XAxis dataKey="segment" tickLine={false} axisLine={false} />
          <YAxis tickLine={false} axisLine={false} tickFormatter={formatChartNumber} />
          <Tooltip formatter={chartTooltipFormatter} />
          <Legend />
          <Bar dataKey="subs" name="Subscribers" fill={COLORS[1]} radius={[5, 5, 0, 0]} />
          <Bar dataKey="buyers" name="Buyers" fill={COLORS[0]} radius={[5, 5, 0, 0]} />
        </BarChart>
      </ChartFrame>
    </article>
  )
}

function SpendPanel({ trend }: { trend: ReturnType<typeof deriveTrend> }) {
  const totalSpend = sumBy(trend, (point) => point.spend)
  const summary = `Daily spend curve over ${trend.length} days totaling ${formatChartCurrency(totalSpend)}.`
  return (
    <article className="panel">
      <PanelHeading eyebrow="Spend Curve" title="Budget pressure" icon={CircleDollarSign} />
      <ChartFrame summary={summary}>
        <AreaChart data={trend}>
          <CartesianGrid strokeDasharray="3 3" vertical={false} />
          <XAxis dataKey="day" tickLine={false} axisLine={false} />
          <YAxis tickLine={false} axisLine={false} tickFormatter={formatAxisCurrency} />
          <Tooltip formatter={chartTooltipFormatter} />
          <Area type="monotone" dataKey="spend" name="Spend" stroke="#7c3aed" fill="#ddd6fe" strokeWidth={3} />
        </AreaChart>
      </ChartFrame>
    </article>
  )
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

function ApprovalGuardrails({ checks }: { checks: ApprovalRequest['guardrailChecks'] }) {
  if (!checks?.length) {
    return null
  }
  return (
    <ul className="approval-guardrails">
      {checks.map((check, index) => {
        const Icon = check.result === 'pass' ? CheckCircle2 : check.result === 'fail' ? XCircle : AlertTriangle
        return (
          <li key={`${check.message}-${index}`} className={`guardrail-${check.result}`}>
            <Icon size={13} />
            <span>{check.message}</span>
          </li>
        )
      })}
    </ul>
  )
}

function ApprovalAfterStructure({ after }: { after: ApprovalRequest['after'] }) {
  const adsets = after.adsets ?? []
  if (!after.campaign && adsets.length === 0) {
    return null
  }
  const totalDaily = adsets.reduce((total, adset) => total + adset.daily_budget / 100, 0)
  const totalAds = adsets.reduce((total, adset) => total + (adset.ads?.length ?? 0), 0)
  return (
    <details className="approval-after">
      <summary>
        Review what will be created: {adsets.length} paused ad set(s)
        {totalAds > 0 ? `, ${totalAds} ad(s)` : ''}, {formatCurrency(totalDaily)}/day total
      </summary>
      {after.campaign && (
        <p className="approval-after-campaign">
          Campaign: <strong>{after.campaign.name}</strong> · {labelRawSetting(after.campaign.objective)} · status {after.campaign.status}
        </p>
      )}
      <ul className="approval-after-adsets">
        {adsets.map((adset, index) => {
          const placements = adset.targeting.publisher_platforms ?? []
          const interests = (adset.targeting.flexible_spec ?? [])
            .flatMap((spec) => spec.interests ?? [])
            .map((interest) => interest.name)
          return (
            <li key={`${adset.name}-${index}`}>
              <strong>{adset.name}</strong>
              <small>
                {formatCurrency(adset.daily_budget / 100)}/day · {labelRawSetting(adset.optimization_goal)} · status {adset.status}
              </small>
              {placements.length > 0 && <small>Placements: {placements.join(', ')}</small>}
              {interests.length > 0 && <small>Interests: {interests.join(', ')}</small>}
              {(adset.ads ?? []).length > 0 && (
                <small>
                  Ads: {(adset.ads ?? []).map((ad) => `${ad.name} (creative ${ad.creativeId})`).join('; ')}
                </small>
              )}
            </li>
          )
        })}
      </ul>
    </details>
  )
}

function ProactiveOpportunityDetails({ opportunity }: { opportunity: ProactiveOpportunity }) {
  const audiences = (opportunity.audiences ?? []).slice(0, 3)
  const creatives = opportunity.creatives ?? []
  const sourceTemplate = opportunity.sourceTemplate
  const config = sourceTemplate?.config
  const reuseNames = creatives.flatMap((creative) =>
    (creative.reuseExisting ?? []).map((item) => item.name),
  )
  const newHooks = creatives.flatMap((creative) =>
    (creative.newAngleBriefs ?? []).map((brief) => brief.hook),
  )

  return (
    <div className="approval-opportunity">
      {opportunity.rationale && <p className="approval-opportunity-rationale">{opportunity.rationale}</p>}

      {audiences.length > 0 && (
        <div className="approval-opportunity-section">
          <span className="approval-opportunity-label">Top audiences</span>
          <ul className="approval-opportunity-audiences">
            {audiences.map((audience, index) => (
              <li key={`${audience.label}-${index}`}>
                <strong>{audience.label}</strong>
                {typeof audience.qualityScore === 'number' && (
                  <small className="approval-opportunity-score">Quality {audience.qualityScore}</small>
                )}
                {audience.rationale && <small>{audience.rationale}</small>}
              </li>
            ))}
          </ul>
        </div>
      )}

      {config && (
        <p className="approval-opportunity-mirror">
          Mirrors <strong>{sourceTemplate?.sourceCampaignName ?? 'top campaign'}</strong>
          {config.objective ? `: ${labelRawSetting(config.objective)}` : ''}
          {config.optimizationGoal ? ` / ${labelRawSetting(config.optimizationGoal)}` : ''}
        </p>
      )}

      {(reuseNames.length > 0 || newHooks.length > 0) && (
        <div className="approval-opportunity-section">
          <span className="approval-opportunity-label">Recommended creatives</span>
          {reuseNames.length > 0 && (
            <small className="approval-opportunity-reuse">Reuse: {reuseNames.join(', ')}</small>
          )}
          {newHooks.length > 0 && (
            <ul className="approval-opportunity-hooks">
              {newHooks.map((hook, index) => (
                <li key={`${hook}-${index}`}>{hook}</li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  )
}

export function ApprovalQueue({ data }: { data: DashboardData }) {
  const [approvals, setApprovals] = useState<ApprovalRequest[]>([])
  const [message, setMessage] = useState<string | null>(null)
  // null = unknown (status not yet loaded); drives whether live execution is offered.
  const [liveWritesEnabled, setLiveWritesEnabled] = useState<boolean | null>(null)

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
    void fetch('/api/meta/status')
      .then((response) => response.json() as Promise<{ liveWritesEnabled?: boolean }>)
      .then((status) => {
        if (!cancelled) {
          setLiveWritesEnabled(Boolean(status.liveWritesEnabled))
        }
      })
      .catch(() => {
        if (!cancelled) {
          setLiveWritesEnabled(false)
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
    // Reject permanently kills a planned packet — confirm and capture a real reason
    // (the backend stores and re-displays it) instead of a meaningless canned string.
    const reason = window.prompt('Reject this approval? Enter a short reason (it will be recorded):')
    if (reason === null) {
      return
    }
    setMessage('Rejecting request...')
    try {
      const response = await fetch(`/api/approvals/${approvalId}/reject`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ rejectedBy: 'dashboard', reason: reason.trim() || 'Rejected in dashboard.' }),
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
    const note = window.prompt('What changes are needed? This note is sent back with the request:')
    if (note === null) {
      return
    }
    setMessage('Marking request as needs changes...')
    try {
      const response = await fetch(`/api/approvals/${approvalId}/changes`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ requestedBy: 'dashboard', note: note.trim() || 'Needs changes in dashboard.' }),
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

  const executeLive = async (approvalId: string) => {
    setMessage('Creating the paused campaign in Meta…')
    try {
      const response = await fetch(`/api/approvals/${approvalId}/execute`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ dryRun: false, confirmLive: true }),
      })
      const result = (await response.json()) as { result?: { note?: string }; detail?: string }
      if (!response.ok) {
        setMessage(result.detail ?? `Live execution failed with ${response.status}`)
        return
      }
      setMessage(result.result?.note ?? 'Created in Meta as PAUSED. Review in Ads Manager before enabling delivery.')
      setApprovals(await fetchApprovals())
    } catch {
      setMessage('Could not create the campaign in Meta.')
    }
  }

  return (
    <article className="panel">
      <PanelHeading eyebrow="Recommended Actions" title="Approval queue" icon={ClipboardCheck} />
      {approvals.length > 0 && (
        <div className="action-list execution-approval-list">
          {approvals.map((approval) => {
            const isProactive = approval.source === 'proactive'
            return (
            <div
              className={`action-item ${approval.risk}${isProactive ? ' approval-proactive' : ''}`}
              key={approval.id}
            >
              <div>
                {isProactive && (
                  <span className="provenance-chip llm approval-suggested-badge">🤖 Suggested for you</span>
                )}
                <strong>{approval.after.campaign?.name ?? approval.actionType}</strong>
                <p>{approval.reason}</p>
                <small>
                  {labelRawSetting(approval.status)} / guardrail {approval.guardrailResult} / {approval.executionMethod}
                </small>
                {approval.expectedImpact && (
                  <small className="approval-impact">Expected impact: {approval.expectedImpact}</small>
                )}
                {isProactive && approval.opportunity && (
                  <ProactiveOpportunityDetails opportunity={approval.opportunity} />
                )}
                <ApprovalGuardrails checks={approval.guardrailChecks} />
                <ApprovalAfterStructure after={approval.after} />
                {approval.rejectionReason && <small>Rejected reason: {approval.rejectionReason}</small>}
                {approval.changeRequestNote && <small>Change request: {approval.changeRequestNote}</small>}
                {approval.status === 'executed' && (
                  <small className="approval-impact">{approval.lastExecutionResult?.note ?? 'Created in Meta as paused.'}</small>
                )}
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
                {approval.status === 'dry_run_completed' && (
                  liveWritesEnabled === false ? (
                    <>
                      <button className="sync-button" type="button" disabled>
                        Create paused campaign in Meta
                      </button>
                      <small className="approval-impact">Live writes disabled by configuration (set META_LIVE_WRITES_ENABLED=true).</small>
                    </>
                  ) : (
                    <button
                      className="sync-button"
                      type="button"
                      disabled={liveWritesEnabled === null || approval.guardrailResult === 'fail'}
                      onClick={() => void executeLive(approval.id)}
                    >
                      Create paused campaign in Meta
                    </button>
                  )
                )}
                {approval.status === 'executed' && <span className="status-pill good">Created (paused)</span>}
                <span>{approval.risk}</span>
              </div>
            </div>
            )
          })}
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
  // Tone reflects whether a rate is on-target, not merely non-zero — so an off-target
  // funnel reads as warning/danger instead of a misleading "good" just because it exists.
  const visitRate = clicks > 0 ? (landingPageViews / clicks) * 100 : 0
  const lpLeadRate = landingPageViews > 0 ? (leads / landingPageViews) * 100 : 0
  const toneForRate = (value: number, good: number, warn: number, hasInputs: boolean): Tone => {
    if (!hasInputs) return 'neutral'
    if (value >= good) return 'good'
    if (value >= warn) return 'warning'
    return 'danger'
  }

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
      tone: toneForRate(visitRate, 70, 40, clicks > 0),
      icon: 'bot',
    },
    {
      label: 'LP Lead Rate',
      value: formatPercent(leads, landingPageViews),
      change: `${formatNumber(leads)} leads`,
      helper: 'Leads / landing visits',
      tone: toneForRate(lpLeadRate, 35, 15, landingPageViews > 0),
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

