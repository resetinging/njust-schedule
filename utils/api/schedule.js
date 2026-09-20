/**
 * API ???: schedule (Phase 3 ? utils/api.js ??)
 */
const { request } = require('./core')

function getCourses(semester) {
  return request('GET', '/api/courses', { semester: semester || storage.getSemester() })
}

/** 刷新课表（从教务拉取） */

function refreshSchedule() {
  return request('POST', '/api/refresh-schedule').then(res => {
    if (res.success) {
      // 刷新接口不返回课程数据，只确认刷新成功
      // 后续 loadFromServer() 会通过 GET /api/courses 获取最新数据
      storage.setSemester(res.semester || '')
    }
    return res
  })
}

// ============================================================
// 考试接口
// ============================================================

/** 获取缓存的考试安排 */

module.exports = { getCourses, refreshSchedule }
