const api = require('./api')
const storage = require('./storage')
const changelog = require('./changelog')

const CACHE_KEY = 'cached_content_board'
const SEEN_KEY = 'content_board_seen'
const FETCH_THROTTLE_MS = 30 * 1000

const ANNOUNCEMENT_TYPE_LABELS = {
  notice: '公告',
  maintenance: '维护',
  feature: '新功能',
  deadline: '期限',
  issue: '已知问题'
}

const ANNOUNCEMENT_PRIORITY_LABELS = {
  normal: '',
  important: '重要',
  urgent: '紧急'
}

const CHANGE_TYPE_LABELS = {
  new: '新增',
  improve: '优化',
  fix: '修复',
  remove: '移除',
  update: '更新'
}

let lastFetch = 0

function emptyBoard() {
  return {
    updated: '',
    announcements: [],
    changelog: [],
    community: { name: '', qq: '', note: '' }
  }
}

function normalizeBoard(value) {
  const board = value || {}
  const today = calendarDate()
  return {
    updated: board.updated || '',
    announcements: (Array.isArray(board.announcements) ? board.announcements : [])
      .filter(item => item && item.enabled !== false &&
        (!item.expires_at || item.expires_at >= today))
      .map(normalizeAnnouncement),
    changelog: changelog.RELEASES.map(normalizeChangelog),
    community: Object.assign({ name: '', qq: '', note: '' }, board.community || {})
  }
}

function calendarDate() {
  const now = new Date()
  const month = String(now.getMonth() + 1).padStart(2, '0')
  const day = String(now.getDate()).padStart(2, '0')
  return now.getFullYear() + '-' + month + '-' + day
}

function normalizeAnnouncement(item) {
  const value = item || {}
  const type = value.type || 'notice'
  const priority = value.priority || 'normal'
  return Object.assign({}, value, {
    type,
    priority,
    type_label: ANNOUNCEMENT_TYPE_LABELS[type] || '公告',
    priority_label: ANNOUNCEMENT_PRIORITY_LABELS[priority] || '',
    audience: value.audience || '',
    action: value.action || '',
    effective_at: value.effective_at || '',
    expires_at: value.expires_at || ''
  })
}

function normalizeChange(item) {
  if (typeof item === 'string') {
    return { type: 'update', text: item, type_label: '更新' }
  }
  const value = item || {}
  const type = value.type || 'update'
  return {
    type,
    text: value.text || '',
    type_label: CHANGE_TYPE_LABELS[type] || '更新'
  }
}

function normalizeChangelog(item) {
  const value = Object.assign({
    version: '',
    title: '',
    published_at: '',
    changes: []
  }, item || {})
  const source = Array.isArray(value.changes) && value.changes.length
    ? value.changes
    : (Array.isArray(value.items) ? value.items : [])
  const seen = new Set()
  value.changes = source
    .map(normalizeChange)
    .filter(change => {
      if (!change.text) return false
      const key = change.type + '|' + change.text
      if (seen.has(key)) return false
      seen.add(key)
      return true
    })
  delete value.items
  return value
}

function load(force) {
  const now = Date.now()
  if (!force && now - lastFetch < FETCH_THROTTLE_MS) {
    return Promise.resolve(cached())
  }
  lastFetch = now
  return api.getContentBoard()
    .then(res => {
      if (!res || !res.success) {
        return loadLegacy(new Error((res && res.message) || '信息中心加载失败'))
      }
      const board = normalizeBoard(res.board)
      storage.setCached(CACHE_KEY, board)
      return board
    })
    .catch(error => loadLegacy(error))
}

function loadLegacy(primaryError) {
  if (typeof api.getAnnouncement !== 'function') {
    return Promise.resolve(cachedOrReject(primaryError))
  }
  return api.getAnnouncement()
    .then(res => {
      if (!res || !res.success) return cachedOrReject(primaryError)
      const updated = res.updated || ''
      const text = String(res.text || '').trim()
      const announcements = res.enabled && text
        ? [{
            id: 'legacy-announcement',
            title: '公告',
            body: text,
            type: 'notice',
            priority: 'important',
            audience: '',
            action: '',
            published_at: contentDate(updated),
            effective_at: '',
            expires_at: '',
            pinned: false,
            enabled: true
          }]
        : []
      const board = normalizeBoard({
        updated,
        announcements,
        changelog: [],
        community: { name: '', qq: '', note: '' }
      })
      storage.setCached(CACHE_KEY, board)
      return board
    })
    .catch(() => cachedOrReject(primaryError))
}

function contentDate(value) {
  const text = String(value || '')
  return /^\d{4}-\d{2}-\d{2}/.test(text) ? text.slice(0, 10) : ''
}

function cached() {
  return normalizeBoard(storage.getCached(CACHE_KEY) || emptyBoard())
}

function cachedOrReject(error) {
  const cachedBoard = storage.getCached(CACHE_KEY)
  if (cachedBoard) return normalizeBoard(cachedBoard)
  throw error instanceof Error ? error : new Error('信息中心加载失败')
}

function isNew(updated) {
  return !!(updated && updated !== storage.get(SEEN_KEY, ''))
}

function markSeen(updated) {
  if (updated) storage.set(SEEN_KEY, updated)
}

module.exports = {
  load,
  cached,
  isNew,
  markSeen,
  normalizeBoard,
  emptyBoard
}
