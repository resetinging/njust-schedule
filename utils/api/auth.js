/**
 * API ???: auth (Phase 3 ? utils/api.js ??)
 */
const { request, TOKEN_KEY } = require('./core')
const storage = require('../storage')

// 注: 教务直连（原 /api/get-captcha、/api/login-manual、/api/login）已于教务改版后
// 下线, 前端不再暴露入口, 只保留智慧理工 SSO 登录（见下方 loginWebvpn*）。

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

/** 智慧理工一步登录（SSO 直连教务，免教务密码/验证码） */

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

module.exports = { logout, loginWebvpn }
