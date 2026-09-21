/**
 * API ???: auth (Phase 3 ? utils/api.js ??)
 */
const { request } = require('./core')
const storage = require('../storage')

function getCaptcha() {
  return request('GET', '/api/get-captcha')
}

/** 手动输入验证码登录（多用户：携带 captcha_id 绑定验证码会话） */

function login(studentId, password, captcha, captchaId) {
  const hadSavedPwd = storage.get('saved_password', '')
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
      if (hadSavedPwd) storage.set('saved_password', password)  // 延续记住密码
    }
    return res
  })
}

/** 教务直连自动登录（服务端 ddddocr 自动识别验证码，无需输入） */

function loginAuto(studentId, password) {
  const hadSavedPwd = storage.get('saved_password', '')
  return request('POST', '/api/login', {
    student_id: studentId,
    password: password
  }).then(res => {
    if (res.success) {
      storage.clearAll()   // 换号登录：清空上一用户的全部本地数据
      storage.setStudentId(studentId)
      storage.setStudentName(res.student_name || '')
      storage.setSemester(res.semester || '')
      storage.set(TOKEN_KEY, res.token || '')
      if (hadSavedPwd) storage.set('saved_password', password)  // 延续记住密码
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

function getWebvpnCaptcha(studentId, password) {
  const hadSavedPwd = storage.get('saved_password', '')
  return request('POST', '/api/get-webvpn-captcha', {
    student_id: studentId,
    password: password
  }).then(res => {
    // SSO 后已有教务会话：直接获得登录 token
    if (res.success && res.already_logged_in && res.token) {
      storage.clearAll()   // 换号登录：清空上一用户的全部本地数据
      storage.setStudentId(studentId)
      storage.setStudentName(res.student_name || '')
      storage.setSemester(res.semester || '')
      storage.set(TOKEN_KEY, res.token)
      if (hadSavedPwd) storage.set('saved_password', password)  // 延续记住密码
    }
    return res
  })
}

/** Step 2: 使用验证码完成教务登录（智慧理工模式，携带 captcha_id） */

function loginWebvpnManual(studentId, password, captcha, captchaId) {
  const hadSavedPwd = storage.get('saved_password', '')
  return request('POST', '/api/login-webvpn-manual', {
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
      if (hadSavedPwd) storage.set('saved_password', password)  // 延续记住密码
    }
    return res
  })
}

/** 智慧理工模式自动登录（SSO 直连教务，服务端自动处理验证码） */

function loginWebvpn(studentId, password) {
  const hadSavedPwd = storage.get('saved_password', '')
  return request('POST', '/api/login-webvpn', {
    student_id: studentId,
    password: password
  }).then(res => {
    if (res.success) {
      storage.clearAll()   // 换号登录：清空上一用户的全部本地数据
      storage.setStudentId(studentId)
      storage.setStudentName(res.student_name || '')
      storage.setSemester(res.semester || '')
      storage.set(TOKEN_KEY, res.token || '')
      if (hadSavedPwd) storage.set('saved_password', password)  // 延续记住密码
    }
    return res
  })
}

// ============================================================
// 设置与校历接口
// ============================================================

/** 保存设置（first_week_date 等） */

module.exports = { getCaptcha, login, loginAuto, logout, getWebvpnCaptcha, loginWebvpnManual, loginWebvpn }
