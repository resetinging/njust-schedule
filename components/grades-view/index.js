/**
 * 成绩查询视图组件 — 由原 pages/grades 页面改造（方案A 合页 swiper）
 * 已勾选课程统计(学分/平均分/GPA) + 分学期卡片(勾选切换/折叠) + 分数胶囊
 * 方案 A: GPA/折算前端计算
 * 生命周期: attached 首次挂载(读缓存); activate 由 main 页面每次激活时调用(onShow 语义)
 * 下拉刷新: scroll-view refresher(refresher-threshold 可自定义)
 */

const api = require('../../utils/api')
const storage = require('../../utils/storage')
const gpaUtil = require('../../utils/gpa')

// ============================================================
// 工具
// ============================================================
const NON_GPA_NATURES = ['通识教育选修课']

function _num(v) { const n = parseFloat(v); return isNaN(n) ? 0 : n }
function _fixed(v, d) { const n = parseFloat(v); return isNaN(n) ? '-' : n.toFixed(d === undefined ? 2 : d) }
function _gpOf(g) {
  let gp = _num(g.grade_point)
  if (gp === 0) gp = gpaUtil.scoreToGp(g.score)
  return gp
}

function _isNonGpa(g) { return NON_GPA_NATURES.includes((g.course_nature || '').trim()) }

/** 是否有有效四六级折算(≥425 分; 存在则英语课默认不勾选, 由 CET 折算替代 — 参考 App 口径) */
function _hasCet(gpaUtil, cetRaw) {
  return (cetRaw || []).some(s => {
    const score = parseFloat(s.score) || 0
    return score >= 425 && gpaUtil.cetToPercentage(s.score, s.type) > 0
  })
}

