/**
 * 成绩查询页面 — GPA 汇总 + 各学期成绩 + 四六级
 * 方案 A: GPA/折算等业务计算全部在前端完成
 * 性能: 成绩列表分页渲染（每次 50 条，"加载更多"追加）
 */

const api = require('../../utils/api')
const storage = require('../../utils/storage')
const gpaUtil = require('../../utils/gpa')

// WXML 不支持函数调用，需要在 JS 中预计算
function _scoreClass(score) {
  const s = parseFloat(score)
  if (isNaN(s)) return ''
  if (s >= 90) return 'score-high'
  if (s >= 60) return 'score-mid'
  return 'score-low'
}

function _gpaClass(gpa) {
  if (gpa >= 3.5) return 'score-high'
  if (gpa >= 2.0) return 'score-mid'
  return 'score-low'
}

function _fixed(val, digits) {
  const n = parseFloat(val)
  return isNaN(n) ? '-' : n.toFixed(digits || 2)
}

function _creditsOf(grades) {
  return _fixed(grades
    .filter(g => gpaUtil.isGpaCourse(g.course_nature))
    .reduce((sum, g) => sum + (parseFloat(g.credit) || 0), 0), 1)
}

const PAGE_SIZE = 50

Page({
  data: {
    // 状态
    loading: true,
    refreshing: false,
    empty: false,
    errorMsg: '',

    // 数据
    gpaMode: '',        // '' | 'baoyan'
    selectedSemester: '__all__',
    availableSemesters: [],
    grades: [],          // 全部成绩（前端本地计算用）
    displayGrades: [],   // 分页显示的切片
    semesterGpas: [],    // 各学期绩点汇总（前端计算）

    // 当前视图的绩点汇总
    gpa: 0,
    gpaAll: 0,
    gpaBaoyan: 0,
    totalCredits: 0,

    // 全部学期汇总
    allGpa: 0,
    allGpaAll: 0,
    allGpaBaoyan: 0,
    allCredits: 0,
    allCount: 0,
    allCountTotal: 0,

    // 预计算的显示值（WXML 不能调用函数）
    bigGpaFixed: '-',
    bigGpaClass: '',
    bigGpaLabel: '计内 GPA',
    currentGpaFixed: '-',
    currentGpaClass: '',

    // 四六级
    cetScores: [],
    showCet: false,

    // 预计算 picker 用的学期数组（WXML 不能拼接数组）
    semesterPickerRange: ['全部学期']
  },

  onLoad() {
    this.loadGrades()
  },

  onShow() {
    // 从缓存读取上次的 gpaMode
    const savedMode = storage.get('gpa_mode', '')
    if (savedMode !== this.data.gpaMode) {
      this.setData({ gpaMode: savedMode })
    }
  },

  // ============================================================
  // 数据加载
  // ============================================================

  async loadGrades() {
    this.setData({ loading: true, errorMsg: '' })

    try {
      const res = await api.getGrades(this.data.selectedSemester, this.data.gpaMode)

      if (!res.success) {
        this.setData({
          loading: false,
          empty: true,
          errorMsg: res.message || '获取成绩失败'
        })
        return
      }

      // 保研模式需要四六级成绩参与计算
      let cetScores = this.data.cetScores || []
      if (this.data.gpaMode === 'baoyan' && cetScores.length === 0) {
        cetScores = await this.loadCetScores()
      }

      const all = res.grades || []
      const semGpaList = gpaUtil.calcSemesterGpas(all).map(info => ({
        semester: info.semester,
        gpa: info.gpa,
        credits: info.credits,
        count: info.count,
        _gpaFixed: _fixed(info.gpa),
        _gpaClass: _gpaClass(info.gpa)
      }))

      // 当前视图的成绩子集（前端过滤）
      let viewGrades = all
      if (this.data.selectedSemester !== '__all__') {
        viewGrades = all.filter(
          g => (g.academic_year || '') + '-' + (g.semester || '') === this.data.selectedSemester
        )
      }

      // 前端计算全部汇总
      const isBaoyan = this.data.gpaMode === 'baoyan'
      const gpa = gpaUtil.calcGpa(viewGrades, true)
      const gpaAll = gpaUtil.calcGpa(viewGrades, false)
      const gpaBaoyan = gpaUtil.calcGpaBaoyan(viewGrades, cetScores, true)
      const allGpa = gpaUtil.calcGpa(all, true)
      const allGpaAll = gpaUtil.calcGpa(all, false)
      const allGpaBaoyan = gpaUtil.calcGpaBaoyan(all, cetScores, true)
      const allCredits = _creditsOf(all)
      const allCount = all.filter(g => gpaUtil.isGpaCourse(g.course_nature)).length

      const bigGpa = isBaoyan ? allGpaBaoyan : allGpa
      const currentGpa = isBaoyan ? gpaBaoyan : gpa

      // 为成绩列表预计算 CSS 类和格式化值（分页切片）
      const grades = viewGrades.map(g => ({
        ...g,
        _scoreClass: _scoreClass(g.score),
        _scoreStr: g.score != null ? String(g.score) : '-',
        _gpStr: g.grade_point != null ? _fixed(g.grade_point, 1) : '-'
      }))

      this.setData({
        loading: false,
        empty: all.length === 0,
        grades: grades,
        displayGrades: grades.slice(0, PAGE_SIZE),
        semesterGpas: semGpaList,
        availableSemesters: res.available_semesters || [],
        gpa: gpa,
        gpaAll: gpaAll,
        gpaBaoyan: gpaBaoyan,
        totalCredits: _creditsOf(viewGrades),
        allGpa: allGpa,
        allGpaAll: allGpaAll,
        allGpaBaoyan: allGpaBaoyan,
        allCredits: allCredits,
        allCount: allCount,
        allCountTotal: all.length,
        // 预计算 picker range
        semesterPickerRange: ['全部学期'].concat(res.available_semesters || []),
        // 预计算显示值
        bigGpaFixed: _fixed(bigGpa),
        bigGpaClass: _gpaClass(bigGpa),
        bigGpaLabel: isBaoyan ? '保研绩点' : '计内 GPA',
        currentGpaFixed: _fixed(currentGpa),
        currentGpaClass: _gpaClass(currentGpa)
      })

      // 缓存
      storage.setCached('cached_grades', res)
    } catch (e) {
      this.setData({
        loading: false,
        empty: true,
        errorMsg: '网络请求失败'
      })
    }
  },

  /** 加载更多成绩（分页） */
  loadMoreGrades() {
    const { grades, displayGrades } = this.data
    if (displayGrades.length >= grades.length) return
    this.setData({
      displayGrades: grades.slice(0, displayGrades.length + PAGE_SIZE)
    })
  },

  /** 刷新成绩 */
  async onRefreshGrades() {
    this.setData({ refreshing: true })
    try {
      const res = await api.refreshGrades()
      if (res.success) {
        wx.showToast({ title: res.message || '刷新成功', icon: 'success' })
        await this.loadGrades()
      } else {
        wx.showToast({ title: res.message || '刷新失败', icon: 'none' })
      }
    } catch (e) {
      wx.showToast({ title: '刷新失败', icon: 'none' })
    } finally {
      this.setData({ refreshing: false })
    }
  },

  /** 刷新四六级 */
  async onRefreshCet() {
    wx.showLoading({ title: '获取中…' })
    try {
      const res = await api.refreshCet()
      wx.hideLoading()
      if (res.success) {
        wx.showToast({ title: res.message || '刷新成功', icon: 'success' })
        await this.loadCetScores()
        await this.loadGrades()
      } else {
        wx.showToast({ title: res.message || '刷新失败', icon: 'none' })
      }
    } catch (e) {
      wx.hideLoading()
      wx.showToast({ title: '刷新失败', icon: 'none' })
    }
  },

  /** 加载四六级原始成绩,返回 scores 数组 */
  async loadCetScores() {
    try {
      const res = await api.getCetScores()
      if (res.success) {
        const scores = res.scores || []
        this.setData({
          cetScores: scores,
          showCet: scores.length > 0
        })
        storage.setCached('cached_cet_scores', res)
        return scores
      }
    } catch (e) {
      // ignore
    }
    return []
  },

  // ============================================================
  // 交互
  // ============================================================

  /** 切换学期 */
  onSemesterChange(e) {
    const idx = e.detail.value
    const range = this.data.semesterPickerRange
    const selected = range[idx] || '__all__'
    this.setData({ selectedSemester: selected === '全部学期' ? '__all__' : selected })
    this.loadGrades()
  },

  /** 点击学期绩点卡片 → 切换到该学期 */
  onSemGpaTap(e) {
    const sem = e.currentTarget.dataset.sem
    if (!sem) return
    this.setData({ selectedSemester: sem })
    this.loadGrades()
  },

  /** 切换 GPA 模式 */
  onGpaModeChange(e) {
    const mode = e.currentTarget.dataset.mode
    this.setData({ gpaMode: mode })
    storage.set('gpa_mode', mode)
    this.loadGrades()
    // 如果切换到保研模式，同步加载四六级
    if (mode === 'baoyan') {
      this.loadCetScores()
    }
  },

  /** 展开/收起四六级 */
  onShowCet() {
    this.setData({ showCet: !this.data.showCet })
    if (this.data.showCet && this.data.cetScores.length === 0) {
      this.loadCetScores()
    }
  }
})
