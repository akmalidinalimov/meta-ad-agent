import { describe, expect, it } from 'vitest'
import {
  buildFunnelEvent,
  buildTelegramStartPayload,
  collectAttribution,
  createVisitorId,
  decorateCrmFormUrl,
  decorateTelegramUrl,
  getOrCreateVisitorId,
  type VisitorStorage,
} from './landingTracker'

function memoryStorage(seed: Record<string, string> = {}): VisitorStorage {
  const values = new Map(Object.entries(seed))
  return {
    getItem: (key) => values.get(key) ?? null,
    setItem: (key, value) => values.set(key, value),
  }
}

describe('landing tracker visitor id', () => {
  it('creates a compact stable visitor id and reuses it from storage', () => {
    const storage = memoryStorage()
    const visitorId = getOrCreateVisitorId(storage, {
      now: () => 1_800_000_000_000,
      random: () => 0.123456789,
    })

    expect(visitorId).toBe('v_mywpiww0_4fzzzx')
    expect(getOrCreateVisitorId(storage, { now: () => 2, random: () => 0.9 })).toBe(visitorId)
  })

  it('can create a visitor id without storage', () => {
    expect(createVisitorId({ now: () => 1_800_000_000_000, random: () => 0.123456789 })).toBe(
      'v_mywpiww0_4fzzzx',
    )
  })
})

describe('landing tracker attribution', () => {
  it('collects Meta and funnel attribution from the URL and config', () => {
    const attribution = collectAttribution(
      'https://example.com/income?utm_source=ig&utm_medium=paid&utm_campaign=camp-1&utm_content=creative-a&fbclid=fb123&campaign_id=cmp_1&adset_id=as_1&ad_id=ad_1&creative_id=cr_1',
      {
        segment: 'income',
        vslId: 'income_vsl_01',
        landingPageId: 'income_lp_01',
        telegramBotId: 'income_bot',
      },
    )

    expect(attribution).toEqual({
      segment: 'income',
      vslId: 'income_vsl_01',
      landingPageId: 'income_lp_01',
      telegramBotId: 'income_bot',
      campaignId: 'cmp_1',
      adSetId: 'as_1',
      adId: 'ad_1',
      creativeId: 'cr_1',
      utmSource: 'ig',
      utmMedium: 'paid',
      utmCampaign: 'camp-1',
      utmContent: 'creative-a',
      fbclid: 'fb123',
    })
  })
})

describe('landing tracker Telegram links', () => {
  it('uses only visitor id in Telegram start payload to stay below Telegram length limits', () => {
    expect(buildTelegramStartPayload('v_lf8b5ts0_4fzzzx')).toBe('v_lf8b5ts0_4fzzzx')
    expect(buildTelegramStartPayload('v_lf8b5ts0_4fzzzx')).toHaveLength(17)
  })

  it('adds a start parameter without losing existing Telegram URL parameters', () => {
    expect(decorateTelegramUrl('https://t.me/shahlo_bot?startgroup=true', 'v_lf8b5ts0_4fzzzx')).toBe(
      'https://t.me/shahlo_bot?startgroup=true&start=v_lf8b5ts0_4fzzzx',
    )
  })
})

describe('landing tracker CRM form links', () => {
  it('adds visitor and attribution fields without losing existing form parameters', () => {
    const decorated = decorateCrmFormUrl(
      'https://inafform.bitrix24.site/crm_form_vospb/?existing=1',
      'v_lf8b5ts0_4fzzzx',
      {
        segment: 'income',
        vslId: 'income_vsl_01',
        landingPageId: 'income_lp_01',
        telegramBotId: 'income_bot',
        campaignId: 'cmp_1',
        adSetId: 'as_1',
        adId: 'ad_1',
        creativeId: 'cr_1',
        utmSource: 'ig',
        utmMedium: 'paid',
        utmCampaign: 'camp-1',
        utmContent: 'creative-a',
        fbclid: 'fb123',
      },
    )

    const url = new URL(decorated)
    expect(url.searchParams.get('existing')).toBe('1')
    expect(url.searchParams.get('visitor_id')).toBe('v_lf8b5ts0_4fzzzx')
    expect(url.searchParams.get('segment')).toBe('income')
    expect(url.searchParams.get('vsl_id')).toBe('income_vsl_01')
    expect(url.searchParams.get('landing_page_id')).toBe('income_lp_01')
    expect(url.searchParams.get('telegram_bot_id')).toBe('income_bot')
    expect(url.searchParams.get('campaign_id')).toBe('cmp_1')
    expect(url.searchParams.get('adset_id')).toBe('as_1')
    expect(url.searchParams.get('ad_id')).toBe('ad_1')
    expect(url.searchParams.get('creative_id')).toBe('cr_1')
    expect(url.searchParams.get('utm_source')).toBe('ig')
    expect(url.searchParams.get('utm_medium')).toBe('paid')
    expect(url.searchParams.get('utm_campaign')).toBe('camp-1')
    expect(url.searchParams.get('utm_content')).toBe('creative-a')
    expect(url.searchParams.get('fbclid')).toBe('fb123')
  })
})

describe('landing tracker events', () => {
  it('builds backend-compatible funnel event payloads', () => {
    const event = buildFunnelEvent('telegram_link_click', 'v_lf8b5ts0_4fzzzx', {
      segment: 'income',
      vslId: 'income_vsl_01',
      landingPageId: 'income_lp_01',
      telegramBotId: 'income_bot',
      campaignId: 'cmp_1',
      adSetId: 'as_1',
      adId: 'ad_1',
      creativeId: 'cr_1',
      fbclid: 'fb123',
    })

    expect(event).toEqual({
      event_name: 'telegram_link_click',
      visitor_id: 'v_lf8b5ts0_4fzzzx',
      segment: 'income',
      vsl_id: 'income_vsl_01',
      landing_page_id: 'income_lp_01',
      telegram_bot_id: 'income_bot',
      campaign_id: 'cmp_1',
      adset_id: 'as_1',
      ad_id: 'ad_1',
      creative_id: 'cr_1',
      fbclid: 'fb123',
    })
  })
})
