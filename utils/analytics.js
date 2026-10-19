/**
 * 使用统计与广告槽位库存采集。
 *
 * 统计只记录页面/功能/槽位上下文，不读取成绩、课程、密码或 Cookie。
 * 所有上报都走后台队列，失败只保留本地队列，不影响页面功能。
 */
const api = require('./api')
const storage = require('./storage')
const config = require('./config')

const CONSENT_KEY = 'analytics_consent'
const VISITOR_KEY = 'analytics_visitor_id'
const QUEUE_KEY = 'analytics_queue'
const MAX_QUEUE = 120
const SLOT_VISIBLE_RATIO = 0.5
const SLOT_MIN_VISIBLE_MS = 1000
const SLOT_REENTRY_COOLDOWN_MS = 10000
const SLOT_REARM_DEDUPE_MS = 500

let queue = _readQueue()
let flushTimer = null
let foreground = false
let sessionId = ''
let sessionStart = 0
let currentPage = ''
let currentPageStart = 0
let consentInitialized = false
const slotStates = new Set()

function _readQueue() {
  try {
    const raw = storage.get(QUEUE_KEY, [])
    return Array.isArray(raw) ? raw.slice(-MAX_QUEUE) : []
  } catch (e) {
    return []
  }
}

function _saveQueue() {
  storage.set(QUEUE_KEY, queue.slice(-MAX_QUEUE))
}

function _randomId(prefix) {
  const body = Date.now().toString(36) + Math.random().toString(36).slice(2, 10)
  return (prefix || '') + body
}

function _visitorId() {
  let value = storage.get(VISITOR_KEY, '')
  if (!value) {
    value = _randomId('v')
    storage.set(VISITOR_KEY, value)
  }
  return value
}

function getConsent() {
  // 统计强制开启：历史本地值不再作为退出依据。
  if (!consentInitialized) {
    storage.set(CONSENT_KEY, '1')
    consentInitialized = true
  }
  return '1'
}

function hasConsent() {
  return true
}

function _pageContext(page, feature) {
  return {
    page: page || currentPage || '',
    feature: feature || ''
  }
}

function _event(name, data) {
  const payload = data || {}
  const properties = {}
  if (payload.duration_s != null) properties.duration_s = Number(payload.duration_s) || 0
  if (payload.visible_ms != null) properties.visible_ms = Number(payload.visible_ms) || 0
  if (payload.result) properties.result = String(payload.result).slice(0, 40)
  if (payload.kind) properties.kind = String(payload.kind).slice(0, 40)
  if (payload.source) properties.source = String(payload.source).slice(0, 40)
  return {
    id: _randomId('e'),
    name,
    ts: Date.now(),
    session_id: sessionId || _randomId('s'),
    page: payload.page || currentPage || '',
    feature: payload.feature || '',
    slot_id: payload.slot_id || '',
    ad_type: payload.ad_type || '',
    visible_ms: Number(payload.visible_ms) || 0,
    app_version: String(config.BUILD || '').slice(0, 40),
    platform: '',
    properties
  }
}

function _enqueue(name, data) {
  if (!hasConsent()) return
  try {
    queue.push(_event(name, data))
    queue = queue.slice(-MAX_QUEUE)
    _saveQueue()
  } catch (e) {
    return
  }
  if (queue.length >= 8) {
    flush()
  } else if (!flushTimer && typeof setTimeout === 'function') {
    flushTimer = setTimeout(() => {
      flushTimer = null
      flush()
    }, 5000)
  }
}

function flush() {
  if (!hasConsent() || !queue.length) return Promise.resolve()
  const batch = queue.slice(0, 20)
  return api.trackEvents(batch, _visitorId()).then((res) => {
    if (!res || !res.success) return
    const sent = new Set(batch.map(item => item.id))
    queue = queue.filter(item => !sent.has(item.id))
    _saveQueue()
    if (queue.length) {
      setTimeout(flush, 800)
    }
  }).catch(() => {})
}

