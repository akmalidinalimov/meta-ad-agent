export interface MetaStatus {
  configured: boolean
  connected: boolean
  apiVersion: string
  appId?: string
  adAccountId: string
  businessId?: string
  pixelConfigured: boolean
  tokenConfigured: boolean
  tokenPreview: string
  liveWritesEnabled?: boolean
  account: {
    id?: string
    name?: string
    account_status?: number
    currency?: string
    timezone_name?: string
    business_name?: string
  } | null
  error: string | null
}

export async function getMetaStatus(): Promise<MetaStatus> {
  const response = await fetch('/api/meta/status')

  if (!response.ok) {
    throw new Error(`Meta status API failed with ${response.status}`)
  }

  return (await response.json()) as MetaStatus
}
