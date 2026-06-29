/**
 * 课表页面 — 周视图课程表
 */

const api = require('../../utils/api')
const storage = require('../../utils/storage')
const { getCurrentWeek } = require('../../utils/date')
const config = require('../../utils/config')

Page({
  data: {
    semesters: [],           // 学期列表
    semester: '',            // 当前学期
    currentWeek: 1,          // 当前周
    courses: [],             // 全部课程
    filteredCourses: [],     // 当前周的课程（含单双周过滤）
    loading: false,
    showDetail: false,
    detailCourse: {}
  },

  onLoad() {
    this.loadCachedData()
    this.loadFromServer()
  },

  onShow() {
    // 每次显示时检查登录状态
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
      // 并行加载课程和学期列表
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

        // 计算当前学期对应的周次
        if (res.courses.length > 0) {
          const minWeek = Math.min(...res.courses.map(c => {
            const parts = (c.weeks || '1-18').split('-')
            return parseInt(parts[0]) || 1
          }))
          const maxWeek = Math.max(...res.courses.map(c => {
            const parts = (c.weeks || '1-18').split('-')
            return parseInt(parts[1] || parts[0]) || 18
          }))
          // 简单估算：学期中期
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

      // 更新学期列表
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
      if (c.week_type === 1 && week % 2 === 0) return false  // 单周课，偶数周跳过
      if (c.week_type === 2 && week % 2 === 1) return false  // 双周课，奇数周跳过
      const parts = (c.weeks || '1-18').split('-')
      const start = parseInt(parts[0]) || 1
      const end = parseInt(parts[1] || parts[0]) || 18
      return week >= start && week <= end
    })
    this.setData({ filteredCourses: filtered, currentWeek: week })
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

  /** 点击课程卡片 */
  onCourseTap(e) {
    const course = e.detail
    this.setData({
      showDetail: true,
      detailCourse: course
    })
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
