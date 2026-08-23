/**
 * API 封装 — 所有后端接口调用
 * 统一错误处理
 */

const config = require('./config')
const storage = require('./storage')

// ============================================================
// 底层请求封装
// ============================================================

/**
 * 发起 HTTP 请求（通过云托管内网，免域名白名单）
 * @param {string} method - GET | POST
 * @param {string} path - API 路径 (如 '/api/get-captcha')
 * @param {object} data - 请求参数
 * @returns {Promise<object>} { success, data, message }
 */
function request(method, path, data = {}) {
  const header = { 'Content-Type': 'application/json' }

  return new Promise((resolve) => {
    wx.cloud.callContainer({
      config: { env: config.CLOUD_ENV, service: config.CLOUD_SERVICE },
      path,
      method,
      header,
      data,
      timeout: config.REQUEST_TIMEOUT,
      success(res) {
        if (res.statusCode === 200) {
          resolve(res.data)
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
  return request('GET', '/api/get-captcha')
}

/** 手动输入验证码登录 */
function login(studentId, password, captcha) {
  return request('POST', '/api/login-manual', {
    student_id: studentId,
    password: password,
    captcha: captcha
  }).then(res => {
    if (res.success) {
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

/** Step 1: 智慧理工 SSO 登录并获取教务验证码 */
function getWebvpnCaptcha(studentId, password) {
  return request('POST', '/api/get-webvpn-captcha', {
    student_id: studentId,
    password: password
  })
}

/** Step 2: 使用验证码完成教务登录（智慧理工模式） */
function loginWebvpnManual(studentId, password, jwcPassword, captcha) {
  return request('POST', '/api/login-webvpn-manual', {
    student_id: studentId,
    password: password,
    jwc_password: jwcPassword || password,
    captcha: captcha
  })
}

/** 智慧理工模式自动登录（自动 OCR 教务验证码） */
function loginWebvpn(studentId, password, jwcPassword) {
  return request('POST', '/api/login-webvpn', {
    student_id: studentId,
    password: password,
    jwc_password: jwcPassword || password
  })
}

// ============================================================
// 设置与校历接口
// ============================================================

/** 保存设置（first_week_date 等） */
function saveSettings(data) {
  return request('POST', '/api/settings', data)
}

/** 获取校历图片列表 */
function getGalleryImages() {
  return request('GET', '/api/gallery-images')
}

/** 获取单张校历图片（base64） */
function getGalleryImage(name) {
  return request('GET', '/api/gallery-image', { name })
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
  getStatus,
  setSemester,
  clearData,
  getSemesters,
  getGrades,
  refreshGrades,
  getCetScores,
  refreshCet,
  getWebvpnCaptcha,
  loginWebvpnManual,
  loginWebvpn,
  saveSettings,
  getGalleryImages,
  getGalleryImage
}
