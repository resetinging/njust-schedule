/**
 * 设置/登录视图组件 — 由原 pages/settings 页面改造（方案A 合页 swiper）
 * 生命周期: attached 首次挂载(读缓存); activate 由 main 页面每次激活时调用(onShow 语义)
 * 无下拉刷新: 不使用 scroll-view refresher
 */

const api = require('../../utils/api')
const storage = require('../../utils/storage')
const subUtil = require('../../utils/subscribe')
const config = require('../../utils/config')
const dataLoader = require('../../utils/data-loader')
const ann = require('../../utils/announcement')
const font = require('../../utils/font')
const analytics = require('../../utils/analytics')
const gpaUtil = require('../../utils/gpa')
const creditUtil = require('../../utils/credit')
const { getDefaultFirstWeekDate } = require('../../utils/date')
// 常用链接数据源(容错加载: 模块异常时降级为空列表,
// 避免 require 失败导致整个组件定义抛错、页面全白)
let linksData = { LINK_GROUPS: [], totalCount: () => 0 }
try {
  linksData = require('../../utils/links') || linksData
} catch (e) {
  console.error('[常用链接] 数据模块加载失败:', e)
}
const LINK_GROUPS = linksData.LINK_GROUPS || []
const LINK_TOTAL = typeof linksData.totalCount === 'function' ? linksData.totalCount() : 0

// 反馈类型中文名(与后端 suggest/bug/other 对应)
const FB_TYPES = { suggest: '功能建议', bug: '问题/Bug', other: '其他' }

