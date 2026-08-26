/**
 * 课表页面 — 周视图课程表 / 列表视图
 * 参考桌面端 static/js/schedule.js 的显示逻辑
 */

const api = require('../../utils/api')
const storage = require('../../utils/storage')
const { calcCurrentWeek, calcTodayDay, isWeekInRange } = require('../../utils/date')

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

    searchText: '',          // 课程/教师搜索
    weekPickerRange: [],     // 周次跳转选择器 (1-20)
    studentName: '',         // 学生姓名(顶部信息卡)
    studentId: ''            // 学号(顶部信息卡)
  },

  onLoad() {
    this.loadCachedData()
    this.loadFromServer()
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

  /** 获取校历设置并定位当前周 */
  async loadFirstWeekDate() {
    try {
      const res = await api.getStatus()
      if (res && res.first_week_date) {
        const firstWeekDate = res.first_week_date
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
      } else {
        const todayDay = calcTodayDay()
        this.setData({ todayDay })
        // 未设置校历日期时与桌面端一致默认第 1 周,提示用户去设置
        if (!this._weekHintShown) {
          this._weekHintShown = true
          wx.showToast({
            title: '未设置第一周日期,默认第1周;可在「我的」页设置以自动定位本周',
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

  /** 从缓存加载 */
  loadCachedData() {
    const courses = storage.getCached('cached_courses')
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

  /** 从服务器加载 */
  async loadFromServer() {
    this.setData({ loading: true })
    try {
      const [res, semRes] = await Promise.all([
        api.getCourses(),
        api.getSemesters()
      ])
      if (res.success && res.courses) {
        this.setData({
          courses: res.courses,
          semester: res.semester || this.data.semester,
          loading: false
        })
        storage.setCached('cached_courses', res.courses)
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

  /** 按周次过滤课程（含搜索关键词） */
  filterByWeek(week) {
    const kw = (this.data.searchText || '').trim().toLowerCase()
    let filtered = this.data.courses.filter(c => {
      if (c.week_type === 1 && week % 2 === 0) return false
      if (c.week_type === 2 && week % 2 === 1) return false
      return isWeekInRange(week, c.weeks)
    })

    if (kw) {
      filtered = filtered.filter(c =>
        (c.name || '').toLowerCase().includes(kw) ||
        (c.teacher || '').toLowerCase().includes(kw)
      )
    }

    // 构建列表视图分组（按天分组 + 去重）
    const listDayGroups = this._buildListGroups(filtered)

    this.setData({ filteredCourses: filtered, currentWeek: week, listDayGroups })
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

  /** 切换学期 */
  async onSemesterChange(e) {
    const idx = e.detail.value
    const semester = this.data.semesters[idx]
    if (semester && semester !== this.data.semester) {
      try {
        await api.setSemester(semester)
        this.setData({ semester })
        this.loadFromServer()
      } catch (e) {
        wx.showToast({ title: '切换学期失败', icon: 'none' })
      }
    }
  },

  /** 上一周 */
  prevWeek() {
    const w = Math.max(1, this.data.currentWeek - 1)
    this.filterByWeek(w)
  },

  /** 下一周 */
  nextWeek() {
    const w = Math.min(20, this.data.currentWeek + 1)
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
      this.setData({
        showDetail: true,
        detailCourse: course
      })
    }
  },

  /** 关闭课程详情 */
  closeDetail() {
    this.setData({ showDetail: false })
  },

  /** 下拉刷新 */
  onPullDownRefresh() {
    this.onRefresh()
    wx.stopPullDownRefresh()
  }
})