Component({
  options: {
    styleIsolation: 'apply-shared'
  },

  data: {
    loading: true,
    refreshing: false,
    empty: false,
    errorMsg: '',
    semester: '',

    // 统计卡
    stats: {
      credits: '0', avg: '-', gpa: '0', gpaClass: '',
      mode: '',            // '' | 'baoyan'
      cet: null            // {line, date} | null
    },

    // 学期卡片组
    semGroups: [],          // [{sem, count, avg, folded, courses:[{id,name,checked,meta,score}]}]

    active: false            // 懒渲染: main 激活时才渲染内容
  },

  lifetimes: {
    attached() {
      // 缓存优先：打开页面只渲染本地缓存，后端请求仅发生在下拉刷新时
      this.loadCached()
      // 本地无数据且已登录: 后台静默拉取, 不阻塞显示
      const cached = storage.getCached('cached_grades')
      if (storage.isLoggedIn() && !(cached && cached.grades && cached.grades.length)) {
        this.loadGrades(true)
      }
    }
  },

  methods: {
    /** 由 main 页面调用: 每次被激活(滑动/点 tab 切换/从子页返回) */
    activate() {
      this.setData({ active: true })   // 懒渲染: 首次激活才渲染内容
      // 退出登录后清空上一用户数据(隐私, 含折叠/模式状态)
      if (!storage.isLoggedIn()) {
        this._allGrades = []
        this._checked = {}
        this._folded = {}
        this._mode = ''
        this.setData({ semGroups: [], empty: true, loading: false })
        return
      }
      this.loadCached()                // 重新读缓存(登录后/刷新后数据自动生效)
    },

    /** 从缓存渲染（不请求后端） */
    loadCached() {
      const gradesRes = storage.getCached('cached_grades')
      if (!gradesRes || !gradesRes.grades || !gradesRes.grades.length) {
        // 无缓存(未登录/首次): 收起加载态, 显示空状态
        this.setData({ loading: false, empty: true })
        return
      }
      this._allGrades = gradesRes.grades
      const cetRes = storage.getCached('cached_cet_scores')
      this._cetRaw = (cetRes && cetRes.success ? cetRes.scores : []) || []
      this._mode = storage.get('gpa_mode', '')
      // 勾选状态保留: 仅对新增课程初始化默认值(切换 Tab 不重置用户勾选)
      const hasCet = _hasCet(gpaUtil, this._cetRaw)
      if (!this._checked) this._checked = {}
      for (const g of this._allGrades) {
        if (this._checked[g.id] === undefined) {
          // 默认不勾: 通识教育选修课; 有 CET 折算时英语课(由 CET 折算替代)
          this._checked[g.id] = !(_isNonGpa(g) || (hasCet && gpaUtil.isEnglishCourse(g.course_name)))
        }
      }
      this._render()
      this.setData({ loading: false, empty: false })
    },

    // ============================================================
    // 数据加载
    // ============================================================
    /** 加载成绩（silent 为后台静默模式: 不显示 loading, 失败不弹提示） */
    async loadGrades(silent) {
      if (!silent) this.setData({ loading: true, errorMsg: '' })
      try {
        const [gradesRes, cetRes] = await Promise.all([
          api.getGrades('__all__'),
          api.getCetScores()
        ])
        const res = gradesRes
        if (!res.success) {
          this.setData({ loading: false, empty: true })
          if (!silent) this.setData({ errorMsg: res.message || '获取成绩失败' })
          return
        }
        this._allGrades = res.grades || []
        this._cetRaw = (cetRes && cetRes.success ? cetRes.scores : []) || []
        this._mode = storage.get('gpa_mode', '')
        // 默认勾选: 通识教育选修课不勾选; 有 CET 折算时英语课不勾
        const hasCet = _hasCet(gpaUtil, this._cetRaw)
        this._checked = {}
        for (const g of this._allGrades) {
          this._checked[g.id] = !(_isNonGpa(g) || (hasCet && gpaUtil.isEnglishCourse(g.course_name)))
        }
        this._render()
        storage.setCached('cached_grades', res)
        storage.setCached('cached_cet_scores', cetRes || {})
      } catch (e) {
        this.setData({ loading: false, empty: true })
        if (!silent) this.setData({ errorMsg: '网络请求失败' })
      }
    },

    // ============================================================
    // 计算与渲染
    // ============================================================
    _checkedList() {
      return this._allGrades.filter(g => this._checked[g.id] !== false)
    },

    _render() {
      const all = this._allGrades
      const checked = this._checkedList().filter(g => _num(g.credit) > 0)
      const isBaoyan = this._mode === 'baoyan'

      // --- 统计 ---
      // 有效计算列表: 保研模式 = 排除英语课 + CET 折算条目(8学分, 参考 App 口径);
      // 普通模式 = 勾选课程(英语课计入)
      let calcList = checked
      if (isBaoyan) {
        let best = null
        for (const s of this._cetRaw) {
          const score = parseFloat(s.score) || 0
          if (score < 425) continue
          const pct = gpaUtil.cetToPercentage(s.score, s.type)
          if (pct > 0 && (!best || pct > best.pct)) best = { pct, s }
        }
        if (best) {
          const nonEng = checked.filter(g => !gpaUtil.isEnglishCourse(g.course_name))
          calcList = nonEng.concat([{
            course_name: 'CET折算(8学分)',
            score: String(best.pct),
            credit: 8,
            grade_point: gpaUtil.scoreToGp(best.pct),
            course_nature: 'CET'
          }])
        }
      }
      const totalCredits = calcList.reduce((s, g) => s + _num(g.credit), 0)
      // 平均分: 学分加权(等级制折算百分制参与, 与参考 App 口径一致)
      const avg = gpaUtil.calcAvg(calcList)
      const gpaV = gpaUtil.calcGpa(calcList, false)
      let gpaClass = ''
      if (gpaV >= 3.0) gpaClass = 'gpa-high'
      else if (gpaV >= 2.0) gpaClass = 'gpa-mid'
      else if (gpaV > 0) gpaClass = 'gpa-low'

      // --- CET 折算行 ---
      let cet = null
      if (this._cetRaw.length) {
        let best = null
        for (const s of this._cetRaw) {
          const pct = gpaUtil.cetToPercentage(s.score, s.type)
          if (pct > 0 && (!best || pct > best.pct)) best = { pct, s }
        }
        if (best) {
          cet = {
            line: best.s.type + ' ' + best.s.score + ' | 折算 ' + _fixed(best.pct, 2) + ' | 学分 8',
            date: best.s.exam_date || ''
          }
        }
      }

      // --- 学期分组(倒序) ---
      const groups = {}
      for (const g of all) {
        const key = (g.academic_year || '') + '-' + (g.semester || '')
        if (!groups[key]) groups[key] = []
        groups[key].push(g)
      }
      const semKeys = Object.keys(groups).sort((a, b) => b.localeCompare(a))
      const semGroups = semKeys.map(sem => {
        const gs = groups[sem].slice().sort((a, b) => (a.course_name || '').localeCompare(b.course_name || ''))
        const semChecked = gs.filter(g => this._checked[g.id] !== false)
        // 每学期均分: 学分加权(等级折算, 与总平均分口径一致)
        const semAvg = gpaUtil.calcAvg(semChecked)
        // 每学期绩点: 始终用普通 GPA(与桌面端 calcSemesterGpas 一致;
        // CET 折算仅作用于总 GPA, 不作用于各学期)
        const semGpa = gpaUtil.calcGpa(semChecked, true)
        let semGpaClass = ''
        if (semGpa >= 3.0) semGpaClass = 'gpa-high'
        else if (semGpa >= 2.0) semGpaClass = 'gpa-mid'
        else if (semGpa > 0) semGpaClass = 'gpa-low'
        return {
          sem,
          count: gs.length,
          avg: semAvg > 0 ? _fixed(semAvg) : '-',
          gpa: _fixed(semGpa),
          gpaClass: semGpaClass,
          folded: this._folded && this._folded[sem] === true,
          courses: gs.map(g => {
            const gp = _gpOf(g)
            return {
              id: g.id,
              name: g.course_name,
              checked: this._checked[g.id] !== false,
              meta: '绩点 ' + (gp < 0 ? '-' : gp.toFixed(1)) +
                ' | 学分 ' + (_num(g.credit) || '-') +
                ' | ' + (g.course_type || '-') +
                ' | ' + (g.course_nature || '-'),
              score: String(g.score)
            }
          })
        }
      })

      this.setData({
        loading: false,
        empty: all.length === 0,
        errorMsg: '',
        semester: storage.getSemester() || '',
        stats: {
          credits: _fixed(totalCredits, 1),
          count: checked.length,
          avg: avg > 0 ? _fixed(avg) : '-',
          gpa: _fixed(gpaV),
          gpaClass,
          mode: this._mode,
          cet
        },
        semGroups
      })
    },

    // ============================================================
    // 交互
    // ============================================================
    onToggle(e) {
      const id = e.currentTarget.dataset.id
      if (id === undefined || this._checked[id] === undefined) return
      this._checked[id] = !this._checked[id]
      this._render()
    },

    onFold(e) {
      const sem = e.currentTarget.dataset.sem
      if (!this._folded) this._folded = {}
      this._folded[sem] = !(this._folded[sem] === true)
      this._render()
    },

    /** 切换 标准/保研 */
    onModeChange(e) {
      const mode = e.currentTarget.dataset.mode
      this._mode = mode
      storage.set('gpa_mode', mode)
      this._render()
    },

    /** 点击 CET 行刷新四六级 */
    async onRefreshCet() {
      wx.showLoading({ title: '获取中…' })
      try {
        const res = await api.refreshCet()
        wx.hideLoading()
        if (res.success) {
          this._cetRaw = res.scores || []
        } else {
          wx.showToast({ title: res.message || '获取失败', icon: 'none' })
        }
        this._render()
      } catch (e) {
        wx.hideLoading()
      }
    },

    /** 刷新成绩(防重复点击) */
    async onRefreshGrades() {
      if (this.data.refreshing) return
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
    }
  }
})
