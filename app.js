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

    // 启动时检查本地是否保存过学号（登录态以学号为准，后端接口无 token 校验）
    if (storage.getStudentId()) {
      this.globalData.isLoggedIn = true
      this.globalData.studentName = storage.getStudentName()
      this.globalData.semester = storage.getSemester()
    }
  },

  /** 更新全局登录状态 */
  setLoginState(loggedIn, studentName, semester) {
    this.globalData.isLoggedIn = loggedIn
    this.globalData.studentName = studentName || ''
    this.globalData.semester = semester || ''
  },

  /** 退出登录 */
  doLogout() {
    api.logout()
    this.globalData.isLoggedIn = false
    this.globalData.studentName = ''
  }
})
