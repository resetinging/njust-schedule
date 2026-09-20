/**
 * API ???: freeclass (Phase 3 ? utils/api.js ??)
 */
const { request } = require('./core')

function getFreeClassrooms(opts) {
  const o = opts || {}
  const params = {}
  if (o.campus) params.campus = o.campus
  if (o.weekday) params.weekday = o.weekday
  if (o.jc1) params.jc1 = o.jc1
  if (o.jc2) params.jc2 = o.jc2
  if (o.week) params.week = o.week
  if (o.semester) params.semester = o.semester
  return request('GET', '/api/free-classrooms', params)
}

/** 提交问题反馈(类型: suggest 功能建议 | bug 问题 | other 其他; 服务端 10 秒限流) */

module.exports = { getFreeClassrooms }
