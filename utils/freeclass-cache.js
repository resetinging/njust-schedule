/**
 * 空教室查询缓存 — 页面与启动预热共用同一套键和读写规则。
 */

const storage = require('./storage')

const CACHE_KEY = 'freeclass_cache_v2'
const LEGACY_CACHE_KEY = 'freeclass_cache'
const CACHE_MAX_ITEMS = 20
const NO_REQUEST_AGE = 5 * 60 * 1000

/**
 * 缓存键: 请求条件(含学期, 跨学期必须区分)
 * weekday/week 用 0 表示"今天/本周"(未指定, 由后端推算)
 */
function cacheKeyOf(params) {
  return [params.campus, params.weekday || 0, params.week || 0, params.jc1, params.jc2,
    params.semester || ''].join('|')
}

/**
 * 响应里后端已把"今天/本周"解析成具体星期/周次 → 用实际条件再算一个键。
 */
function resolvedKeyOf(res) {
  if (!res || !res.campus) return ''
  return [res.campus, res.weekday || 0, res.week || 0, res.jc1, res.jc2,
    res.semester || ''].join('|')
}

function readCache(key) {
  try {
    const box = storage.getCached(CACHE_KEY) || {}
    const item = (box.items || {})[key]
    return item && item.data ? { t: item.t || 0, data: item.data } : null
  } catch (e) {
    return null
  }
}

function writeCache(key, data) {
  try {
    const box = storage.getCached(CACHE_KEY) || {}
    if (!box.items) box.items = {}
    box.items[key] = { t: Date.now(), data }
    const keys = Object.keys(box.items)
    if (keys.length > CACHE_MAX_ITEMS) {
      keys.sort((a, b) => (box.items[a].t || 0) - (box.items[b].t || 0))
      keys.slice(0, keys.length - CACHE_MAX_ITEMS).forEach(k => delete box.items[k])
    }
    storage.setCached(CACHE_KEY, box)
  } catch (e) {
    // 缓存写入失败不影响主流程
  }
}

/**
 * 后台预热默认查询条件: 页面打开时可直接命中本地缓存。
 * 失败静默忽略, 不阻塞启动或用户操作。
 */
function warm(params) {
  const key = cacheKeyOf(params || {})
  const hit = readCache(key)
  if (hit && Date.now() - hit.t < NO_REQUEST_AGE) {
    return Promise.resolve(hit.data)
  }
  const api = require('./api')
  return api.getFreeClassrooms(params || {}).then(res => {
    if (!res || !res.success) return null
    writeCache(key, res)
    const resolvedKey = resolvedKeyOf(res)
    if (resolvedKey && resolvedKey !== key) writeCache(resolvedKey, res)
    return res
  }).catch(() => null)
}

module.exports = {
  CACHE_KEY,
  LEGACY_CACHE_KEY,
  NO_REQUEST_AGE,
  cacheKeyOf,
  resolvedKeyOf,
  readCache,
  writeCache,
  warm
}