Component({
  options: {
    styleIsolation: 'apply-shared'
  },

  data: {
    isLoggedIn: false,
    fontMode: 'pixel',      // 字体档位: pixel | system
    fontSwitching: false,
    studentId: '',
    studentName: '',
    semester: '',
    gradeCount: 0,
    gpa: '--',
    creditProgress: '--',

    // 登录模式

    // 登录表单
    password: '',
    loggingIn: false,
    canLogin: false,
    // 微信扫码登录
    qrMode: false,
    qrSrc: '',
    qrFallback: '',
    qrId: '',
    qrHint: '',
    showPassword: false,   // 密码明文显示开关

    // 校历设置
    firstWeekDate: '',
    calendarSyncing: false,

    // 消息提醒(订阅消息): 由后端返回可用类型与剩余额度
    subKinds: [],
    subEnabled: false,
    subSummary: '',
    subHasQuota: false,
    showSubscriptions: false,

    // 问题反馈弹窗(不另开页面)
    showFeedback: false,
    fbType: 'suggest',     // suggest 功能建议 | bug 问题/Bug | other 其他
    fbContent: '',
    fbSending: false,

    // 我的反馈(含管理员回复; 有新回复时入口显示小红点)
    showMyFeedback: false,
    myFeedback: [],
    fbLoading: false,
    fbUnread: 0,

    // 赞赏支持弹窗(展示赞赏码; 长按可保存/识别)
    showAppreciate: false,

    // 公告栏(常驻: 展示当前公告; 展开即视为已读, 主页面顶部横幅随之隐藏)
    announcement: '',
    annUpdated: '',        // 公告更新时间(已读标记)
    annExpanded: false,    // 长公告展开全文
    annLong: false,        // 超过折叠阈值(需要"查看全文"提示)
    annIsNew: false,       // 未读新公告(显示"新"标记, 展开查看后消失)

    // 常用链接弹窗
    showLinks: false,
    linkGroups: LINK_GROUPS,     // 分组链接(静态数据, 无搜索/过滤)
    linkTotal: LINK_TOTAL,

    // 版本标识（排查线上版本用）
    build: config.BUILD || '',

    // 连接测试/自动恢复会话
    testingConnection: false,
    connectionStatus: '',   // '' | ok | fail
    connectionText: '',

    active: false        // 懒渲染: main 激活时才渲染内容
  },

  lifetimes: {
  attached() {
      this.refreshState()
      this.loadSettings()
      this._loadAnnouncement()
    },
    detached() {
      this._stopQrPoll()      // 组件销毁时停止扫码轮询
      if (this._fontTimer) clearTimeout(this._fontTimer)
      if (this._fontDoneTimer) clearTimeout(this._fontDoneTimer)
      analytics.disconnectSlots(this)
    }
  },

  methods: {
    /** 切换字体档位(像素 / 系统) */
    onPickFont(e) {
      const mode = e.currentTarget.dataset.mode
      if (!mode || mode === this.data.fontMode) return
      if (this._fontTimer) clearTimeout(this._fontTimer)
      if (this._fontDoneTimer) clearTimeout(this._fontDoneTimer)
      this.setData({ fontSwitching: true })
      this._fontTimer = setTimeout(() => {
        font.setMode(mode)
        this.setData({ fontMode: font.getMode() })
        this._fontDoneTimer = setTimeout(() => {
          this.setData({ fontSwitching: false })
        }, 240)
      }, 70)
    },

    /** 由 main 页面调用: 每次被激活时触发 */
    activate() {
      this.setData({ active: true })   // 懒渲染: 首次激活才渲染内容
      this.refreshState()
      analytics.observeSlots(this, [
        { id: 'slot-profile-bottom', page: 'profile', ad_type: 'banner' }
      ])
      this.setData({ fontMode: font.getMode() })
      this.loadSubscribeStatus()
      // 回填记住的学号与密码（登录走自动 OCR，无需预取验证码）
      if (!this.data.isLoggedIn) {
        const updates = {}
        // 回填上次登录的学号(登出后会保留在 last_login_sid; 未登出时直接用当前学号)
        const lastSid = storage.getStudentId() || storage.get('last_login_sid', '')
        if (lastSid) updates.studentId = lastSid
        const savedPwd = storage.get('saved_password', '')
        if (savedPwd) updates.password = savedPwd
        if (Object.keys(updates).length) {
          this.setData(updates)
          this._updateCanLogin()
        }
      }
      this._loadAnnouncement()
      // 我的反馈未读回复(小红点)
      if (this.data.isLoggedIn) this._loadMyFeedback(false)
    },

    /** 拉取公告并展示(有无新公告都常驻显示; 30s 节流) */
    _loadAnnouncement() {
      ann.load().then(a => {
        const show = a.enabled && !!a.text
        if (!show) {
          if (this.data.announcement) this.setData({ announcement: '', annLong: false, annExpanded: false, annIsNew: false })
          return
        }
        this.setData({
          announcement: a.text,
          annUpdated: a.updated,
          annLong: a.text.length > 24,   // 超过 24 字默认折叠, 点击展开
          annExpanded: false,
          annIsNew: ann.isNew(a.updated)  // 未读 → 显示"新"标记
        })
      })
    },

    /** 点击公告栏: 展开/收起; 用户查看后标记已读, 并通知主页面隐藏顶部横幅 */
    onToggleAnnounce() {
      if (!this.data.announcement) return
      if (!this.data.annExpanded && this.data.annUpdated) {
        ann.markSeen(this.data.annUpdated)
        this.setData({ annIsNew: false })   // 已读: 移除"新"标记
        const pages = getCurrentPages()
        const page = pages[pages.length - 1]
        if (page && typeof page.onAnnSeen === 'function') page.onAnnSeen()
      }
      this.setData({ annExpanded: !this.data.annExpanded })
    },

    /** 刷新页面状态 */
    refreshState() {
      const loggedIn = storage.isLoggedIn()
      // 成绩数量(本地缓存, 供"信息行"展示)
      const gradesRes = storage.getCached('cached_grades')
      const grades = gradesRes && gradesRes.grades ? gradesRes.grades : []
      const cetRes = storage.getCached('cached_cet_scores')
      const cetScores = (cetRes && cetRes.success ? cetRes.scores : []) || []
      const gradeCount = grades.length
      const gpa = gradeCount
        ? Number(gpaUtil.calcScholarshipGpa(grades, cetScores)).toFixed(2)
        : '--'
      const programme = (storage.getCached('cached_programme') || {}).courses || []
      let creditProgress = '--'
      if (programme.length) {
        const credit = creditUtil.computeCredit(
          programme, grades, storage.getSemester())
        if (credit.totalRequired > 0) {
          creditProgress = `${credit.totalEarned}/${credit.totalRequired}`
        }
      }
      this.setData({
        isLoggedIn: loggedIn,
        studentId: storage.getStudentId(),
        studentName: storage.getStudentName(),
        semester: storage.getSemester(),
        gradeCount,
        gpa,
        creditProgress
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

    /** 切换密码明文显示 */
    onTogglePassword() {
      this.setData({ showPassword: !this.data.showPassword })
    },

    /** 计算登录按钮是否可用（学号 + 智慧理工密码即可） */
    _updateCanLogin() {
      const { studentId, password } = this.data
      this.setData({ canLogin: !!(studentId && password) })
    },

    // ============================================================
    // 微信扫码登录（免密码, 单设备：长按二维码 → 识别图中二维码 → 确认）
    // ============================================================

    /** 申请/刷新二维码 */
    async onStartQr() {
      this._stopQrPoll()
      wx.showLoading({ title: '获取二维码…' })
      try {
        const res = await api.startSsoQr()
        wx.hideLoading()
        if (!res || !res.success || !res.qr_b64) {
          wx.showToast({ title: (res && res.message) || '获取二维码失败', icon: 'none' })
          return
        }
        this.setData({
          qrMode: true,
          qrId: res.qr_id || '',
          // 真机必须用图片 URL: base64 图片长按不会弹出「识别图中二维码」
          qrSrc: api.ssoQrImageUrl(res.qr_id),
          qrFallback: res.qr_b64 ? ('data:image/png;base64,' + res.qr_b64) : '',
          qrHint: res.message || '长按二维码 → 识别图中二维码 → 确认登录'
        })
        this._startQrPoll()
      } catch (e) {
        wx.hideLoading()
        wx.showToast({ title: '获取二维码失败', icon: 'none' })
      }
    },

    /** 关闭扫码面板, 回密码登录 */
    async onCloseQr() {
      this._stopQrPoll()
      const qrId = this.data.qrId
      this.setData({ qrMode: false, qrSrc: '', qrId: '', qrHint: '', qrFallback: '' })
      if (qrId) {
        try { await api.cancelSsoQr(qrId) } catch (e) { /* 忽略 */ }
      }
    },

    _startQrPoll() {
      this._stopQrPoll()
      // 每 2 秒问一次后端; 二维码约 3 分钟有效, 失效后提示刷新
      this._qrTimer = setInterval(() => this._pollQr(), 2000)
    },

    _stopQrPoll() {
      if (this._qrTimer) {
        clearInterval(this._qrTimer)
        this._qrTimer = null
      }
    },

    async _pollQr() {
      const qrId = this.data.qrId
      if (!qrId) return
      const res = await api.ssoQrStatus(qrId)
      if (!res) return
      if (res.success && res.status === 'ok') {
        this._onQrSuccess(res)
        return
      }
      if (res.status === 'expired' || res.success === false) {
        // 后端对失效 qr_id 返回 400(带 status=expired)；失败也必须停止轮询
        this._stopQrPoll()
        this.setData({ qrHint: res.message || '二维码已失效，请点「刷新二维码」' })
      } else if (res.status === 'scanned') {
        this.setData({ qrHint: '已扫码，请在手机上点「确认登录」' })
      }
    },

    /** 用户点「我已确认」: 立即查一次, 不必等下一次轮询 */
    async onQrConfirmTap() {
      const qrId = this.data.qrId
      if (!qrId) return
      wx.showLoading({ title: '正在确认…' })
      let res = null
      try {
        res = await api.ssoQrStatus(qrId)
      } catch (e) {
        wx.hideLoading()
        wx.showToast({ title: '网络异常，请重试', icon: 'none' })
        return
      }
      wx.hideLoading()
      if (res && res.success && res.status === 'ok') {
        this._onQrSuccess(res)
        return
      }
      if (res && (res.status === 'expired' || res.success === false)) {
        this._stopQrPoll()
        this.setData({ qrHint: '二维码已失效，请点「刷新二维码」' })
        wx.showToast({ title: '二维码已失效', icon: 'none' })
        return
      }
      if (res && res.status === 'scanned') {
        this.setData({ qrHint: '已扫码，请在手机上点「确认登录」' })
        wx.showToast({ title: '还没确认，请在手机上点确认', icon: 'none' })
        return
      }
      wx.showToast({ title: '还没检测到确认，请稍后再试', icon: 'none' })
    },

    /** 扫码登录成功: 统一处理(轮询命中与手动确认共用) */
    _onQrSuccess(res) {
      this._stopQrPoll()
      this.setData({ qrMode: false, qrSrc: '', qrId: '', qrHint: '', qrFallback: '' })
      wx.showToast({ title: '登录成功，正在同步数据…', icon: 'success' })
      this.refreshState()
      getApp().setLoginState(true, res.student_name || res.student_id || '',
                              res.semester || '')
      this.loadSettings()
      this._loadMyFeedback(false)
      dataLoader.fetchAllData().then((ok) => {
        if (ok > 0) wx.showToast({ title: '数据已更新', icon: 'success' })
      })
    },

    /** 图片 URL 加载失败时回退 base64（本地联调或域名未配置时兜底） */
    onQrImgError() {
      if (this.data.qrFallback && this.data.qrSrc !== this.data.qrFallback) {
        this.setData({ qrSrc: this.data.qrFallback })
      }
    },

    /**
     * 保存二维码到相册。
     *
     * 小程序内只能识别「小程序码」(太阳码), 普通二维码长按只有翻译/保存
     * (社区实测结论), 因此普通二维码只能走「保存到相册 → 微信扫一扫 → 相册」。
     */
    onQrSave() {
      const url = this.data.qrSrc
      if (!url) return
      const save = (path) => {
        wx.saveImageToPhotosAlbum({
          filePath: path,
          success: () => {
            wx.hideLoading()
            wx.showModal({
              title: '已保存到相册',
              content: '打开微信「扫一扫」→ 右下角相册 → 选择刚保存的二维码 → 点「确认登录」，回到小程序即自动完成登录。',
              showCancel: false,
              confirmText: '我知道了'
            })
          },
          fail: (err) => {
            wx.hideLoading()
            const msg = (err && err.errMsg) || ''
            if (msg.indexOf('auth') >= 0 || msg.indexOf('deny') >= 0) {
              wx.showModal({
                title: '需要相册权限',
                content: '请在设置里允许「保存到相册」，再回来点一次。',
                confirmText: '去设置',
                success: (r) => { if (r.confirm) wx.openSetting() }
              })
            } else {
              wx.showToast({ title: '保存失败，请重试', icon: 'none' })
            }
          }
        })
      }

      wx.showLoading({ title: '正在保存…' })
      if (url.indexOf('data:') === 0) {
        const b64 = url.split(',')[1] || ''
        const path = `${wx.env.USER_DATA_PATH}/sso-qr-save.png`
        wx.getFileSystemManager().writeFile({
          filePath: path, data: b64, encoding: 'base64',
          success: () => save(path),
          fail: () => {
            wx.hideLoading()
            wx.showToast({ title: '保存失败，请重试', icon: 'none' })
          }
        })
        return
      }
      wx.downloadFile({
        url,
        timeout: 20000,
        success: (res) => {
          if (res.statusCode === 200 && res.tempFilePath) save(res.tempFilePath)
          else { wx.hideLoading(); wx.showToast({ title: '保存失败，请重试', icon: 'none' }) }
        },
        fail: () => {
          wx.hideLoading()
          wx.showToast({ title: '保存失败，请重试', icon: 'none' })
        }
      })
    },

    /**
     * 点二维码 → 放大预览(WX 原生预览器) → 在预览页长按识别。
     *
     * image 组件的 show-menu-by-longpress 在真机上对第三方链接二维码经常不生效
     * (社区实测: 开发者工具可以、真机不行), 而「预览态长按识别」是微信原生预览器
     * 的能力, 与在聊天里长按图片识别是同一套逻辑 —— 本项目图鉴页也是这条路径。
     */
    onQrPreview() {
      const url = this.data.qrSrc
      if (!url) return
      const open = (path) => {
        wx.hideLoading()
        wx.previewImage({
          urls: [path],
          current: path,
          fail: () => wx.showToast({ title: '打开预览失败，请重试', icon: 'none' })
        })
      }
      if (url.indexOf('data:') === 0) {
        // base64 兜底: 预览器对 data URL 支持有限 → 先写成本地文件再预览
        const b64 = url.split(',')[1] || ''
        if (!b64) {
          wx.showToast({ title: '二维码图片异常，请刷新', icon: 'none' })
          return
        }
        wx.showLoading({ title: '打开预览…' })
        wx.getFileSystemManager().writeFile({
          filePath: `${wx.env.USER_DATA_PATH}/sso-qr-preview.png`,
          data: b64,
          encoding: 'base64',
          success: () => open(`${wx.env.USER_DATA_PATH}/sso-qr-preview.png`),
          fail: () => {
            wx.hideLoading()
            wx.showToast({ title: '打开预览失败，请重试', icon: 'none' })
          }
        })
        return
      }
      wx.showLoading({ title: '打开预览…' })
      wx.downloadFile({
        url,
        timeout: 20000,
        success: (res) => {
          if (res.statusCode === 200 && res.tempFilePath) open(res.tempFilePath)
          else open(url)          // 下载失败也尝试直接用网络地址预览
        },
        fail: () => open(url)
      })
    },

    /** 登录：智慧理工 SSO 一步直连教务（免教务密码/验证码） */
    async onLogin() {
      const { studentId, password } = this.data
      if (!studentId || !password) {
        wx.showToast({ title: '请填写学号和智慧理工密码', icon: 'none' })
        return
      }

      let res
      this.setData({ loggingIn: true })
      try {
        wx.showLoading({ title: '智慧理工登录中…' })
        res = await api.loginWebvpn(studentId, password)
        wx.hideLoading()
        this.setData({ loggingIn: false })

        if (res.success) {
          analytics.track('login_success', {
            feature: 'login', page: 'profile', source: 'password'
          })
          // 默认保存本机密码; 服务端也会始终加密保存。
          storage.set('saved_password', password)
          storage.setStudentId(studentId)
          storage.setStudentName(res.student_name || '')
          storage.setSemester(res.semester || '')
          // 账号类型(研究生/本科): 决定课表/成绩页走哪套数据
          storage.set('account_type', res.account_type || 'undergraduate')
          if (res.credential_saved === false) {
            wx.showToast({
              title: '登录成功，但服务端未启用密码保存',
              icon: 'none', duration: 2600
            })
          } else {
            wx.showToast({ title: '登录成功，正在同步数据…', icon: 'success' })
          }
          this.refreshState()
          // 通知全局
          getApp().setLoginState(true, res.student_name || studentId, res.semester || '')
          this.setData({
            password: ''
          })
          this.loadSettings()
          // 登录后立即刷新「我的反馈」未读回复(小红点)
          this._loadMyFeedback(false)
          // 自动向后端获取全部数据并载入缓存(课表/考试/评教/成绩/CET/校历)
          dataLoader.fetchAllData().then((ok) => {
            if (ok > 0) {
              wx.showToast({ title: '数据已更新', icon: 'success' })
            }
          })
        } else {
          wx.showToast({ title: res.message || '登录失败', icon: 'none' })
          this._updateCanLogin()
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

    /**
     * 从教务教学周历同步第一周周一(教务为准)。
     * 后端 refresh-calendar 会重新抓取并顺带回写 first_week_date, 这里只负责刷新本地展示。
     */
    async onSyncCalendar() {
      if (this.data.calendarSyncing) return
      this.setData({ calendarSyncing: true })
      try {
        const sem = storage.getSemester()
        let res = await api.refreshCalendar(sem)
        if (!res || !res.first_monday) res = await api.getCalendar(sem)
        const fm = res && res.first_monday
        if (fm) {
          this.setData({ firstWeekDate: fm })
          const sid = storage.getStudentId() || 'guest'
          storage.remove('cached_status_' + sid + '_' + (sem || 'default'))
          wx.showToast({ title: '已按教务周历校准', icon: 'success' })
        } else {
          wx.showToast({ title: (res && res.message) || '教务周历获取失败', icon: 'none' })
        }
      } catch (e) {
        wx.showToast({ title: '同步失败，稍后再试', icon: 'none' })
      }
      this.setData({ calendarSyncing: false })
    },

    // ============================================================
    // 消息提醒(订阅消息): 微信一次性订阅, 授权一次可发一条
    // ============================================================

    /** 拉取可用提醒类型与剩余额度 */
    async loadSubscribeStatus() {
      if (!storage.isLoggedIn()) {
        if (this.data.subKinds.length || this.data.subSummary) {
          this.setData({
            subKinds: [], subSummary: '', subHasQuota: false,
            showSubscriptions: false
          })
        }
        return
      }
      const res = await subUtil.loadStatus()
      const kinds = res.kinds || []
      const summary = kinds.map(item => {
        return item.label + ' ' + (item.quota > 0 ? item.quota + ' 条' : '未开启')
      }).join(' · ')
      this.setData({
        subKinds: kinds,
        subEnabled: !!res.enabled,
        subSummary: summary,
        subHasQuota: kinds.some(item => item.quota > 0)
      })
    },

    onOpenSubscriptions() {
      if (!this.data.subKinds.length) return
      this.setData({ showSubscriptions: true })
    },

    onSubscriptionsClose() {
      this.setData({ showSubscriptions: false })
    },

    /** 点击提醒条目: 请求订阅授权 → 上报额度 */
    async onSubscribeTap(e) {
      const kind = e.currentTarget.dataset.kind
      const item = (this.data.subKinds || []).find(x => x.kind === kind)
      if (!item || !item.templateId) {
        wx.showToast({ title: '该提醒暂不可用', icon: 'none' })
        return
      }
      if (!this.data.subEnabled) {
        wx.showToast({ title: '服务端未配置，暂不可用', icon: 'none' })
        return
      }
      const r = await subUtil.requestGrant(kind, item.templateId)
      if (r.ok) {
        wx.showToast({ title: '已 +1 条（剩余 ' + (r.quota || 1) + ' 次）', icon: 'none' })
        this.loadSubscribeStatus()
      } else if (r.reason === 'reject' || r.reason === 'ban') {
        wx.showToast({ title: '未授权', icon: 'none' })
      } else {
        wx.showToast({ title: '授权未完成，请重试', icon: 'none' })
      }
    },

    // ============================================================
    // 已登录操作
    // ============================================================

    /** 跳成绩页（合页方案: 通知 main 切 swiper 到成绩 Tab） */
    onGoGrades() {
      const pages = getCurrentPages()
      const page = pages[pages.length - 1]
      // 成绩已移入"功能"页: 切到功能页并直接打开成绩二级视图
      if (page && typeof page.goFeature === 'function') {
        page.goFeature('grades')
      } else if (page && typeof page.onTabTap === 'function') {
        page.onTabTap(0)
      } else {
        wx.reLaunch({ url: '/pages/main/main' })
      }
    },

    /** 打开空教室查询页 */
    onGoFreeClass() {
      wx.navigateTo({ url: '/pages/freeclass/freeclass' })
    },

    /** 打开校历照片墙 */
    onGoGallery() {
      wx.navigateTo({ url: '/pages/gallery/gallery' })
    },

    /** 打开常用链接弹窗 */
    onOpenLinks() {
      this.setData({ showLinks: true })
    },

    /** 测试服务端连通性; 会话失效时用已保存凭据自动重建服务端会话 */
    async onTestConnection() {
      if (this.data.testingConnection) return
      this.setData({
        testingConnection: true,
        connectionStatus: '',
        connectionText: '正在测试连接…'
      })

      let res
      try {
        res = await api.testConnection()
      } catch (e) {
        res = null
      }

      if (!res || typeof res.ok !== 'boolean') {
        this.setData({
          testingConnection: false,
          connectionStatus: 'fail',
          connectionText: '服务器连接失败，请稍后重试'
        })
        wx.showToast({ title: '服务器连接失败', icon: 'none' })
        return
      }

      if (!res.ok) {
        this.setData({
          testingConnection: false,
          connectionStatus: 'fail',
          connectionText: '智慧理工或教务入口不可达'
        })
        wx.showModal({
          title: '连接失败',
          content: res.message || '智慧理工或教务入口当前不可达，请检查网络后重试',
          showCancel: false,
          confirmText: '知道了'
        })
        return
      }

      const sid = storage.getStudentId() || storage.get('last_login_sid', '')
      const password = storage.get('saved_password', '')
      const manualLogout = !!storage.get('manual_logout', false)
      const hasToken = !!storage.get('token', '')
      if (!sid || !password || manualLogout) {
        this.setData({
          testingConnection: false,
          connectionStatus: 'ok',
          connectionText: '连接正常，请手动登录'
        })
        wx.showToast({ title: '连接正常', icon: 'success' })
        return
      }

      // token 存在但服务端会话可能已被清理: 先轻量校验, 有效时不重复登录。
      if (hasToken && !storage.isOffline()) {
        let sessionRes
        try {
          sessionRes = await api.getStatus()
        } catch (e) {
          sessionRes = null
        }
        if (sessionRes && sessionRes.logged_in === true) {
          this.setData({
            testingConnection: false,
            connectionStatus: 'ok',
            connectionText: '连接正常，当前会话仍有效'
          })
          wx.showToast({ title: '连接正常', icon: 'success' })
          return
        }
        if (!sessionRes || typeof sessionRes.logged_in !== 'boolean') {
          this.setData({
            testingConnection: false,
            connectionStatus: 'ok',
            connectionText: '连接正常，但无法确认会话状态'
          })
          wx.showToast({ title: '连接正常', icon: 'success' })
          return
        }
      }

      this.setData({ connectionText: '连接正常，正在建立会话…' })
      let loginRes
      try {
        loginRes = await api.loginWebvpn(sid, password)
      } catch (e) {
        loginRes = null
      }

      if (loginRes && loginRes.success && loginRes.token) {
        this.setData({
          testingConnection: false,
          connectionStatus: 'ok',
          connectionText: '连接正常，会话已建立'
        })
        this.refreshState()
        getApp().setLoginState(
          true,
          loginRes.student_name || sid,
          loginRes.semester || ''
        )
        this.loadSettings()
        this._loadMyFeedback(false)
        wx.showToast({ title: '会话已建立', icon: 'success' })
        dataLoader.fetchAllData().then((ok) => {
          if (ok > 0) wx.showToast({ title: '数据已更新', icon: 'success' })
        })
        return
      }

      this.setData({
        testingConnection: false,
        connectionStatus: 'fail',
        connectionText: '连接正常，但自动登录失败，请手动登录'
      })
      wx.showToast({
        title: (loginRes && loginRes.message) || '自动登录失败，请手动登录',
        icon: 'none'
      })
    },

    /** 关闭常用链接弹窗 */
    onLinksClose() {
      this.setData({ showLinks: false })
    },

    /** 点击链接: 复制到剪贴板(小程序无法直接打开外部网页)
     *  复制成功由系统自带"内容已复制"提示, 不再叠加 toast;
     *  "去浏览器粘贴打开"的引导常驻在弹窗顶部提示行 */
    onCopyLink(e) {
      const url = e.currentTarget.dataset.url
      if (!url) return
      wx.setClipboardData({
        data: url,
        fail() {
          wx.showToast({ title: '复制失败，可长按查看完整链接', icon: 'none' })
        },
      })
    },

    /** 长按链接: 弹窗显示完整网址(便于核对/手动复制) */
    onShowLink(e) {
      const ds = e.currentTarget.dataset
      if (!ds.url) return
      wx.showModal({
        title: ds.name || '链接',
        content: ds.url,
        confirmText: '复制',
        cancelText: '关闭',
        success(res) {
          if (res.confirm) wx.setClipboardData({ data: ds.url })
        },
      })
    },

    /** 打开问题反馈弹窗 */
    onOpenFeedback() {
      this.setData({ showFeedback: true })
    },

    /** 关闭反馈弹窗(提交中不允许关闭, 防打断) */
    onFbClose() {
      if (this.data.fbSending) return
      this.setData({ showFeedback: false })
    },

    /** 弹窗内点击透传拦截(防止冒泡到遮罩关闭) */
    noop() {},

    onFbType(e) {
      this.setData({ fbType: e.currentTarget.dataset.type })
    },

    onFbInput(e) {
      this.setData({ fbContent: e.detail.value })
    },

    /** 提交反馈(防双击 + 客户端 10 秒冷却 + 服务端限流兜底) */
    async onFbSubmit() {
      if (this.data.fbSending) return
      const text = (this.data.fbContent || '').trim()
      if (!text) {
        wx.showToast({ title: '请填写反馈内容', icon: 'none' })
        return
      }
      if (!storage.isLoggedIn()) {
        wx.showToast({ title: '请先登录后再提交反馈', icon: 'none' })
        return
      }
      const now = Date.now()
      if (now - (this._fbLastTs || 0) < 10000) {
        const remain = Math.ceil((10000 - (now - this._fbLastTs)) / 1000)
        wx.showToast({ title: `提交太频繁，请 ${remain} 秒后再试`, icon: 'none' })
        return
      }
      this.setData({ fbSending: true })
      try {
        const res = await api.submitFeedback(this.data.fbType, text)
        if (res.success) {
          analytics.track('feedback_submit', {
            feature: 'feedback', page: 'profile', kind: this.data.fbType
          })
          this._fbLastTs = Date.now()
          this.setData({ showFeedback: false, fbContent: '' })
          wx.showToast({ title: '已提交，回复见「我的反馈」', icon: 'none', duration: 2500 })
          this._loadMyFeedback(false)
        } else {
          wx.showToast({ title: res.message || '提交失败', icon: 'none' })
        }
      } catch (e) {
        wx.showToast({ title: '提交失败，请稍后再试', icon: 'none' })
      } finally {
        this.setData({ fbSending: false })
      }
    },

    // ── 我的反馈(查看官方回复) ──
    /** 打开「我的反馈」: 拉取列表 + 清除未读小红点 */
    async onOpenMyFeedback() {
      if (!storage.isLoggedIn()) {
        wx.showToast({ title: '请先登录后查看反馈', icon: 'none' })
        return
      }
      this.setData({ showMyFeedback: true })
      await this._loadMyFeedback(true)
    },

    onMyFbClose() {
      this.setData({ showMyFeedback: false })
    },

    // ============================================================
    // 赞赏支持(弹窗显示赞赏码; 长按图片可保存或识别)
    // ============================================================

    onOpenAppreciate() {
      this.setData({ showAppreciate: true })
    },

    onCloseAppreciate() {
      this.setData({ showAppreciate: false })
    },

    /** 拉取我的反馈; markRead=true 时把回复标记为已读(清小红点) */
    async _loadMyFeedback(markRead) {
      if (!storage.isLoggedIn() || !storage.get('token', '')) {
        this.setData({ myFeedback: [], fbUnread: 0, fbLoading: false })
        return
      }
      this.setData({ fbLoading: true })
      try {
        const res = await api.getMyFeedback()
        if (res && res.success) {
          const list = (res.feedback || []).map(f => ({
            ...f,
            _typeLabel: FB_TYPES[f.type] || '其他',
            _reply: (f.reply || '').trim()
          }))
          const unread = res.unread || 0
          this.setData({ myFeedback: list, fbUnread: unread })
          if (markRead && unread > 0) {
            await api.markFeedbackRead()
            this.setData({ fbUnread: 0 })
          }
        }
      } catch (e) {
        // 静默: 反馈列表加载失败不影响其他功能
      } finally {
        this.setData({ fbLoading: false })
      }
    },

    /** 一键刷新课表+考试(走 dataLoader: 刷新教务后查询写新缓存, 各 Tab 自动生效) */
    async onRefreshAll() {
      wx.showLoading({ title: '刷新中…' })
      try {
        const ok = await dataLoader.fetchAllData({ force: true })
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
          if (!res.confirm) return
          // 加可见反馈 + 兜底: 之前这里 await 抛错时界面毫无变化, 看起来就是"点了没反应"
          wx.showLoading({ title: '正在退出…', mask: true })
          try {
            await getApp().doLogout()   // 等待后端登出 + 本地清理完成, 避免状态未清导致要点两次
          } catch (e) {
            wx.showToast({ title: '退出失败，请重试', icon: 'none', duration: 2500 })
          }
          wx.hideLoading()
          this.refreshState()
          // 登出后立刻回填"上次登录的学号 + 记住的密码"(不用切 Tab 再触发 activate)
          this.setData({
            studentId: storage.get('last_login_sid', '') || storage.getStudentId() || '',
            password: ''
          })
          this._updateCanLogin()
        },
        fail: () => {
          wx.showToast({ title: '弹窗打开失败，请重进小程序', icon: 'none', duration: 2500 })
        }
      })
    }
  }
})