function _startForeground(source) {
  if (!hasConsent() || foreground) return
  foreground = true
  sessionId = _randomId('s')
  sessionStart = Date.now()
  _enqueue('app_open', { source })
  _enqueue('session_start', { source })
}

function _endForeground() {
  if (!hasConsent() || !foreground) return
  const durationS = Math.max(0, Math.round((Date.now() - sessionStart) / 1000))
  _enqueue('session_end', { duration_s: durationS })
  _enqueue('app_background', { duration_s: durationS })
  foreground = false
  flush()
}

function onLaunch() {
  if (getConsent() === '1') {
    _startForeground('launch')
  }
}

function onShow() {
  if (getConsent() === '1') _startForeground('show')
}

function onHide() {
  _finalizeAllSlots()
  _endForeground()
}

function pageView(page, feature) {
  if (currentPage && currentPage !== page) {
    _enqueue('page_leave', {
      page: currentPage,
      duration_s: Math.max(0, Math.round((Date.now() - currentPageStart) / 1000))
    })
  }
  currentPage = page || ''
  currentPageStart = Date.now()
  _enqueue('page_view', _pageContext(page, feature))
}

function featureOpen(feature, page) {
  _enqueue('feature_open', _pageContext(page, feature))
}

function featureAction(feature, page, extra) {
  _enqueue('feature_action', Object.assign(
    { feature, page: page || currentPage || '' }, extra || {}))
}

function refreshResult(feature, ok, page) {
  _enqueue(ok ? 'refresh_success' : 'refresh_fail', {
    feature,
    page: page || currentPage || '',
    result: ok ? 'ok' : 'fail'
  })
}

function track(name, extra) {
  _enqueue(name, extra || {})
}

function _clearSlotTimers(state) {
  if (!state) return
  if (state.timer) clearTimeout(state.timer)
  if (state.retryTimer) clearTimeout(state.retryTimer)
  state.timer = null
  state.retryTimer = null
}

function _scheduleSlotQualification(state) {
  if (!state || state.cancelled || !state.visible || !state.armed ||
      state.countedInActivation) return
  if (state.timer) clearTimeout(state.timer)
  const now = Date.now()
  const cooldownDelay = Math.max(0, (state.cooldownUntil || 0) - now)
  const delay = cooldownDelay > 0 ? cooldownDelay : SLOT_MIN_VISIBLE_MS
  state.timer = setTimeout(() => {
    state.timer = null
    if (state.cancelled || !state.visible || !state.armed ||
        state.countedInActivation) return
    if (Date.now() < (state.cooldownUntil || 0)) {
      _scheduleSlotQualification(state)
      return
    }
    state.countedInActivation = true
    state.segmentCounted = true
    state.countedAt = Date.now()
    _enqueue('slot_view', {
      slot_id: state.slotId,
      page: state.page,
      ad_type: state.adType
    })
    _enqueue('slot_visible', {
      slot_id: state.slotId,
      page: state.page,
      ad_type: state.adType,
      visible_ms: SLOT_MIN_VISIBLE_MS
    })
  }, delay)
}

function _finalizeSlot(state, now) {
  if (!state || !state.visible) return
  if (state.timer) clearTimeout(state.timer)
  state.timer = null
  const endedAt = now || Date.now()
  if (state.segmentCounted) {
    const remainder = Math.max(0, endedAt - (state.countedAt || endedAt))
    if (remainder > 0) {
      _enqueue('slot_leave', {
        slot_id: state.slotId,
        page: state.page,
        ad_type: state.adType,
        visible_ms: remainder
      })
    }
    state.cooldownUntil = endedAt + SLOT_REENTRY_COOLDOWN_MS
  }
  state.visible = false
  state.segmentCounted = false
  state.countedAt = 0
}

function _armSlot(state, now) {
  if (!state || state.cancelled) return
  if (now - (state.lastArmedAt || 0) < SLOT_REARM_DEDUPE_MS) return
  state.lastArmedAt = now
  if (state.visible) {
    _finalizeSlot(state, now)
    state.visible = true
    state.visibleSince = now
    state.countedAt = 0
  }
  state.armed = true
  state.countedInActivation = false
  if (state.visible) _scheduleSlotQualification(state)
}

