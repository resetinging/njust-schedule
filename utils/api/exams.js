/**
 * API ???: exams (Phase 3 ? utils/api.js ??)
 */
const { request } = require('./core')

function getExams(semester) {
  return request('GET', '/api/exams', { semester: semester || storage.getSemester() })
}

/** 刷新考试安排 */

function refreshExams() {
  return request('POST', '/api/refresh-exams').then(res => {
    if (res.success) {
      // 刷新接口不返回考试数据，后续通过 GET /api/exams 获取
    }
    return res
  })
}

/** 一键刷新课表+考试(刷新成功后移除学期后缀缓存, 由后续查询重新载入) */

module.exports = { getExams, refreshExams }
