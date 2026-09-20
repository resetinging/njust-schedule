/**
 * API ???: feedback (Phase 3 ? utils/api.js ??)
 */
const { request } = require('./core')

function getAnnouncement() {
  return request('GET', '/api/announcement')
}

/**
 * 空教室查询(需登录)
 * @param {object} opts { campus: '孝陵卫'|'江阴', weekday: 1-7(周一=1),
 *   jc1/jc2: 节次范围起止(1-13), week: 周次, semester: 学年学期(可选) }
 * weekday/week 省略时由后端取默认(今天/本周);
 * semester 传入时后端仅在教务学期选项里存在时采用, 否则回退教务当前学期
 */

function submitFeedback(fbType, content) {
  return request('POST', '/api/feedback', {
    type: fbType || 'other',
    content: content || ''
  })
}

/** 我的反馈列表(含管理员回复) + 未读回复数 */

function getMyFeedback() {
  return request('GET', '/api/my-feedback')
}

/** 标记回复已读(打开「我的反馈」时调用) */

function markFeedbackRead() {
  return request('POST', '/api/my-feedback/read')
}

/** 获取系统状态（登录状态、学期等） */

module.exports = { getAnnouncement, submitFeedback, getMyFeedback, markFeedbackRead }
