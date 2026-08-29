/**
 * 教学评价视图组件 — 由原 pages/eval 页面改造（方案A 合页 swiper）
 * 生命周期: attached 首次挂载(读缓存); activate 由 main 页面每次激活时调用(onShow 语义)
 * 下拉刷新: scroll-view refresher(refresher-threshold 可自定义)
 */

const api = require('../../utils/api')
const storage = require('../../utils/storage')
const { timeUntilDeadline, parseDateStr } = require('../../utils/date')

Component({
  options: {
    styleIsolation: 'apply-shared'
  },

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
    batchId: '',

    active: false            // 懒渲染: main 激活时才渲染内容
  },

  lifetimes: {
    attached() {
      // 缓存优先：打开页面只渲染本地缓存，后端请求仅发生在下拉刷新时
      // （评教返回全部批次, 与学期切换无关, 固定缓存键）
      const batches = storage.getCached('cached_evaluations')
      if (batches && batches.evaluations) {
        this.setData({ batches: batches.evaluations })
        this._processBatches(batches.evaluations)
      }
      // 本地无数据且已登录: 后台静默拉取, 不阻塞显示
      if (storage.isLoggedIn() && !(batches && batches.evaluations && batches.evaluations.length)) {
        this.loadFromServer(true)
      }
    }
  },

  methods: {
    /** 由 main 页面调用: 每次被激活时触发 */
    activate() {
      this.setData({ active: true })   // 懒渲染: 首次激活才渲染内容
      // 退出登录后清空上一用户数据(隐私)
      if (!storage.isLoggedIn()) {
        this.setData({ batches: [], batchCourses: [], countdowns: [] })
        return
      }
      // 重新读缓存(登录后/刷新后数据自动生效)
      const batches = storage.getCached('cached_evaluations')
      if (batches && batches.evaluations) {
        this.setData({ batches: batches.evaluations })
        this._processBatches(batches.evaluations)
      }
    },

    /** 加载评教批次（silent 为后台静默模式: 不显示 loading, 失败不弹提示） */
    async loadFromServer(silent) {
      if (!storage.isLoggedIn()) return
      if (!silent) this.setData({ loading: true })
      try {
        const res = await api.getEvalBatches()
        if (!silent) this.setData({ loading: false })
        if (res.success) {
          const batches = res.evaluations || []
          this.setData({ batches })
          this._processBatches(batches)
          storage.setCached('cached_evaluations', res)
        } else {
          if (!silent) wx.showToast({ title: res.message || '加载失败', icon: 'none' })
        }
      } catch (e) {
        if (!silent) {
          this.setData({ loading: false })
          wx.showToast({ title: '加载失败', icon: 'none' })
        }
      }
    },

    /** 处理批次数据：去重 + 倒计时 + 每批次紧迫度 + 日期清洗 */
    _processBatches(batches) {
      // 防御去重: 同一批次(batch+category)只保留一条
      const seen = {}
      const unique = []
      for (const b of batches || []) {
        const key = (b.batch || '') + '|' + (b.category || '')
        if (seen[key]) continue
        seen[key] = true
        unique.push(b)
      }

      // 日期清洗: "2025-12-01 00:00:00" → "2025-12-01"
      const cleanDate = (s) => {
        if (!s) return ''
        const d = parseDateStr(s)
        if (!d) return String(s)
        const m = String(d.getMonth() + 1).padStart(2, '0')
        const dd = String(d.getDate()).padStart(2, '0')
        return `${d.getFullYear()}-${m}-${dd}`
      }

      // 批次名去除与学期标签重复的前缀(学期已单独用 sem-tag 显示)
      const stripSemesterPrefix = (b) => {
        let name = b.batch || ''
        if (b.semester && name.startsWith(b.semester)) {
          name = name.slice(b.semester.length).replace(/^[-_：:\s]+/, '')
        }
        return name || b.batch || ''
      }

      // 给每个批次附加紧迫度信息
      const enriched = unique.map(b => {
        const info = timeUntilDeadline(b.end_date)
        return {
          ...b,
          _batchText: stripSemesterPrefix(b),
          start_date: cleanDate(b.start_date),
          end_date: cleanDate(b.end_date),
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
            course_name: '全部评教已完成', cardClass: ''
          }]
        }
      } else {
        countdowns = undone.slice(0, 3).map(b => {
          const totalHours = (() => {
            const end = parseDateStr(b.end_date)
            if (!end) return 0
            end.setHours(23, 59, 59, 0)
            return (end - new Date()) / (1000 * 60 * 60)
          })()
          let bigNum, bigLabel
          if (totalHours < 0) { bigNum = '!'; bigLabel = '已截止' }
          else if (totalHours < 24) { bigNum = Math.floor(totalHours) + 'h'; bigLabel = '小时后截止' }
          else { bigNum = Math.floor(totalHours / 24); bigLabel = '天后截止' }

          return {
            bigNum, bigLabel,
            course_name: b.batch || b.category,
            cardClass: b._urgency === 'urgent' ? 'urgent' : (b._urgency === 'warning' ? 'warning' : '')
          }
        })
      }

      this.setData({ batches: enriched, countdowns })
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

      // 实时计算总分(所有指标一次性计分: 变更项按新选项, 其他项按已选)
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

      this.setData({ selections, indicators, liveTotal: total })
    },

    /** 自动填写输入框值变化 */
    onAutoFillScoreInput(e) {
      this.setData({ autoFillScore: e.detail.value })
    },

    /** 自动填写评教（纯前端算法，方案 A） */
    onAutoFill() {
      const score = parseFloat(this.data.autoFillScore)
      if (isNaN(score) || score < 0 || score > 100) {
        wx.showToast({ title: '请输入0-100的目标分数', icon: 'none' })
        return
      }
      this._autoFillSelections(score)
    },

    /**
     * 增强版自动评分（移植自服务端算法，方案 A）：
     * 贪心选择 → 防同列作弊 → 单指标微调
     * 返回 { selections: {seq: value}, total }
     */
    _computeAutoFill(indicators, targetScore) {
      const selections = []
      let totalMax = 0
      for (const ind of indicators) {
        const opts = ind.options || []
        let indMax = 0
        opts.forEach(o => {
          const s = this._optionScore(o)
          if (s > indMax) indMax = s
        })
        totalMax += indMax
        selections.push({
          seq: ind.seq,
          maxScore: indMax,
          opts: opts.map((o, i) => ({ idx: i, score: this._optionScore(o), name: o.name, value: o.value })),
          colIndex: 0, score: 0, name: '', value: ''
        })
      }
      if (totalMax <= 0) return { selections: {}, total: 0 }

      // 步骤 1: 贪心 — 每条指标选最接近目标比例的选项
      selections.forEach(sel => {
        const target = (targetScore / totalMax) * sel.maxScore
        let best = sel.opts[0], bestDist = Infinity
        sel.opts.forEach(o => {
          const d = Math.abs(o.score - target)
          if (d < bestDist) { bestDist = d; best = o }
        })
        sel.colIndex = best.idx
        sel.score = best.score
        sel.name = best.name
        sel.value = best.value
      })

      const allSame = () => selections.length > 1 &&
        selections.every(s => s.colIndex === selections[0].colIndex)
      const total = () => selections.reduce((sum, s) => sum + s.score, 0)

      // 步骤 2: 防作弊 — 不能所有指标选同一列
      if (allSame()) {
        const cur = total()
        let bestPenalty = Math.abs(cur - targetScore), bestCombo = null
        selections.forEach((sel, si) => {
          sel.opts.forEach(o => {
            if (o.idx === sel.colIndex) return
            const p = Math.abs(cur - sel.score + o.score - targetScore)
            if (p < bestPenalty) { bestPenalty = p; bestCombo = { si, o } }
          })
        })
        if (bestCombo) {
          const s = selections[bestCombo.si]
          s.colIndex = bestCombo.o.idx
          s.score = bestCombo.o.score
          s.name = bestCombo.o.name
          s.value = bestCombo.o.value
        }
      }

      // 步骤 3: 微调（最多 10 轮，连续 3 轮无改善则停）
      let noImprove = 0
      for (let round = 0; round < 10; round++) {
        const cur = total()
        const curPenalty = Math.abs(cur - targetScore)
        if (curPenalty < 0.5) break
        let bestSwap = null, bestPenalty = curPenalty
        selections.forEach((sel, si) => {
          sel.opts.forEach(o => {
            if (o.idx === sel.colIndex) return
            const newPenalty = Math.abs(cur - sel.score + o.score - targetScore)
            const saved = sel.colIndex
            sel.colIndex = o.idx
            const same = allSame()
            sel.colIndex = saved
            if (same) return
            if (newPenalty < bestPenalty) { bestPenalty = newPenalty; bestSwap = { si, o } }
          })
        })
        if (bestSwap && bestPenalty < curPenalty) {
          const s = selections[bestSwap.si]
          s.colIndex = bestSwap.o.idx
          s.score = bestSwap.o.score
          s.name = bestSwap.o.name
          s.value = bestSwap.o.value
          noImprove = 0
        } else {
          noImprove++
          if (noImprove >= 3) break
        }
      }

      const result = {}
      selections.forEach(s => { result[s.seq] = s.value })
      return { selections: result, total: Math.round(total() * 10) / 10 }
    },

    /** 应用自动填写结果到表单 UI */
    _autoFillSelections(targetScore) {
      const filled = this._computeAutoFill(this.data.indicators, targetScore)
      const selections = filled.selections
      let total = 0
      const indicators = this.data.indicators.map(ind => {
        const val = selections[ind.seq]
        if (val !== undefined) {
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
      wx.showToast({ title: `已自动填写,总分 ${total}`, icon: 'none' })
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
    // 一键评教（前端顺序循环，方案 A）
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

    /** 开始批量评教：逐门「取表单 → 前端自动评分 → 提交」 */
    async startBatchEval() {
      this.setData({ showBatchDialog: false })
      const targetScore = this.data.targetScore
      const targets = this.data.batchCourses.filter(c => !c.submitted)

      if (targets.length === 0) {
        wx.showToast({ title: '✅ 所有课程已提交', icon: 'success' })
        return
      }

      this.setData({
        batchRunning: true, batchDone: false, batchCurrent: 0,
        batchTotal: targets.length,
        batchMessage: '正在提交…', batchPercent: 0, batchResults: []
      })

      const results = []
      for (let i = 0; i < targets.length; i++) {
        if (!this.data.batchRunning) break // 用户关闭进度弹窗
        const course = targets[i]
        try {
          this.setData({ batchMessage: `正在加载 ${course.name}...` })
          const formRes = await api.getEvalForm(course.eval_url)
          if (!formRes.success || !(formRes.indicators || []).length) {
            results.push({ course: course.name, status: 'failed', error: formRes.message || '无法解析表单' })
          } else {
            this.setData({ batchMessage: `正在为 ${course.name} 自动评分...` })
            const filled = this._computeAutoFill(formRes.indicators, targetScore)
            const formData = { ...(formRes.hidden_fields || {}) }
            Object.entries(filled.selections).forEach(([seq, val]) => {
              const ind = formRes.indicators.find(x => x.seq === seq)
              const opt = ind && ind.options.find(o => o.value === val)
              if (opt) formData[opt.name] = val
            })
            // 补课程列表页的批次级隐藏字段（如 cj0701id）
            const batchHf = this.data.currentBatchHiddenFields || {}
            Object.keys(batchHf).forEach(k => {
              if (!(k in formData)) formData[k] = batchHf[k]
            })
            formData.issubmit = '1'
            this.setData({ batchMessage: `正在提交 ${course.name}...` })
            const subRes = await api.submitEval(formData, '1', formRes.action || '')
            if (subRes.success) {
              results.push({ course: course.name, status: 'success', score: filled.total })
            } else {
              results.push({ course: course.name, status: 'failed', error: subRes.message || '提交失败' })
            }
          }
        } catch (e) {
          results.push({ course: course.name, status: 'failed', error: (e && e.message) || '请求失败' })
        }

        const done = i + 1
        this.setData({
          batchCurrent: done,
          batchPercent: Math.round(done / targets.length * 100),
          batchResults: results.slice()
        })
      }

      const successCount = results.filter(r => r.status === 'success').length
      const failCount = results.filter(r => r.status === 'failed').length
      this.setData({
        batchRunning: false,
        batchDone: true,
        batchMessage: `完成:成功 ${successCount}/${targets.length}`,
        batchPercent: 100,
        batchResults: results
      })

      // 更新课程已提交状态
      const courses = this.data.batchCourses.map(c => {
        const r = results.find(x => x.course === c.name)
        if (r && r.status === 'success') return { ...c, submitted: true }
        return c
      })
      this.setData({ batchCourses: courses })

      let msg = `✅ 批量评教：${successCount} 成功`
      if (failCount > 0) msg += `，${failCount} 失败`
      wx.showToast({ title: msg, icon: failCount > 0 ? 'none' : 'success' })
    },

    closeBatchProgress() {
      this.setData({ batchDone: false, batchRunning: false, batchResults: [] })
    }
  }
})
