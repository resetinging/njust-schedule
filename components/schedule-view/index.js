/**
 * 课表视图组件 — 由原 pages/schedule 页面改造（方案A 合页 swiper）
 * 生命周期: attached 首次挂载(读缓存); activate 由 main 页面每次激活时调用(onShow 语义)
 * 刷新: 工具栏手动 🔄 按钮
 */

const api = require('../../utils/api')
const storage = require('../../utils/storage')
const config = require('../../utils/config')
const { calcCurrentWeek, calcTodayDay, isWeekInRange, getDateLabel, getDefaultFirstWeekDate } = require('../../utils/date')

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
    announcement: '',        // 系统公告(公开, 未登录也显示)

    active: false            // 懒渲染: main 激活时才渲染内容
  },

  lifetimes: {
    attached() {
      // 缓存优先：打开只渲染本地缓存，网络仅在下拉刷新/学期切换时发生
      this.loadCachedData()
      this.loadFirstWeekDate()
      this._loadAnnouncement()
      this.setData({
        weekPickerRange: Array.from({ length: 20 }, (_, i) => String(i + 1))
      })
      this._syncUser()
      // 本地无数据且已登录: 后台静默拉取, 不阻塞显示
      if (storage.isLoggedIn() && !(storage.getCached(this._coursesCacheKey()) || []).length) {
        this.loadFromServer('', true)
      }
    }
  },

  methods: {
    /** 加载系统公告(公开接口; 本地缓存兜底立即显示, 后台刷新) */
    _loadAnnouncement() {
      const cached = storage.getCached('cached_announcement')
      if (cached && cached.enabled && cached.text && !this.data.announcement) {
        this.setData({ announcement: cached.text })
      }
      api.getAnnouncement().then(res => {
        if (res && res.success) {
          storage.setCached('cached_announcement', { t: Date.now(), enabled: res.enabled, text: res.text })
          this.setData({ announcement: (res.enabled && res.text) ? res.text : '' })
        }
      }).catch(() => {})
    },

    /** 由 main 页面调用: 每次被激活(滑动/点 tab 切换/从子页返回) */
    activate() {
      this.setData({ active: true })   // 懒渲染: 首次激活才渲染内容
      this._loadAnnouncement()         // 公告公开, 未登录也刷新
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
        this.setData({ courses, semester: semester || '' })
        this.filterByWeek(this.data.currentWeek)
      }
      if (semesters.length) {
        this.setData({ semesters })
      }
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
          this.setData({
            courses: res.courses,
            semester: res.semester || this.data.semester,
            loading: false
          })
          // 缓存键带学期: 按实际返回的学期写缓存
          const cacheSem = res.semester || storage.getSemester() || 'default'
          storage.setCached('cached_courses_' + cacheSem, res.courses)
          if (res.semester) {
            storage.setSemester(res.semester)
            getApp().globalData.semester = res.semester   // 同步全局
          }
          this.filterByWeek(this.data.currentWeek)
        } else {
          this.setData({ loading: false })
          if (!silent && !res.success && res.message) {
            wx.showToast({ title: res.message, icon: 'none' })
          }
        }

        if (semRes.success && semRes.semesters) {
          this.setData({ semesters: semRes.semesters })
          storage.setCached('semester_list', semRes.semesters)
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
          _timeText: (s && en) ? `第${s}~${en}节` : '',
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
