import { useEffect, useState } from 'react'
import {
  getAgentStatus,
  type AgentStatus,
  type AgentStatusPayload,
} from '../../../services/agentStatusProvider'

const AGENT_ICONS: Record<string, string> = {
  monitor: '🛰️',
  analyst: '📊',
  planner: '🧭',
  creative: '🎨',
}

const DESK_POSITIONS: Record<string, { left: string; top: string }> = {
  monitor: { left: '16%', top: '12%' },
  analyst: { left: '62%', top: '12%' },
  planner: { left: '14%', top: '56%' },
  creative: { left: '64%', top: '56%' },
}

// Working agents "walk" to the center table; the move is a CSS transition on
// left/top (spec §3.3 — walk plays on state change between polls).
const TABLE_POSITIONS: Record<string, { left: string; top: string }> = {
  monitor: { left: '30%', top: '26%' },
  analyst: { left: '52%', top: '26%' },
  planner: { left: '30%', top: '46%' },
  creative: { left: '52%', top: '46%' },
}

function formatElapsed(seconds: number | null): string {
  if (seconds === null) return ''
  if (seconds < 60) return 'just now'
  const minutes = Math.floor(seconds / 60)
  if (minutes < 60) return `${minutes}m`
  return `${Math.floor(minutes / 60)}h ${minutes % 60}m`
}

function formatClock(iso: string): string {
  return new Date(iso).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
}

function relativeTime(iso: string | null): string {
  if (!iso) return ''
  const minutes = Math.round((Date.now() - new Date(iso).getTime()) / 60000)
  if (minutes < 1) return 'just now'
  if (minutes < 60) return `${minutes}m ago`
  const hours = Math.round(minutes / 60)
  if (hours < 24) return `${hours}h ago`
  return `${Math.round(hours / 24)}d ago`
}

function statusSentence(agent: AgentStatus): string {
  if (agent.state === 'working') {
    const elapsed = formatElapsed(agent.sinceSeconds)
    return `working — ${agent.activity ?? '…'}${elapsed ? ` · ${elapsed}` : ''}`
  }
  const last = agent.lastActivity
    ? `last: ${agent.lastActivity}, ${relativeTime(agent.lastActiveAt)}`
    : 'no recent activity'
  if (agent.state === 'scheduled' && agent.nextRunAt) {
    return `${last} · next ${formatClock(agent.nextRunAt)}`
  }
  return last
}

export function AgentOffice({ pollMs = 30000 }: { pollMs?: number }) {
  const [payload, setPayload] = useState<AgentStatusPayload | null>(null)
  const [failed, setFailed] = useState(false)

  useEffect(() => {
    let cancelled = false
    const load = async () => {
      try {
        const next = await getAgentStatus()
        if (!cancelled) {
          setPayload(next)
          setFailed(false)
        }
      } catch {
        if (!cancelled) {
          setFailed(true) // keeps last payload if any; shows unavailable otherwise
        }
      }
    }
    void load()
    const id = setInterval(() => void load(), pollMs)
    return () => {
      cancelled = true
      clearInterval(id)
    }
  }, [pollMs])

  if (!payload) {
    return (
      <section className="monitor-office" aria-label="Agent Office">
        <div className="office-heading">
          <h5>Agent Office</h5>
        </div>
        <p className="office-empty">{failed ? 'Agent status unavailable' : 'Connecting…'}</p>
      </section>
    )
  }

  const working = payload.agents.filter((agent) => agent.state === 'working').length
  const idle = payload.agents.length - working
  const summary = `${working} working · ${idle} idle${failed ? ' · stale' : ''}`

  return (
    <section className="monitor-office" aria-label="Agent Office">
      <div className="office-heading">
        <h5>Agent Office</h5>
        <small>{summary}</small>
      </div>

      <div className="office-scene" aria-hidden="true">
        <div className="office-table" />
        {payload.agents.map((agent) => (
          <div
            key={agent.id}
            className={`office-desk ${agent.state === 'working' ? 'working' : 'resting'}`}
            style={agent.state === 'working' ? TABLE_POSITIONS[agent.id] : DESK_POSITIONS[agent.id]}
          >
            <span className="office-face">
              {AGENT_ICONS[agent.id] ?? '🤖'}
              <i />
            </span>
            <span className="office-name">{agent.name}</span>
          </div>
        ))}
      </div>

      <div className="office-strip" aria-hidden="true">
        {payload.agents.map((agent) => (
          <span
            key={agent.id}
            className={`strip-agent ${agent.state === 'working' ? 'working' : 'resting'}`}
          >
            {AGENT_ICONS[agent.id] ?? '🤖'}
            <i />
          </span>
        ))}
      </div>

      <ul className="office-list">
        {payload.agents.map((agent) => (
          <li key={agent.id} className={agent.state === 'working' ? 'working' : 'resting'}>
            <span className="office-mini">{AGENT_ICONS[agent.id] ?? '🤖'}</span>
            <div>
              <strong>{agent.name}</strong>
              <span>{statusSentence(agent)}</span>
            </div>
          </li>
        ))}
      </ul>

      {payload.events.length > 0 && (
        <div className="office-feed">
          <h6>Recent activity</h6>
          <ul>
            {payload.events.slice(0, 5).map((event, index) => (
              <li key={`${event.at}-${index}`}>
                <time>{formatClock(event.at)}</time>
                <span>
                  <b>{payload.agents.find((a) => a.id === event.agentId)?.name ?? event.agentId}</b>{' '}
                  — {event.summary}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
  )
}
