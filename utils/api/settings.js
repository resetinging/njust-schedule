/**
 * API ???: settings (Phase 3 ? utils/api.js ??)
 */
const { request } = require('./core')
const storage = require('../storage')

function getStatus() {
  return request('GET', '/api/status')
}

/** 切换学期 */

function setSemester(semester) {
  return request('POST', '/api/semester', { semester }).then(res => {
    if (res.success) {
      storage.setSemester(semester)
    }
    return res
  })
}

/** 清除服务端缓存数据 */

function clearData() {
  return request('POST', '/api/clear-data')
}

// ============================================================
// 学期接口
// ============================================================

/** 获取可用学期列表（从 settings 接口获取，避免额外路由依赖） */

function getSemesters() {
  return request('GET', '/api/settings').then(res => {
    if (res.semester_list) {
      return { success: true, semesters: res.semester_list, current: res.current_semester }
    }
    return { success: false, semesters: [], current: '' }
  })
}

// ============================================================
// 成绩接口
// ============================================================

/** 获取成绩数据 */

function saveSettings(data) {
  return request('POST', '/api/settings', data)
}

/** 校历图片直链 URL（后端静态文件, 二进制直传）
 *  不走 callContainer: 该通道在部分环境(开发者工具/弱网)会 ERR_CONNECTION_CLOSED
 *  或受返回包 ~1000KB 限制; 直链无这些限制。真机需将 API_BASE 域名加入
 *  downloadFile 合法域名白名单; 开发者工具 urlCheck=false 无需配置。 */

module.exports = { getStatus, setSemester, clearData, getSemesters, saveSettings }
