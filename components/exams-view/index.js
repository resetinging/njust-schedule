/**
 * 考试安排视图组件 — 由原 pages/exams 页面改造（方案A 合页 swiper）
 * 生命周期: attached 首次挂载(读缓存); activate 由 main 页面每次激活时调用(onShow 语义)
 * 刷新: 顶部 hero 「🔄 刷新」按钮
 *
 * 状态显示（2026-10-28 修复）：
 * - 逐场状态由「日期 + 开始/结束时间」按 Asia/Shanghai 判定（utils/date.js 的考试函数）
 * - 开考瞬间 ongoing、结束瞬间 done；倒计时以开始时间为目标，开考后显示「进行中」
 * - 缺日期/非法日期/缺时段/仅开始无结束 → 保守 unknown（时间待定），不误标 done
 * - 日期组：有进行中优先；全部结束才 done 且允许折叠；卡片状态取自身，不继承组状态
 * - 缓存/异步：空数组/缺失/切学期/退出统一清空；迟到响应按「账号+学期」丢弃；卸载后不再 setData
 */

const api = require('../../utils/api')
const storage = require('../../utils/storage')
const subUtil = require('../../utils/subscribe')
const analytics = require('../../utils/analytics')
const {
  parseExamDate,
  getExamTiming,
  formatExamCountdown,
  getExamGroupStatus
} = require('../../utils/date')

const WEEKDAY = ['日', '一', '二', '三', '四', '五', '六']
const EXAM_AUTO_REFRESH_MS = 30 * 60 * 1000

