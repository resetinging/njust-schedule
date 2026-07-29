/**
 * 成绩查询页面 — GPA 汇总 + 各学期成绩 + 四六级
 */

const api = require('../../utils/api')
const storage = require('../../utils/storage')

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
    grades: [],
    semesterGpas: [],   // 各学期绩点汇总

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

      // 转换 semester_gpas 对象为数组，并预计算显示值
      const semGpaList = []
      if (res.semester_gpas) {
        for (const [sem, info] of Object.entries(res.semester_gpas)) {
          const gpa = info.gpa || 0
          semGpaList.push({
            semester: sem,
            gpa: gpa,
            credits: info.credits || 0,
            count: info.count || 0,
            _gpaFixed: _fixed(gpa),
            _gpaClass: _gpaClass(gpa)
          })
        }
      }

      // 为成绩列表预计算 CSS 类和格式化值
      const grades = (res.grades || []).map(g => ({
        ...g,
        _scoreClass: _scoreClass(g.score),
        _scoreStr: g.score != null ? String(g.score) : '-',
        _gpStr: g.grade_point != null ? _fixed(g.grade_point, 1) : '-'
      }))

      // 根据模式计算大卡片显示值
      const isBaoyan = this.data.gpaMode === 'baoyan'
      const bigGpa = isBaoyan ? (res.all_gpa_baoyan || 0) : (res.all_gpa || 0)
      const currentGpa = isBaoyan ? (res.gpa_baoyan || 0) : (res.gpa || 0)

      this.setData({
        loading: false,
        empty: res.count === 0,
        grades: grades,
        semesterGpas: semGpaList,
        availableSemesters: res.available_semesters || [],
        gpa: res.gpa || 0,
        gpaAll: res.gpa_all || 0,
        gpaBaoyan: res.gpa_baoyan || 0,
        totalCredits: res.total_credits || 0,
        allGpa: res.all_gpa || 0,
        allGpaAll: res.all_gpa_all || 0,
        allGpaBaoyan: res.all_gpa_baoyan || 0,
        allCredits: res.all_credits || 0,
        allCount: res.all_count || 0,
        allCountTotal: res.all_count_total || 0,
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
      } else {
        wx.showToast({ title: res.message || '刷新失败', icon: 'none' })
      }
    } catch (e) {
      wx.hideLoading()
      wx.showToast({ title: '刷新失败', icon: 'none' })
    }
  },

  async loadCetScores() {
    try {
      const res = await api.getCetScores()
      if (res.success) {
        this.setData({
          cetScores: res.scores || [],
          showCet: (res.scores || []).length > 0
        })
        storage.setCached('cached_cet_scores', res)
      }
    } catch (e) {
      // ignore
    }
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
