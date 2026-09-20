/**
 * API ???: refresh (Phase 3 ? utils/api.js ??)
 */
const { request } = require('./core')

function refreshAll() {
  return request('POST', '/api/refresh-all').then(res => {
    if (res.success) {
      // 移除带学期后缀的缓存键(旧的裸键无读取方, 已废弃)
      try {
        const info = wx.getStorageInfoSync()
        info.keys.forEach(k => {
          const key = String(k)
          if (res.schedule && res.schedule.ok && key.indexOf('cached_courses_') === 0) storage.remove(key)
          if (res.exams && res.exams.ok && key.indexOf('cached_exams_') === 0) storage.remove(key)
        })
      } catch (e) {
        // 忽略
      }
    }
    return res
  })
}

// ============================================================
// 评教接口
// ============================================================

/** 获取评教批次列表 */

module.exports = { refreshAll }
