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

let queue = _readQueue()
let flushTimer = null
let foreground = false
let sessionId = ''
let sessionStart = 0
let currentPage = ''
let currentPageStart = 0
let consentInitialized = false

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

function observeSlot(ctx, slotId, page, adType) {
  if (!ctx || !slotId || typeof wx === 'undefined' ||
      typeof wx.createIntersectionObserver !== 'function') return
  if (!ctx._usageSlots) ctx._usageSlots = {}
  if (ctx._usageSlots[slotId]) return
  const state = { visible: false, enteredAt: 0, timer: null }
  ctx._usageSlots[slotId] = state
  let observer = null
  try {
    observer = wx.createIntersectionObserver(ctx, { thresholds: [0.5] })
    observer.relativeToViewport({ bottom: 0 }).observe('#' + slotId, (res) => {
      const visible = !!(res && res.intersectionRatio >= 0.5)
      if (visible && !state.visible) {
        state.visible = true
        state.enteredAt = Date.now()
        _enqueue('slot_view', { slot_id: slotId, page, ad_type: adType })
        state.timer = setTimeout(() => {
          if (state.visible) {
            _enqueue('slot_visible', {
              slot_id: slotId,
              page,
              ad_type: adType,
              visible_ms: Math.max(0, Date.now() - state.enteredAt)
            })
          }
        }, 1000)
      } else if (!visible && state.visible) {
        state.visible = false
        if (state.timer) clearTimeout(state.timer)
        state.timer = null
        _enqueue('slot_leave', {
          slot_id: slotId,
          page,
          ad_type: adType,
          visible_ms: Math.max(0, Date.now() - state.enteredAt - 1000)
        })
      }
    })
    state.observer = observer
  } catch (e) {
    if (observer && observer.disconnect) observer.disconnect()
    delete ctx._usageSlots[slotId]
  }
}

function observeSlots(ctx, slots) {
  ;(slots || []).forEach(item => {
    if (!item || !item.id) return
    observeSlot(ctx, item.id, item.page, item.ad_type || '')
  })
}

function disconnectSlots(ctx) {
  if (!ctx || !ctx._usageSlots) return
  Object.keys(ctx._usageSlots).forEach((key) => {
    const state = ctx._usageSlots[key]
    if (!state) return
    if (state.timer) clearTimeout(state.timer)
    if (state.observer && state.observer.disconnect) state.observer.disconnect()
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
