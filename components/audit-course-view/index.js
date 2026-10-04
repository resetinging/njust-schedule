/**
 * 蹭课查询: 仅展示教务课程课表页面实际返回的字段。
 */
const api = require('../../utils/api')
const auditCourseUtil = require('../../utils/audit-course')
const { classClock } = require('../../utils/period-time')
const storage = require('../../utils/storage')
const analytics = require('../../utils/analytics')
const {
  getDefaultFirstWeekDate,
  calcCurrentWeek,
  calcTodayDay,
  isWeekInRange,
  getWeekBounds
} = require('../../utils/date')

const DAY_NAMES = ['', '星期一', '星期二', '星期三', '星期四', '星期五', '星期六', '星期日']
const WEEKDAY_OPTIONS = ['不限'].concat(DAY_NAMES.slice(1))
const PERIOD_OPTIONS = ['不限'].concat(
  Array.from({ length: 13 }, (_, index) => `第${index + 1}节`)
)
const WEEK_OPTIONS = Array.from({ length: 20 }, (_, index) => `第${index + 1}周`)
const QUERY_OPTIONS_FORMAT = 3
const SUGGEST_TOGGLE_GUARD_MS = 350

function fmtTime(ts) {
  if (!ts) return ''
  const d = new Date(ts * 1000)
  const p = n => (n < 10 ? '0' : '') + n
  return `${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`
}

