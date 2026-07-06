/**
 * 教学评价页面
 * 参考桌面端 static/js/evaluations.js
 * 功能：批次列表 → 课程列表 → 评教表单（含自动填写）→ 提交
 *       一键评教 → 进度追踪 / 查看已提交评分
 */

const api = require('../../utils/api')
const storage = require('../../utils/storage')
const config = require('../../utils/config')
const { timeUntilDeadline } = require('../../utils/date')

Page({
  data: {
    // 批次列表
    batches: [],
    countdowns: [],        // 顶部倒计时卡片
    loading: false,

    // 当前批次的课程
    batchCourses: [],
    currentBatch: null,
    currentBatchHiddenFields: {},

    // 评教表单
    showForm: false,
    formReadonly: false,   // 已提交查看评分模式
    formCourseName: '',
    formCourseUrl: '',
    formAction: '',
    formHiddenFields: {},
    indicators: [],
    selections: {},        // {seq: value}
    liveTotal: 0,          // 当前总分
    maxTotal: 0,           // 满分
    autoFillScore: '',     // 自动填写目标分

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
    if (!storage.isLoggedIn()) return
    this.setData({ loading: true })
    try {
      const res = await api.getEvalBatches()
      this.setData({ loading: false })
      if (res.success) {
        const batches = res.evaluations || []
        this.setData({ batches })
        this._processBatches(batches)
      }
    } catch (e) {
      this.setData({ loading: false })
      wx.showToast({ title: '加载失败', icon: 'none' })
    }
  },

  /** 处理批次数据：倒计时 + 每批次紧迫度 */
  _processBatches(batches) {
    // 给每个批次附加紧迫度信息
    const enriched = batches.map(b => {
      const info = timeUntilDeadline(b.end_date)
      return {
        ...b,
        _urgency: b.is_done ? '' : info.cls,
        _deadlineText: b.is_done ? '已完成' : info.text
      }
    })

    const undone = enriched
      .filter(b => !b.is_done && b.end_date)
      .sort((a, b) => (a.end_date || '').localeCompare(b.end_date || ''))

    let countdowns = []
    if (undone.length === 0) {
      const allDone = enriched.filter(b => b.is_done)
      if (allDone.length > 0) {
        countdowns = [{
          bigNum: '✓', bigLabel: '全部已完成',
          course_name: '本学期评价已全部完成', cardClass: ''
        }]
      }
    } else {
      countdowns = undone.slice(0, 3).map(b => {
        const totalHours = (() => {
          const end = this._parseDate(b.end_date)
          if (!end) return 0
          end.setHours(23, 59, 59, 0)
          return (end - new Date()) / (1000 * 60 * 60)
        })()
        let bigNum, bigLabel
        if (totalHours < 0) { bigNum = '!'; bigLabel = '已截止' }
        else if (totalHours < 24) { bigNum = Math.floor(totalHours) + 'h'; bigLabel = '小时后截止' }
        else { bigNum = Math.floor(totalHours / 24); bigLabel = b._deadlineText }

        return {
          bigNum, bigLabel,
          course_name: b.batch || b.category,
          cardClass: b._urgency === 'urgent' ? 'urgent' : (b._urgency === 'warning' ? 'warning' : '')
        }
      })
    }

    this.setData({ batches: enriched, countdowns })
  },

  _parseDate(str) {
    if (!str) return null
    const parts = str.split('-')
    if (parts.length !== 3) return null
    return new Date(parseInt(parts[0]), parseInt(parts[1]) - 1, parseInt(parts[2]))
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
    if (!batch || !(batch.items && batch.items.length > 0)) {
      wx.showToast({ title: '批次信息不完整', icon: 'none' })
      return
    }

    wx.showLoading({ title: '加载课程…' })
    try {
      const batchUrl = batch.items[0].url
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

  /** 返回课程列表（保留数据不重新请求） */
  backToCourses() {
    this.setData({ showForm: false, formReadonly: false, indicators: [], selections: {}, liveTotal: 0, maxTotal: 0 })
  },

  /** 打开评教表单 */
  async openEvalForm(e) {
    const course = this.data.batchCourses[e.currentTarget.dataset.index]
    if (!course || !course.eval_url) {
      wx.showToast({ title: '课程信息不完整', icon: 'none' })
      return
    }

    // 已提交的课程 → 查看评分（只读模式）
    const readonly = !!course.submitted

    wx.showLoading({ title: readonly ? '加载评分…' : '加载表单…' })
    try {
      const res = await api.getEvalForm(course.eval_url)
      wx.hideLoading()
      if (res.success) {
        const selections = {}
        let total = 0, max = 0
        ;(res.indicators || []).forEach(ind => {
          const checked = ind.options.find(o => o.checked)
          if (checked) {
            selections[ind.seq] = checked.value
            const score = this._optionScore(checked)
            total += score
          }
          max += this._maxOptionScore(ind.options)
        })

        this.setData({
          showForm: true,
          formReadonly: readonly,
          formCourseName: res.course_name || course.name,
          formCourseUrl: course.eval_url,
          formAction: res.action || '',
          formHiddenFields: res.hidden_fields || {},
          indicators: res.indicators || [],
          selections,
          liveTotal: total,
          maxTotal: max,
          autoFillScore: ''
        })
      } else {
        wx.showToast({ title: res.message || '加载失败', icon: 'none' })
      }
    } catch (e) {
      wx.hideLoading()
      wx.showToast({ title: '加载失败', icon: 'none' })
    }
  },

  /** 查看已提交评分 */
  async viewScores(e) {
    const course = this.data.batchCourses[e.currentTarget.dataset.index]
    if (!course || !course.eval_url) return
    // 复用 openEvalForm，submitted 状态会触发只读模式
    await this.openEvalForm(e)
  },

  /** 获取选项的分数（从 value 或 label 中提取数字） */
  _optionScore(opt) {
    if (opt.score) return parseFloat(opt.score) || 0
    const num = parseFloat(opt.value)
    return isNaN(num) ? 0 : num
  },

  /** 获取一组选项中的最高分 */
  _maxOptionScore(opts) {
    if (!opts || opts.length === 0) return 0
    return Math.max(...opts.map(o => this._optionScore(o)))
  },

  /** 选择指标选项 */
  selectOption(e) {
    const { seq, value } = e.currentTarget.dataset
    const selections = { ...this.data.selections, [seq]: value }

    // 实时计算总分
    let total = 0
    const indicators = this.data.indicators.map(ind => {
      if (ind.seq === seq) {
        const updated = {
          ...ind,
          options: ind.options.map(o => {
            if (o.value === value) {
              total += this._optionScore(o)
              return { ...o, checked: true }
            }
            return { ...o, checked: false }
          })
        }
        return updated
      } else {
        const checkedOpt = ind.options.find(o => o.checked)
        if (checkedOpt) total += this._optionScore(checkedOpt)
        return ind
      }
    })

    // 更新 indicators 以反映选中状态
    indicators.forEach(ind => {
      if (ind.seq !== seq) {
        const val = selections[ind.seq]
        if (val) {
          total += this._optionScore(ind.options.find(o => o.value === val) || {})
        }
      }
    })

    this.setData({ selections, indicators, liveTotal: total })
  },

  /** 自动填写输入框值变化 */
  onAutoFillScoreInput(e) {
    this.setData({ autoFillScore: e.detail.value })
  },

  /** 自动填写评教（参考桌面端 autoFillEval） */
  async onAutoFill() {
    const score = parseFloat(this.data.autoFillScore)
    if (isNaN(score) || score < 0 || score > 100) {
      wx.showToast({ title: '请输入0-100的目标分数', icon: 'none' })
      return
    }

    const formData = this.buildFormData('0')
    try {
      const res = await api.getAutoFillSuggestion(formData, score)
      if (res.success && res.selections) {
        const selections = { ...res.selections }
        let total = 0
        const indicators = this.data.indicators.map(ind => {
          const val = selections[ind.seq]
          if (val) {
            const opt = ind.options.find(o => o.value === val)
            if (opt) total += this._optionScore(opt)
            return {
              ...ind,
              options: ind.options.map(o => ({ ...o, checked: o.value === val }))
            }
          }
          return ind
        })
        this.setData({ selections, indicators, liveTotal: total })
      }
      // 服务端不支持自动填写时，本地按高分策略自动选
      if (!res.success || !res.selections) {
        this._localAutoFill(score)
      }
    } catch (e) {
      // 降级为本地自动填写
      this._localAutoFill(score)
    }
  },

  /** 本地自动填写：每个指标选最接近目标比例的选项 */
  _localAutoFill(targetScore) {
    const selections = {}
    let total = 0
    const indicators = this.data.indicators.map(ind => {
      const opts = ind.options || []
      if (opts.length === 0) return ind
      // 选分数最接近 targetScore/max 比例的选项
      const targetRatio = targetScore / Math.max(this.data.maxTotal, 1)
      let best = opts[0], bestDiff = Infinity
      for (const o of opts) {
        const s = this._optionScore(o)
        const ratio = s / Math.max(this._maxOptionScore(opts), 1)
        const diff = Math.abs(ratio - targetRatio)
        if (diff < bestDiff) { bestDiff = diff; best = o }
      }
      selections[ind.seq] = best.value
      total += this._optionScore(best)
      return {
        ...ind,
        options: opts.map(o => ({ ...o, checked: o.value === best.value }))
      }
    })
    this.setData({ selections, indicators, liveTotal: total })
  },

  /** 构建提交数据 */
  buildFormData(submitType) {
    const data = { ...this.data.formHiddenFields }
    data.issubmit = submitType
    Object.entries(this.data.selections).forEach(([seq, val]) => {
      const ind = this.data.indicators.find(i => i.seq === seq)
      if (ind) {
        const opt = ind.options.find(o => o.value === val)
        if (opt) data[opt.name] = val
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
    const batchUrl = (this.data.currentBatch && this.data.currentBatch.items && this.data.currentBatch.items.length > 0)
      ? this.data.currentBatch.items[0].url : ''

    this.setData({
      batchRunning: true, batchDone: false, batchCurrent: 0,
      batchTotal: this.data.batchCourses.filter(c => !c.submitted).length,
      batchMessage: '正在提交…', batchPercent: 0, batchResults: []
    })

    try {
      const res = await api.startBatchEval(
        batchUrl, this.data.targetScore, '1',
        this.data.currentBatchHiddenFields.action || '',
        this.data.currentBatchHiddenFields
      )
      if (!res.success) {
        this.setData({ batchRunning: false, batchDone: true, batchMessage: res.message || '启动失败' })
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
      if (!this.data.batchRunning) { clearInterval(this._pollTimer); return }
      this._pollCount++
      if (this._pollCount > config.MAX_POLL_RETRIES) {
        clearInterval(this._pollTimer)
        this.setData({ batchRunning: false, batchDone: true, batchMessage: '轮询超时' })
        return
      }
      try {
        const res = await api.getBatchProgress(this.data.batchId)
        if (!res.success) {
          clearInterval(this._pollTimer)
          this.setData({ batchRunning: false, batchDone: true, batchMessage: res.message || '查询失败' })
          return
        }
        this.setData({
          batchCurrent: res.current || 0, batchTotal: res.total || 0,
          batchMessage: res.message || '',
          batchPercent: res.total > 0 ? Math.round((res.current || 0) / res.total * 100) : 0,
          batchResults: res.results || []
        })
        if (res.done) {
          clearInterval(this._pollTimer)
          this.setData({ batchRunning: false, batchDone: true })
          const results = res.results || []
          const courses = this.data.batchCourses.map(c => {
            const result = results.find(r => r.course === c.name)
            if (result && result.status === 'success') return { ...c, submitted: true }
            return c
          })
          this.setData({ batchCourses: courses })
        }
      } catch (e) {
        clearInterval(this._pollTimer)
        this.setData({ batchRunning: false })
      }
    }, config.POLL_INTERVAL)
  },

  closeBatchProgress() {
    if (this._pollTimer) { clearInterval(this._pollTimer); this._pollTimer = null }
    this.setData({ batchDone: false, batchRunning: false, batchResults: [] })
  },

  onUnload() {
    if (this._pollTimer) { clearInterval(this._pollTimer); this._pollTimer = null }
  },

  onPullDownRefresh() {
    this.onRefresh()
    wx.stopPullDownRefresh()
  }
})
