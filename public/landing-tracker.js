;(function () {
  'use strict'

  var STORAGE_KEY = 'meta_agent_visitor_id'
  var DEFAULT_SELECTOR = '[data-meta-agent-telegram]'
  var ATTR_KEYS = [
    ['campaign_id', 'campaign_id'],
    ['campaign.id', 'campaign_id'],
    ['adset_id', 'adset_id'],
    ['adset.id', 'adset_id'],
    ['ad_id', 'ad_id'],
    ['ad.id', 'ad_id'],
    ['creative_id', 'creative_id'],
    ['creative.id', 'creative_id'],
    ['utm_source', 'utm_source'],
    ['utm_medium', 'utm_medium'],
    ['utm_campaign', 'utm_campaign'],
    ['utm_content', 'utm_content'],
    ['utm_term', 'utm_term'],
    ['fbclid', 'fbclid'],
  ]

  var config = window.MetaAdAgentTracker || {}

  function createVisitorId() {
    return 'v_' + Date.now().toString(36) + '_' + Math.random().toString(36).slice(2, 8).padEnd(6, '0')
  }

  function getVisitorId() {
    try {
      var existing = window.localStorage.getItem(STORAGE_KEY)
      if (existing) return existing
      var next = createVisitorId()
      window.localStorage.setItem(STORAGE_KEY, next)
      return next
    } catch (_) {
      return createVisitorId()
    }
  }

  function setIfPresent(target, key, value) {
    if (value !== undefined && value !== null && value !== '') {
      target[key] = value
    }
  }

  function collectAttribution() {
    var params = new URLSearchParams(window.location.search)
    var attribution = {}
    setIfPresent(attribution, 'segment', config.segment || params.get('segment'))
    setIfPresent(attribution, 'vsl_id', config.vslId || params.get('vsl_id'))
    setIfPresent(attribution, 'landing_page_id', config.landingPageId || params.get('landing_page_id'))
    setIfPresent(attribution, 'telegram_bot_id', config.telegramBotId || params.get('telegram_bot_id'))
    ATTR_KEYS.forEach(function (entry) {
      if (attribution[entry[1]]) return
      setIfPresent(attribution, entry[1], params.get(entry[0]))
    })
    return attribution
  }

  function buildEvent(eventName) {
    var event = collectAttribution()
    event.event_name = eventName
    event.visitor_id = visitorId
    return event
  }

  function sendEvent(eventName) {
    if (!config.endpoint) return
    var payload = JSON.stringify({ event: buildEvent(eventName) })
    if (navigator.sendBeacon) {
      var blob = new Blob([payload], { type: 'application/json' })
      if (navigator.sendBeacon(config.endpoint, blob)) return
    }
    if (window.fetch) {
      window.fetch(config.endpoint, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: payload,
        keepalive: true,
      }).catch(function () {})
    }
  }

  function decorateTelegramLink(anchor) {
    var href = anchor.getAttribute('href')
    if (!href) return
    try {
      var url = new URL(href, window.location.href)
      url.searchParams.set('start', visitorId.slice(0, 64))
      anchor.setAttribute('href', url.toString())
    } catch (_) {}
  }

  function bindTelegramLinks() {
    var links = document.querySelectorAll(config.telegramSelector || DEFAULT_SELECTOR)
    links.forEach(function (anchor) {
      decorateTelegramLink(anchor)
      anchor.addEventListener('click', function () {
        sendEvent(config.telegramClickEventName || 'telegram_link_click')
      })
    })
  }

  var visitorId = getVisitorId()
  window.MetaAdAgentVisitorId = visitorId

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', function () {
      bindTelegramLinks()
      sendEvent(config.landingViewEventName || 'landing_view')
    })
  } else {
    bindTelegramLinks()
    sendEvent(config.landingViewEventName || 'landing_view')
  }
})()
