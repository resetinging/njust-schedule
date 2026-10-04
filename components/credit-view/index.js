/**
 * 学分进度视图组件 —— 培养方案(应修) × 成绩(已修, 按课程代码匹配)
 *
 * 数据来源:
 * - /api/programme  专业培养方案(登录后后端自动预抓; 也可手动刷新)
 * - 本地成绩缓存(cached_grades, 与成绩页同一份)
 *
 * 计算在前端完成(与项目"后端只存原始数据"的分工一致)。
 */
const api = require('../../utils/api')
const storage = require('../../utils/storage')
const creditUtil = require('../../utils/credit')
const analytics = require('../../utils/analytics')

const PROGRAMME_CACHE = 'cached_programme'
const GRADES_CACHE = 'cached_grades'

Component({
  options: { styleIsolation: 'apply-shared' },

  data: {
    active: false,
    loading: true,
    refreshing: false,
    empty: false,
    errorMsg: '',
    updated: '',
    expanded: false,
    expandedCurrent: false,
    expandedUpcoming: false,
    view: {
      rows: [], totalRequired: 0, totalEarned: 0, totalPercent: 0,
      planCount: 0,
      failed: { groups: [], count: 0, credits: 0 },
      current: { groups: [], count: 0, credits: 0 },
      upcoming: { groups: [], count: 0, credits: 0 },
      remainingCount: 0,
      alternativesCount: 0, alternativesCredits: 0,
      unplannedCount: 0, unplannedCredits: 0
    }
  },

  lifetimes: {
    attached() {
      this.loadCached()
      if (storage.isLoggedIn() && this.data.empty) this.loadFromServer(true)
      if (storage.isLoggedIn()) this._ensureGrades().then(ok => { if (ok) this.loadCached() })
    },
    detached() {
      analytics.disconnectSlots(this)
    }
  },

  methods: {
    /** 由 main 页面在激活时调用 */
    async activate() {
      this.setData({ active: true })
      analytics.observeSlots(this, [
        { id: 'slot-credit-bottom', page: 'credit', ad_type: 'native' }
      ])
      this.loadCached()
      if (!storage.isLoggedIn()) return
      if (this.data.empty || !this.data.view.planCount) await this.loadFromServer(true)
      if (await this._ensureGrades()) this.loadCached()
    },

    /** 成绩缓存缺失/强制时补拉一次(与成绩页共用 cached_grades, 数据结构一致) */
    async _ensureGrades(force) {
      if (!force) {
        const cached = storage.getCached(GRADES_CACHE)
        if (cached && cached.grades && cached.grades.length) return false
      }
      try {
        const r = await api.getGrades('__all__')
        if (r && r.success) {
          storage.setCached(GRADES_CACHE, r)
          return true
        }
      } catch (e) { /* 静默: 没有成绩时进度显示已修 0 */ }
      return false
    },

    /** 本地缓存渲染(打开即显示) */
    loadCached() {
      const cached = storage.getCached(PROGRAMME_CACHE) || {}
      const grades = (storage.getCached(GRADES_CACHE) || {}).grades || []
      const courses = cached.courses || []
      if (!courses.length) {
        this.setData({ loading: false, empty: true, errorMsg: '' })
        return
      }
      const view = creditUtil.computeCredit(courses, grades, storage.getSemester())
      this.setData({
        loading: false,
        empty: false,
        view,
        updated: cached.fetched_at ? this._fmtTime(cached.fetched_at) : ''
      })
    },

    /** 后端拉取(静默或用户触发) */
    async loadFromServer(silent) {
      if (!silent) this.setData({ refreshing: true })
      try {
        const r = await api.getProgramme()
        if (r && r.success && r.courses && r.courses.length) {
          storage.setCached(PROGRAMME_CACHE, {
            t: Date.now(), courses: r.courses, fetched_at: r.fetched_at || 0, count: r.count || r.courses.length
          })
          this.loadCached()
        } else if (!silent) {
          this.setData({ loading: false, empty: true, errorMsg: (r && r.message) || '培养方案获取失败' })
        }
      } catch (e) {
        if (!silent) this.setData({ loading: false, errorMsg: '网络异常，稍后再试' })
      }
      if (!silent) this.setData({ refreshing: false })
    },

    /** 手动刷新: 培养方案 + 成绩都拉一次(成绩页同源) */
    async onRefresh() {
      if (this.data.refreshing) return
      this.setData({ refreshing: true })
      let ok = true
      try {
        await api.refreshProgramme()
      } catch (e) { ok = false }
      try {
        await api.refreshGrades()
      } catch (e) { /* 成绩刷新失败不阻断展示 */ }
      await this.loadFromServer(true)
      await this._ensureGrades(true)
      this.loadCached()
      this.setData({ refreshing: false })
      wx.showToast({ title: ok ? '已更新' : '培养方案刷新失败', icon: ok ? 'success' : 'none' })
    },

    onToggleExpand() {
      this.setData({ expanded: !this.data.expanded })
    },

    onToggleCurrent() {
      this.setData({ expandedCurrent: !this.data.expandedCurrent })
    },

    onToggleUpcoming() {
      this.setData({ expandedUpcoming: !this.data.expandedUpcoming })
    },

    _fmtTime(ts) {
      const d = new Date(ts * 1000)
      const p = n => (n < 10 ? '0' + n : '' + n)
      return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`
    }
  }
})
