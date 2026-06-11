export type AgentState = 'working' | 'idle' | 'scheduled'

export interface AgentStatus {
  id: string
  name: string
  state: AgentState
  activity: string | null
  sinceSeconds: number | null
  nextRunAt: string | null
  lastActivity: string | null
  lastActiveAt: string | null
}

export interface AgentEvent {
  agentId: string
  summary: string
  at: string
}

export interface AgentStatusPayload {
  agents: AgentStatus[]
  events: AgentEvent[]
  updatedAt: string
}

export async function getAgentStatus(): Promise<AgentStatusPayload> {
  const response = await fetch('/api/agents/status')

  if (!response.ok) {
    throw new Error(`Agent status request failed: ${response.status}`)
  }

  return (await response.json()) as AgentStatusPayload
}
