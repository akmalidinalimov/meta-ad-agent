import type { AgentSpec, AgentTask } from '../types/marketing'

export interface AgentTaskCreateRequest {
  source: 'dashboard' | 'telegram' | 'codex'
  command: string
  campaignGroupId?: string
  segmentIds?: string[]
  prepareApproval?: boolean
}

export interface AgentCommandCenterPayload {
  tasks: AgentTask[]
  agents: AgentSpec[]
}

export async function getAgentCommandCenter(): Promise<AgentCommandCenterPayload> {
  const [tasksResponse, agentsResponse] = await Promise.all([
    fetch('/api/tasks'),
    fetch('/api/agents'),
  ])

  if (!tasksResponse.ok) {
    throw new Error(`Agent tasks API failed with ${tasksResponse.status}`)
  }
  if (!agentsResponse.ok) {
    throw new Error(`Agents API failed with ${agentsResponse.status}`)
  }

  const tasksPayload = (await tasksResponse.json()) as { tasks?: AgentTask[] }
  const agentsPayload = (await agentsResponse.json()) as { agents?: AgentSpec[] }
  return {
    tasks: tasksPayload.tasks ?? [],
    agents: agentsPayload.agents ?? [],
  }
}

export async function createAgentTask(request: AgentTaskCreateRequest): Promise<{ ok: boolean; task: AgentTask }> {
  const response = await fetch('/api/tasks', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(request),
  })

  if (!response.ok) {
    throw new Error(`Create task API failed with ${response.status}`)
  }

  return (await response.json()) as { ok: boolean; task: AgentTask }
}
