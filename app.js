/**
 * 课表助手 — 小程序入口
 */

const api = require('./utils/api')
const storage = require('./utils/storage')
const config = require('./utils/config')

App({
  globalData: {
    isLoggedIn: false,
    studentName: '',
    semester: ''
  },

  onLaunch() {
    // 初始化微信云开发（用于云托管免域名调用）
    if (wx.cloud) {
      wx.cloud.init({
        env: config.CLOUD_ENV,
        traceUser: false
      })
    }

    // 启动时检查本地是否保存过学号（登录态以学号为准）
    if (storage.getStudentId()) {
      this.globalData.isLoggedIn = true
      this.globalData.studentName = storage.getStudentName()
      this.globalData.semester = storage.getSemester()
      // 静默校验后端会话: 容器重启/会话过期后立即提示, 而不是等用户刷新数据才报错
      this._checkSession()
    }
  },

  /** 静默校验后端会话: 失效时先尝试自动重登(记住密码), 失败才提示 */
  _checkSession() {
    api.getStatus().then((res) => {
      if (res && res.logged_in) return
      if (res && !res.logged_in) {
        api.autoRelogin().then((newToken) => {
          if (newToken) {
            // 自动恢复登录成功
            this.globalData.isLoggedIn = true
            this.globalData.studentName = storage.getStudentName()
            this.globalData.semester = storage.getSemester()
          } else {
            storage.clearAll()
            this.globalData.isLoggedIn = false
            this.globalData.studentName = ''
            this.globalData.semester = ''
            wx.showModal({
              title: '登录已过期',
              content: '后端会话已失效且自动重登失败，请手动登录',
              showCancel: false,
              confirmText: '去登录'
            })
          }
        })
      }
    }).catch(() => {
      // 网络失败不打扰用户, 由后续请求的 401 自动重登兜底
    })
  },

  /** 更新全局登录状态 */
  setLoginState(loggedIn, studentName, semester) {
    this.globalData.isLoggedIn = loggedIn
    this.globalData.studentName = studentName || ''
    this.globalData.semester = semester || ''
  },

  /** 退出登录（等待后端登出 + 本地清理完成） */
  async doLogout() {
    await api.logout()
    this.globalData.isLoggedIn = false
    this.globalData.studentName = ''
    this.globalData.semester = ''
  }
})
