import {
  AlertTriangle,
  BookOpen,
  Bot,
  CheckCircle2,
  ClipboardCheck,
  ListChecks,
  RadioTower,
  RefreshCcw,
  Send,
  Settings,
  ShieldAlert,
  SlidersHorizontal,
  Target,
  Users,
  XCircle,
} from 'lucide-react'
import { useEffect, useState } from 'react'
import {
  formatCurrency,
  formatDateTime,
  formatRate,
  labelEventName,
  labelRawSetting,
  shortText,
} from '../../../lib/format'
import type { MetaStatus } from '../../../services/metaStatusProvider'
import type {
  CampaignPlaybook,
  DashboardData,
  FunnelEventSummary,
  MetaSettingsAudit,
  MetaSnapshot,
  SystemChecklist,
} from '../../../types/marketing'
import { MiniMetric } from '../shared/MiniMetric'
import { PanelHeading } from '../shared/PanelHeading'

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

function DiagnosticsView({ data }: { data: DashboardData }) {
  const [systemChecklist, setSystemChecklist] = useState<SystemChecklist | null>(null)
  const [isSendingTelegramTest, setIsSendingTelegramTest] = useState(false)
  const [message, setMessage] = useState<string | null>(null)

  useEffect(() => {
    if (typeof fetch !== 'function') {
      return
    }
    let cancelled = false
    void fetch('/api/system/checklist')
      .then((response) => (response.ok ? response.json() : null))
      .then((checklist) => {
        if (!cancelled) {
          setSystemChecklist(checklist as SystemChecklist | null)
        }
      })
      .catch(() => {
        if (!cancelled) {
          setSystemChecklist(null)
        }
      })
    return () => {
      cancelled = true
    }
  }, [])

  const recentCampaigns = data.campaigns.slice(0, 8)

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
          <div className="metric-list">
            <div><strong>No checklist yet</strong><span>Start the backend to load the regression checklist.</span></div>
          </div>
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
          {message && <small className="sync-message">{message}</small>}
        </div>
      </article>
    </section>
  )
}

const TARGET_FIELDS = [
  { key: 'maxCpl', label: 'Max cost per lead ($)', hint: 'Flag when CPL rises above this' },
  { key: 'minLeadRate', label: 'Min lead rate (%)', hint: 'Leads / clicks floor' },
  { key: 'maxCostPerStart', label: 'Max cost per Telegram START ($)', hint: 'Spend / START ceiling' },
  { key: 'minStartRate', label: 'Min START rate (%)', hint: 'START-rate floor' },
  { key: 'weeklyBudgetTargetUsd', label: 'Weekly budget target ($)', hint: 'Monitor shows spend pace against this' },
] as const

function TargetsView() {
  const [draft, setDraft] = useState<Record<string, string>>({})
  const [message, setMessage] = useState<string | null>(null)
  const [isSaving, setIsSaving] = useState(false)

  useEffect(() => {
    if (typeof fetch !== 'function') {
      return
    }
    void fetch('/api/targets')
      .then((response) => (response.ok ? response.json() : { targets: null }))
      .then((result: { targets?: Record<string, number | null> }) => {
        if (result.targets) {
          setDraft(
            Object.fromEntries(
              TARGET_FIELDS.map((field) => [
                field.key,
                result.targets?.[field.key] != null ? String(result.targets[field.key]) : '',
              ]),
            ),
          )
        }
      })
      .catch(() => undefined)
  }, [])

  const save = async () => {
    if (isSaving) {
      return
    }
    setIsSaving(true)
    setMessage('Saving targets...')
    try {
      const body = Object.fromEntries(
        TARGET_FIELDS.map((field) => [field.key, draft[field.key] === '' || draft[field.key] == null ? null : Number(draft[field.key])]),
      )
      const response = await fetch('/api/targets', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      })
      const result = (await response.json()) as { ok?: boolean }
      setMessage(
        response.ok && result.ok
          ? 'Targets saved. The 4-hour Telegram digest now marks each KPI ✅ on target or ⚠️ off target.'
          : 'Could not save targets.',
      )
    } catch {
      setMessage('Could not reach the targets endpoint.')
    } finally {
      setIsSaving(false)
    }
  }

  return (
    <article className="panel panel-wide">
      <PanelHeading eyebrow="Goals" title="KPI targets" icon={Target} />
      <p>
        Set the goals the agent steers toward. The 4-hour Telegram digest marks each KPI ✅ on target or ⚠️ off
        target. Leave a field blank to ignore that metric.
      </p>
      <div className="command-grid">
        {TARGET_FIELDS.map((field) => (
          <label key={field.key}>
            <span>{field.label}</span>
            <input
              type="number"
              step="any"
              min="0"
              value={draft[field.key] ?? ''}
              placeholder="—"
              onChange={(event) => setDraft((current) => ({ ...current, [field.key]: event.target.value }))}
            />
            <small>{field.hint}</small>
          </label>
        ))}
      </div>
      <div className="command-actions">
        <button className="sync-button" type="button" onClick={save} disabled={isSaving}>
          {isSaving ? 'Saving...' : 'Save targets'}
        </button>
        {message && <small className="sync-message">{message}</small>}
      </div>
    </article>
  )
}

export function SettingsView({
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
      <TargetsView />
      <details className="advanced-command-section settings-diagnostics">
        <summary>Diagnostics</summary>
        <DiagnosticsView data={data} />
      </details>
      <details className="advanced-command-section settings-diagnostics">
        <summary>Tracking diagnostics</summary>
        <TrackingView data={data} />
      </details>
      <details className="advanced-command-section settings-diagnostics">
        <summary>Meta settings audit</summary>
        <SettingsAuditView />
      </details>
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
