/**
 * 课表视图组件 — 由原 pages/schedule 页面改造（方案A 合页 swiper）
 * 生命周期: attached 首次挂载(读缓存); activate 由 main 页面每次激活时调用(onShow 语义)
 * 刷新: 工具栏手动 🔄 按钮
 */

const api = require('../../utils/api')
const storage = require('../../utils/storage')
const config = require('../../utils/config')
const { courseColors } = require('../../utils/course-color')
const { periodStart } = require('../../utils/period-time')
const { calcCurrentWeek, calcTodayDay, isWeekInRange, getDateLabel, getDefaultFirstWeekDate } = require('../../utils/date')

// ── 自定义课程(本地存储, 与教务课程合并显示) ──
const CUSTOM_KEY = 'custom_courses'
const DAY_OPTIONS = ['周一', '周二', '周三', '周四', '周五', '周六', '周日']
const PERIOD_OPTIONS = (() => {
  const a = []
  for (let i = 1; i <= 13; i++) a.push('第' + i + '节')
  return a
})()
const WEEK_TYPE_OPTIONS = ['每周（全学期）', '仅单周', '仅双周']
const WEEK_OPTIONS = (() => {
  const a = []
  for (let i = 1; i <= 20; i++) a.push('第' + i + '周')
  return a
})()

