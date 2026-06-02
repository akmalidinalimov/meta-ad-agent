export interface MetaAiScores {
  specificity: number
  metricAccuracy: number
  actionability: number
  businessRealism: number
  riskAwareness: number
}

export interface MetaAiAnalysis {
  advisor: {
    recommendationSummary: string[]
    evidenceUsed: string[]
    whatItMissed: string[]
    trustLevel: 'high' | 'medium' | 'low' | string
  }
  strategist: {
    comparedAgainst: string[]
    scores: MetaAiScores
    overallScore: number
    businessCounterpoints: string[]
    campaign: { id: string; name: string } | null
  }
}

export interface MetaAiCapture {
  id: string
  createdAt: string
  capturedBy: string
  objectLevel?: string | null
  campaignId?: string | null
  campaignName?: string | null
  sourceText: string
  screenshotText: string
  analysis: MetaAiAnalysis
}

export interface CreateMetaAiCaptureInput {
  sourceText: string
  screenshotText?: string
  campaignName?: string
  objectLevel?: string
}

export async function getMetaAiCaptures(): Promise<MetaAiCapture[]> {
  const response = await fetch('/api/meta-ai/captures')
  if (!response.ok) {
    throw new Error(`Meta AI captures API failed with ${response.status}`)
  }
  const payload = (await response.json()) as { captures: MetaAiCapture[] }
  return payload.captures
}

export async function createMetaAiCapture(input: CreateMetaAiCaptureInput): Promise<MetaAiCapture> {
  const response = await fetch('/api/meta-ai/captures', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(input),
  })
  if (!response.ok) {
    const detail = await response.json().catch(() => null)
    throw new Error((detail as { detail?: string } | null)?.detail ?? `Capture failed with ${response.status}`)
  }
  const payload = (await response.json()) as { capture: MetaAiCapture }
  return payload.capture
}
