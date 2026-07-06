/**
 * 课表页面 — 周视图课程表 / 列表视图
 * 参考桌面端 static/js/schedule.js 的显示逻辑
 */

const api = require('../../utils/api')
const storage = require('../../utils/storage')
const { getCurrentWeek, isWeekInRange, getWeekBounds } = require('../../utils/date')
const config = require('../../utils/config')

Page({
  data: {
    semesters: [],           // 学期列表
    semester: '',            // 当前学期
    currentWeek: 1,          // 当前周
    courses: [],             // 全部课程
    filteredCourses: [],     // 当前周的课程（含单双周过滤）
    listDayGroups: [],       // 列表视图分组数据
    viewMode: 'grid',        // 'grid' | 'list'
    loading: false,
    showDetail: false,
    detailCourse: {}
  },

  onLoad() {
    this.loadCachedData()
    this.loadFromServer()
  },

  onShow() {
    const app = getApp()
    if (app.globalData.semester) {
      this.setData({ semester: app.globalData.semester })
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

        // 估算当前学期所处周次
        if (res.courses.length > 0) {
          const minWeek = Math.min(...res.courses.map(c => getWeekBounds(c.weeks).min))
          const maxWeek = Math.max(...res.courses.map(c => getWeekBounds(c.weeks).max))
          const midWeek = Math.floor((minWeek + maxWeek) / 2)
          this.setData({ currentWeek: Math.max(1, midWeek) })
          this.filterByWeek(midWeek)
        }
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

  /** 按周次过滤课程 */
  filterByWeek(week) {
    const filtered = this.data.courses.filter(c => {
      if (c.week_type === 1 && week % 2 === 0) return false
      if (c.week_type === 2 && week % 2 === 1) return false
      return isWeekInRange(week, c.weeks)
    })

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