Component({
  options: {
    styleIsolation: 'apply-shared'
  },

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
    studentId: '',           // 学号(顶部信息卡)

    // 自定义课程弹窗表单
    showCustomForm: false,
    formTitle: '添加自定义课程',
    formCid: '',
    formName: '',
    formTeacher: '',
    formClassroom: '',
    formDayIdx: 0,
    formStartIdx: 0,
    formEndIdx: 0,
    formTypeIdx: 0,
    formWeekStartIdx: 0,    // 周次范围起(第1周)
    formWeekEndIdx: 19,     // 周次范围止(第20周, 默认全学期)
    dayOptions: DAY_OPTIONS,
    periodOptions: PERIOD_OPTIONS,
    weekTypeOptions: WEEK_TYPE_OPTIONS,
    weekOptions: WEEK_OPTIONS,

    active: false            // 懒渲染: main 激活时才渲染内容
  },

  lifetimes: {
    attached() {
      // 缓存优先：打开只渲染本地缓存，网络仅在下拉刷新/学期切换时发生
      this._customs = this._readCustoms()
      this.loadCachedData()
      this.loadFirstWeekDate()
      this.setData({
        weekPickerRange: Array.from({ length: 20 }, (_, i) => String(i + 1))
      })
      this._syncUser()
      this._ensureSemesterData()
    }
  },

  methods: {
    /**
     * 学期数据兜底: 已登录但本地缺学期/学期列表时后台静默补拉,
     * 避免顶栏一直"选择学期"、切换列表为空(清缓存/首次登录等场景)
     */
    _ensureSemesterData() {
      if (!storage.isLoggedIn()) return
      const hasCourses = (storage.getCached(this._coursesCacheKey()) || []).length > 0
      const hasSemester = !!this.data.semester
      const hasSemesters = this.data.semesters.length > 0
      if (!hasCourses || !hasSemester || !hasSemesters) {
        this.loadFromServer('', true)
      }
    },

    /** 由 main 页面调用: 每次被激活(滑动/点 tab 切换/从子页返回) */
    activate() {
      this.setData({ active: true })   // 懒渲染: 首次激活才渲染内容
      // 退出登录后清空上一用户数据(隐私)
      if (!storage.isLoggedIn()) {
        this.setData({ courses: [], filteredCourses: [], listDayGroups: [], studentName: '', studentId: '' })
        return
      }
      this.loadCachedData()            // 重新读缓存(登录后/刷新后数据自动生效)
      const app = getApp()
      // 仅当尚未选择学期时用全局值, 避免覆盖手动切换的学期
      if (app.globalData.semester && !this.data.semester) {
        this.setData({ semester: app.globalData.semester })
      }
      this._syncUser()
      // 学期/学期列表仍缺失时静默补拉(登录后回到课表即补上)
      this._ensureSemesterData()
      // 从「我的」页设置第一周日期后回到课表, 自动刷新定位本周
      this.loadFirstWeekDate()
    },

    /** 同步学生姓名/学号到顶部信息卡 */
    _syncUser() {
      this.setData({
        studentName: storage.getStudentName(),
        studentId: storage.getStudentId()
      })
    },

    /** 获取校历设置并定位当前周（本地优先: 有缓存值立即渲染, 过期则后台静默刷新） */
    async loadFirstWeekDate() {
      const sid = storage.getStudentId() || 'guest'
      // 后端按学期存储 first_week_date, 缓存键必须带学期
      const sem = this.data.semester || storage.getSemester() || 'default'
      const statusKey = 'cached_status_' + sid + '_' + sem
      const cache = storage.getCached(statusKey)
      const cachedVal = (cache && cache.first_week_date) || ''
      const age = cache && cache.t ? Date.now() - cache.t : Infinity

      if (cachedVal) {
        // 本地优先: 有缓存值(无论是否过期)立即渲染, 保证切换零等待
        this._applyFirstWeek(cachedVal, false)
        if (age < config.CACHE_TTL.status) return   // 新鲜: 零网络
        // 过期: 后台静默刷新, 不阻塞显示
        try {
          const res = await api.getStatus()
          if (res && res.first_week_date) {
            storage.setCached(statusKey, { t: Date.now(), first_week_date: res.first_week_date })
            if (res.first_week_date !== cachedVal) {
              this._applyFirstWeek(res.first_week_date, false)
            }
          }
        } catch (e) {
          // 静默: 继续显示本地值
        }
        return
      }

      // 无缓存值: 请求后端(失败用默认值兜底)
      try {
        const res = await api.getStatus()
        const firstWeekDate = (res && res.first_week_date) || getDefaultFirstWeekDate()
        if (res && res.first_week_date) {
          storage.setCached(statusKey, { t: Date.now(), first_week_date: res.first_week_date })
        }
        this._applyFirstWeek(firstWeekDate, !(res && res.first_week_date))
      } catch (e) {
        // 网络失败: 用默认值兜底定位
        this._applyFirstWeek(getDefaultFirstWeekDate(), false)
      }
    },

    /** 应用第一周日期: 计算当前周并刷新显示(保留用户手动跳转的周次) */
    _applyFirstWeek(firstWeekDate, showHint) {
      const actualWeek = calcCurrentWeek(firstWeekDate)
      const todayDay = calcTodayDay()
      // 仅首次设置或日期变化时定位本周; 否则保留用户当前查看的周次
      const firstTime = !this.data.firstWeekDate || this.data.firstWeekDate !== firstWeekDate
      const keepWeek = firstTime ? actualWeek : this.data.currentWeek
      this.setData({
        firstWeekDate,
        actualWeek,
        todayDay,
        currentWeek: keepWeek
      })
      // 如果已加载课程，重新过滤(用保留后的周次, 不覆盖用户跳转)
      if (this.data.courses.length > 0) {
        this.filterByWeek(keepWeek)
      }
      // 首次未设置时提示一次
      if (showHint && !this._weekHintShown) {
        this._weekHintShown = true
        wx.showToast({
          title: '未设置第一周日期,已默认本周为第 1 周;可在「我的」页设置',
          icon: 'none',
          duration: 3500
        })
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
        this._serverCourses = courses
        this._composeCourses()
        this.setData({ semester: semester || '' })
      } else if (semester && !this.data.semester) {
        // 无课程缓存时也补上学期文本(否则顶栏恒为"选择学期")
        this.setData({ semester })
      }
      if (semesters.length) {
        this.setData({ semesters })
      }
    },

    // ── 自定义课程: 本地读写 + 与教务课程合并 ──
    _readCustoms() {
      const arr = storage.get(CUSTOM_KEY, [])
      const list = Array.isArray(arr) ? arr.slice() : []
      list.forEach(c => { c._custom = true })
      return list
    },

    _persistCustoms() {
      storage.set(CUSTOM_KEY, this._customs || [])
    },

    /** 合并并重渲染: 教务课(基础) + 自定义课 */
    _composeCourses() {
      const merged = (this._serverCourses || []).concat(this._customs || [])
      this.setData({ courses: merged })
      this.filterByWeek(this.data.currentWeek)
    },

    /** 打开添加/编辑自定义课程弹窗 */
    onAddCustom() {
      this._openCustomForm(null)
    },

    _openCustomForm(course) {
      const has = !!course
      // 周次范围: 解析存量 weeks(如 "3-16"/"1-20"), 默认全学期
      let ws = 1
      let we = 20
      if (has) {
        const m = /(\d{1,2})\s*[-~至]\s*(\d{1,2})/.exec(String(course.weeks || ''))
        if (m) {
          ws = Math.max(1, Math.min(20, parseInt(m[1], 10) || 1))
          we = Math.max(ws, Math.min(20, parseInt(m[2], 10) || 20))
        }
      }
      this.setData({
        showCustomForm: true,
        formTitle: has ? '编辑自定义课程' : '添加自定义课程',
        formCid: has ? String(course._cid || '') : '',
        formName: has ? (course.name || '') : '',
        formTeacher: has ? (course.teacher || '') : '',
        formClassroom: has ? (course.classroom || '') : '',
        formDayIdx: has ? Math.max(0, ((course.day || course.day_of_week) || 1) - 1)
          : Math.max(0, (this.data.todayDay || 1) - 1),
        formStartIdx: has ? Math.max(0, ((course.start || course.start_period) || 1) - 1) : 0,
        formEndIdx: has ? Math.max(0, ((course.end || course.end_period) || 1) - 1) : 1,
        formTypeIdx: has ? (course.week_type || 0) : 0,
        formWeekStartIdx: ws - 1,
        formWeekEndIdx: we - 1
      })
    },

    closeCustomForm() {
      this.setData({ showCustomForm: false })
    },

    onFormName(e) { this.setData({ formName: e.detail.value }) },
    onFormTeacher(e) { this.setData({ formTeacher: e.detail.value }) },
    onFormClassroom(e) { this.setData({ formClassroom: e.detail.value }) },
    onFormDay(e) { this.setData({ formDayIdx: Number(e.detail.value) }) },
    onFormStart(e) {
      let s = Number(e.detail.value)
      const end = this.data.formEndIdx
      if (s > end) s = end   // 起 <= 止
      this.setData({ formStartIdx: s })
    },
    onFormEnd(e) {
      let en = Number(e.detail.value)
      const start = this.data.formStartIdx
      if (en < start) en = start
      this.setData({ formEndIdx: en })
    },
    onFormType(e) { this.setData({ formTypeIdx: Number(e.detail.value) }) },
    onFormWeekStart(e) {
      let s = Number(e.detail.value)
      const end = this.data.formWeekEndIdx
      if (s > end) s = end   // 起 <= 止
      this.setData({ formWeekStartIdx: s })
    },
    onFormWeekEnd(e) {
      let en = Number(e.detail.value)
      const start = this.data.formWeekStartIdx
      if (en < start) en = start
      this.setData({ formWeekEndIdx: en })
    },

    /** 保存自定义课程(新增/编辑) */
    onSaveCustom() {
      const name = (this.data.formName || '').trim()
      if (!name) {
        wx.showToast({ title: '请填写课程名称', icon: 'none' })
        return
      }
      const typeMap = [0, 1, 2]
      // 周次范围(与单/双周类型组合): 如 "3-16" + 单周 → 第3-16周中的单周
      const ws = this.data.formWeekStartIdx + 1
      const we = this.data.formWeekEndIdx + 1
      const weeks = `${ws}-${we}`
      const rec = {
        _custom: true,
        _cid: this.data.formCid || ('c' + Date.now()),
        name,
        teacher: (this.data.formTeacher || '').trim(),
        classroom: (this.data.formClassroom || '').trim(),
        day: this.data.formDayIdx + 1,
        start: this.data.formStartIdx + 1,
        end: this.data.formEndIdx + 1,
        weeks,
        week_type: typeMap[this.data.formTypeIdx] || 0,
        course_type: '自定义',
        credits: ''
      }
      const list = (this._customs || []).filter(c => String(c._cid) !== rec._cid)
      list.push(rec)
      this._customs = list
      this._persistCustoms()
      this.setData({ showCustomForm: false })
      this._composeCourses()
      wx.showToast({ title: '已保存', icon: 'success' })
    },

    /** 删除自定义课程(弹窗内/详情内) */
    onDeleteCustom(e) {
      const cid = String((e && e.currentTarget.dataset.cid) || this.data.formCid || '')
      if (!cid) return
      wx.showModal({
        title: '删除自定义课程',
        content: '确认删除这门自定义课程？',
        confirmColor: '#D9534F',
        success: (r) => {
          if (!r.confirm) return
          this._customs = (this._customs || []).filter(c => String(c._cid) !== cid)
          this._persistCustoms()
          this.setData({ showCustomForm: false, showDetail: false })
          this._composeCourses()
          wx.showToast({ title: '已删除', icon: 'none' })
        }
      })
    },

    /** 从课程详情进入编辑 */
    onEditCustom() {
      const course = this.data.detailCourse
      this.setData({ showDetail: false })
      if (course && course._custom) this._openCustomForm(course)
    },

    /** 从服务器加载（semester 参数可显式指定, 不依赖 storage 时序; silent 为后台静默模式） */
    async loadFromServer(semester, silent) {
      if (!silent) this.setData({ loading: true })
      try {
        const [res, semRes] = await Promise.all([
          api.getCourses(semester),   // 切换学期时显式传参, 确保请求目标学期
          api.getSemesters()
        ])
        if (res.success && res.courses) {
          this._serverCourses = res.courses
          this.setData({
            semester: res.semester || this.data.semester,
            loading: false
          })
          // 缓存键带学期: 按实际返回的学期写缓存(只存教务课, 自定义课独立存储)
          const cacheSem = res.semester || storage.getSemester() || 'default'
          storage.setCached('cached_courses_' + cacheSem, res.courses)
          if (res.semester) {
            storage.setSemester(res.semester)
            getApp().globalData.semester = res.semester   // 同步全局
          }
          this._composeCourses()
        } else {
          this.setData({ loading: false })
          if (!silent && !res.success && res.message) {
            wx.showToast({ title: res.message, icon: 'none' })
          }
        }

        if (semRes.success && semRes.semesters) {
          this.setData({ semesters: semRes.semesters })
          storage.setCached('semester_list', semRes.semesters)
        } else if (!this.data.semesters.length) {
          // 学期列表接口不可用时的本地兜底(与后端生成规则一致:
          // 当前学年 ±2 年的秋/春学期), 保证切换界面始终可见学期
          const cur = this.data.semester || storage.getSemester() || ''
          const m = /^(\d{4})/.exec(cur)
          const y = m ? parseInt(m[1], 10) : new Date().getFullYear()
          const fallback = []
          for (let yy = y - 2; yy <= y + 2; yy++) {
            fallback.push(`${yy}-${yy + 1}-1`, `${yy}-${yy + 1}-2`)
          }
          this.setData({ semesters: fallback })
          storage.setCached('semester_list', fallback)
        }
      } catch (e) {
        this.setData({ loading: false })
        if (!silent) wx.showToast({ title: '加载失败', icon: 'none' })
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

      // 课程配色: 不同课不同色(按课程名稳定分配; 网格/列表共用)
      // 上下课钟点: 与网格时间列同一作息(45 分钟/节)
      filtered.forEach(c => {
        if (!c._bg) {
          const pal = courseColors(c.name)
          c._bg = pal.bg
          c._bar = pal.bar
          c._text = pal.text
        }
        if (!c._clock) {
          const cs = c.start || c.start_period
          c._clock = cs ? periodStart(cs) : ''   // 仅显示上课时间 xx.xx
        }
        if (!c._periodLabel) {
          const cs = c.start || c.start_period
          const ce = c.end || c.end_period
          const range = (cs && ce) ? `${cs}-${ce}节` : ''
          c._periodLabel = (range && c._clock) ? `${range} · ${c._clock}` : (range || c._clock)
        }
      })

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

    /** 搜索课程/教师(200ms 防抖) */
    onSearchInput(e) {
      this.setData({ searchText: e.detail.value })
      if (this._searchTimer) clearTimeout(this._searchTimer)
      this._searchTimer = setTimeout(() => {
        this.filterByWeek(this.data.currentWeek)
      }, 200)
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

    /** 切换学期（显式传学期请求数据 + 自动从教务拉取该学期课表） */
    async onSemesterChange(e) {
      const idx = e.detail.value
      const semester = this.data.semesters[idx]
      if (semester && semester !== this.data.semester) {
        try {
          const res = await api.setSemester(semester)
          if (res && res.success) {
            this.setData({ semester, loading: true })
            getApp().globalData.semester = semester   // 同步全局, 防止 activate 覆盖回旧学期
            // 自动从教务拉取该学期课表(避免无缓存学期显示空白, 需手动下拉)
            const r = await api.refreshSchedule()
            this.setData({ loading: false })
            if (r && r.success) {
              wx.showToast({ title: `已获取 ${r.count || 0} 门课程`, icon: 'success' })
            } else {
              wx.showToast({ title: (r && r.message) || '获取课表失败', icon: 'none' })
            }
            this.loadFirstWeekDate()        // 刷新该学期第一周日期(周次下方日期随学期切换)
            this.loadFromServer(semester)   // 显式传参加载最新数据
          } else {
            wx.showToast({ title: (res && res.message) || '切换学期失败', icon: 'none' })
          }
        } catch (e) {
          this.setData({ loading: false })
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

    /** 手动刷新(主动操作, 显示反馈; 防重复点击) */
    async onRefresh() {
      if (this.data.loading) return
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
          _timeText: s ? `第${s}~${en}节 · ${periodStart(s)}` : '',
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
    }
  }
})
