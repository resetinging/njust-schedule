/**
 * API 封装 — 所有后端接口调用
 * 统一错误处理
 */

const config = require('./config')
const storage = require('./storage')

// 登录 token 存储键（多用户：请求携带 X-Auth-Token 标识会话）
const TOKEN_KEY = 'token'

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
  const token = storage.get(TOKEN_KEY, '')
  if (token) header['X-Auth-Token'] = token

  // 本地联调: 直连本机 Flask(需开发者工具勾选「不校验合法域名」)
  if (config.USE_LOCAL) {
    return new Promise((resolve) => {
      wx.request({
        url: config.LOCAL_BASE + path,
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
              message: (res.data && res.data.message) || ('服务器错误 ' + res.statusCode)
            })
          }
        },
        fail(err) {
          resolve({
            success: false,
            message: '网络请求失败: ' + (err.errMsg || '未知错误')
          })
        }
      })
    })
  }

  return new Promise((resolve) => {
    // 服务名通过 X-WX-SERVICE header 传递（官方兼容写法）；
    // config 仅放 env，避免部分基础库版本不支持 config.service 导致
    // 请求丢失服务名 → 网关 INVALID_PATH。
    wx.cloud.callContainer({
      config: { env: config.CLOUD_ENV },
      path,
      method,
      header: Object.assign({ 'X-WX-SERVICE': config.CLOUD_SERVICE }, header),
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

/** 手动输入验证码登录（多用户：携带 captcha_id 绑定验证码会话） */
function login(studentId, password, captcha, captchaId) {
  return request('POST', '/api/login-manual', {
    student_id: studentId,
    password: password,
    captcha: captcha,
    captcha_id: captchaId || ''
  }).then(res => {
    if (res.success) {
      storage.clearAll()   // 换号登录：清空上一用户的全部本地数据
      storage.setStudentId(studentId)
      storage.setStudentName(res.student_name || '')
      storage.setSemester(res.semester || '')
      storage.set(TOKEN_KEY, res.token || '')
    }
    return res
  })
}

/** 退出登录（销毁后端会话 + 清空本地） */
function logout() {
  return request('POST', '/api/logout').then(() => {
    storage.clearAll()
  }).catch(() => {
    storage.clearAll()
  })
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

/** Step 1: 智慧理工 SSO 登录并获取教务验证码（含 captcha_id / 直接登录 token） */
function getWebvpnCaptcha(studentId, password) {
  return request('POST', '/api/get-webvpn-captcha', {
    student_id: studentId,
    password: password
  }).then(res => {
    // SSO 后已有教务会话：直接获得登录 token
    if (res.success && res.already_logged_in && res.token) {
      storage.clearAll()   // 换号登录：清空上一用户的全部本地数据
      storage.setStudentId(studentId)
      storage.set(TOKEN_KEY, res.token)
    }
    return res
  })
}

/** Step 2: 使用验证码完成教务登录（智慧理工模式，携带 captcha_id） */
function loginWebvpnManual(studentId, password, jwcPassword, captcha, captchaId) {
  return request('POST', '/api/login-webvpn-manual', {
    student_id: studentId,
    password: password,
    jwc_password: jwcPassword || password,
    captcha: captcha,
    captcha_id: captchaId || ''
  }).then(res => {
    if (res.success) {
      storage.clearAll()   // 换号登录：清空上一用户的全部本地数据
      storage.setStudentId(studentId)
      storage.setStudentName(res.student_name || '')
      storage.setSemester(res.semester || '')
      storage.set(TOKEN_KEY, res.token || '')
    }
    return res
  })
}

/** 智慧理工模式自动登录（自动 OCR 教务验证码） */
function loginWebvpn(studentId, password, jwcPassword) {
  return request('POST', '/api/login-webvpn', {
    student_id: studentId,
    password: password,
    jwc_password: jwcPassword || password
  }).then(res => {
    if (res.success) {
      storage.clearAll()   // 换号登录：清空上一用户的全部本地数据
      storage.setStudentId(studentId)
      storage.setStudentName(res.student_name || '')
      storage.setSemester(res.semester || '')
      storage.set(TOKEN_KEY, res.token || '')
    }
    return res
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
