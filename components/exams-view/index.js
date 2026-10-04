/**
 * 考试安排视图组件 — 由原 pages/exams 页面改造（方案A 合页 swiper）
 * 生命周期: attached 首次挂载(读缓存); activate 由 main 页面每次激活时调用(onShow 语义)
 * 刷新: 顶部 hero 「🔄 刷新」按钮
 */

const api = require('../../utils/api')
const storage = require('../../utils/storage')
const subUtil = require('../../utils/subscribe')
const analytics = require('../../utils/analytics')
const { timeUntil } = require('../../utils/date')

Component({
  options: {
    styleIsolation: 'apply-shared'
  },

  data: {
    exams: [],
    countdowns: [],    // 顶部倒计时卡片（最近 3 场）
    dayGroups: [],     // 按日期分组 [{date, weekday, urgency, exams}]
    loading: false,
    errorMsg: '',
    semester: '',
    collapsedDates: {}, // 已结束日期组折叠状态

    // 研究生: 考试信息(表格行, 本地优先)
    isGraduate: false,
    examRows: [],

    // 考前提醒(订阅消息): 有可用模板时显示入口
    subExam: null,

    active: false            // 懒渲染: main 激活时才渲染内容
  },

  lifetimes: {
    attached() {
      // 缓存优先：打开页面只渲染本地缓存，后端请求仅发生在下拉刷新时
      this.loadCachedData()
      // 本地无数据且已登录: 后台静默拉取, 不阻塞显示
      if (storage.isLoggedIn() && !(storage.getCached(this._examsCacheKey()) || []).length) {
        this.loadFromServer(true)
      }
    },
    detached() {
      analytics.disconnectSlots(this)
    }
  },

  methods: {
    /** 由 main 页面调用: 每次被激活(滑动/点 tab 切换/从子页返回) */
    activate() {
      this.setData({ active: true })   // 懒渲染: 首次激活才渲染内容
      analytics.observeSlots(this, [
        { id: 'slot-exams-bottom', page: 'exams', ad_type: 'native' }
      ])
      this.loadExamSubscribe()
      // 研究生账号: 考试来自研究生系统, 先渲染本地缓存
      const isGrad = storage.get('account_type', '') === 'graduate'
      this.setData({ isGraduate: isGrad })
      if (isGrad) {
        if (!storage.isLoggedIn()) {
          this.setData({ examRows: [] })
          return
        }
        this.loadYjsCached()
        return
      }
      // 退出登录后清空上一用户数据(隐私)
      if (!storage.isLoggedIn()) {
        this.setData({ exams: [], countdowns: [], dayGroups: [] })
        return
      }
      this.loadCachedData()            // 重新读缓存(登录后/刷新后数据自动生效)
    },

    /** 研究生考试: 只读本地缓存渲染 */
    loadYjsCached() {
      const cached = storage.getCached('cached_yjs_exams')
      if (cached && cached.success) {
        this._applyYjsExams(cached)
      } else {
        this.setData({ loading: false, examRows: [], errorMsg: '' })
      }
    },

    /** 考前提醒入口: 拉取订阅状态(只显示考试类型) */
    async loadExamSubscribe() {
      if (!storage.isLoggedIn() || storage.get('account_type', '') === 'graduate') {
        if (this.data.subExam) this.setData({ subExam: null })
        return
      }
      const res = await subUtil.loadStatus()
      const exam = (res.kinds || []).find(k => k.kind === 'exam') || null
      this.setData({ subExam: res.enabled ? exam : null })
    },

    /** 点击: 授权一次并上报额度(微信要求必须用户点击触发) */
    async onSubscribeExamTap() {
      const item = this.data.subExam
      if (!item || !item.templateId) {
        wx.showToast({ title: '该提醒暂不可用', icon: 'none' })
        return
      }
      const r = await subUtil.requestGrant('exam', item.templateId)
      if (r.ok) {
        analytics.track('reminder_grant', {
          feature: 'subscription', kind: 'exam', page: 'exams'
        })
        wx.showToast({ title: '已开启考前提醒（剩余 ' + (r.quota || 1) + ' 条）', icon: 'none' })
        this.loadExamSubscribe()
      } else if (r.reason === 'reject' || r.reason === 'ban') {
        wx.showToast({ title: '未授权', icon: 'none' })
      } else {
        wx.showToast({ title: '授权未完成，请重试', icon: 'none' })
      }
    },

    /** 用户主动刷新: 才请求后端并写缓存 */
    async onRefreshYjsExams() {
      if (this.data.refreshing) return
      this.setData({ refreshing: true })
      try {
        const res = await api.getYjsExams()
        if (res && res.success) {
          storage.setCached('cached_yjs_exams', res)
          this._applyYjsExams(res)
          wx.showToast({ title: '考试信息已更新', icon: 'success' })
        } else {
          wx.showToast({ title: (res && res.message) || '刷新失败', icon: 'none' })
        }
      } catch (e) {
        wx.showToast({ title: '网络异常，请稍后重试', icon: 'none' })
      }
      this.setData({ refreshing: false })
    },

    _applyYjsExams(res) {
      this.setData({
        loading: false,
        errorMsg: '',
        examRows: ((res && res.rows) || []).map((cells, i) => ({ i, cells }))
      })
    },

    /** 考试缓存键按学期隔离 */
    _examsCacheKey() {
      return 'cached_exams_' + (storage.getSemester() || 'default')
    },

    /** 从缓存加载 */
    loadCachedData() {
      this.setData({ semester: storage.getSemester() || '' })
      const exams = storage.getCached(this._examsCacheKey())
      if (exams && exams.length > 0) {
        this.setData({ exams })
        this._processExams(exams)
      }
    },

    /** 从服务器加载（silent 为后台静默模式: 不显示 loading, 失败不弹提示） */
    async loadFromServer(silent) {
      if (!storage.isLoggedIn() || !storage.get('token', '')) return
      if (!silent) this.setData({ loading: true })
      try {
        const res = await api.getExams()
        if (res.success && res.exams) {
          this.setData({ exams: res.exams, loading: false })
          // 缓存键带学期: 按实际返回学期写缓存
          const cacheSem = res.semester || storage.getSemester() || 'default'
          storage.setCached('cached_exams_' + cacheSem, res.exams)
          this._processExams(res.exams)
        } else {
          this.setData({ loading: false })
          if (!silent) wx.showToast({ title: res.message || '加载失败', icon: 'none' })
        }
      } catch (e) {
        this.setData({ loading: false })
        if (!silent) wx.showToast({ title: '加载失败', icon: 'none' })
      }
    },

    /** 处理考试数据：倒计时 + 日期分组 */
    _processExams(exams) {
      // --- 倒计时卡片：按时间排序，取最近 3 场 ---
      const now = new Date()
      const withTime = exams
        .map(e => ({ exam: e, info: timeUntil(e.date, e.time) }))
        .filter(x => x.info.text)

      const future = withTime
        .filter(x => x.info.cls !== 'done')
        .sort((a, b) => (a.exam.date || '').localeCompare(b.exam.date || '') || (a.exam.time || '').localeCompare(b.exam.time || ''))

      const past = withTime
        .filter(x => x.info.cls === 'done')
        .sort((a, b) => (b.exam.date || '').localeCompare(a.exam.date || '') || (b.exam.time || '').localeCompare(a.exam.time || ''))

      const display = [...future, ...past].slice(0, 3)
      const countdowns = display.map(x => {
        const diffMs = x.info.cls === 'done' ? -1 : (() => {
          const d = this._parseDate(x.exam.date)
          if (d && x.exam.time) {
            const m = x.exam.time.match(/(\d{1,2}):(\d{2})/)
            if (m) { d.setHours(parseInt(m[1]), parseInt(m[2]), 0, 0) }
          }
          return d ? (d - now) / (1000 * 60 * 60) : 0
        })()
        return {
          course_name: x.exam.course_name,
          date: x.exam.date,
          time: x.exam.time,
          info: x.info,
          bigNum: diffMs < 0 ? '✓' : (diffMs < 24 ? Math.floor(diffMs) + 'h' : Math.floor(diffMs / 24)),
          bigLabel: diffMs < 0 ? '已结束' : (diffMs < 24 ? '小时后' : '天后'),
          cardClass: x.info.cls === 'done' ? 'done' : (diffMs <= 72 ? 'urgent' : (diffMs <= 168 ? 'warning' : ''))
        }
      })

      // --- 按日期分组 ---
      const grouped = {}
      const WEEKDAY = ['日', '一', '二', '三', '四', '五', '六']
      for (const exam of exams) {
        const date = exam.date || '日期待定'
        if (!grouped[date]) grouped[date] = []
        grouped[date].push(exam)
      }
      for (const date of Object.keys(grouped)) {
        grouped[date].sort((a, b) => (a.time || '').localeCompare(b.time || ''))
      }
      const sortedDates = Object.keys(grouped).sort((a, b) => {
        if (a === '日期待定') return 1
        if (b === '日期待定') return -1
        return a.localeCompare(b)
      })

      const dayGroups = sortedDates.map(date => {
        const firstExam = grouped[date][0]
        const info = timeUntil(date, firstExam.time)
        let weekday = ''
        if (date !== '日期待定') {
          const d = this._parseDate(date)
          if (d) weekday = '周' + WEEKDAY[d.getDay()]
        }
        return { date, weekday, urgency: info.cls, urgencyText: info.text, exams: grouped[date] }
      })

      this.setData({ countdowns, dayGroups })
    },

    _parseDate(str) {
      if (!str) return null
      const parts = str.split('-')
      if (parts.length !== 3) return null
      return new Date(parseInt(parts[0]), parseInt(parts[1]) - 1, parseInt(parts[2]))
    },

    /** 折叠/展开已结束的日期组 */
    onToggleGroup(e) {
      // 只有已结束的日期组可折叠
      if (!e.currentTarget.dataset.done) return
      const date = e.currentTarget.dataset.date
      const collapsed = { ...this.data.collapsedDates }
      collapsed[date] = !collapsed[date]
      this.setData({ collapsedDates: collapsed })
    },

    /** 刷新(防重复点击) */
    async onRefresh() {
      if (this.data.loading) return
      if (!storage.isLoggedIn()) {
        wx.showToast({ title: '请先在"我的"页面登录', icon: 'none' })
        return
      }
      this.setData({ loading: true })
      try {
        const res = await api.refreshExams()
        this.setData({ loading: false })
        if (res.success) {
          analytics.refreshResult('exams', true, 'exams')
          wx.showToast({ title: `已刷新 ${res.count || 0} 场考试`, icon: 'success' })
          this.loadFromServer()
        } else {
          analytics.refreshResult('exams', false, 'exams')
          wx.showToast({ title: res.message || '刷新失败', icon: 'none' })
        }
      } catch (e) {
        this.setData({ loading: false })
        analytics.refreshResult('exams', false, 'exams')
        wx.showToast({ title: '刷新失败', icon: 'none' })
      }
    }
  }
})
