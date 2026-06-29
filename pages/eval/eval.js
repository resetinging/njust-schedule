/**
 * 教学评价页面
 * 功能：批次列表 → 课程列表 → 评教表单 → 提交
 *       一键评教 → 进度追踪
 */

const api = require('../../utils/api')
const storage = require('../../utils/storage')
const config = require('../../utils/config')

Page({
  data: {
    // 批次列表
    batches: [],
    loading: false,

    // 当前批次的课程
    batchCourses: [],
    currentBatch: null,
    currentBatchHiddenFields: {},

    // 评教表单
    showForm: false,
    formCourseName: '',
    formCourseUrl: '',
    formAction: '',
    formHiddenFields: {},
    indicators: [],
    selections: {},  // {seq: value}

    // 一键评教弹窗
    showBatchDialog: false,
    targetScore: 95,

    // 批量进度
    batchRunning: false,
    batchDone: false,
    batchCurrent: 0,
    batchTotal: 0,
    batchMessage: '',
    batchPercent: 0,
    batchResults: [],
    batchId: ''
  },

  onLoad() {
    this.loadFromServer()
  },

  /** 加载评教批次 */
  async loadFromServer() {
    if (!storage.isLoggedIn()) {
      return
    }
    this.setData({ loading: true })
    try {
      const res = await api.getEvalBatches()
      this.setData({ loading: false })
      if (res.success) {
        this.setData({ batches: res.evaluations || [] })
      }
    } catch (e) {
      this.setData({ loading: false })
      wx.showToast({ title: '加载失败', icon: 'none' })
    }
  },

  /** 刷新 */
  async onRefresh() {
    if (!storage.isLoggedIn()) {
      wx.showToast({ title: '请先在"我的"页面登录', icon: 'none' })
      return
    }
    this.setData({ loading: true })
    try {
      const res = await api.refreshEvaluations()
      this.setData({ loading: false })
      if (res.success) {
        wx.showToast({ title: res.message || '刷新成功', icon: 'success' })
        this.loadFromServer()
      } else {
        wx.showToast({ title: res.message || '刷新失败', icon: 'none' })
      }
    } catch (e) {
      this.setData({ loading: false })
      wx.showToast({ title: '刷新失败', icon: 'none' })
    }
  },

  /** 打开批次 → 加载课程列表 */
  async openBatch(e) {
    const batch = this.data.batches[e.currentTarget.dataset.index]
    if (!batch || !batch.batch) {
      wx.showToast({ title: '批次信息不完整', icon: 'none' })
      return
    }

    wx.showLoading({ title: '加载课程…' })
    try {
      // 构造批次 URL：需要从 evaluations 的 link 字段获取，这里用 batch 作为标识
      const batchUrl = batch.batch  // 后端返回的 URL 路径
      const res = await api.getEvalCourses(batchUrl)
      wx.hideLoading()
      if (res.success) {
        this.setData({
          batchCourses: res.courses || [],
          currentBatch: batch,
          currentBatchHiddenFields: res.hidden_fields || {}
        })
      } else {
        wx.showToast({ title: res.message || '加载失败', icon: 'none' })
      }
    } catch (e) {
      wx.hideLoading()
      wx.showToast({ title: '加载失败', icon: 'none' })
    }
  },

  /** 返回批次列表 */
  backToBatches() {
    this.setData({ batchCourses: [], currentBatch: null, showForm: false })
  },

  /** 返回课程列表 */
  backToCourses() {
    this.setData({ showForm: false, indicators: [], selections: {} })
  },

  /** 打开评教表单 */
  async openEvalForm(e) {
    const course = this.data.batchCourses[e.currentTarget.dataset.index]
    if (!course || !course.eval_url) {
      wx.showToast({ title: '课程信息不完整', icon: 'none' })
      return
    }

    wx.showLoading({ title: '加载表单…' })
    try {
      const res = await api.getEvalForm(course.eval_url)
      wx.hideLoading()
      if (res.success) {
        // 默认选中已勾选的选项
        const selections = {}
        ;(res.indicators || []).forEach(ind => {
          const checked = ind.options.find(o => o.checked)
          if (checked) {
            selections[ind.seq] = checked.value
          }
        })

        this.setData({
          showForm: true,
          formCourseName: res.course_name || course.name,
          formCourseUrl: course.eval_url,
          formAction: res.action || '',
          formHiddenFields: res.hidden_fields || {},
          indicators: res.indicators || [],
          selections
        })
      } else {
        wx.showToast({ title: res.message || '加载失败', icon: 'none' })
      }
    } catch (e) {
      wx.hideLoading()
      wx.showToast({ title: '加载失败', icon: 'none' })
    }
  },

  /** 选择指标选项 */
  selectOption(e) {
    const { seq, value } = e.currentTarget.dataset
    const selections = { ...this.data.selections, [seq]: value }
    // 更新 indicators 中的 checked 状态
    const indicators = this.data.indicators.map(ind => {
      if (ind.seq === seq) {
        return {
          ...ind,
          options: ind.options.map(o => ({
            ...o,
            checked: o.value === value
          }))
        }
      }
      return ind
    })
    this.setData({ selections, indicators })
  },

  /** 构建提交数据 */
  buildFormData(submitType) {
    const data = { ...this.data.formHiddenFields }
    data.issubmit = submitType
    // 写入用户选择的 radio 值
    Object.entries(this.data.selections).forEach(([seq, val]) => {
      // 需要找到对应的 radio name
      const ind = this.data.indicators.find(i => i.seq === seq)
      if (ind) {
        const opt = ind.options.find(o => o.value === val)
        if (opt) {
          data[opt.name] = val
        }
      }
    })
    return data
  },

  /** 保存评教 */
  async onSaveEval() {
    wx.showLoading({ title: '保存中…' })
    try {
      const formData = this.buildFormData('0')
      const res = await api.submitEval(formData, '0', this.data.formAction)
      wx.hideLoading()
      if (res.success) {
        wx.showToast({ title: '已保存', icon: 'success' })
      } else {
        wx.showToast({ title: res.message || '保存失败', icon: 'none' })
      }
    } catch (e) {
      wx.hideLoading()
      wx.showToast({ title: '保存失败', icon: 'none' })
    }
  },

  /** 提交评教 */
  async onSubmitEval() {
    wx.showLoading({ title: '提交中…' })
    try {
      const formData = this.buildFormData('1')
      const res = await api.submitEval(formData, '1', this.data.formAction)
      wx.hideLoading()
      if (res.success) {
        wx.showToast({ title: '评教提交成功！', icon: 'success' })
        // 标记为已提交
        const courses = this.data.batchCourses.map(c => {
          if (c.eval_url === this.data.formCourseUrl) {
            return { ...c, submitted: true }
          }
          return c
        })
        this.setData({ showForm: false, batchCourses: courses })
      } else {
        wx.showToast({ title: res.message || '提交失败', icon: 'none' })
      }
    } catch (e) {
      wx.hideLoading()
      wx.showToast({ title: '提交失败', icon: 'none' })
    }
  },

  // ============================================================
  // 一键评教
  // ============================================================

  showBatchDialog() {
    this.setData({ showBatchDialog: true, targetScore: 95 })
  },

  closeBatchDialog() {
    this.setData({ showBatchDialog: false })
  },

  onScoreChange(e) {
    this.setData({ targetScore: e.detail.value })
  },

  /** 开始批量评教 */
  async startBatchEval() {
    this.setData({ showBatchDialog: false })

    const unsubmitted = this.data.batchCourses.filter(c => !c.submitted)
    if (unsubmitted.length === 0) {
      wx.showToast({ title: '所有课程已提交', icon: 'none' })
      return
    }

    // 构造批次 URL
    const batchUrl = this.data.currentBatch ? this.data.currentBatch.batch : ''

    this.setData({
      batchRunning: true,
      batchDone: false,
      batchCurrent: 0,
      batchTotal: unsubmitted.length,
      batchMessage: '正在提交…',
      batchPercent: 0,
      batchResults: []
    })

    try {
      const res = await api.startBatchEval(
        batchUrl,
        this.data.targetScore,
        '1',
        this.data.currentBatchHiddenFields.action || '',
        this.data.currentBatchHiddenFields
      )

      if (!res.success) {
        this.setData({
          batchRunning: false,
          batchDone: true,
          batchMessage: res.message || '启动失败'
        })
        return
      }

      this.setData({ batchId: res.batch_id })
      this.pollBatchProgress()
    } catch (e) {
      this.setData({ batchRunning: false })
      wx.showToast({ title: '启动失败', icon: 'none' })
    }
  },

  /** 轮询批量评教进度 */
  pollBatchProgress() {
    this._pollCount = 0
    this._pollTimer = setInterval(async () => {
      if (!this.data.batchRunning) {
        clearInterval(this._pollTimer)
        return
      }

      this._pollCount++
      if (this._pollCount > config.MAX_POLL_RETRIES) {
        clearInterval(this._pollTimer)
        this.setData({
          batchRunning: false,
          batchDone: true,
          batchMessage: '轮询超时，请手动检查结果'
        })
        return
      }

      try {
        const res = await api.getBatchProgress(this.data.batchId)
        if (!res.success) {
          clearInterval(this._pollTimer)
          this.setData({
            batchRunning: false,
            batchDone: true,
            batchMessage: res.message || '查询进度失败'
          })
          return
        }

        this.setData({
          batchCurrent: res.current || 0,
          batchTotal: res.total || 0,
          batchMessage: res.message || '',
          batchPercent: res.total > 0
            ? Math.round((res.current || 0) / res.total * 100)
            : 0,
          batchResults: res.results || []
        })

        if (res.done) {
          clearInterval(this._pollTimer)
          this.setData({ batchRunning: false, batchDone: true })

          // 更新课程提交状态
          const results = res.results || []
          const courses = this.data.batchCourses.map(c => {
            const result = results.find(r => r.course === c.name)
            if (result && result.status === 'success') {
              return { ...c, submitted: true }
            }
            return c
          })
          this.setData({ batchCourses: courses })
        }
      } catch (e) {
        clearInterval(this._pollTimer)
        this.setData({ batchRunning: false })
        wx.showToast({ title: '查询进度失败', icon: 'none' })
      }
    }, config.POLL_INTERVAL)
  },

  closeBatchProgress() {
    if (this._pollTimer) {
      clearInterval(this._pollTimer)
      this._pollTimer = null
    }
    this.setData({
      batchDone: false,
      batchRunning: false,
      batchResults: []
    })
  },

  onUnload() {
    if (this._pollTimer) {
      clearInterval(this._pollTimer)
      this._pollTimer = null
    }
  },

  onPullDownRefresh() {
    this.onRefresh()
    wx.stopPullDownRefresh()
  }
})