Component({
  options: { styleIsolation: 'apply-shared' },

  lifetimes: {
    attached() {
      this._queryToken = 0
      this._suggestOptionsAll = []
      this._favoriteMap = {}
      this._normalResultState = null
      this._appliedSelections = { names: [], teachers: [], classrooms: [] }
      this._loadRecentSelections()
      this._loadOwnCourses()
      this._loadFavorites()
      this._loadQueryOptions()
      analytics.observeSlots(this, [
        { id: 'slot-audit-bottom', page: 'audit', ad_type: 'native' }
      ])
    },
    detached() {
      analytics.disconnectSlots(this)
    }
  },

  data: {
    courseName: '',
    teacher: '',
    classroom: '',
    weekdayIndex: 0,
    startPeriodIndex: 0,
    endPeriodIndex: 0,
    weekdayOptions: WEEKDAY_OPTIONS,
    periodOptions: PERIOD_OPTIONS,
    suggestField: '',
    suggestOptions: [],
    suggestHeight: 0,
    suggestVisibleCount: 50,
    suggestLoading: false,
    loading: false,
    searched: false,
    errorMsg: '',
    courses: [],
    total: 0,
    page: 1,
    hasMore: false,
    updatedAt: '',
    showWeekly: false,
    weeklyName: '',
    weeklyTeacher: '',
    weeklyCourses: [],
    weeklyWeek: 1,
    weeklyWeekIndex: 0,
    weeklyWeekOptions: WEEK_OPTIONS,
    weeklyFirstWeekDate: '',
    weeklyActualWeek: 0,
    weeklyTodayDay: 0,
    showQueryExplorer: false,
    explorerTab: 'names',
    explorerKeyword: '',
    explorerItems: [],
    explorerTotal: 0,
    explorerAllTotal: 0,
    explorerVisibleCount: 80,
    explorerHasMore: false,
    selectedNames: [],
    selectedTeachers: [],
    selectedClassrooms: [],
    activeChips: [],
    recentItems: [],
    workbenchSelectedCount: 0,
    workbenchMatchCount: 0,
    favorites: [],
    favoriteCount: 0,
    favoritesLoading: false,
    showFavoritesOnly: false,
    ownCourses: [],
    ownCoursesLoaded: false,
    ownCoursesLoading: false,
    weeklyConflictText: '',
    weeklyConflictClass: '',
    weeklyIsFavorite: false,
    weeklyFavoriteId: ''
  },

  methods: {
    onFilterFocus(e) {
      const field = e.currentTarget.dataset.field
      if (!field) return
      if (this._suggestClosedAt &&
          Date.now() - this._suggestClosedAt < SUGGEST_TOGGLE_GUARD_MS) {
        return
      }
      this._openSuggestions(field)
    },

    onFilterTap(e) {
      const field = e.currentTarget.dataset.field
      if (!field) return
      const touchState = this._suggestTouchWasOpen || {}
      let wasOpen = touchState[field]
      if (wasOpen === undefined) {
        wasOpen = this.data.suggestField === field &&
          !(this._suggestOpenedAt &&
            Date.now() - this._suggestOpenedAt < SUGGEST_TOGGLE_GUARD_MS)
      }
      if (wasOpen) {
        delete touchState[field]
        this._suggestClosedAt = Date.now()
        clearTimeout(this._suggestTimer)
        this._suggestTouching = false
        this.setData({
          suggestField: '',
          suggestOptions: [],
          suggestHeight: 0,
          suggestVisibleCount: 50,
          suggestLoading: false
        })
        return
      }
      delete touchState[field]
      this._suggestClosedAt = 0
      this._openSuggestions(field)
    },

    onFilterTouchStart(e) {
      const field = e.currentTarget.dataset.field
      if (!field) return
      this._suggestTouchWasOpen = this._suggestTouchWasOpen || {}
      this._suggestTouchWasOpen[field] = this.data.suggestField === field
    },

    _openSuggestions(field) {
      clearTimeout(this._suggestTimer)
      this._suggestTouching = false
      this._suggestClosedAt = 0
      this._suggestOpenedAt = Date.now()
      const patch = { suggestField: field, suggestLoading: true }
      if (this.data.suggestField !== field) {
        patch.suggestOptions = []
        patch.suggestHeight = 0
        patch.suggestVisibleCount = 50
      }
      this.setData(patch)
      this._applyLocalSuggestions(field, this.data[field] || '')
    },

    _coursesCacheKey() {
      return 'cached_courses_' + (storage.getSemester() || 'default')
    },

    _favoritesCacheKey() {
      const sid = storage.getStudentId() || 'guest'
      const semester = storage.getSemester() || 'default'
      return 'audit_favorites_' + sid + '_' + semester
    },

    async _loadOwnCourses() {
      const semester = storage.getSemester() || ''
      const cached = storage.getCached(this._coursesCacheKey())
      if (Array.isArray(cached)) {
        this.setData({
          ownCourses: cached,
          ownCoursesLoaded: true,
          ownCoursesLoading: false
        })
        this._refreshDecoratedCourses()
        return
      }
      if (!storage.isLoggedIn()) {
        this.setData({
          ownCourses: [],
          ownCoursesLoaded: true,
          ownCoursesLoading: false
        })
        this._refreshDecoratedCourses()
        return
      }
      this.setData({ ownCoursesLoading: true })
      try {
        const res = await api.getCourses(semester)
        const courses = (res && res.success && Array.isArray(res.courses))
          ? res.courses : []
        if (res && res.success) {
          storage.setCached(this._coursesCacheKey(), courses)
        }
        this.setData({
          ownCourses: courses,
          ownCoursesLoaded: true,
          ownCoursesLoading: false
        })
      } catch (_e) {
        this.setData({
          ownCoursesLoaded: true,
          ownCoursesLoading: false
        })
      }
      this._refreshDecoratedCourses()
    },

    async _loadFavorites() {
      const cacheKey = this._favoritesCacheKey()
      const cached = storage.getCached(cacheKey)
      if (Array.isArray(cached)) this._applyFavorites(cached)
      if (!storage.isLoggedIn()) {
        this.setData({ favoritesLoading: false })
        return
      }
      this.setData({ favoritesLoading: true })
      try {
        const res = await api.listAuditFavorites({
          semester: storage.getSemester() || ''
        })
        if (res && res.success && Array.isArray(res.favorites)) {
          this._applyFavorites(res.favorites)
          storage.setCached(cacheKey, res.favorites)
        }
      } catch (_e) {
        // 保留本地收藏，网络恢复后下次进入再同步。
      }
      this.setData({ favoritesLoading: false })
    },

    _applyFavorites(favorites) {
      const list = Array.isArray(favorites) ? favorites.slice() : []
      const map = {}
      list.forEach(favorite => {
        const rawKey = auditCourseUtil.favoriteKey(favorite)
        if (favorite.favorite_key) map[favorite.favorite_key] = favorite
        map[rawKey] = favorite
      })
      this._favoriteMap = map
      this.setData({
        favorites: list,
        favoriteCount: list.length
      }, () => {
        if (this.data.showFavoritesOnly) this._renderFavoriteCourses()
        else this._refreshDecoratedCourses()
      })
    },

    openFavoritesView() {
      if (!this.data.showFavoritesOnly) {
        this.toggleFavorites()
        return
      }
      if (this.data.favorites.length) {
        this._renderFavoriteCourses()
      } else {
        this._loadFavorites()
      }
    },

    toggleFavorites() {
      const show = !this.data.showFavoritesOnly
      clearTimeout(this._suggestTimer)
      this._suggestTouching = false
      if (show) {
        this._normalResultState = {
          courses: this.data.courses,
          total: this.data.total,
          page: this.data.page,
          hasMore: this.data.hasMore,
          updatedAt: this.data.updatedAt,
          searched: this.data.searched,
          errorMsg: this.data.errorMsg
        }
      }
      const patch = {
        showFavoritesOnly: show,
        suggestField: '',
        suggestOptions: [],
        suggestHeight: 0,
        suggestVisibleCount: 50,
        suggestLoading: false
      }
      if (!show && this._normalResultState) {
        Object.assign(patch, {
          courses: this._normalResultState.courses,
          total: this._normalResultState.total,
          page: this._normalResultState.page,
          hasMore: this._normalResultState.hasMore,
          updatedAt: this._normalResultState.updatedAt,
          searched: this._normalResultState.searched,
          errorMsg: this._normalResultState.errorMsg,
          loading: false
        })
      }
      this.setData(patch, () => {
        if (show) {
          if (this.data.favorites.length) this._renderFavoriteCourses()
          else this._loadFavorites()
        }
      })
    },

    _favoriteMatchesFilters(favorite) {
      const data = this.data
      const normalize = value => String(value || '').toLowerCase()
      const text = value => normalize(value)
      const matchText = (value, keyword) => {
        const q = String(keyword || '').trim().toLowerCase()
        return !q || text(value).indexOf(q) >= 0
      }
      const matchSelected = (value, selected) => {
        if (!selected || !selected.length) return true
        const values = normalize(value).split(/[,，]/).map(item => item.trim())
        return selected.some(item => {
          const target = normalize(item)
          return values.indexOf(target) >= 0
            || normalize(value).indexOf(target) >= 0
        })
      }
      if (!matchText(favorite.name, data.courseName)) return false
      if (!matchSelected(favorite.name, data.selectedNames)) return false
      if (!matchText(favorite.teacher, data.teacher)) return false
      if (!matchSelected(favorite.teacher, data.selectedTeachers)) return false
      if (!matchText(favorite.classroom, data.classroom)) return false
      if (!matchSelected(favorite.classroom, data.selectedClassrooms)) return false

      const weekday = Number(data.weekdayIndex || 0)
      const jc1 = Number(data.startPeriodIndex || 0)
      const jc2 = Number(data.endPeriodIndex || 0)
      if (!weekday && !jc1 && !jc2) return true
      return (favorite.schedules || []).some(schedule => {
        const day = Number(schedule.day || schedule.day_of_week || 0)
        const start = Number(schedule.start || schedule.start_period || 0)
        const end = Number(schedule.end || schedule.end_period || start)
        if (weekday && day !== weekday) return false
        if (jc1 && end < jc1) return false
        if (jc2 && start > jc2) return false
        return true
      })
    },

    _renderFavoriteCourses() {
      const courses = (this.data.favorites || [])
        .filter(favorite => this._favoriteMatchesFilters(favorite))
        .map(favorite => this._decorate(favorite))
      this.setData({
        courses,
        total: courses.length,
        page: 1,
        hasMore: false,
        searched: true,
        loading: false,
        errorMsg: '',
        updatedAt: ''
      })
    },

    _findFavorite(course) {
      const key = (course && course._favoriteKey)
        || auditCourseUtil.favoriteKey(course || {})
      if (this._favoriteMap && this._favoriteMap[key]) {
        return this._favoriteMap[key]
      }
      const raw = auditCourseUtil.favoriteKey(course || {})
      return (this.data.favorites || []).find(item =>
        auditCourseUtil.favoriteKey(item) === raw) || null
    },

    _conflictFor(course) {
      if (this.data.ownCoursesLoading) {
        return { hasConflict: false, loading: true, text: '课表同步中' }
      }
      if (!this.data.ownCoursesLoaded) {
        return { hasConflict: false, loading: true, text: '课表同步中' }
      }
      if (!storage.isLoggedIn()) {
        return { hasConflict: false, unavailable: true, text: '登录后可检测' }
      }
      const result = auditCourseUtil.conflictForCourse(
        course, this.data.ownCourses || [])
      if (!result.hasConflict) {
        return { hasConflict: false, text: '可旁听' }
      }
      return Object.assign({}, result, {
        text: '有冲突',
        detailText: auditCourseUtil.describeConflict(result.conflicts)
      })
    },

    _refreshDecoratedCourses() {
      if (!this.data.courses.length) return
      this.setData({
        courses: this.data.courses.map(course => this._decorate(course))
      })
    },

    _favoritePayload(course) {
      return {
        name: course.name || '',
        class_info: course.class_info || '',
        teacher: course.teacher || '',
        classroom: course.classroom || '',
        schedules: (course.schedules || []).map(item => ({
          day: item.day || item.day_of_week || 0,
          start: item.start || item.start_period || 0,
          end: item.end || item.end_period || 0,
          weeks: item.weeks || '',
          teacher: item.teacher || course.teacher || '',
          classroom: item.classroom || course.classroom || ''
        }))
      }
    },

    async _toggleFavorite(course) {
      if (!course) return false
      if (!storage.isLoggedIn()) {
        wx.showToast({ title: '请先登录后再收藏', icon: 'none' })
        return false
      }
      if (this._favoriteBusy) return false
      const favorite = this._findFavorite(course)
      const semester = storage.getSemester() || ''
      this._favoriteBusy = true
      try {
        const res = favorite
          ? await api.deleteAuditFavorite(favorite.id)
          : await api.saveAuditFavorite({
            semester,
            course: this._favoritePayload(course)
          })
        if (!res || !res.success) {
          throw new Error((res && res.message) || '收藏失败')
        }
        if (favorite) {
          this._applyFavorites((this.data.favorites || []).filter(
            item => String(item.id) !== String(favorite.id)))
        } else if (res.favorite) {
          this._applyFavorites((this.data.favorites || []).concat([
            res.favorite
          ]))
        }
        analytics.track('audit_favorite', {
          feature: 'audit', page: 'audit',
          result: favorite ? 'removed' : 'added'
        })
        storage.setCached(this._favoritesCacheKey(), this.data.favorites)
        this.triggerEvent('favoritechange')
        wx.showToast({
          title: favorite ? '已取消收藏' : '已收藏',
          icon: 'success'
        })
        return true
      } catch (e) {
        wx.showToast({
          title: e.message || '收藏操作失败',
          icon: 'none'
        })
        return false
      } finally {
        this._favoriteBusy = false
      }
    },

    onFilterInput(e) {
      const field = e.currentTarget.dataset.field
      if (!field) return
      if (this._pickedFields) delete this._pickedFields[field]
      const value = e.detail.value || ''
      const selectedKey = this._selectedKeyForField(field)
      const appliedKey = field === 'courseName'
        ? 'names'
        : (field === 'teacher' ? 'teachers' : 'classrooms')
      if (this._appliedSelections) this._appliedSelections[appliedKey] = []
      // 手动编辑会覆盖旧的精确选择，并让在途查询失效。
      this._queryToken = (this._queryToken || 0) + 1
      const patch = {
        [field]: value,
        [selectedKey]: [],
        suggestField: field,
        suggestLoading: true,
        courses: [],
        total: 0,
        page: 1,
        hasMore: false,
        searched: false,
        errorMsg: '',
        loading: false,
        updatedAt: ''
      }
      if (this.data.suggestField !== field) patch.suggestOptions = []
      this.setData(patch, () => this._refreshWorkbenchMeta())
      this._applyLocalSuggestions(field, value)
    },

    onFilterBlur(e) {
      const field = e.currentTarget.dataset.field
      if (!field) return
      if (this._suggestTouching) return
      clearTimeout(this._suggestTimer)
      this._suggestTimer = setTimeout(() => {
        if (this.data.suggestField === field) {
          this._suggestClosedAt = Date.now()
          this.setData({
            suggestField: '',
            suggestOptions: [],
            suggestHeight: 0,
            suggestVisibleCount: 50,
            suggestLoading: false
          })
        }
      }, 180)
    },

    onSuggestTouchStart() {
      this._suggestTouching = true
      clearTimeout(this._suggestTimer)
    },

    onSuggestTouchMove() {
      this._suggestTouching = true
      clearTimeout(this._suggestTimer)
    },

    onSuggestTouchEnd() {
      this._suggestTouching = false
    },

    onSuggestScrollToLower() {
      const allOptions = this._suggestOptionsAll || []
      const current = Number(this.data.suggestVisibleCount || 50)
      if (this._suggestLoadingMore || current >= allOptions.length) return
      this._suggestLoadingMore = true
      const next = Math.min(allOptions.length, current + 50)
      this.setData({ suggestVisibleCount: next }, () => {
        this._renderSuggestOptions(allOptions)
        this._suggestLoadingMore = false
      })
    },

    onSelectSuggestion(e) {
      const field = e.currentTarget.dataset.field
      const value = e.currentTarget.dataset.value || ''
      if (!field || !value) return
      clearTimeout(this._suggestTimer)
      this._suggestTouching = false
      this._suggestRequestId = (this._suggestRequestId || 0) + 1
      this._suggestClosedAt = 0
      this._suggestOpenedAt = 0
      this._suggestTouchWasOpen = {}
      this._pickedFields = this._pickedFields || {}
      this._pickedFields[field] = true
      this.setData({
        [field]: value,
        suggestField: '',
        suggestOptions: [],
        suggestHeight: 0,
        suggestVisibleCount: 50,
        suggestLoading: false
      }, () => {
        this._reconcileExplorerSelections()
      })
    },

    openQueryExplorer() {
      const field = this.data.suggestField || 'courseName'
      const tab = field === 'teacher'
        ? 'teachers'
        : (field === 'classroom' ? 'classrooms' : 'names')
      this._pickedFields = this._pickedFields || {}
      this._workbenchOriginal = {
        names: (this.data.selectedNames || []).slice(),
        teachers: (this.data.selectedTeachers || []).slice(),
        classrooms: (this.data.selectedClassrooms || []).slice()
      }
      const applied = this._appliedSelections || {}
      const selectedNames = (applied.names || []).length
        ? applied.names
        : (this.data.selectedNames.length
        ? this.data.selectedNames
        : (String(this.data.courseName || '').trim()
          ? [String(this.data.courseName).trim()] : []))
      const selectedTeachers = (applied.teachers || []).length
        ? applied.teachers
        : (this.data.selectedTeachers.length
        ? this.data.selectedTeachers
        : (String(this.data.teacher || '').trim()
          ? [String(this.data.teacher).trim()] : []))
      const selectedClassrooms = (applied.classrooms || []).length
        ? applied.classrooms
        : (this.data.selectedClassrooms.length
        ? this.data.selectedClassrooms
        : (String(this.data.classroom || '').trim()
          ? [String(this.data.classroom).trim()] : []))
      this.setData({
        showQueryExplorer: true,
        explorerTab: tab,
        explorerKeyword: '',
        explorerVisibleCount: 80,
        selectedNames,
        selectedTeachers,
        selectedClassrooms
      }, () => {
        this._refreshWorkbenchMeta()
        this._refreshExplorer()
        this._measureExplorerViewport()
      })
    },

    closeQueryExplorer() {
      const applied = this._appliedSelections || {
        names: [], teachers: [], classrooms: []
      }
      const hasApplied = (applied.names || []).length ||
        (applied.teachers || []).length ||
        (applied.classrooms || []).length
      const target = hasApplied
        ? applied
        : (this._workbenchOriginal || {
          names: [], teachers: [], classrooms: []
        })
      this.setData({
        showQueryExplorer: false,
        selectedNames: target.names || [],
        selectedTeachers: target.teachers || [],
        selectedClassrooms: target.classrooms || [],
        courseName: (target.names || [])[0] || '',
        teacher: (target.teachers || [])[0] || '',
        classroom: (target.classrooms || [])[0] || ''
      }, () => this._refreshWorkbenchMeta())
    },

    onExplorerTab(e) {
      this.setData({
        explorerTab: e.currentTarget.dataset.tab || 'names',
        explorerKeyword: '',
        explorerVisibleCount: 80
      }, () => this._refreshExplorer())
    },

    onExplorerInput(e) {
      this.setData({
        explorerKeyword: e.detail.value || '',
        explorerVisibleCount: 80
      }, () => this._refreshExplorer())
    },

    onExplorerClear() {
      this.setData({ explorerKeyword: '', explorerVisibleCount: 80 },
        () => this._refreshExplorer())
    },

    onExplorerScrollToLower() {
      this._loadMoreExplorer()
    },

    onExplorerScroll(e) {
      const detail = (e && e.detail) || {}
      const scrollTop = Number(detail.scrollTop || 0)
      const scrollHeight = Number(detail.scrollHeight || 0)
      const viewport = Number(this._explorerViewportHeight || 0)
      if (!this.data.explorerHasMore || !scrollHeight || !viewport) return
      if (scrollHeight - scrollTop - viewport <= 240) {
        this._loadMoreExplorer()
      }
    },

    onExplorerLoadMore() {
      this._loadMoreExplorer()
    },

    _measureExplorerViewport() {
      if (!wx.createSelectorQuery) return
      wx.createSelectorQuery()
        .in(this)
        .select('.explorer-scroll')
        .boundingClientRect(rect => {
          if (rect && rect.height) this._explorerViewportHeight = rect.height
        })
        .exec()
    },

    _loadMoreExplorer() {
      if (!this.data.explorerHasMore || this._explorerLoadingMore) return
      this._explorerLoadingMore = true
      const visible = this.data.explorerVisibleCount + 80
      this.setData({ explorerVisibleCount: visible }, () => {
        this._refreshExplorer()
        this._explorerLoadingMore = false
      })
    },

    onExplorerSelect(e) {
      const value = e.currentTarget.dataset.value || ''
      if (!value) return
      const fieldMap = {
        names: 'courseName',
        teachers: 'teacher',
        classrooms: 'classroom'
      }
      const field = fieldMap[this.data.explorerTab] || 'courseName'
      const key = this._selectedKeyForField(field)
      const selected = (this.data[key] || []).slice()
      const index = selected.indexOf(value)
      if (index >= 0) selected.splice(index, 1)
      else selected.push(value)
      this.setData({ [key]: selected, [field]: selected[0] || '' }, () => {
        this._pickedFields = this._pickedFields || {}
        this._pickedFields[field] = selected.length > 0
        this._refreshWorkbenchMeta()
        this._refreshExplorer()
      })
    },

    clearExplorerField(e) {
      const field = e.currentTarget.dataset.field
      if (!field) return
      if (this._pickedFields) delete this._pickedFields[field]
      const value = e.currentTarget.dataset.value || ''
      const key = this._selectedKeyForField(field)
      const selected = (this.data[key] || []).filter(item => item !== value)
      this.setData({ [key]: selected, [field]: selected[0] || '' }, () => {
        this._refreshWorkbenchMeta()
        const tabMap = {
          courseName: 'names',
          teacher: 'teachers',
          classroom: 'classrooms'
        }
        this.setData({
          explorerTab: tabMap[field] || this.data.explorerTab,
          explorerKeyword: '',
          explorerVisibleCount: 80
        }, () => this._refreshExplorer())
      })
    },

    onExplorerSheetTap() {
      // 拦截扩展查询面板内部点击，避免冒泡关闭。
    },

    onRecentTap(e) {
      const field = e.currentTarget.dataset.field
      const value = e.currentTarget.dataset.value || ''
      if (!field || !value) return
      const key = this._selectedKeyForField(field)
      const selected = (this.data[key] || []).slice()
      const index = selected.indexOf(value)
      if (index >= 0) selected.splice(index, 1)
      else selected.push(value)
      this.setData({ [key]: selected, [field]: selected[0] || '' }, () => {
        this._pickedFields = this._pickedFields || {}
        this._pickedFields[field] = selected.length > 0
        this._refreshWorkbenchMeta()
        this._refreshExplorer()
      })
    },

    clearWorkbenchChip(e) {
      const field = e.currentTarget.dataset.field
      const value = e.currentTarget.dataset.value || ''
      if (!field) return
      if (field === 'weekday') {
        this.setData({ weekdayIndex: 0 }, () => this._onTimeFilterChange())
        return
      }
      if (field === 'start') {
        this.setData({ startPeriodIndex: 0 }, () => this._onTimeFilterChange())
        return
      }
      if (field === 'end') {
        this.setData({ endPeriodIndex: 0 }, () => this._onTimeFilterChange())
        return
      }
      this.clearExplorerField({
        currentTarget: { dataset: { field, value } }
      })
    },

    _selectedKeyForField(field) {
      if (field === 'courseName') return 'selectedNames'
      if (field === 'teacher') return 'selectedTeachers'
      return 'selectedClassrooms'
    },

    _selectedForField(field) {
      return this.data[this._selectedKeyForField(field)] || []
    },

    _workbenchField() {
      if (this.data.explorerTab === 'teachers') return 'teacher'
      if (this.data.explorerTab === 'classrooms') return 'classroom'
      return 'courseName'
    },

    _timeMatches(relation) {
      const weekday = Number(this.data.weekdayIndex || 0)
      const jc1 = Number(this.data.startPeriodIndex || 0)
      const jc2 = Number(this.data.endPeriodIndex || 0)
      if (weekday && Number(relation.day || 0) !== weekday) return false
      if (jc1 && Number(relation.end || 0) < jc1) return false
      if (jc2 && Number(relation.start || 0) > jc2) return false
      return true
    },

    _workbenchMatchingRelations(skipField) {
      const fields = ['courseName', 'teacher', 'classroom']
      return (this._relations || []).filter(relation => {
        if (!this._timeMatches(relation)) return false
        for (const field of fields) {
          if (field === skipField) continue
          const selected = this._selectedForField(field)
          if (!selected.length) continue
          const relationValues = this._relationValues(relation, field)
          if (!selected.some(value => relationValues.indexOf(value) >= 0)) {
            return false
          }
        }
        return true
      })
    },

    _workbenchOptions(field, keyword) {
      const relations = this._workbenchMatchingRelations(field)
      const counts = {}
      relations.forEach(relation => {
        this._relationValues(relation, field).forEach(value => {
          counts[value] = (counts[value] || 0) + 1
        })
      })
      const query = String(keyword || '').trim()
      return Object.keys(counts)
        .filter(value => !query || value.indexOf(query) >= 0)
        .sort((a, b) => this._rankOption(a, query) - this._rankOption(b, query)
          || counts[b] - counts[a] || a.localeCompare(b, 'zh-CN'))
        .map(value => ({ value, count: counts[value] }))
    },

    _rankOption(value, query) {
      if (!query) return 0
      if (value === query) return 0
      if (value.indexOf(query) === 0) return 1
      return 2
    },

    _refreshWorkbenchMeta() {
      const activeChips = []
      const fields = [
        ['courseName', '课程'],
        ['teacher', '教师'],
        ['classroom', '地点']
      ]
      fields.forEach(([field, label]) => {
        this._selectedForField(field).forEach(value => {
          activeChips.push({ key: field + ':' + value, field, label, value })
        })
      })
      if (this.data.weekdayIndex) {
        activeChips.push({
          key: 'weekday',
          field: 'weekday',
          label: '星期',
          value: this.data.weekdayOptions[this.data.weekdayIndex]
        })
      }
      if (this.data.startPeriodIndex) {
        activeChips.push({
          key: 'start',
          field: 'start',
          label: '开始',
          value: this.data.periodOptions[this.data.startPeriodIndex]
        })
      }
      if (this.data.endPeriodIndex) {
        activeChips.push({
          key: 'end',
          field: 'end',
          label: '结束',
          value: this.data.periodOptions[this.data.endPeriodIndex]
        })
      }
      const matched = this._relations && this._relations.length
        ? this._workbenchMatchingRelations('').length : 0
      this.setData({
        activeChips,
        workbenchSelectedCount: activeChips.length,
        workbenchMatchCount: matched
      })
    },

    _refreshExplorer() {
      if (!this._queryOptionsReady) {
        this._loadQueryOptions().then(() => this._refreshExplorer())
        return
      }
      if (this.data.explorerTab === 'time') {
        this.setData({
          explorerItems: [],
          explorerTotal: 0,
          explorerAllTotal: 0,
          explorerHasMore: false
        })
        this._refreshWorkbenchMeta()
        return
      }
      const field = this._workbenchField()
      const all = this._workbenchOptions(field, '')
      const selected = new Set(this._selectedForField(field))
      const filtered = this._workbenchOptions(
        field, this.data.explorerKeyword || '')
      const visible = filtered.slice(0, this.data.explorerVisibleCount)
      this.setData({
        explorerItems: visible.map(item => Object.assign({}, item, {
          selected: selected.has(item.value)
        })),
        explorerTotal: filtered.length,
        explorerAllTotal: all.length,
        explorerHasMore: visible.length < filtered.length
      }, () => this._refreshWorkbenchMeta())
    },

    _optionKeyForField(field) {
      return field === 'courseName'
        ? 'names'
        : (field === 'teacher' ? 'teachers' : 'classrooms')
    },

    _fieldValues() {
      return {
        courseName: String(this.data.courseName || '').trim(),
        teacher: String(this.data.teacher || '').trim(),
        classroom: String(this.data.classroom || '').trim(),
        weekdayIndex: Number(this.data.weekdayIndex || 0),
        startPeriodIndex: Number(this.data.startPeriodIndex || 0),
        endPeriodIndex: Number(this.data.endPeriodIndex || 0)
      }
    },

    _fieldPicked(field) {
      return !!(this._pickedFields && this._pickedFields[field])
    },

    _relationValues(relation, field) {
      if (field === 'courseName') {
        return relation.name ? [relation.name] : []
      }
      if (field === 'teacher') return relation.teachers || []
      return relation.classrooms || []
    },

    _relationsMatchingValues(values, skipField) {
      const fields = ['courseName', 'teacher', 'classroom']
      return (this._relations || []).filter(relation => {
        const weekday = Number(values.weekdayIndex || 0)
        const jc1 = Number(values.startPeriodIndex || 0)
        const jc2 = Number(values.endPeriodIndex || 0)
        if (weekday && Number(relation.day || 0) !== weekday) return false
        if (jc1 && Number(relation.end || 0) < jc1) return false
        if (jc2 && Number(relation.start || 0) > jc2) return false
        for (const field of fields) {
          if (field === skipField) continue
          const selected = values[field]
          if (!selected) continue
          const relationValues = this._relationValues(relation, field)
          const matched = this._fieldPicked(field)
            ? relationValues.indexOf(selected) >= 0
            : relationValues.some(value =>
              String(value).indexOf(selected) >= 0)
          if (!matched) return false
        }
        return true
      })
    },

    _matchingRelations(field) {
      return this._relationsMatchingValues(this._fieldValues(), field)
    },

    _domainOptions(field, values, keyword) {
      const relations = this._relationsMatchingValues(values, field)
      const source = relations.length
        ? relations.reduce((options, relation) => {
          this._relationValues(relation, field).forEach(value => {
            if (options.indexOf(value) < 0) options.push(value)
          })
          return options
        }, [])
        : []
      const query = String(keyword || '').trim()
      return source
        .filter(value => !query || String(value).indexOf(query) >= 0)
        .sort()
    },

    _optionsForField(field, keyword) {
      const key = this._optionKeyForField(field)
      const selected = String(this.data[field] || '').trim()
      const query = String(keyword || '').trim()
      if (this._fieldPicked(field) && selected) {
        return !query || selected.indexOf(query) >= 0 ? [selected] : []
      }
      const source = this._relations && this._relations.length
        ? this._domainOptions(field, this._fieldValues(), query)
        : ((this._queryOptions && this._queryOptions[key]) || [])
      if (this._relations && this._relations.length) return source
      return source
        .filter(value => !query || String(value).indexOf(query) >= 0)
        .sort()
    },

    _reconcileExplorerSelections(allowAuto) {
      const relations = this._relations || []
      if (!relations.length) return this._fieldValues()
      const fields = [
        ['courseName', 'names'],
        ['teacher', 'teachers'],
        ['classroom', 'classrooms']
      ]
      const values = this._fieldValues()
      const patch = {}
      fields.forEach(([field]) => {
        if (values[field]) return
        const options = this._domainOptions(field, values, '')
        if (allowAuto !== false && options.length === 1) {
          values[field] = options[0]
          patch[field] = options[0]
          this._pickedFields = this._pickedFields || {}
          this._pickedFields[field] = true
        }
      })
      if (Object.keys(patch).length) this.setData(patch)
      return values
    },

    _nextExplorerTab(values) {
      const selections = values || this._fieldValues()
      if (!selections.courseName) return 'names'
      if (!selections.teacher) return 'teachers'
      if (!selections.classroom) return 'classrooms'
      return this.data.explorerTab
    },

    onWeekdayChange(e) {
      this.setData({ weekdayIndex: Number(e.detail.value || 0) },
        () => this._onTimeFilterChange())
    },

    onStartPeriodChange(e) {
      const startPeriodIndex = Number(e.detail.value || 0)
      const endPeriodIndex = (
        startPeriodIndex && this.data.endPeriodIndex &&
        startPeriodIndex > this.data.endPeriodIndex
      ) ? startPeriodIndex : this.data.endPeriodIndex
      this.setData({ startPeriodIndex, endPeriodIndex },
        () => this._onTimeFilterChange())
    },

    onEndPeriodChange(e) {
      const endPeriodIndex = Number(e.detail.value || 0)
      const startPeriodIndex = (
        endPeriodIndex && this.data.startPeriodIndex &&
        endPeriodIndex < this.data.startPeriodIndex
      ) ? endPeriodIndex : this.data.startPeriodIndex
      this.setData({ startPeriodIndex, endPeriodIndex },
        () => this._onTimeFilterChange())
    },

    _onTimeFilterChange() {
      const patch = {}
      ;['courseName', 'teacher', 'classroom'].forEach(field => {
        const options = this._workbenchOptions(field, '')
          .map(item => item.value)
        const selected = this._selectedForField(field)
          .filter(value => options.indexOf(value) >= 0)
        const key = this._selectedKeyForField(field)
        if (selected.length !== this._selectedForField(field).length) {
          patch[key] = selected
          patch[field] = selected[0] || ''
        }
        if (!selected.length && this._pickedFields) {
          delete this._pickedFields[field]
        }
      })
      if (Object.keys(patch).length) this.setData(patch)
      this._refreshWorkbenchMeta()
      if (this.data.showQueryExplorer) {
        this.setData({ explorerVisibleCount: 80 },
          () => this._refreshExplorer())
      }
      if (this.data.showFavoritesOnly) this._renderFavoriteCourses()
    },

    onCourseTap(e) {
      const index = Number(e.currentTarget.dataset.index)
      const selected = this.data.courses[index]
      if (!selected) return
      const favorite = this._findFavorite(selected)
      const conflict = selected._conflict || this._conflictFor(selected)
      const marked = auditCourseUtil.markScheduleConflicts(
        selected, this.data.ownCourses || [])
      const weeklyCourses = (marked.schedules || []).map(schedule =>
        Object.assign({}, schedule, {
          name: selected.name || '',
          class_info: selected.class_info || ''
        })
      )
      const group = weeklyCourses.length ? weeklyCourses : [selected]
      const sid = storage.getStudentId() || 'guest'
      const semester = storage.getSemester() || 'default'
      const cache = storage.getCached('cached_status_' + sid + '_' + semester)
      const firstWeekDate = (
        cache && cache.first_week_date
      ) || getDefaultFirstWeekDate()
      const actualWeek = calcCurrentWeek(firstWeekDate)
      let week = actualWeek
      if (!group.some(course => isWeekInRange(week, course.weeks))) {
        week = Math.min(...group.map(course => getWeekBounds(course.weeks).min))
      }
      this.setData({
        showWeekly: true,
        weeklyName: selected.name || '',
        weeklyTeacher: selected.teacher || '',
        weeklyCourses: group,
        weeklyWeek: week,
        weeklyWeekIndex: week - 1,
        weeklyFirstWeekDate: firstWeekDate,
        weeklyActualWeek: actualWeek,
        weeklyTodayDay: calcTodayDay(),
        weeklyConflictText: conflict.text || '',
        weeklyConflictClass: conflict.hasConflict
          ? 'conflict'
          : (conflict.loading
            ? 'loading'
            : (conflict.unavailable ? 'unavailable' : 'free')),
        weeklyIsFavorite: !!favorite,
        weeklyFavoriteId: favorite ? favorite.id : ''
      })
      this._weeklyFavoriteCourse = selected
    },

    async onToggleFavorite(e) {
      const index = Number(e.currentTarget.dataset.index)
      const course = this.data.courses[index]
      if (!course) return
      await this._toggleFavorite(course)
    },

    async onToggleWeeklyFavorite() {
      const course = this._weeklyFavoriteCourse
      if (!course) return
      const changed = await this._toggleFavorite(course)
      if (!changed) return
      const updated = this._decorate(course)
      this._weeklyFavoriteCourse = updated
      this.setData({
        weeklyIsFavorite: !!updated._isFavorite,
        weeklyFavoriteId: updated._favoriteId || ''
      })
    },

    closeWeekly() {
      this.setData({ showWeekly: false })
    },

    onWeeklySheetTap() {
      // 拦截课表内部点击，避免冒泡到遮罩层关闭周课表。
    },

    onWeeklyWeekChange(e) {
      const week = Number(e.detail.value || 0) + 1
      this.setData({ weeklyWeek: week, weeklyWeekIndex: week - 1 })
    },

    prevWeeklyWeek() {
      const week = Math.max(1, this.data.weeklyWeek - 1)
      this.setData({ weeklyWeek: week, weeklyWeekIndex: week - 1 })
    },

    nextWeeklyWeek() {
      const week = Math.min(20, this.data.weeklyWeek + 1)
      this.setData({ weeklyWeek: week, weeklyWeekIndex: week - 1 })
    },

    onClear() {
      clearTimeout(this._suggestTimer)
      this._suggestTouching = false
      this._suggestRequestId = (this._suggestRequestId || 0) + 1
      this._suggestClosedAt = 0
      this._suggestOpenedAt = 0
      this._suggestTouchWasOpen = {}
      this._queryToken = (this._queryToken || 0) + 1
      this._pickedFields = {}
      this._appliedSelections = { names: [], teachers: [], classrooms: [] }
      this.setData({
        courseName: '', teacher: '', classroom: '',
        selectedNames: [], selectedTeachers: [], selectedClassrooms: [],
        activeChips: [], workbenchSelectedCount: 0, workbenchMatchCount: 0,
        weekdayIndex: 0, startPeriodIndex: 0, endPeriodIndex: 0,
        suggestField: '', suggestOptions: [], suggestHeight: 0,
        suggestVisibleCount: 50,
        suggestLoading: false,
        courses: [], total: 0, searched: false,
        errorMsg: '', loading: false, page: 1, hasMore: false, updatedAt: ''
      }, () => {
        if (this.data.showFavoritesOnly) this._renderFavoriteCourses()
      })
    },

    onSearch() {
      clearTimeout(this._suggestTimer)
      this._suggestTouching = false
      this._suggestRequestId = (this._suggestRequestId || 0) + 1
      this._suggestClosedAt = 0
      this._suggestOpenedAt = 0
      this.setData({
        suggestField: '',
        suggestOptions: [],
        suggestHeight: 0,
        suggestVisibleCount: 50,
        suggestLoading: false
      })
      if (this.data.showFavoritesOnly) {
        this._renderFavoriteCourses()
        return
      }
      const hasFilter = [
        this.data.courseName,
        this.data.teacher,
        this.data.classroom,
        this.data.selectedNames.length,
        this.data.selectedTeachers.length,
        this.data.selectedClassrooms.length,
        this.data.weekdayIndex,
        this.data.startPeriodIndex,
        this.data.endPeriodIndex
      ].some(value => String(value || '').trim())
      if (!hasFilter) {
        wx.showToast({ title: '请至少填写一个查询条件', icon: 'none' })
        return
      }
      // 普通输入继续走单值 name/teacher/classroom 参数；
      // 只有扩展查询面板产生的多选才使用数组协议。
      const applied = {
        names: (this.data.selectedNames || []).slice(),
        teachers: (this.data.selectedTeachers || []).slice(),
        classrooms: (this.data.selectedClassrooms || []).slice()
      }
      this._appliedSelections = applied
      this.setData({
        selectedNames: applied.names,
        selectedTeachers: applied.teachers,
        selectedClassrooms: applied.classrooms
      }, () => {
        this._refreshWorkbenchMeta()
        this._query(1)
      })
    },

    applyWorkbenchQuery() {
      if (!this.data.workbenchSelectedCount) {
        wx.showToast({ title: '请至少选择一个条件', icon: 'none' })
        return
      }
      this._saveRecentSelections()
      this._appliedSelections = {
        names: (this.data.selectedNames || []).slice(),
        teachers: (this.data.selectedTeachers || []).slice(),
        classrooms: (this.data.selectedClassrooms || []).slice()
      }
      this.setData({
        showQueryExplorer: false,
        courseName: this.data.selectedNames[0] || '',
        teacher: this.data.selectedTeachers[0] || '',
        classroom: this.data.selectedClassrooms[0] || ''
      }, () => this._query(1))
    },

    _recentStorageKey() {
      const sid = storage.getStudentId() || 'guest'
      const semester = storage.getSemester() || 'default'
      return 'audit_recent_' + sid + '_' + semester
    },

    _loadRecentSelections() {
      const items = storage.getCached(this._recentStorageKey())
      this.setData({ recentItems: Array.isArray(items) ? items : [] })
    },

    _saveRecentSelections() {
      const next = []
      ;(this.data.activeChips || []).forEach(chip => {
        if (chip.field === 'weekday' || chip.field === 'start' ||
            chip.field === 'end') return
        if (!next.some(item => item.field === chip.field &&
            item.value === chip.value)) {
          next.push({
            key: chip.field + ':' + chip.value,
            field: chip.field,
            label: chip.label,
            value: chip.value
          })
        }
      })
      const merged = next.concat((this.data.recentItems || []).filter(item =>
        !next.some(x => x.field === item.field && x.value === item.value)))
        .slice(0, 10)
      storage.setCached(this._recentStorageKey(), merged)
      this.setData({ recentItems: merged })
    },

    onLoadMore() {
      if (this.data.loading || !this.data.hasMore) return
      this._query(this.data.page + 1)
    },

    _loadQueryOptions() {
      if (this._queryOptionsPromise) return this._queryOptionsPromise
      const semester = storage.getSemester() || ''
      const cacheKey = 'cached_audit_options_' + semester
      const cached = storage.getCached(cacheKey)
      if (cached && cached.data
          && cached.format_version === QUERY_OPTIONS_FORMAT) {
        this._applyQueryOptions(cached.data)
        if (cached.version !== undefined) {
          this._queryOptionsPromise = api.listAuditOptions({
            field: 'version',
            semester
          }).then(res => {
            const version = Number((res && res.catalog_version) || 0)
            if (res && res.success
                && version !== Number(cached.version || 0)) {
              return this._fetchAllQueryOptions(semester, cacheKey)
            }
            return true
          }).catch(() => true).then(() => {
            this._queryOptionsPromise = null
            return true
          })
          return this._queryOptionsPromise
        }
      }
      this._queryOptionsPromise = this._fetchAllQueryOptions(
        semester, cacheKey)
      return this._queryOptionsPromise
    },

    _applyQueryOptions(data) {
      const names = (data && data.names) || []
      const teachers = (data && data.teachers) || []
      const classrooms = (data && data.classrooms) || []
      this._queryOptions = {
        names,
        teachers,
        classrooms
      }
      this._relations = ((data && data.relations) || []).map(relation => {
        if (!Array.isArray(relation)) return relation
        return {
          name: names[relation[0]] || '',
          teachers: (relation[1] || [])
            .map(index => teachers[index]).filter(Boolean),
          classrooms: (relation[2] || [])
            .map(index => classrooms[index]).filter(Boolean),
          day: Number(relation[3] || 0),
          start: Number(relation[4] || 0),
          end: Number(relation[5] || 0)
        }
      })
      this._queryOptionsReady = true
      if (this.data.suggestField) {
        this._applyLocalSuggestions(
          this.data.suggestField,
          this.data[this.data.suggestField] || ''
        )
      } else {
        this.setData({ suggestLoading: false })
      }
      this._refreshWorkbenchMeta()
      if (this.data.showQueryExplorer) this._refreshExplorer()
    },

    async _fetchAllQueryOptions(semester, cacheKey) {
      this.setData({ suggestLoading: true })
      try {
        const first = await api.listAuditOptions({
          field: 'all',
          part: 0,
          semester
        })
        if (!first || !first.success) {
          throw new Error((first && first.message) || '查询列表加载失败')
        }
        const version = Number(first.catalog_version || 0)
        const data = {
          names: first.names || [],
          teachers: first.teachers || [],
          classrooms: first.classrooms || [],
          relations: first.relations || []
        }
        const parts = Math.max(1, Number(first.parts || 1))
        for (let part = 1; part < parts; part += 1) {
          const chunk = await api.listAuditOptions({
            field: 'all',
            part,
            semester
          })
          if (!chunk || !chunk.success
              || Number(chunk.catalog_version || 0) !== version) {
            throw new Error((chunk && chunk.message) || '查询列表分片加载失败')
          }
          data.relations = data.relations.concat(chunk.relations || [])
        }
        if (first.relations_total !== undefined
            && data.relations.length !== Number(first.relations_total)) {
          throw new Error('查询列表分片不完整')
        }
        this._applyQueryOptions(data)
        storage.setCached(cacheKey, {
          version,
          format_version: QUERY_OPTIONS_FORMAT,
          data
        })
        this._queryOptionsPromise = null
        return true
      } catch (_e) {
        if (!this._queryOptionsReady) {
          this._applyQueryOptions({
            names: [], teachers: [], classrooms: [], relations: []
          })
        }
        this.setData({
          suggestOptions: [],
          suggestHeight: 0,
          suggestVisibleCount: 50,
          suggestLoading: false
        })
        this._queryOptionsPromise = null
        return false
      }
    },

    _applyLocalSuggestions(field, keyword) {
      if (!this._queryOptionsReady) {
        this.setData({ suggestLoading: true })
        this._loadQueryOptions()
        return
      }
      const allOptions = this._optionsForField(field, keyword)
      this._suggestOptionsAll = allOptions
      this.setData({ suggestVisibleCount: 50 }, () => {
        this._renderSuggestOptions(allOptions)
      })
    },

    _renderSuggestOptions(allOptions) {
      const all = Array.isArray(allOptions) ? allOptions : []
      const visibleCount = Number(this.data.suggestVisibleCount || 50)
      const options = all.slice(0, visibleCount)
      const suggestHeight = options.length > 5
        ? 360
        : options.length * 68
      this.setData({
        suggestOptions: options,
        suggestHeight,
        suggestLoading: false
      })
    },

    _decorate(course) {
      const schedules = (course.schedules || []).map(schedule => {
        const day = Number(schedule.day || 0)
        const start = Number(schedule.start || 0)
        const end = Number(schedule.end || 0)
        return Object.assign({}, schedule, {
          dayName: DAY_NAMES[day] || '时间未知',
          timeText: start ? classClock(start, end) : '',
          periodText: start ? `第${start}-${end}节` : ''
        })
      })
      const days = []
      const periods = []
      const weeks = []
      schedules.forEach(schedule => {
        if (schedule.dayName && days.indexOf(schedule.dayName) < 0) {
          days.push(schedule.dayName)
        }
        if (schedule.periodText && periods.indexOf(schedule.periodText) < 0) {
          periods.push(schedule.periodText)
        }
        if (schedule.weeks && weeks.indexOf(schedule.weeks) < 0) {
          weeks.push(schedule.weeks)
        }
      })
      const periodSummary = periods.slice(0, 3).join('、')
        + (periods.length > 3 ? ' 等' : '')
      const timeTexts = []
      schedules.forEach(schedule => {
        const period = schedule.periodText || '时段未知'
        const clock = schedule.timeText ? ` ${schedule.timeText}` : ''
        if (timeTexts.indexOf(period + clock) < 0) {
          timeTexts.push(period + clock)
        }
      })
      const timeSummary = timeTexts.slice(0, 3).join('、')
        + (timeTexts.length > 3 ? ' 等' : '')
      const favorite = this._findFavorite(course)
      const conflict = this._conflictFor(course)
      return Object.assign({}, course, {
        schedules,
        scheduleCount: schedules.length,
        daySummary: days.join('、'),
        periodSummary: periodSummary || '时段未知',
        timeSummary: timeSummary || '钟点未知',
        weeksSummary: weeks.join('、') || '周次未知',
        _conflict: conflict,
        _conflictText: conflict.text || '',
        _isFavorite: !!favorite,
        _favoriteId: favorite ? favorite.id : '',
        _favoriteKey: favorite
          ? (favorite.favorite_key || auditCourseUtil.favoriteKey(favorite))
          : auditCourseUtil.favoriteKey(course)
      })
    },

    async _query(page) {
      const token = (this._queryToken || 0) + 1
      this._queryToken = token
      const patch = {
        loading: true,
        errorMsg: '',
        searched: page === 1 ? true : this.data.searched
      }
      if (page === 1) {
        Object.assign(patch, {
          courses: [],
          total: 0,
          page: 1,
          hasMore: false,
          updatedAt: ''
        })
      }
      this.setData(patch)
      try {
        const params = {
          weekday: this.data.weekdayIndex,
          jc1: this.data.startPeriodIndex,
          jc2: this.data.endPeriodIndex,
          page,
          limit: 20,
          semester: storage.getSemester() || ''
        }
        const selectedNames = this.data.selectedNames || []
        const selectedTeachers = this.data.selectedTeachers || []
        const selectedClassrooms = this.data.selectedClassrooms || []
        if (selectedNames.length) {
          params.names = JSON.stringify(selectedNames)
          if (selectedNames.length === 1) params.name = selectedNames[0]
          params.name_exact = 1
        } else {
          params.name = String(this.data.courseName || '').trim()
          params.name_exact = this._fieldPicked('courseName') ? 1 : 0
        }
        if (selectedTeachers.length) {
          params.teachers = JSON.stringify(selectedTeachers)
          if (selectedTeachers.length === 1) {
            params.teacher = selectedTeachers[0]
          }
          params.teacher_exact = 1
        } else {
          params.teacher = String(this.data.teacher || '').trim()
          params.teacher_exact = this._fieldPicked('teacher') ? 1 : 0
        }
        if (selectedClassrooms.length) {
          params.classrooms = JSON.stringify(selectedClassrooms)
          if (selectedClassrooms.length === 1) {
            params.classroom = selectedClassrooms[0]
          }
          params.classroom_exact = 1
        } else {
          params.classroom = String(this.data.classroom || '').trim()
          params.classroom_exact = this._fieldPicked('classroom') ? 1 : 0
        }
        const res = await api.searchAuditCourses(params)
        if (token !== this._queryToken) return
        if (!res || !res.success) {
          throw new Error((res && res.message) || '课程查询失败')
        }
        analytics.refreshResult('audit', true, 'audit')
        const fresh = (res.courses || []).map(c => this._decorate(c))
        if (token !== this._queryToken) return
        this.setData({
          courses: page === 1 ? fresh : this.data.courses.concat(fresh),
          total: res.total || fresh.length,
          page: res.page || page,
          hasMore: !!res.has_more,
          updatedAt: fmtTime(res.updated_at),
          loading: false
        })
      } catch (e) {
        if (token !== this._queryToken) return
        this.setData({
          loading: false,
          errorMsg: e.message || '课程查询失败'
        })
        analytics.refreshResult('audit', false, 'audit')
      }
    }
  }
})
