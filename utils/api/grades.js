/**
 * API ???: grades (Phase 3 ? utils/api.js ??)
 */
const { request } = require('./core')

function getGrades(semester, gpaMode) {
  const params = {}
  if (semester) params.semester = semester
  else params.semester = '__all__'
  if (gpaMode) params.gpa_mode = gpaMode
  return request('GET', '/api/grades', params)
}

/** 刷新成绩（从教务抓取） */

function refreshGrades() {
  return request('POST', '/api/refresh-grades')
}

/** 获取四六级成绩 */

function getCetScores() {
  return request('GET', '/api/cet-scores')
}

/** 刷新四六级成绩 */

function refreshCet() {
  return request('POST', '/api/refresh-cet')
}

// ============================================================
// 智慧理工 SSO 登录接口
// ============================================================

/** Step 1: 智慧理工 SSO 登录并获取教务验证码（含 captcha_id / 直接登录 token）
 *  教务走 SSO 直连（indexsso.jsp），无需教务密码 */

module.exports = { getGrades, refreshGrades, getCetScores, refreshCet }
