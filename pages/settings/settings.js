/**
 * 设置/登录页面
 * 登录模式: direct(教务直连) | webvpn(智慧理工 SSO 两步)
 */

const api = require('../../utils/api')
const storage = require('../../utils/storage')

Page({
  data: {
    isLoggedIn: false,
    studentId: '',
    studentName: '',
    semester: '',

    // 登录模式
    loginMode: 'direct',   // 'direct' | 'webvpn'

    // 登录表单
    password: '',
    jwcPassword: '',       // 智慧理工模式下可选的教务密码
    captcha: '',
    captchaId: '',         // 当前验证码会话 ID（多用户：登录时回传绑定）
    captchaSrc: '',
    loggingIn: false,
    canLogin: false,
    ssoStepDone: false,    // 智慧理工模式: SSO 已通过, 显示教务验证码

    // 校历设置
    firstWeekDate: ''
  },

  onLoad() {
    this.refreshState()
    this.loadSettings()
  },

  onShow() {
    this.refreshState()
    // 如果已保存学号但未登录，自动获取验证码
    if (!this.data.isLoggedIn && storage.getStudentId()) {
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

  /** 加载设置（第一周日期来自 /api/status） */
  async loadSettings() {
    try {
      const res = await api.getStatus()
      if (res && res.first_week_date !== undefined) {
        this.setData({ firstWeekDate: res.first_week_date || '' })
      }
    } catch (e) {
      // 忽略
    }
  },

  // ============================================================
  // 登录模式切换
  // ============================================================

  switchLoginMode(e) {
    const mode = e.currentTarget.dataset.mode
    if (mode === this.data.loginMode) return
    this.setData({
      loginMode: mode,
      captcha: '',
      captchaSrc: '',
      ssoStepDone: false,
      jwcPassword: ''
    })
    this._updateCanLogin()
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

  onJwcPasswordInput(e) {
    this.setData({ jwcPassword: e.detail.value })
    this._updateCanLogin()
  },

  onCaptchaInput(e) {
    this.setData({ captcha: e.detail.value })
    this._updateCanLogin()
  },

  /** 计算登录按钮是否可用（手动验证码流程） */
  _updateCanLogin() {
    const { studentId, password, captcha } = this.data
    this.setData({ canLogin: !!(studentId && password && captcha) })
  },

  /** 获取验证码（按登录模式选择端点） */
  async onRefreshCaptcha() {
    const { loginMode, studentId, password } = this.data

    if (loginMode === 'webvpn') {
      if (!studentId || !password) {
        wx.showToast({ title: '请先输入学号和智慧理工密码', icon: 'none' })
        return
      }
      wx.showLoading({ title: '智慧理工登录中…' })
      try {
        const res = await api.getWebvpnCaptcha(studentId, password)
        wx.hideLoading()
        if (res.success && res.captcha_b64) {
          this.setData({
            captchaId: res.captcha_id || '',
            captchaSrc: 'data:' + (res.captcha_mime || 'image/png') + ';base64,' + res.captcha_b64,
            captcha: '',
            ssoStepDone: true
          })
          wx.showToast({ title: '✅ 智慧理工已通过，请输入教务密码和验证码', icon: 'none' })
        } else if (res.success && res.already_logged_in) {
          this.setData({ captchaId: '' })
          this.refreshState()
          wx.showToast({ title: '✅ 已有教务会话，无需重复登录', icon: 'success' })
        } else {
          this.setData({ captchaId: '' })
          wx.showToast({ title: res.message || '智慧理工登录失败', icon: 'none' })
        }
      } catch (e) {
        wx.hideLoading()
        wx.showToast({ title: '获取验证码失败', icon: 'none' })
      }
      return
    }

    // 教务直连模式
    try {
      const res = await api.getCaptcha()
      if (res.success && res.captcha_b64) {
        this.setData({
          captchaId: res.captcha_id || '',
          captchaSrc: 'data:' + (res.captcha_mime || 'image/png') + ';base64,' + res.captcha_b64,
          captcha: ''
        })
        this._updateCanLogin()
      } else {
        this.setData({ captchaId: '' })
        wx.showToast({ title: res.message || '获取验证码失败', icon: 'none' })
      }
    } catch (e) {
      wx.showToast({ title: '获取验证码失败', icon: 'none' })
    }
  },

  /** 登录 */
  async onLogin() {
    const { loginMode, studentId, password, jwcPassword, captcha } = this.data
    if (!studentId || !password) {
      wx.showToast({ title: '请填写学号和密码', icon: 'none' })
      return
    }
    if (!captcha) {
      wx.showToast({ title: '请先获取并输入验证码', icon: 'none' })
      return
    }
    if (loginMode === 'webvpn' && !this.data.ssoStepDone) {
      wx.showToast({ title: '请先完成智慧理工登录（点击验证码刷新）', icon: 'none' })
      return
    }

    this.setData({ loggingIn: true })
    try {
      const res = loginMode === 'webvpn'
        ? await api.loginWebvpnManual(studentId, password, jwcPassword, captcha, this.data.captchaId)
        : await api.login(studentId, password, captcha, this.data.captchaId)
      this.setData({ loggingIn: false })

      if (res.success) {
        storage.setStudentId(studentId)
        storage.setStudentName(res.student_name || '')
        storage.setSemester(res.semester || '')
        wx.showToast({ title: '登录成功，下拉刷新获取数据', icon: 'success' })
        this.refreshState()
        // 通知全局
        getApp().setLoginState(true, res.student_name || studentId, res.semester || '')
        this.setData({
          password: '', jwcPassword: '', captcha: '', captchaId: '', captchaSrc: '', ssoStepDone: false
        })
        this.loadSettings()
      } else {
        wx.showToast({ title: res.message || '登录失败', icon: 'none' })
        // 刷新验证码重试
        this.setData({ captcha: '', captchaId: '' })
        this._updateCanLogin()
        this.onRefreshCaptcha()
      }
    } catch (e) {
      this.setData({ loggingIn: false })
      wx.showToast({ title: '登录失败', icon: 'none' })
    }
  },

  // ============================================================
  // 校历设置
  // ============================================================

  onFirstWeekDateChange(e) {
    const date = e.detail.value
    this.setData({ firstWeekDate: date })
    api.saveSettings({ first_week_date: date }).then(res => {
      wx.showToast({
        title: res.success ? '✅ 已保存，课表将自动跳转本周' : (res.message || '保存失败'),
        icon: 'none'
      })
    }).catch(() => {
      wx.showToast({ title: '保存失败', icon: 'none' })
    })
  },

  // ============================================================
  // 已登录操作
  // ============================================================

  /** 跳转成绩页（TabBar 页面需要用 switchTab） */
  onGoGrades() {
    wx.switchTab({ url: '/pages/grades/grades' })
  },

  /** 打开校历照片墙 */
  onGoGallery() {
    wx.navigateTo({ url: '/pages/gallery/gallery' })
  },

  /** 一键刷新 */
  async onRefreshAll() {
    wx.showLoading({ title: '刷新中…' })
    try {
      const res = await api.refreshAll()
      wx.hideLoading()
      if (res.success) {
        const parts = []
        if (res.schedule && res.schedule.ok) parts.push(`课表 ${res.schedule.count} 门`)
        if (res.exams && res.exams.ok) parts.push(`考试 ${res.exams.count} 场`)
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
            jwcPassword: '',
            captcha: '',
            captchaSrc: '',
            ssoStepDone: false
          })
        }
      }
    })
  }
})
