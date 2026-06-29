/**
 * 南理工课表 — 小程序入口
 */

const api = require('./utils/api')
const storage = require('./utils/storage')

App({
  globalData: {
    isLoggedIn: false,
    studentName: '',
    semester: ''
  },

  onLaunch() {
    // 启动时检查是否有已保存的 token
    const token = storage.getToken()
    if (token) {
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
