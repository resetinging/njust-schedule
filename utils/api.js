/**
 * API 封装 — 所有后端接口调用
 * 自动附加 token，统一错误处理
 */

const config = require('./config')
const storage = require('./storage')

// ============================================================
// 底层请求封装
// ============================================================

/**
 * 发起 HTTP 请求
 * @param {string} method - GET | POST
 * @param {string} path - API 路径 (如 '/api/get-captcha')
 * @param {object} data - 请求参数
 * @param {boolean} auth - 是否需要 token
 * @returns {Promise<object>} { success, data, message }
 */
function request(method, path, data = {}, auth = true) {
  const header = { 'Content-Type': 'application/json' }
  if (auth) {
    const token = storage.getToken()
    if (token) {
      header['Authorization'] = `Bearer ${token}`
    }
  }

  return new Promise((resolve, reject) => {
    wx.request({
      url: config.API_BASE + path,
      method,
      data,
      header,
      timeout: config.REQUEST_TIMEOUT,
      success(res) {
        if (res.statusCode === 200) {
          resolve(res.data)
        } else if (res.statusCode === 401) {
          // token 过期，清除并提示
          storage.clearToken()
          resolve({ success: false, message: '登录已过期，请重新登录' })
        } else {
          resolve({
            success: false,
            message: res.data?.message || `服务器错误 ${res.statusCode}`
          })
        }
      },
      fail(err) {
        resolve({
          success: false,
          message: `网络请求失败: ${err.errMsg || '未知错误'}`
        })
      }
    })
  })
}

// ============================================================
// 认证接口
// ============================================================

/** 获取验证码图片 (base64) */
function getCaptcha() {
  return request('GET', '/api/get-captcha', {}, false)
}

/** 手动输入验证码登录 */
function login(studentId, password, captcha) {
  return request('POST', '/api/login-manual', {
    student_id: studentId,
    password: password,
    captcha: captcha
  }, false).then(res => {
    if (res.success) {
      storage.setToken(res.token || '')
      storage.setStudentId(studentId)
      storage.setStudentName(res.student_name || '')
      storage.setSemester(res.semester || '')
    }
    return res
  })
}

/** 退出登录 */
function logout() {
  storage.clearAll()
}

// ============================================================
// 课表接口
// ============================================================

/** 获取缓存的课表 */
function getCourses(semester) {
  return request('GET', '/api/courses', { semester: semester || storage.getSemester() })
}

/** 刷新课表（从教务拉取） */
function refreshSchedule() {
  return request('POST', '/api/refresh-schedule').then(res => {
    if (res.success) {
      storage.setCached('cached_courses', res.courses || [])
      storage.setSemester(res.semester || '')
    }
    return res
  })
}

// ============================================================
// 考试接口
// ============================================================

/** 获取缓存的考试安排 */
function getExams(semester) {
  return request('GET', '/api/exams', { semester: semester || storage.getSemester() })
}

/** 刷新考试安排 */
function refreshExams() {
  return request('POST', '/api/refresh-exams').then(res => {
    if (res.success) {
      storage.setCached('cached_exams', res.exams || [])
    }
    return res
  })
}

/** 一键刷新课表+考试 */
function refreshAll() {
  return request('POST', '/api/refresh-all').then(res => {
    if (res.success) {
      if (res.schedule?.ok) storage.setCached('cached_courses', [])
      if (res.exams?.ok) storage.setCached('cached_exams', [])
    }
    return res
  })
}

// ============================================================
// 评教接口
// ============================================================

/** 获取评教批次列表 */
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

/** 发起批量评教 */
function startBatchEval(batchUrl, targetScore, submitType, actionPath, hiddenFields) {
  return request('POST', '/api/batch-submit-eval', {
    batch_url: batchUrl,
    target_score: targetScore,
    submit_type: submitType || '1',
    action_path: actionPath || '/njlgdx/xspj/xspj_save.do',
    hidden_fields: hiddenFields || {}
  })
}

/** 查询批量评教进度 */
function getBatchProgress(batchId) {
  return request('GET', `/api/batch-progress/${batchId}`)
}

/** 自动评分建议（不下发表单） */
function getAutoFillSuggestion(formData, targetScore) {
  return request('POST', '/api/eval/auto-fill', {
    form_data: formData,
    target_score: targetScore
  })
}

// ============================================================
// 系统状态
// ============================================================

/** 获取系统状态（登录状态、学期等） */
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

/** 获取可用学期列表 */
function getSemesters() {
  return request('GET', '/api/semesters')
}

module.exports = {
  getCaptcha,
  login,
  logout,
  getCourses,
  refreshSchedule,
  getExams,
  refreshExams,
  refreshAll,
  getEvalBatches,
  refreshEvaluations,
  getEvalCourses,
  getEvalForm,
  submitEval,
  startBatchEval,
  getBatchProgress,
  getAutoFillSuggestion,
  getStatus,
  setSemester,
  clearData,
  getSemesters
}
