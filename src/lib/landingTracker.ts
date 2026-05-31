export type VisitorStorage = Pick<Storage, 'getItem' | 'setItem'>

export type TrackerConfig = {
  segment?: string
  vslId?: string
  landingPageId?: string
  telegramBotId?: string
}

export type FunnelAttribution = {
  segment?: string
  vslId?: string
  landingPageId?: string
  telegramBotId?: string
  campaignId?: string
  adSetId?: string
  adId?: string
  creativeId?: string
  utmSource?: string
  utmMedium?: string
  utmCampaign?: string
  utmContent?: string
  utmTerm?: string
  fbclid?: string
}

export type FunnelEventName =
  | 'landing_view'
  | 'vsl_button_click'
  | 'telegram_link_click'
  | 'bot_start'
  | 'vsl_sequence_started'
  | 'vsl_key_message_sent'
  | 'form_button_click'
  | 'form_opened'
  | 'crm_form_submit'
  | 'qualified_lead'
  | 'partial_payment'
  | 'full_payment'

const VISITOR_STORAGE_KEY = 'meta_agent_visitor_id'

export function createVisitorId(options: { now?: () => number; random?: () => number } = {}) {
  const now = options.now ?? Date.now
  const random = options.random ?? Math.random
  const timePart = now().toString(36)
  const randomPart = random().toString(36).slice(2, 8).padEnd(6, '0')
  return `v_${timePart}_${randomPart}`
}

export function getOrCreateVisitorId(
  storage: VisitorStorage | undefined | null,
  options: { now?: () => number; random?: () => number } = {},
) {
  const existing = storage?.getItem(VISITOR_STORAGE_KEY)
  if (existing) {
    return existing
  }
  const visitorId = createVisitorId(options)
  storage?.setItem(VISITOR_STORAGE_KEY, visitorId)
  return visitorId
}

export function collectAttribution(url: string, config: TrackerConfig = {}): FunnelAttribution {
  const parsed = new URL(url)
  const value = (key: string) => parsed.searchParams.get(key) || undefined
  return compact({
    segment: config.segment ?? value('segment'),
    vslId: config.vslId ?? value('vsl_id'),
    landingPageId: config.landingPageId ?? value('landing_page_id'),
    telegramBotId: config.telegramBotId ?? value('telegram_bot_id'),
    campaignId: value('campaign_id') ?? value('campaign.id'),
    adSetId: value('adset_id') ?? value('adset.id'),
    adId: value('ad_id') ?? value('ad.id'),
    creativeId: value('creative_id') ?? value('creative.id'),
    utmSource: value('utm_source'),
    utmMedium: value('utm_medium'),
    utmCampaign: value('utm_campaign'),
    utmContent: value('utm_content'),
    utmTerm: value('utm_term'),
    fbclid: value('fbclid'),
  })
}

export function buildTelegramStartPayload(visitorId: string) {
  return visitorId.slice(0, 64)
}

export function decorateTelegramUrl(url: string, visitorId: string) {
  const parsed = new URL(url)
  parsed.searchParams.set('start', buildTelegramStartPayload(visitorId))
  return parsed.toString()
}

export function decorateCrmFormUrl(url: string, visitorId: string, attribution: FunnelAttribution = {}) {
  const parsed = new URL(url)
  const fields = compact({
    visitor_id: visitorId,
    segment: attribution.segment,
    vsl_id: attribution.vslId,
    landing_page_id: attribution.landingPageId,
    telegram_bot_id: attribution.telegramBotId,
    campaign_id: attribution.campaignId,
    adset_id: attribution.adSetId,
    ad_id: attribution.adId,
    creative_id: attribution.creativeId,
    utm_source: attribution.utmSource,
    utm_medium: attribution.utmMedium,
    utm_campaign: attribution.utmCampaign,
    utm_content: attribution.utmContent,
    utm_term: attribution.utmTerm,
    fbclid: attribution.fbclid,
  })
  Object.entries(fields).forEach(([key, value]) => {
    parsed.searchParams.set(key, String(value))
  })
  return parsed.toString()
}

export function buildFunnelEvent(
  eventName: FunnelEventName,
  visitorId: string,
  attribution: FunnelAttribution = {},
) {
  return compact({
    event_name: eventName,
    visitor_id: visitorId,
    segment: attribution.segment,
    vsl_id: attribution.vslId,
    landing_page_id: attribution.landingPageId,
    telegram_bot_id: attribution.telegramBotId,
    campaign_id: attribution.campaignId,
    adset_id: attribution.adSetId,
    ad_id: attribution.adId,
    creative_id: attribution.creativeId,
    utm_source: attribution.utmSource,
    utm_medium: attribution.utmMedium,
    utm_campaign: attribution.utmCampaign,
    utm_content: attribution.utmContent,
    utm_term: attribution.utmTerm,
    fbclid: attribution.fbclid,
  })
}

function compact<T extends Record<string, unknown>>(value: T) {
  return Object.fromEntries(Object.entries(value).filter(([, item]) => item !== undefined && item !== '')) as Partial<T>
}
