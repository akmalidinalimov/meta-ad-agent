// Pure transform + types for the per-audience CRM funnel matrix (Part 4).
// Kept separate from Dashboard.tsx so it can be unit-tested without rendering the
// whole dashboard, and reused by the CrmFunnelByAudience component.

export interface CrmFunnelAudience {
  submits: number
  paid: number
  botStarts: number
  paidRate: number
  paidRatePerStart: number
  // per-stage counts live under their stage id (all numeric).
  [stageId: string]: number
}

export interface CrmFunnelPayload {
  ok: boolean
  stages: string[]
  stageLabels: Record<string, string>
  paidStageIds: string[]
  audiences: Record<string, CrmFunnelAudience>
  matchRate: number
  refreshedAt?: string
  entity?: string
  error?: string
}

export const AUDIENCE_ORDER = ['ai', 'business', 'it', 'original', 'content']

export interface AudienceRow {
  audience: string
  botStarts: number
  submits: number
  paid: number
  paidRatePct: string
  cells: { stageId: string; count: number }[]
}

// Known audiences first (in canonical order), then any unexpected audience, then the
// honest `unattributed` bucket last.
export function buildAudienceRows(payload: CrmFunnelPayload): AudienceRow[] {
  const auds = Object.keys(payload.audiences ?? {})
  if (auds.length === 0) return []
  const ordered = [
    ...AUDIENCE_ORDER.filter((aud) => aud in payload.audiences),
    ...auds.filter((aud) => !AUDIENCE_ORDER.includes(aud) && aud !== 'unattributed'),
    ...(payload.audiences.unattributed ? ['unattributed'] : []),
  ]
  return ordered.map((audience) => {
    const data = payload.audiences[audience]
    return {
      audience,
      botStarts: data.botStarts ?? 0,
      submits: data.submits ?? 0,
      paid: data.paid ?? 0,
      paidRatePct: `${Math.round((data.paidRate ?? 0) * 100)}%`,
      cells: payload.stages.map((stageId) => ({ stageId, count: Number(data[stageId] ?? 0) })),
    }
  })
}
