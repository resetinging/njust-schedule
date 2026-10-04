/**
 * API ???: auth (Phase 3 ? utils/api.js ??)
 */
const { request, TOKEN_KEY } = require('./core')
const storage = require('../storage')
const config = require('../config')

// 注: 教务直连（原 /api/get-captcha、/api/login-manual、/api/login）已于教务改版后
// 下线, 前端不再暴露入口, 只保留智慧理工 SSO 登录（见下方 loginWebvpn*）。

/** 微信扫码登录 Step 1: 申请一张智慧理工登录二维码（约 3 分钟有效） */

function startSsoQr() {
  // 带上本地学号: 素材服务器据此判断"演示账号"并返回演示二维码(不连真实智慧理工)
  return request('POST', '/api/sso-qr/start', { student_id: storage.getStudentId() })
}

/** 微信扫码登录 Step 2: 轮询状态; 确认后后端直接返回 token */

function ssoQrStatus(qrId) {
  return request('GET', '/api/sso-qr/status?qr_id=' + encodeURIComponent(qrId || ''))
    .then(res => {
      // 扫码确认后后端直接签发 token: 与密码登录一致地落本地登录态
      if (res && res.success && res.status === 'ok' && res.token) {
        const prevSid = storage.getStudentId()
        if (prevSid && res.student_id && prevSid !== res.student_id) {
          storage.clearAll()   // 换号扫码: 清空上一用户本地数据
        }
        storage.remove('analytics_queue')
        storage.setStudentId(res.student_id || '')
        storage.setStudentName(res.student_name || '')
        storage.setSemester(res.semester || '')
        storage.set(TOKEN_KEY, res.token)
        storage.remove('manual_logout')
        if (res.credential_delete_token) {
          storage.set('credential_delete_token', res.credential_delete_token)
        }
      }
      return res
    })
}

/** 二维码图片直链(真机上必须用 URL: base64 图片不会触发长按识别菜单) */

function ssoQrImageUrl(qrId) {
  const base = config.USE_LOCAL ? config.LOCAL_BASE : config.API_BASE
  return base + '/api/sso-qr/image?qr_id=' + encodeURIComponent(qrId || '')
}

/** 放弃本次扫码（释放后端临时会话） */

function cancelSsoQr(qrId) {
  return request('POST', '/api/sso-qr/cancel', { qr_id: qrId || '' })
}

/** 退出登录: 销毁后端 token 会话, 保留本机密码供下次回填 */

function logout() {
  const savedPassword = storage.get('saved_password', '')
  const lastSid = storage.getStudentId() || storage.get('last_login_sid', '')
  const finish = () => {
    storage.clearAll()
    storage.remove('analytics_queue')
    if (savedPassword) {
      storage.set('saved_password', savedPassword)
    }
    if (lastSid) storage.set('last_login_sid', lastSid)
    storage.set('manual_logout', true)
  }
  return request('POST', '/api/logout').then(finish).catch(finish)
}

// ============================================================
// 课表接口
// ============================================================

/** 获取缓存的课表 */

/** 智慧理工一步登录（SSO 直连教务，免教务密码/验证码） */

function loginWebvpn(studentId, password) {
  return request('POST', '/api/login-webvpn', {
    student_id: studentId,
    password: password,
    // 兼容旧后端字段; 新后端固定默认保存密码。
    remember: true
  }).then(res => {
    if (res.success) {
      storage.clearAll()   // 换号登录：清空上一用户的全部本地数据
      storage.remove('analytics_queue')
      storage.setStudentId(studentId)
      storage.setStudentName(res.student_name || '')
      storage.setSemester(res.semester || '')
      storage.set(TOKEN_KEY, res.token || '')
      if (res.credential_delete_token) {
        storage.set('credential_delete_token', res.credential_delete_token)
      }
      storage.set('saved_password', password)
    }
    return res
  })
}

/** 删除服务端加密保存的密码 */
function deleteCredential() {
  const deleteToken = storage.get('credential_delete_token', '')
  const headers = deleteToken ? { 'X-Credential-Delete-Token': deleteToken } : {}
  return request('DELETE', '/api/credentials', {}, { headers })
}

// ============================================================
// 设置与校历接口
// ============================================================

/** 保存设置（first_week_date 等） */

module.exports = {
  logout, loginWebvpn, deleteCredential,
  startSsoQr, ssoQrStatus, ssoQrImageUrl, cancelSsoQr
}
