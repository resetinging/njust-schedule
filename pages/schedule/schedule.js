/**
 * 课表页面 — 周视图课程表 / 列表视图
 * 参考桌面端 static/js/schedule.js 的显示逻辑
 */

const api = require('../../utils/api')
const storage = require('../../utils/storage')
const { calcCurrentWeek, calcTodayDay, isWeekInRange, getDateLabel, getDefaultFirstWeekDate } = require('../../utils/date')

Page({
  data: {
    semesters: [],           // 学期列表
    semester: '',            // 当前学期
    currentWeek: 1,          // 当前显示的周
    actualWeek: 1,           // 实际教学周（根据校历）
    todayDay: 0,             // 今天星期几 (1-7)
    courses: [],             // 全部课程
    filteredCourses: [],     // 当前周的课程（含单双周过滤）
    listDayGroups: [],       // 列表视图分组数据
    viewMode: 'grid',        // 'grid' | 'list'
    loading: false,
    showDetail: false,
    detailCourse: {},
    firstWeekDate: '',       // 学期第一周周一日期
    weekRange: '',           // 当前周日期范围(如 "9/1-9/7")

    searchText: '',          // 课程/教师搜索
    weekPickerRange: [],     // 周次跳转选择器 (1-20)
    studentName: '',         // 学生姓名(顶部信息卡)
    studentId: ''            // 学号(顶部信息卡)
  },

  onLoad() {
    // 缓存优先：打开页面只渲染本地缓存，后端请求仅发生在
    // 下拉刷新 / 学期切换等主动操作时
    this.loadCachedData()
    this.loadFirstWeekDate()
    this.setData({
      weekPickerRange: Array.from({ length: 20 }, (_, i) => String(i + 1))
    })
    this._syncUser()
  },

  onShow() {
    const app = getApp()
    if (app.globalData.semester) {
      this.setData({ semester: app.globalData.semester })
    }
    this._syncUser()
    // 从「我的」页设置第一周日期后回到课表页,自动刷新定位本周
    this.loadFirstWeekDate()
  },

  /** 同步学生姓名/学号到顶部信息卡 */
  _syncUser() {
    this.setData({
      studentName: storage.getStudentName(),
      studentId: storage.getStudentId()
    })
  },

  /** 获取校历设置并定位当前周（未设置时使用默认: 本周周一为第一周） */
  async loadFirstWeekDate() {
    try {
      const res = await api.getStatus()
      const firstWeekDate = (res && res.first_week_date) || getDefaultFirstWeekDate()
      const actualWeek = calcCurrentWeek(firstWeekDate)
      const todayDay = calcTodayDay()
      this.setData({
        firstWeekDate,
        actualWeek,
        todayDay,
        currentWeek: actualWeek
      })
      // 如果已加载课程，重新过滤
      if (this.data.courses.length > 0) {
        this.filterByWeek(actualWeek)
      }
      // 首次未设置时提示一次
      if (!res || !res.first_week_date) {
        if (!this._weekHintShown) {
          this._weekHintShown = true
          wx.showToast({
            title: '未设置第一周日期,已默认本周为第 1 周;可在「我的」页设置',
            icon: 'none',
            duration: 3500
          })
        }
      }
    } catch (e) {
      const todayDay = calcTodayDay()
      this.setData({ todayDay })
    }
  },

  /** 课表缓存键按学期隔离(切换学期后不显示上一学期缓存) */
  _coursesCacheKey() {
    return 'cached_courses_' + (storage.getSemester() || 'default')
  },

  /** 从缓存加载 */
  loadCachedData() {
    const courses = storage.getCached(this._coursesCacheKey())
    const semester = storage.getSemester()
    const semesters = storage.getCached('semester_list') || []

    if (courses) {
      this.setData({ courses, semester: semester || '' })
      this.filterByWeek(this.data.currentWeek)
    }
    if (semesters.length) {
      this.setData({ semesters })
    }
  },

  /** 从服务器加载（semester 参数可显式指定, 不依赖 storage 时序） */
  async loadFromServer(semester) {
    this.setData({ loading: true })
    try {
      const [res, semRes] = await Promise.all([
        api.getCourses(semester),   // 切换学期时显式传参, 确保请求目标学期
        api.getSemesters()
      ])
      if (res.success && res.courses) {
        this.setData({
          courses: res.courses,
          semester: res.semester || this.data.semester,
          loading: false
        })
        // 缓存键带学期: 按实际返回的学期写缓存
        const cacheSem = res.semester || storage.getSemester() || 'default'
        storage.setCached('cached_courses_' + cacheSem, res.courses)
        if (res.semester) storage.setSemester(res.semester)
        this.filterByWeek(this.data.currentWeek)
      } else {
        this.setData({ loading: false })
        if (!res.success && res.message) {
          wx.showToast({ title: res.message, icon: 'none' })
        }
      }

      if (semRes.success && semRes.semesters) {
        this.setData({ semesters: semRes.semesters })
        storage.setCached('semester_list', semRes.semesters)
      }
    } catch (e) {
      this.setData({ loading: false })
      wx.showToast({ title: '加载失败', icon: 'none' })
    }
  },

  /** 按周次过滤课程（含搜索关键词）；week 非法时兜底为 1，避免显示 null 周 */
  filterByWeek(week) {
    const w = (typeof week === 'number' && !isNaN(week) && week >= 1 && week <= 20) ? week : 1
    const kw = (this.data.searchText || '').trim().toLowerCase()
    // 当前周日期范围
    let weekRange = ''
    if (this.data.firstWeekDate) {
      const s = getDateLabel(this.data.firstWeekDate, w, 1)
      const e = getDateLabel(this.data.firstWeekDate, w, 7)
      if (s && e) weekRange = `${s} - ${e}`
    }
    let filtered = this.data.courses.filter(c => {
      if (c.week_type === 1 && w % 2 === 0) return false
      if (c.week_type === 2 && w % 2 === 1) return false
      return isWeekInRange(w, c.weeks)
    })

    if (kw) {
      filtered = filtered.filter(c =>
        (c.name || '').toLowerCase().includes(kw) ||
        (c.teacher || '').toLowerCase().includes(kw)
      )
    }

    // 构建列表视图分组（按天分组 + 去重）
    const listDayGroups = this._buildListGroups(filtered)

    this.setData({ filteredCourses: filtered, currentWeek: w, listDayGroups, weekRange })
  },

  /**
   * 构建列表视图数据：按天分组，同一课程多节次去重
   * 参考桌面端 renderListView() 的去重逻辑
   */
  _buildListGroups(courses) {
    const DAY_NAMES = ['', '周一', '周二', '周三', '周四', '周五', '周六', '周日']
    const groups = []

    for (let d = 1; d <= 7; d++) {
      const dayCourses = courses.filter(c => (c.day || c.day_of_week) === d)
      if (dayCourses.length === 0) continue

      // 去重：同一课程名+起始节次保留一条
      const seen = new Set()
      const unique = []
      for (const c of dayCourses) {
        const key = `${c.name}-${c.start || c.start_period}-${c.end || c.end_period}`
        if (!seen.has(key)) {
          seen.add(key)
          unique.push(c)
        }
      }
      unique.sort((a, b) => (a.start || a.start_period) - (b.start || b.start_period))

      groups.push({ day: d, dayName: DAY_NAMES[d], courses: unique })
    }

    return groups
  },

  /** 切换视图模式 */
  switchView(e) {
    const mode = e.currentTarget.dataset.mode
    this.setData({ viewMode: mode })
  },

  /** 搜索课程/教师 */
  onSearchInput(e) {
    this.setData({ searchText: e.detail.value })
    this.filterByWeek(this.data.currentWeek)
  },

  /** 清空搜索 */
  onClearSearch() {
    this.setData({ searchText: '' })
    this.filterByWeek(this.data.currentWeek)
  },

  /** 周次跳转 */
  onJumpWeek(e) {
    const idx = e.detail.value
    const week = parseInt(this.data.weekPickerRange[idx]) || 1
    this.filterByWeek(week)
  },

  /** 切换学期（显式传学期请求数据, 保证课表随学期切换） */
  async onSemesterChange(e) {
    const idx = e.detail.value
    const semester = this.data.semesters[idx]
    if (semester && semester !== this.data.semester) {
      try {
        const res = await api.setSemester(semester)
        if (res && res.success) {
          this.setData({ semester })
          this.loadFromServer(semester)   // 显式传参
        } else {
          wx.showToast({ title: (res && res.message) || '切换学期失败', icon: 'none' })
        }
      } catch (e) {
        wx.showToast({ title: '切换学期失败', icon: 'none' })
      }
    }
  },

  /** 上一周 */
  prevWeek() {
    const w = Math.max(1, (this.data.currentWeek || 1) - 1)
    this.filterByWeek(w)
  },

  /** 下一周 */
  nextWeek() {
    const w = Math.min(20, (this.data.currentWeek || 1) + 1)
    this.filterByWeek(w)
  },

  /** 下拉刷新 */
  async onRefresh() {
    if (!storage.isLoggedIn()) {
      wx.showToast({ title: '请先在"我的"页面登录', icon: 'none' })
      return
    }
    this.setData({ loading: true })
    try {
      const res = await api.refreshSchedule()
      this.setData({ loading: false })
      if (res.success) {
        wx.showToast({ title: `已刷新 ${res.count || 0} 门课程`, icon: 'success' })
        this.loadFromServer()
      } else {
        wx.showToast({ title: res.message || '刷新失败', icon: 'none' })
      }
    } catch (e) {
      this.setData({ loading: false })
      wx.showToast({ title: '刷新失败', icon: 'none' })
    }
  },

  /** 点击课程卡片 — 打开详情弹窗 */
  onCourseTap(e) {
    // 网格视图通过组件 triggerEvent 传 e.detail
    // 列表视图通过 data-course 传 e.currentTarget.dataset.course
    const course = e.detail || e.currentTarget.dataset.course
    if (course) {
      const DAY = ['', '周一', '周二', '周三', '周四', '周五', '周六', '周日']
      const d = course.day || course.day_of_week || 0
      const s = course.start || course.start_period
      const en = course.end || course.end_period
      const weeksRaw = String(course.weeks || '1-18')
      const enriched = {
        ...course,
        _dayName: DAY[d] || '',
        _timeText: (s && en) ? `第${s}~${en}节` : '',
        _weeksText: weeksRaw.includes('周') ? weeksRaw : `第${weeksRaw}周`
      }
      this.setData({
        showDetail: true,
        detailCourse: enriched
      })
    }
  },

  /** 关闭课程详情 */
  closeDetail() {
    this.setData({ showDetail: false })
  },

  /** 下拉刷新（等待完成后再收起下拉动画） */
  async onPullDownRefresh() {
    try {
      await this.onRefresh()
    } finally {
      wx.stopPullDownRefresh()
    }
  }
})
