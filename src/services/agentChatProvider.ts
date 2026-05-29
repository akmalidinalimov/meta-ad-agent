export interface AgentChatResponse {
  answer: string
  sources: string[]
  suggestedQuestions: string[]
  activeAgent?: string | null
  routeReason?: string | null
  generatedPlaybook?: unknown
  generatedStrategy?: unknown
}

export async function askAgent(message: string): Promise<AgentChatResponse> {
  const response = await fetch('/api/agent/chat', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ message }),
  })

  if (!response.ok) {
    throw new Error(`Agent chat API failed with ${response.status}`)
  }

  return (await response.json()) as AgentChatResponse
}
