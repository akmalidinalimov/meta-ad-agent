import type { AgentCouncilSession } from '../types/marketing'

export interface AgentChatResponse {
  answer: string
  sources: string[]
  suggestedQuestions: string[]
  activeAgent?: string | null
  routeReason?: string | null
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
    status: 'usable' | 'needs_refinement' | 'blocked' | string
    issues: string[]
  } | null
  generatedPlaybook?: unknown
  generatedStrategy?: unknown
  agentCouncil?: AgentCouncilSession | null
}

// A stable per-tab session id so the backend can refine an in-flight autonomous draft
// across chat turns (maps to a pending_context_store operator key). autoExecute defaults
// to true on the backend, so we only need to send the session id.
function chatSessionId(): string {
  try {
    const existing = sessionStorage.getItem('agentChatSessionId')
    if (existing) return existing
    const fresh = `web-${Math.random().toString(36).slice(2)}-${Date.now()}`
    sessionStorage.setItem('agentChatSessionId', fresh)
    return fresh
  } catch {
    return 'web:default'
  }
}

export async function askAgent(message: string): Promise<AgentChatResponse> {
  const response = await fetch('/api/agent/chat', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ message, sessionId: chatSessionId() }),
  })

  if (!response.ok) {
    throw new Error(`Agent chat API failed with ${response.status}`)
  }

  return (await response.json()) as AgentChatResponse
}

export async function runAgentCouncil(message: string): Promise<AgentCouncilSession> {
  const response = await fetch('/api/agent/council', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ message }),
  })

  if (!response.ok) {
    throw new Error(`Agent council API failed with ${response.status}`)
  }

  const payload = (await response.json()) as { ok?: boolean; council?: AgentCouncilSession }
  if (!payload.ok || !payload.council) {
    throw new Error('Agent council API did not return a council session')
  }

  return payload.council
}