function _finalizeAllSlots() {
  const now = Date.now()
  slotStates.forEach((state) => {
    _finalizeSlot(state, now)
  })
}

function observeSlot(ctx, slotId, page, adType) {
  if (!ctx || !slotId || typeof wx === 'undefined') return
  const hasContextObserver = typeof ctx.createIntersectionObserver === 'function'
  const hasGlobalObserver = typeof wx.createIntersectionObserver === 'function'
  if (!hasContextObserver && !hasGlobalObserver) return
  if (!ctx._usageSlots) ctx._usageSlots = {}
  if (ctx._usageSlots[slotId]) {
    _armSlot(ctx._usageSlots[slotId], Date.now())
    return
  }
  const state = {
    slotId,
    page,
    adType,
    visible: false,
    visibleSince: 0,
    countedAt: 0,
    segmentCounted: false,
    countedInActivation: false,
    armed: true,
    cooldownUntil: 0,
    lastArmedAt: Date.now(),
    timer: null,
    retryTimer: null,
    observer: null,
    cancelled: false,
    retries: 0
  }
  ctx._usageSlots[slotId] = state
  slotStates.add(state)
  const handleIntersection = (res) => {
    if (state.cancelled) return
    try {
      const visible = !!(res && res.intersectionRatio >= SLOT_VISIBLE_RATIO)
      if (visible && !state.visible) {
        state.visible = true
        state.visibleSince = Date.now()
        _scheduleSlotQualification(state)
      } else if (!visible && state.visible) {
        _finalizeSlot(state, Date.now())
      }
    } catch (e) { /* 统计异常不影响页面 */ }
  }

  const attach = () => {
    if (state.cancelled || !ctx._usageSlots || ctx._usageSlots[slotId] !== state) return
    if (typeof ctx.createSelectorQuery !== 'function') return
    let query = null
    try {
      query = ctx.createSelectorQuery()
    } catch (e) {
      return
    }
    if (!query || typeof query.select !== 'function') return
    query.select('#' + slotId).boundingClientRect((rect) => {
      if (state.cancelled || !ctx._usageSlots ||
          ctx._usageSlots[slotId] !== state) return
      if (!rect) {
        state.retries += 1
        if (state.retries <= 16) {
          state.retryTimer = setTimeout(attach, 120)
        } else {
          delete ctx._usageSlots[slotId]
          slotStates.delete(state)
        }
        return
      }
      try {
        const options = { thresholds: [0.5], nativeMode: true }
        const observer = hasContextObserver
          ? ctx.createIntersectionObserver(options)
          : wx.createIntersectionObserver(ctx, options)
        state.observer = observer
        observer.relativeToViewport({ bottom: 0 })
          .observe('#' + slotId, handleIntersection)
      } catch (e) {
        if (state.observer && state.observer.disconnect) {
          state.observer.disconnect()
        }
        delete ctx._usageSlots[slotId]
        slotStates.delete(state)
      }
    }).exec()
  }
  setTimeout(attach, 0)
}

function observeSlots(ctx, slots) {
  ;(slots || []).forEach(item => {
    if (!item || !item.id) return
    observeSlot(ctx, item.id, item.page, item.ad_type || '')
  })
}

function disconnectSlots(ctx) {
  if (!ctx || !ctx._usageSlots) return
  const now = Date.now()
  Object.keys(ctx._usageSlots).forEach((key) => {
    const state = ctx._usageSlots[key]
    if (!state) return
    _finalizeSlot(state, now)
    state.cancelled = true
    _clearSlotTimers(state)
    if (state.observer && state.observer.disconnect) state.observer.disconnect()
    slotStates.delete(state)
  })
  ctx._usageSlots = {}
}

module.exports = {
  getConsent,
  hasConsent,
  onLaunch,
  onShow,
  onHide,
  pageView,
  featureOpen,
  featureAction,
  refreshResult,
  track,
  observeSlot,
  observeSlots,
  disconnectSlots
}
