/**
 * API 封装: 教学周历 / 培养方案(学分进度)
 */
const { request } = require('./core')

/** 教学周历(第 N 周 → 日期; 后端全局缓存 7 天) */
function getCalendar(semester) {
  const params = {}
  if (semester) params.semester = semester
  return request('GET', '/api/calendar', params)
}

/** 强制刷新教学周历 */
function refreshCalendar(semester) {
  return request('POST', '/api/refresh-calendar', semester ? { semester } : {})
}

/** 专业培养方案(整份; 登录后后端会自动预抓一次) */
function getProgramme() {
  return request('GET', '/api/programme')
}

/** 强制刷新培养方案 */
function refreshProgramme() {
  return request('POST', '/api/refresh-programme')
}

module.exports = { getCalendar, refreshCalendar, getProgramme, refreshProgramme }
