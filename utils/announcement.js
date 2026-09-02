/**
 * 公告工具 — 拉取/缓存/已读标记
 * 主页面顶部横幅 + "我的"页公告栏共用:
 * - updated 由管理端保存时间决定, "未读" = updated 与本地已读标记不同
 * - 用户查看(点击展开/弹窗确认)后 markSeen, 主页面横幅即隐藏
 * - 拉取带 30s 节流, 失败回退本地缓存(离线也能看到上次公告)
 */

const api = require('./api')
const storage = require('./storage')

const SEEN_KEY = 'ann_seen'              // 已读的公告 updated 值
const CACHE_KEY = 'cached_announcement'  // 最近一次公告快照
const FETCH_THROTTLE_MS = 30 * 1000

let lastFetch = 0

/** 拉取最新公告(节流); 返回 {enabled, text, updated} */
function load(force) {
  const now = Date.now()
  if (!force && now - lastFetch < FETCH_THROTTLE_MS) {
    return Promise.resolve(cached())
  }
  lastFetch = now
  return api.getAnnouncement()
    .then(res => {
      if (res && res.success) {
        const data = {
          enabled: !!res.enabled,
          text: res.text || '',
          updated: res.updated || ''
        }
        storage.setCached(CACHE_KEY, data)
        return data
      }
      return cached()
    })
    .catch(() => cached())
}

/** 本地缓存(无网络时兜底展示) */
function cached() {
  const c = storage.getCached(CACHE_KEY) || {}
  return { enabled: !!c.enabled, text: c.text || '', updated: c.updated || '' }
}

/** 是否为新公告(有更新时间且与已读标记不同) */
function isNew(updated) {
  return !!(updated && updated !== storage.get(SEEN_KEY, ''))
}

/** 标记已读(查看后主页面顶部横幅不再展示) */
function markSeen(updated) {
  if (updated) storage.set(SEEN_KEY, updated)
}

module.exports = { load, cached, isNew, markSeen }
