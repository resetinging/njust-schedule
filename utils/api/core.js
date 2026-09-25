/**
 * API ???: ?????? + 401 ????
 */
/**
 * API 封装 — 所有后端接口调用
 * 统一错误处理
 */

const config = require('../config')
const storage = require('../storage')

// 登录 token 存储键（多用户：请求携带 X-Auth-Token 标识会话）
const TOKEN_KEY = 'token'

// ============================================================
// 底层请求封装
// ============================================================

/**
 * 发起 HTTP 请求（通过云托管内网，免域名白名单）
 * 401 自动重登: 非登录接口收到 401 时, 若本地记住了学号密码,
 * 自动重登一次并重试原请求; 重登失败才清理登录态并提示。
 * @param {string} method - GET | POST
 * @param {string} path - API 路径 (如 '/api/get-captcha')
 * @param {object} data - 请求参数
 * @param {object} opts - 可选 { timeout: 毫秒 }
 * @returns {Promise<object>} { success, data, message }
 */
function request(method, path, data = {}, opts) {
  const timeout = (opts && opts.timeout) || config.REQUEST_TIMEOUT
  // 登录/验证码/登出接口不触发 401 自动重登(登出 401 时重登会白跑一轮 OCR)
  const isLoginPath = /\/api\/(login|logout|get-webvpn-captcha|get-captcha)/.test(path)
  let attempt = 0   // 401 自动重登只尝试一次, 避免循环

  // 离线模式: 会话失效后保留本地缓存只读展示, 不再打网络(登录类接口除外)
  if (!isLoginPath && storage.isOffline()) {
    return Promise.resolve({
      success: false, offline: true, message: '离线模式：显示本地缓存'
    })
  }

  const handleFail = (statusCode, payload) => {
    // 会话失效且非登录接口: 尝试自动重登(记住密码), 成功则重试
    if (statusCode === 401 && !isLoginPath && attempt === 0) {
      attempt = 1
      return autoRelogin().then((newToken) => {
        if (newToken) return send(newToken)
        clearSessionAndToast()
        return {
          success: false,
          message: (payload && payload.message) || '登录已过期，请重新登录'
        }
      })
    }
    if (statusCode === 401 && !isLoginPath) clearSessionAndToast()
    return {
      success: false,
      message: (payload && payload.message) || ('服务器错误 ' + statusCode)
    }
  }

  const send = (token) => {
    const header = { 'Content-Type': 'application/json' }
    if (token) header['X-Auth-Token'] = token

    // 本地联调: 直连本机 Flask(需开发者工具勾选「不校验合法域名」)
    if (config.USE_LOCAL) {
      return new Promise((resolve) => {
        wx.request({
          url: config.LOCAL_BASE + path,
          method,
          header,
          data,
          timeout,
          success(res) {
            if (res.statusCode === 200) resolve(res.data)
            else resolve(handleFail(res.statusCode, res.data))
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
        timeout,
        success(res) {
          if (res.statusCode === 200) resolve(res.data)
          else resolve(handleFail(res.statusCode, res.data))
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

  return send(storage.get(TOKEN_KEY, ''))
}

// 会话失效时自动重登（记住密码的防并发重入）
let _autoReloginPromise = null

/**
 * 用记住的学号和密码自动重新登录（服务端 OCR 识别验证码, 无需用户操作）
 * @returns {Promise<string|null>} 新 token 或 null(失败/未记住密码)
 */

function autoRelogin() {
  const sid = storage.getStudentId()
  const pwd = storage.get('saved_password', '')
  if (!sid || !pwd) return Promise.resolve(null)
  if (_autoReloginPromise) return _autoReloginPromise
  _autoReloginPromise = request('POST', '/api/login', {
    student_id: sid,
    password: pwd
  }).then((res) => {
    _autoReloginPromise = null
    if (res && res.success && res.token) {
      // 关键: 新 token 必须持久化, 否则后续请求仍携带旧 token → 401 循环
      storage.set(TOKEN_KEY, res.token)
      if (res.semester) storage.setSemester(res.semester)
      return res.token
    }
    return null
  }).catch(() => {
    _autoReloginPromise = null
    return null
  })
  return _autoReloginPromise
}

/** 清理本地登录态并提示（自动重登失败后的兜底） */

function clearSessionAndToast() {
  if (storage.get(TOKEN_KEY, '')) {
    // 只失效登录凭证, 保留本地缓存数据 → 切离线模式继续展示已保存数据
    storage.remove(TOKEN_KEY)
    storage.remove('saved_password')
    storage.setOffline(true)
    wx.showToast({
      title: '登录已过期，已切换离线模式(显示本地缓存)',
      icon: 'none', duration: 2500
    })
  }
}

// ============================================================
// 认证接口
// ============================================================

/** 获取验证码图片 (base64) */

module.exports = { TOKEN_KEY, request, autoRelogin, clearSessionAndToast }
