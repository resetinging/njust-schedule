/**
 * 设置/登录页面
 */

const api = require('../../utils/api')
const storage = require('../../utils/storage')

Page({
  data: {
    isLoggedIn: false,
    studentId: '',
    studentName: '',
    semester: '',

    // 登录表单
    password: '',
    captcha: '',
    captchaSrc: '',
    loggingIn: false,
    canLogin: false
  },

  onLoad() {
    this.refreshState()
  },

  onShow() {
    this.refreshState()
    // 如果已登录且有密码，自动获取验证码
    if (this.data.isLoggedIn === false && storage.getStudentId()) {
      this.setData({ studentId: storage.getStudentId() })
      this.onRefreshCaptcha()
    }
  },

  /** 刷新页面状态 */
  refreshState() {
    const loggedIn = storage.isLoggedIn()
    this.setData({
      isLoggedIn: loggedIn,
      studentId: storage.getStudentId(),
      studentName: storage.getStudentName(),
      semester: storage.getSemester()
    })
  },

  // ============================================================
  // 登录
  // ============================================================

  onStudentIdInput(e) {
    this.setData({ studentId: e.detail.value })
    this._updateCanLogin()
  },

  onPasswordInput(e) {
    this.setData({ password: e.detail.value })
    this._updateCanLogin()
  },

  onCaptchaInput(e) {
    this.setData({ captcha: e.detail.value })
    this._updateCanLogin()
  },

  /** 计算登录按钮是否可用 */
  _updateCanLogin() {
    const { studentId, password, captcha } = this.data
    this.setData({ canLogin: !!(studentId && password && captcha) })
  },

  /** 获取验证码 */
  async onRefreshCaptcha() {
    try {
      const res = await api.getCaptcha()
      if (res.success && res.captcha_b64) {
        this.setData({
          captchaSrc: 'data:image/jpeg;base64,' + res.captcha_b64
        })
      } else {
        wx.showToast({ title: res.message || '获取验证码失败', icon: 'none' })
      }
    } catch (e) {
      wx.showToast({ title: '获取验证码失败', icon: 'none' })
    }
  },

  /** 登录 */
  async onLogin() {
    const { studentId, password, captcha } = this.data
    if (!studentId || !password || !captcha) {
      wx.showToast({ title: '请填写所有字段', icon: 'none' })
      return
    }

    this.setData({ loggingIn: true })
    try {
      const res = await api.login(studentId, password, captcha)
      this.setData({ loggingIn: false })

      if (res.success) {
        wx.showToast({ title: '登录成功', icon: 'success' })
        this.refreshState()
        // 通知全局
        getApp().setLoginState(true, res.student_name || studentId, res.semester || '')
      } else {
        wx.showToast({ title: res.message || '登录失败', icon: 'none' })
        // 刷新验证码
        this.onRefreshCaptcha()
        this.setData({ captcha: '' })
        this._updateCanLogin()
      }
    } catch (e) {
      this.setData({ loggingIn: false })
      wx.showToast({ title: '登录失败', icon: 'none' })
    }
  },

  // ============================================================
  // 已登录操作
  // ============================================================

  /** 一键刷新 */
  async onRefreshAll() {
    wx.showLoading({ title: '刷新中…' })
    try {
      const res = await api.refreshAll()
      wx.hideLoading()
      if (res.success) {
        const parts = []
        if (res.schedule?.ok) parts.push(`课表 ${res.schedule.count} 门`)
        if (res.exams?.ok) parts.push(`考试 ${res.exams.count} 场`)
        wx.showToast({ title: parts.join('，') || '已刷新', icon: 'success' })
      } else {
        wx.showToast({ title: res.message || '刷新失败', icon: 'none' })
      }
    } catch (e) {
      wx.hideLoading()
    }
  },

  /** 清除缓存 */
  onClearData() {
    wx.showModal({
      title: '确认清除',
      content: '将清除本地缓存的课表和考试数据',
      success: (modalRes) => {
        if (modalRes.confirm) {
          this._doClearData()
        }
      }
    })
  },

  /** 执行清除缓存 */
  async _doClearData() {
    try {
      await api.clearData()
      storage.remove('cached_courses')
      storage.remove('cached_exams')
      wx.showToast({ title: '已清除', icon: 'success' })
    } catch (e) {
      wx.showToast({ title: '清除失败', icon: 'none' })
    }
  },

  /** 退出登录 */
  onLogout() {
    wx.showModal({
      title: '确认退出',
      content: '退出后需要重新登录才能查看数据',
      success: (res) => {
        if (res.confirm) {
          getApp().doLogout()
          this.refreshState()
          this.setData({
            password: '',
            captcha: '',
            captchaSrc: ''
          })
        }
      }
    })
  }
})
