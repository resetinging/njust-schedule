/**
 * 设置/登录视图组件 — 由原 pages/settings 页面改造（方案A 合页 swiper）
 * 生命周期: attached 首次挂载(读缓存); activate 由 main 页面每次激活时调用(onShow 语义)
 * 无下拉刷新: 不使用 scroll-view refresher
 */

const api = require('../../utils/api')
const storage = require('../../utils/storage')
const config = require('../../utils/config')
const dataLoader = require('../../utils/data-loader')
const { getDefaultFirstWeekDate } = require('../../utils/date')

Component({
  options: {
    styleIsolation: 'apply-shared'
  },

  data: {
    isLoggedIn: false,
    studentId: '',
    studentName: '',
    semester: '',
    gradeCount: 0,

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
    rememberPwd: true,     // 记住学号与密码（保存在本机）
    showPassword: false,   // 密码明文显示开关
    showJwcPassword: false,// 教务密码明文显示开关

    // 校历设置
    firstWeekDate: '',

    // 版本标识（排查线上版本用）
    build: config.BUILD || '',

    active: false        // 懒渲染: main 激活时才渲染内容
  },

  lifetimes: {
    attached() {
      this.refreshState()
      // 回读记住密码开关状态
      const rp = storage.get('remember_pwd', '1') !== '0'
      if (rp !== this.data.rememberPwd) this.setData({ rememberPwd: rp })
      this.loadSettings()
    }
  },

  methods: {
    /** 由 main 页面调用: 每次被激活时触发 */
    activate() {
      this.setData({ active: true })   // 懒渲染: 首次激活才渲染内容
      this.refreshState()
      // 回填记住的学号与密码（登录走自动 OCR，无需预取验证码）
      if (!this.data.isLoggedIn) {
        const updates = {}
        if (storage.getStudentId()) updates.studentId = storage.getStudentId()
        const savedPwd = storage.get('saved_password', '')
        if (savedPwd) updates.password = savedPwd
        if (Object.keys(updates).length) {
          this.setData(updates)
          this._updateCanLogin()
        }
      }
    },

    /** 刷新页面状态 */
    refreshState() {
      const loggedIn = storage.isLoggedIn()
      // 成绩数量(本地缓存, 供"信息行"展示)
      const gradesRes = storage.getCached('cached_grades')
      const gradeCount = gradesRes && gradesRes.grades ? gradesRes.grades.length : 0
      this.setData({
        isLoggedIn: loggedIn,
        studentId: storage.getStudentId(),
        studentName: storage.getStudentName(),
        semester: storage.getSemester(),
        gradeCount
      })
    },

    /** 加载设置（第一周日期来自 /api/status；未设置时显示默认值） */
    async loadSettings() {
      try {
        const res = await api.getStatus()
        if (res && res.first_week_date !== undefined) {
          this.setData({ firstWeekDate: res.first_week_date || getDefaultFirstWeekDate() })
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

    /** 切换密码明文显示 */
    onTogglePassword() {
      this.setData({ showPassword: !this.data.showPassword })
    },

    /** 切换教务密码明文显示 */
    onToggleJwcPassword() {
      this.setData({ showJwcPassword: !this.data.showJwcPassword })
    },

    onCaptchaInput(e) {
      this.setData({ captcha: e.detail.value })
      this._updateCanLogin()
    },

    /** 计算登录按钮是否可用（学号+密码即可；验证码可选，自动识别时无需输入） */
    _updateCanLogin() {
      const { studentId, password } = this.data
      this.setData({ canLogin: !!(studentId && password) })
    },

    /** 记住密码开关(状态持久化) */
    onToggleRemember(e) {
      const val = !!e.detail.value
      this.setData({ rememberPwd: val })
      storage.set('remember_pwd', val ? '1' : '0')
      if (!val) {
        storage.remove('saved_password')
      }
    },

    /** 点击文字切换记住密码 */
    onTapRemember() {
      const next = !this.data.rememberPwd
      this.setData({ rememberPwd: next })
      storage.set('remember_pwd', next ? '1' : '0')
      if (!next) {
        storage.remove('saved_password')
      }
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

    /** 登录（无验证码时走服务端自动 OCR，失败自动切换手动验证码） */
    async onLogin() {
      const { loginMode, studentId, password, jwcPassword, captcha, rememberPwd } = this.data
      if (!studentId || !password) {
        wx.showToast({ title: '请填写学号和密码', icon: 'none' })
        return
      }

      let res
      this.setData({ loggingIn: true })
      try {
        if (loginMode === 'webvpn') {
          // 智慧理工：SSO 已完成且有验证码 → 手动两步；否则全自动（含教务 OCR）
          if (captcha && this.data.ssoStepDone) {
            wx.showLoading({ title: '登录中…' })
            res = await api.loginWebvpnManual(studentId, password, jwcPassword, captcha, this.data.captchaId)
          } else if (!this.data.ssoStepDone) {
            wx.showLoading({ title: '智慧理工自动登录中…' })
            res = await api.loginWebvpn(studentId, password, jwcPassword)
          } else {
            wx.showToast({ title: '请先输入验证码', icon: 'none' })
            this.setData({ loggingIn: false })
            return
          }
        } else {
          // 教务直连：有验证码 → 手动；无验证码 → 服务端自动 OCR
          if (captcha) {
            wx.showLoading({ title: '登录中…' })
            res = await api.login(studentId, password, captcha, this.data.captchaId)
          } else {
            wx.showLoading({ title: '自动识别验证码登录中…' })
            res = await api.loginAuto(studentId, password)
          }
        }
        wx.hideLoading()
        this.setData({ loggingIn: false })

        if (res.success) {
          // 记住密码（保存在本机；退出登录时自动清除）
          if (rememberPwd) {
            storage.set('saved_password', password)
          } else {
            storage.remove('saved_password')
          }
          storage.setStudentId(studentId)
          storage.setStudentName(res.student_name || '')
          storage.setSemester(res.semester || '')
          wx.showToast({ title: '登录成功，正在同步数据…', icon: 'success' })
          this.refreshState()
          // 通知全局
          getApp().setLoginState(true, res.student_name || studentId, res.semester || '')
          this.setData({
            password: '', jwcPassword: '', captcha: '', captchaId: '', captchaSrc: '', ssoStepDone: false
          })
          this.loadSettings()
          // 自动向后端获取全部数据并载入缓存(课表/考试/评教/成绩/CET/校历)
          dataLoader.fetchAllData().then((ok) => {
            if (ok > 0) {
              wx.showToast({ title: '数据已更新', icon: 'success' })
            }
          })
        } else {
          wx.showToast({ title: res.message || '登录失败', icon: 'none' })
          // 自动识别失败 → 显示验证码图片，切换为手动输入
          this.setData({ captcha: '', captchaId: '', ssoStepDone: false })
          this._updateCanLogin()
          this.onRefreshCaptcha()
        }
      } catch (e) {
        wx.hideLoading()
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
        if (res.success) {
          // 使课表页本地校历缓存立即失效, 切回即可看到新周次
          const sid = storage.getStudentId() || 'guest'
          const sem = storage.getSemester() || 'default'
          storage.remove('cached_status_' + sid + '_' + sem)
        }
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

    /** 跳成绩页（合页方案: 通知 main 切 swiper 到成绩 Tab） */
    onGoGrades() {
      const pages = getCurrentPages()
      const page = pages[pages.length - 1]
      // 当前页面可能是 main(合页) 或本组件所在页; main 提供 onTabTap 切换 swiper
      if (page && typeof page.onTabTap === 'function') {
        page.onTabTap(3)
      } else {
        wx.switchTab({ url: '/pages/grades/grades' })
      }
    },

    /** 打开校历照片墙 */
    onGoGallery() {
      wx.navigateTo({ url: '/pages/gallery/gallery' })
    },

    /** 打开留言板(合页方案: 通知 main 切 swiper 到留言板 Tab) */
    onGoBoard() {
      const pages = getCurrentPages()
      const page = pages[pages.length - 1]
      if (page && typeof page.onTabTap === 'function') {
        page.onTabTap(4)
      } else {
        wx.navigateTo({ url: '/pages/board/board' })
      }
    },

    /** 一键刷新课表+考试(走 dataLoader: 刷新教务后查询写新缓存, 各 Tab 自动生效) */
    async onRefreshAll() {
      wx.showLoading({ title: '刷新中…' })
      try {
        const ok = await dataLoader.fetchAllData()
        wx.hideLoading()
        wx.showToast({ title: ok > 0 ? '数据已更新' : '刷新失败', icon: ok > 0 ? 'success' : 'none' })
      } catch (e) {
        wx.hideLoading()
        wx.showToast({ title: '刷新失败', icon: 'none' })
      }
    },

    /** 清除缓存 */
    onClearData() {
      wx.showModal({
        title: '确认清除',
        content: '将清除本地全部缓存数据（课表/考试/评教/成绩等），重新登录后自动恢复',
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
        // 清理全部本地缓存键(含学期后缀键)
        try {
          const info = wx.getStorageInfoSync()
          info.keys.forEach(k => {
            if (k === 'cached_evaluations' || k === 'cached_grades' ||
                k === 'cached_cet_scores' || k === 'semester_list' ||
                k === 'cached_gallery_meta' ||
                String(k).indexOf('cached_courses_') === 0 ||
                String(k).indexOf('cached_exams_') === 0 ||
                String(k).indexOf('cached_status_') === 0) {
              storage.remove(k)
            }
          })
        } catch (e) {
          // 忽略
        }
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
        success: async (res) => {
          if (res.confirm) {
            await getApp().doLogout()   // 等待后端登出 + 本地清理完成, 避免状态未清导致要点两次
            this.refreshState()
            this.setData({
              password: '',
              jwcPassword: '',
              captcha: '',
              captchaId: '',
              captchaSrc: '',
              ssoStepDone: false
            })
          }
        }
      })
    }
  }
})
