/**
 * API ???: eval (Phase 3 ? utils/api.js ??)
 */
const { request } = require('./core')

function getEvalBatches() {
  return request('GET', '/api/evaluations')
}

/** 刷新评教数据 */

function refreshEvaluations() {
  return request('POST', '/api/refresh-evaluations')
}

/** 获取某批次下的课程列表 */

function getEvalCourses(batchUrl) {
  return request('GET', '/api/eval-courses', { url: batchUrl })
}

/** 获取某课程的评价表单 */

function getEvalForm(courseUrl) {
  return request('GET', '/api/eval-form', { url: courseUrl })
}

/** 提交单门评教 */

function submitEval(formData, submitType, action) {
  return request('POST', '/api/submit-eval', {
    form_data: formData,
    submit_type: submitType,
    action: action || '/njlgdx/xspj/xspj_save.do'
  })
}

// ============================================================
// 系统状态
// ============================================================

/** 获取公告(公开接口; 含 updated 时间, 用于"新公告未读"判断) */

module.exports = { getEvalBatches, refreshEvaluations, getEvalCourses, getEvalForm, submitEval }