Component({
  options: {
    styleIsolation: 'apply-shared'
  },

  data: {
    exams: [],
    countdowns: [],    // 顶部倒计时卡片（进行中优先 + 最近未开始，最多 3 场）
    dayGroups: [],     // 按日期分组 [{date, weekday, urgency, urgencyText, exams}]
    loading: false,
    refreshing: false,
    errorMsg: '',
    semester: '',
    collapsedDates: {}, // 已结束日期组折叠状态（仅全部结束的组可折叠）

    // 研究生: 考试信息(表格行, 本地优先)
    isGraduate: false,
    examRows: [],

    // 考前提醒(订阅消息): 有可用模板时显示入口
    subExam: null,

    active: false            // 懒渲染: main 激活时才渲染内容
  },

  lifetimes: {
    attached() {
      this._detached = false
      this._loadedSemester = undefined
      this._reqSeq = 0
      this._activeIdentity = this._identityKey()
      const isGrad = storage.get('account_type', '') === 'graduate'
      this.setData({ isGraduate: isGrad })
      if (!isGrad) {
        // 本科：缓存优先；本地无数据且已登录时后台静默拉取 GET /api/exams
        this.loadCachedData()
        if (storage.isLoggedIn() && !(storage.getCached(this._examsCacheKey()) || []).length) {
          this.loadFromServer(true)
        }
        return
      }
      // 研究生：只读 cached_yjs_exams；必要后台请求也只走 GET /api/yjs/exams
      this.loadYjsCached()
      const cached = storage.getCached('cached_yjs_exams')
      const hasRows = !!(cached && cached.success && (cached.rows || []).length)
      if (storage.isLoggedIn() && !hasRows) this.loadYjsFromServer(true)
    },
    detached() {
      // 卸载后所有异步响应都不得再 setData
      this._detached = true
      this._reqSeq = (this._reqSeq || 0) + 1
      analytics.disconnectSlots(this)
    }
  },

  pageLifetimes: {
    /** 页面回到前台：按当前时间本地重算状态（不发任何网络请求）；研究生保持分流 */
    show() {
      if (this._detached || !this.data.active) return
      if (this.data.isGraduate) return
      if (Array.isArray(this.data.exams) && this.data.exams.length) this._processExams(this.data.exams)
    }
  },

  methods: {
    /**
     * 当前身份+学期快照。异步响应回来时比对：
     * 账号或学期已变化则丢弃响应，避免旧数据覆盖新视图或污染缓存。
     */
    _identityKey() {
      return [
        storage.getStudentId() || '',
        storage.get('account_type', '') || '',
        storage.getSemester() || ''
      ].join('|')
    },

    /**
     * 发起请求时绑定「身份 + 学期 + 递增序号」。
     * 任何 success/catch/finally 分支都必须用 _isCurrentRequest 校验：
     * - 身份或学期已变化 → 丢弃（不 setData / 不写缓存 / 不 toast）
     * - 同一身份的新操作（如刷新）会使旧的静默加载失效（序号递增）
     * - 组件卸载后一律失效
     */
    _beginRequest(kind) {
      return {
        kind: kind || '',
        identity: this._identityKey(),
        semester: storage.getSemester() || '',
        seq: (this._reqSeq = (this._reqSeq || 0) + 1)
      }
    },

    _isCurrentRequest(token) {
      if (!token || this._detached) return false
      if (token.seq !== this._reqSeq) return false
      if (token.identity !== this._identityKey()) return false
      if (token.semester !== (storage.getSemester() || '')) return false
      return true
    },

    /** 统一清空考试视图（含折叠状态、研究生 rows；复位忙态并让在途请求失效） */
    _clearExamView() {
      this._reqSeq = (this._reqSeq || 0) + 1
      this.setData({
        exams: [],
        countdowns: [],
        dayGroups: [],
        collapsedDates: {},
        examRows: [],
        loading: false,
        refreshing: false,
        errorMsg: '',
        subExam: null
      })
    },

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
      // 退出登录后清空上一用户数据(隐私)，含研究生 rows 与忙态
      if (!storage.isLoggedIn()) {
        this._clearExamView()
        return
      }
      // 切换账号/学期：让旧身份的在途请求失效，并复位忙态/错误/订阅入口
      const identity = this._identityKey()
      if (this._activeIdentity !== undefined && this._activeIdentity !== identity) {
        this._reqSeq = (this._reqSeq || 0) + 1
        this.setData({ loading: false, refreshing: false, errorMsg: '', subExam: null, collapsedDates: {} })
      }
      this._activeIdentity = identity
      const semester = storage.getSemester() || ''
      if (isGrad) {
        this.setData({
          semester, exams: [], countdowns: [], dayGroups: [],
          collapsedDates: this.data.collapsedDates,
          loading: false, refreshing: false, errorMsg: ''
        })
        this.loadYjsCached()
        return
      }
      this.setData({ semester, examRows: [], loading: false, refreshing: false, errorMsg: '' })
      // 每次激活都重读缓存并按当前时间重算状态（进行中/已结束会随时间变化）
      this.loadCachedData()
      this._maybeAutoRefresh()
    },

    _examAutoRefreshKey() {
      return 'exam_auto_refresh_' + (storage.getStudentId() || '') + '_' + (storage.getSemester() || '')
    },

    _maybeAutoRefresh() {
      if (this.data.isGraduate || !storage.hasSession() || this.data.loading || this.data.refreshing) return
      const key = this._examAutoRefreshKey()
      const previous = parseInt(storage.get(key, '0'), 10) || 0
      if (Date.now() - previous < EXAM_AUTO_REFRESH_MS) return
      storage.set(key, String(Date.now()))
      this.onRefresh(true)
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
      const identity = this._identityKey()
      const res = await subUtil.loadStatus()
      // 订阅状态只做身份校验：不占用数据请求序号，避免把在途考试加载误判为过期
      if (this._detached || identity !== this._identityKey()) return
      const exam = ((res && res.kinds) || []).find(k => k.kind === 'exam') || null
      this.setData({ subExam: res && res.enabled ? exam : null })
    },

    /** 点击: 授权一次并上报额度(微信要求必须用户点击触发) */
    async onSubscribeExamTap() {
      const item = this.data.subExam
      if (!item || !item.templateId) {
        wx.showToast({ title: '该提醒暂不可用', icon: 'none' })
        return
      }
      const r = await subUtil.requestGrant('exam', item.templateId)
      if (this._detached) return
      if (r && r.ok) {
        analytics.track('reminder_grant', {
          feature: 'subscription', kind: 'exam', page: 'exams'
        })
        wx.showToast({ title: '已开启考前提醒（剩余 ' + (r.quota || 1) + ' 条）', icon: 'none' })
        this.loadExamSubscribe()
      } else if (r && (r.reason === 'reject' || r.reason === 'ban')) {
        wx.showToast({ title: '未授权', icon: 'none' })
      } else {
        wx.showToast({ title: '授权未完成，请重试', icon: 'none' })
      }
    },

    /** 研究生：静默加载（只在缓存缺失时由 attached 调用，不阻塞显示） */
    async loadYjsFromServer(silent) {
      if (!storage.isLoggedIn()) return
      if (!silent) this.setData({ loading: true })
      const token = this._beginRequest('yjs')
      try {
        const res = await api.getYjsExams()
        if (!this._isCurrentRequest(token)) return
        if (res && res.success) {
          storage.setCached('cached_yjs_exams', res)
          this._applyYjsExams(res)
        } else {
          this.setData({ loading: false })
          if (!silent) wx.showToast({ title: (res && res.message) || '加载失败', icon: 'none' })
        }
      } catch (e) {
        if (!this._isCurrentRequest(token)) return
        this.setData({ loading: false })
        if (!silent) wx.showToast({ title: '加载失败', icon: 'none' })
      }
    },

    /** 用户主动刷新: 才请求后端并写缓存 */
    async onRefreshYjsExams() {
      if (this.data.refreshing) return
      this.setData({ refreshing: true })
      const token = this._beginRequest('yjs-refresh')
      try {
        const res = await api.getYjsExams()
        if (!this._isCurrentRequest(token)) return
        if (res && res.success) {
          storage.setCached('cached_yjs_exams', res)
          this._applyYjsExams(res)
          wx.showToast({ title: '考试信息已更新', icon: 'success' })
        } else {
          wx.showToast({ title: (res && res.message) || '刷新失败', icon: 'none' })
        }
      } catch (e) {
        if (!this._isCurrentRequest(token)) return
        wx.showToast({ title: '网络异常，请稍后重试', icon: 'none' })
      }
      if (this._isCurrentRequest(token)) this.setData({ refreshing: false })
    },

    _applyYjsExams(res) {
      if (this._detached) return
      this.setData({
        loading: false,
        refreshing: false,
        errorMsg: '',
        examRows: ((res && res.rows) || []).map((cells, i) => ({ i, cells }))
      })
    },

    /** 考试缓存键按学期隔离 */
    _examsCacheKey() {
      return 'cached_exams_' + (storage.getSemester() || 'default')
    },

    /** 从缓存加载（空数组/缺失/切学期都清空旧视图与折叠状态） */
    loadCachedData() {
      if (this._detached) return
      const sem = storage.getSemester() || ''
      const semesterChanged = this._loadedSemester !== sem
      this._loadedSemester = sem
      const exams = storage.getCached(this._examsCacheKey())
      const list = Array.isArray(exams) ? exams : []
      if (semesterChanged) this.setData({ collapsedDates: {} })
      if (!list.length) {
        this.setData({ semester: sem, exams: [], countdowns: [], dayGroups: [], collapsedDates: {} })
        return
      }
      this.setData({ semester: sem, exams: list })
      this._processExams(list)
    },

    /** 从服务器加载（silent 为后台静默模式: 不显示 loading, 失败不弹提示） */
    async loadFromServer(silent) {
      if (!storage.isLoggedIn() || !storage.get('token', '')) return
      if (!silent) this.setData({ loading: true })
      const token = this._beginRequest('exams')
      try {
        // 明确把请求学期传给 GET /api/exams（api 层签名 getExams(semester)）
        const res = await api.getExams(token.semester)
        if (!this._isCurrentRequest(token)) return
        // 服务端明确返回的学期与本次请求学期不一致 → 丢弃，不覆盖当前视图/缓存
        if (res && res.semester && token.semester && res.semester !== token.semester) {
          this.setData({ loading: false })
          return
        }
        if (res && res.success && Array.isArray(res.exams)) {
          // 缓存键带学期: 按实际返回学期写缓存
          const cacheSem = res.semester || token.semester || 'default'
          storage.setCached('cached_exams_' + cacheSem, res.exams)
          this._loadedSemester = cacheSem
          this.setData({ exams: res.exams, semester: cacheSem, loading: false, errorMsg: '' })
          this._processExams(res.exams)
        } else {
          // 失败时保留同学期已有数据
          this.setData({ loading: false })
          if (!silent) wx.showToast({ title: (res && res.message) || '加载失败', icon: 'none' })
        }
      } catch (e) {
        if (!this._isCurrentRequest(token)) return
        this.setData({ loading: false })
        if (!silent) wx.showToast({ title: '加载失败', icon: 'none' })
      }
    },

    /** 处理考试数据：逐场状态 + 倒计时 + 日期分组 */
    _processExams(exams, nowMs) {
      if (this._detached) return
      const list = Array.isArray(exams) ? exams : []
      const now = Number.isFinite(nowMs) ? nowMs : Date.now()
      if (!list.length) {
        // 服务器刷新返回空数组同样要复位折叠状态
        this.setData({ countdowns: [], dayGroups: [], collapsedDates: {} })
        return
      }
      const items = list.map(exam => ({ exam, timing: getExamTiming(exam, now) }))

      // --- 倒计时卡片：进行中优先，其次最近未开始；最多 3 场；不含已结束/时间待定 ---
      const countdowns = items
        .filter(x => x.timing.status === 'ongoing' || x.timing.status === 'upcoming')
        .sort((a, b) => {
          const rank = x => (x.timing.status === 'ongoing' ? 0 : 1)
          if (rank(a) !== rank(b)) return rank(a) - rank(b)
          return (a.timing.startMs || 0) - (b.timing.startMs || 0)
        })
        .slice(0, 3)
        .map(x => {
          const cd = formatExamCountdown(x.timing, now)
          return {
            course_name: x.exam.course_name,
            date: x.exam.date,
            time: x.exam.time,
            info: { text: cd.statusText, cls: cd.cls },
            bigNum: cd.bigNum,
            bigLabel: cd.bigLabel,
            cardClass: cd.cls
          }
        })

      // --- 按日期分组（日期待定单独一组，排最后） ---
      const grouped = {}
      const order = []
      for (const item of items) {
        const parsed = parseExamDate(item.exam.date)
        const date = parsed ? String(item.exam.date).trim() : '日期待定'
        if (!grouped[date]) {
          grouped[date] = []
          order.push(date)
        }
        grouped[date].push(item)
      }
      const dateSortKey = (s) => {
        const p = parseExamDate(s)
        return p ? p.y * 10000 + p.mo * 100 + p.d : Infinity
      }
      const sortedDates = order.sort((a, b) => dateSortKey(a) - dateSortKey(b))

      const dayGroups = sortedDates.map(date => {
        const entries = grouped[date].slice().sort((a, b) => {
          const sa = a.timing.startMs == null ? Infinity : a.timing.startMs
          const sb = b.timing.startMs == null ? Infinity : b.timing.startMs
          return sa - sb
        })
        const groupStatus = getExamGroupStatus(entries.map(e => e.timing), now)
        const parsed = parseExamDate(date)
        let weekday = ''
        if (parsed) {
          const d = new Date(Date.UTC(parsed.y, parsed.mo - 1, parsed.d))
          weekday = '周' + WEEKDAY[d.getUTCDay()]
        }
        const exams = entries.map(({ exam, timing }) => {
          const cd = formatExamCountdown(timing, now)
          let cardClass = ''
          if (timing.status === 'done') cardClass = 'exam-done'
          else if (timing.status === 'ongoing') cardClass = 'exam-ongoing'
          else if (timing.status === 'unknown') cardClass = 'exam-unknown'
          else if (cd.cls === 'urgent') cardClass = 'exam-urgent'
          else if (cd.cls === 'warning') cardClass = 'exam-warning'
          return Object.assign({}, exam, {
            status: timing.status,
            statusText: cd.statusText,
            statusClass: 'is-' + timing.status,
            cardClass
          })
        })
        return {
          date,
          weekday,
          urgency: groupStatus.status,
          urgencyText: groupStatus.text,
          exams
        }
      })

      this.setData({ countdowns, dayGroups })
    },

    /** 折叠/展开已结束的日期组（仅全部结束的组可折叠） */
    onToggleGroup(e) {
      if (!(e && e.currentTarget && e.currentTarget.dataset && e.currentTarget.dataset.done)) return
      const date = e.currentTarget.dataset.date
      const collapsed = Object.assign({}, this.data.collapsedDates)
      collapsed[date] = !collapsed[date]
      this.setData({ collapsedDates: collapsed })
    },

    /** 刷新(防重复点击; quiet=true 时用于后台自动刷新) */
    async onRefresh(quiet) {
      const isQuiet = quiet === true
      if (this.data.loading) return
      if (!storage.isLoggedIn()) {
        wx.showToast({ title: '请先在"我的"页面登录', icon: 'none' })
        return
      }
      if (storage.isOffline() && !storage.get('saved_password', '')) {
        wx.showToast({ title: '登录已过期，请先在"我的"页面重新登录', icon: 'none' })
        return
      }
      this.setData({ loading: true })
      storage.set(this._examAutoRefreshKey(), String(Date.now()))
      const token = this._beginRequest('exams-refresh')
      try {
        const res = await api.refreshExams()
        if (!this._isCurrentRequest(token)) return
        this.setData({ loading: false })
        if (res && res.success && res.refreshed !== false) {
          analytics.refreshResult('exams', true, 'exams')
          if (!isQuiet) wx.showToast({ title: '已刷新 ' + (res.count || 0) + ' 场考试', icon: 'success' })
          // 刷新→加载链继续保持同一身份/学期绑定；loadFromServer 内部再校验
          if (this._isCurrentRequest(token)) this.loadFromServer()
        } else if (res && res.success && res.refreshed === false) {
          analytics.refreshResult('exams', false, 'exams')
          if (!isQuiet) wx.showToast({ title: res.message || '服务器未开启实时刷新', icon: 'none' })
          if (this._isCurrentRequest(token)) this.loadFromServer()
        } else {
          analytics.refreshResult('exams', false, 'exams')
          if (!isQuiet) wx.showToast({ title: (res && res.message) || '刷新失败', icon: 'none' })
        }
      } catch (e) {
        if (!this._isCurrentRequest(token)) return
        this.setData({ loading: false })
        analytics.refreshResult('exams', false, 'exams')
        if (!isQuiet) wx.showToast({ title: '刷新失败', icon: 'none' })
      }
    }
  }
})
