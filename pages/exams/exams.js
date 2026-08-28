/**
 * 考试安排页面
 * 参考桌面端 static/js/exams.js — 倒计时卡片 + 按日期分组
 */

const api = require('../../utils/api')
const storage = require('../../utils/storage')
const swipeNav = require('../../utils/swipe-nav')
const { timeUntil } = require('../../utils/date')

Page({
  data: {
    exams: [],
    countdowns: [],    // 顶部倒计时卡片（最近 3 场）
    dayGroups: [],     // 按日期分组 [{date, weekday, urgency, exams}]
    loading: false,
    collapsedDates: {}, // 已结束日期组折叠状态

    swipeX: 0,         // Tab 滑动切换: 跟手平移
    swipeTrans: false, // Tab 滑动切换: 回弹过渡
    animClass: ''      // Tab 滑动切换: 进入动画类
  },

  onLoad() {
    // 缓存优先：打开页面只渲染本地缓存，后端请求仅发生在下拉刷新时
    this.loadCachedData()
    swipeNav.attach(this, 'pages/exams/exams')
    // 本地无数据且已登录: 后台静默拉取, 不阻塞显示
    if (storage.isLoggedIn() && !(storage.getCached(this._examsCacheKey()) || []).length) {
      this.loadFromServer(true)
    }
  },

  onShow() {
    swipeNav.playEnterAnim(this)
  },

  /** 考试缓存键按学期隔离 */
  _examsCacheKey() {
    return 'cached_exams_' + (storage.getSemester() || 'default')
  },

  /** 从缓存加载 */
  loadCachedData() {
    const exams = storage.getCached(this._examsCacheKey())
    if (exams && exams.length > 0) {
      this.setData({ exams })
      this._processExams(exams)
    }
  },

  /** 从服务器加载（silent 为后台静默模式: 不显示 loading, 失败不弹提示） */
  async loadFromServer(silent) {
    if (!storage.isLoggedIn()) return
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

  /** 刷新 */
  async onRefresh() {
    if (!storage.isLoggedIn()) {
      wx.showToast({ title: '请先在"我的"页面登录', icon: 'none' })
      return
    }
    this.setData({ loading: true })
    try {
      const res = await api.refreshExams()
      this.setData({ loading: false })
      if (res.success) {
        wx.showToast({ title: `已刷新 ${res.count || 0} 场考试`, icon: 'success' })
        this.loadFromServer()
      } else {
        wx.showToast({ title: res.message || '刷新失败', icon: 'none' })
      }
    } catch (e) {
      this.setData({ loading: false })
      wx.showToast({ title: '刷新失败', icon: 'none' })
    }
  },

  onPullDownRefresh() {
    // 横滑切换手势后短暂时间内的下拉视为误触
    if (swipeNav.wasSwiping(this)) {
      wx.stopPullDownRefresh()
      return
    }
    this.onRefresh()
    wx.stopPullDownRefresh()
  }
})
