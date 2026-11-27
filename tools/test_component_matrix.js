const assert = require('assert')
const path = require('path')

const ROOT = path.resolve(__dirname, '..')
const SEMESTER = '2026-2027-1'
const store = new Map()

let network = null
let componentConfig = null
let toasts = []
let unhandled = []

process.on('unhandledRejection', (error) => {
  unhandled.push(error)
})

global.wx = {
  getStorageSync: (key) => store.has(key) ? store.get(key) : '',
  setStorageSync: (key, value) => store.set(key, value),
  removeStorageSync: (key) => store.delete(key),
  getStorageInfoSync: () => ({ keys: Array.from(store.keys()) }),
  getWindowInfo: () => ({ windowWidth: 375, windowHeight: 667, safeArea: { bottom: 667 } }),
  showToast: (payload) => toasts.push(payload),
  showLoading: () => {},
  hideLoading: () => {},
  showModal: () => {},
  nextTick: (fn) => { if (typeof fn === 'function') fn() },
  request: (options) => network.respond(options),
  cloud: {
    callContainer: (options) => network.respond(options)
  }
}

const appStub = {
  globalData: {},
  waitForSessionReady: () => Promise.resolve(),
  setLoginState: () => {},
  doLogout: () => Promise.resolve()
}
global.getApp = () => appStub
global.getCurrentPages = () => []
global.Component = (config) => { componentConfig = config }

const storage = require(path.join(ROOT, 'utils', 'storage'))

function inject(relativePath, exports) {
  const filename = require.resolve(path.join(ROOT, relativePath))
  require.cache[filename] = { id: filename, filename, loaded: true, exports }
}

inject('utils/analytics', {
  observeSlots() {},
  disconnectSlots() {},
  track() {},
  refreshResult() {},
  featureOpen() {},
  pageView() {}
})
inject('utils/subscribe', {
  loadStatus: () => Promise.resolve({
    enabled: true,
    kinds: [
      { kind: 'exam', label: '考试提醒', templateId: 'stub-exam', quota: 1 },
      { kind: 'grade', label: '成绩提醒', templateId: 'stub-grade', quota: 1 }
    ]
  }),
  requestGrant: () => Promise.resolve({ ok: true, quota: 1 })
})
inject('utils/announcement', {
  load: () => Promise.resolve({ enabled: true, text: 'test', updated: '2026-11-27' }),
  cached: () => ({ enabled: false, text: '', updated: '' }),
  isNew: () => false,
  markSeen() {}
})
inject('utils/font', {
  getMode: () => 'system',
  setMode() {},
  loadForText: () => Promise.resolve()
})
inject('utils/data-loader', {
  fetchAllData: () => Promise.resolve(0)
})

const states = [
  { key: 'anonymous', sid: '', token: '', password: '', offline: false, mode: 'anonymous' },
  { key: 'valid_ug', sid: '924101960000', token: 'valid-token', password: 'pwd', offline: false, mode: 'valid' },
  { key: 'valid_grad', sid: '126126220000', token: 'valid-token', password: 'pwd', offline: false, mode: 'valid', graduate: true },
  { key: 'expired_saved', sid: '924101960000', token: 'old-token', password: 'pwd', offline: false, mode: 'expired' },
  { key: 'expired_no_pwd', sid: '924101960000', token: 'old-token', password: '', offline: false, mode: 'expired' },
  { key: 'offline_saved', sid: '924101960000', token: '', password: 'pwd', offline: true, mode: 'expired' },
  { key: 'offline_no_pwd', sid: '924101960000', token: '', password: '', offline: true, mode: 'expired' },
  { key: 'partner', sid: 'partner-preview', token: 'partner-token', password: 'pwd', offline: false, mode: 'valid', partner: true }
]

const cacheModes = ['empty', 'full']
const operations = ['schedule', 'exams', 'grades', 'audit_favorites', 'feedback']

function successPayload(pathName, state) {
  if (pathName.includes('/api/login-webvpn')) {
    return {
      success: true,
      token: 'new-token',
      student_id: state.sid,
      student_name: '测试用户',
      semester: SEMESTER,
      role: state.partner ? 'partner' : 'student',
      account_type: state.graduate ? 'graduate' : 'undergraduate'
    }
  }
  if (pathName.includes('/api/status')) {
    return {
      success: true,
      logged_in: true,
      semester: SEMESTER,
      first_week_date: '2026-09-01',
      data_refresh: { state: 'done' }
    }
  }
  if (pathName.includes('/api/semesters')) {
    return { success: true, semesters: [SEMESTER] }
  }
  if (pathName.includes('/api/courses')) {
    return {
      success: true,
      semester: SEMESTER,
      courses: [{
        id: 'course-1',
        name: '高等数学',
        teacher: '张老师',
        classroom: 'Ⅰ-A101',
        day: 1,
        start: 1,
        end: 2,
        weeks: '1-18'
      }]
    }
  }
  if (pathName.includes('/api/exams')) {
    return {
      success: true,
      semester: SEMESTER,
      exams: [{
        course_name: '高等数学',
        date: '2026-12-20',
        time: '09:00~11:00',
        location: 'Ⅰ-A101'
      }]
    }
  }
  if (pathName.includes('/api/yjs/exams')) {
    return { success: true, rows: [] }
  }
  if (pathName.includes('/api/yjs/grades')) {
    return { success: true, stats: [], rows: [] }
  }
  if (pathName.includes('/api/grades')) {
    return {
      success: true,
      semester: SEMESTER,
      grades: [{
        id: 'grade-1',
        course_name: '高等数学',
        course_nature: '必修',
        credit: 4,
        score: '90',
        grade_point: 4
      }]
    }
  }
  if (pathName.includes('/api/cet-scores')) {
    return { success: true, scores: [] }
  }
  if (pathName.includes('/api/audit-favorites')) {
    return { success: true, favorites: [] }
  }
  if (pathName.includes('/api/my-feedback')) {
    return { success: true, feedback: [], unread: 0 }
  }
  if (pathName.includes('/api/calendar')) {
    return { success: true, first_monday: '2026-09-01' }
  }
  if (pathName.includes('/api/announcement')) {
    return { success: true, enabled: true, text: 'test', updated: '2026-11-27' }
  }
  return { success: true }
}

function createNetwork(state) {
  return {
    calls: [],
    respond(options) {
      const pathName = String(options.path || '')
      this.calls.push(pathName)
      const isExpired = state.mode === 'expired' &&
        !pathName.includes('/api/login-webvpn') &&
        !pathName.includes('/api/logout') &&
        storage.get('token', '') !== 'new-token'
      if (isExpired) {
        options.success({
          statusCode: 401,
          data: { success: false, message: '会话失效' }
        })
        return
      }
      options.success({
        statusCode: 200,
        data: successPayload(pathName, state)
      })
    }
  }
}

function seedStore(state, cacheMode) {
  store.clear()
  toasts = []
  appStub.globalData = {}
  if (state.sid) storage.setStudentId(state.sid)
  if (state.token) storage.set('token', state.token)
  if (state.password) storage.set('saved_password', state.password)
  storage.set('semester', SEMESTER)
  storage.setOffline(state.offline)
  storage.setRole(state.partner ? 'partner' : 'student')
  storage.set('account_type', state.graduate ? 'graduate' : 'undergraduate')
  if (state.sid) {
    storage.set('exam_auto_refresh_' + state.sid + '_' + SEMESTER, String(Date.now()))
  }
  if (cacheMode !== 'full') return

  storage.setCached('cached_courses_' + SEMESTER, [{
    id: 'cache-course',
    name: '缓存课程',
    teacher: '李老师',
    classroom: 'Ⅱ-B201',
    day: 2,
    start: 3,
    end: 4,
    weeks: '1-18'
  }])
  storage.setCached('semester_list', [SEMESTER])
  storage.setCached('cached_exams_' + SEMESTER, [{
    course_name: '缓存考试',
    date: '2026-12-21',
    time: '09:00~11:00',
    location: 'Ⅱ-B201'
  }])
  storage.setCached('cached_yjs_exams', { success: true, rows: [] })
  storage.setCached('cached_grades', {
    success: true,
    grades: [{
      id: 'cache-grade',
      course_name: '缓存课程',
      course_nature: '必修',
      credit: 2,
      score: '85',
      grade_point: 3.5
    }]
  })
  storage.setCached('cached_yjs_grades', { success: true, stats: [], rows: [] })
  storage.setCached('cached_cet_scores', { success: true, scores: [] })
  storage.setCached('audit_favorites_' + state.sid + '_' + SEMESTER, [{
    id: 'favorite-1',
    course_name: '蹭课课程',
    teacher: '王老师',
    classroom: 'Ⅲ-C301',
    day_of_week: 3,
    start_period: 5,
    end_period: 6,
    weeks: '1-18'
  }])
  storage.setCached('cached_status_' + state.sid + '_' + SEMESTER, {
    t: Date.now(),
    first_week_date: '2026-09-01'
  })
}

function loadComponent(relativePath) {
  componentConfig = null
  require(path.join(ROOT, relativePath))
  assert.ok(componentConfig && componentConfig.methods, 'component not loaded: ' + relativePath)
  return componentConfig
}

function instanceOf(config) {
  const baseData = typeof config.data === 'function' ? config.data() : config.data
  return Object.assign({}, config.methods, {
    data: JSON.parse(JSON.stringify(baseData || {})),
    setData(patch, callback) {
      Object.assign(this.data, patch || {})
      if (typeof callback === 'function') setTimeout(callback, 0)
    },
    triggerEvent() {}
  })
}

async function settle(rounds) {
  for (let i = 0; i < (rounds || 8); i++) {
    await new Promise((resolve) => setTimeout(resolve, 0))
  }
}

const components = {
  schedule: loadComponent('components/schedule-view/index.js'),
  exams: loadComponent('components/exams-view/index.js'),
  grades: loadComponent('components/grades-view/index.js'),
  settings: loadComponent('components/settings-view/index.js')
}

async function execute(state, cacheMode, operation) {
  seedStore(state, cacheMode)
  network = createNetwork(state)

  if (operation === 'schedule') {
    const instance = instanceOf(components.schedule)
    instance._customs = []
    instance._auditFavorites = []
    instance.activate()
    await settle(12)
    assert.ok(Array.isArray(instance.data.courses), 'schedule courses must stay an array')
    if (state.offline && cacheMode === 'full') {
      assert.ok(instance.data.courses.length > 0, 'schedule full cache should render offline')
    }
  } else if (operation === 'exams') {
    const instance = instanceOf(components.exams)
    instance._detached = false
    instance._loadedSemester = undefined
    instance._reqSeq = 0
    instance._activeIdentity = instance._identityKey()
    instance.activate()
    await settle(8)
    assert.ok(Array.isArray(instance.data.exams), 'exams must stay an array')
    assert.ok(Array.isArray(instance.data.examRows), 'exam rows must stay an array')
    if (state.offline && cacheMode === 'full' && !state.graduate) {
      assert.ok(instance.data.exams.length > 0, 'exam full cache should render offline')
    }
  } else if (operation === 'grades') {
    const instance = instanceOf(components.grades)
    instance.activate()
    await settle(10)
    assert.ok(Array.isArray(instance.data.semGroups), 'grade groups must stay an array')
    if (state.offline && cacheMode === 'full' && !state.graduate) {
      assert.ok(instance.data.semGroups.length > 0, 'grade full cache should render offline')
    }
  } else if (operation === 'audit_favorites') {
    const instance = instanceOf(components.schedule)
    instance._customs = []
    instance._auditFavorites = []
    await instance._loadAuditFavorites()
    await settle(4)
    assert.ok(Array.isArray(instance._auditFavorites), 'favorites must stay an array')
    if (state.offline && cacheMode === 'full') {
      assert.ok(instance._auditFavorites.length > 0, 'favorite cache should survive offline')
    }
  } else if (operation === 'feedback') {
    const instance = instanceOf(components.settings)
    await instance._loadMyFeedback(false)
    await settle(4)
    assert.ok(Array.isArray(instance.data.myFeedback), 'feedback must stay an array')
  }

  const loginCalls = network.calls.filter((item) => item.includes('/api/login-webvpn')).length
  const protectedCalls = network.calls.filter((item) => !item.includes('/api/login-webvpn') &&
    !item.includes('/api/logout'))

  if (state.key === 'anonymous' || state.offline) {
    assert.strictEqual(network.calls.length, 0,
      `${state.key}/${cacheMode}/${operation}: should not touch network: ${network.calls.join(',')}`)
  }

  if (state.partner) {
    assert.strictEqual(loginCalls, 0,
      `${state.key}/${cacheMode}/${operation}: partner must never auto-relogin`)
  }

  if (state.graduate && operation === 'exams') {
    assert.ok(!network.calls.some((item) => item === '/api/exams'),
      `${state.key}/${cacheMode}/${operation}: graduate must not call undergraduate exams`)
  }
  if (state.graduate && operation === 'grades') {
    assert.ok(!network.calls.some((item) => item === '/api/grades'),
      `${state.key}/${cacheMode}/${operation}: graduate must not call undergraduate grades`)
  }

  if (state.mode === 'expired' && state.password && loginCalls > 0) {
    assert.strictEqual(loginCalls, 1,
      `${state.key}/${cacheMode}/${operation}: concurrent 401s should share one relogin`)
    assert.strictEqual(storage.get('token'), 'new-token',
      `${state.key}/${cacheMode}/${operation}: recovered token was not persisted`)
    assert.strictEqual(storage.isOffline(), false,
      `${state.key}/${cacheMode}/${operation}: recovery should clear offline mode`)
  }

  if (state.mode === 'expired' && !state.password && protectedCalls.length > 0) {
    assert.strictEqual(storage.isOffline(), true,
      `${state.key}/${cacheMode}/${operation}: failed recovery should enter offline mode`)
    assert.ok(!storage.get('token'),
      `${state.key}/${cacheMode}/${operation}: failed recovery should clear token`)
  }
}

;(async () => {
  let executed = 0
  for (const state of states) {
    for (const cacheMode of cacheModes) {
      for (const operation of operations) {
        await execute(state, cacheMode, operation)
        if (unhandled.length) {
          throw unhandled[0]
        }
        executed++
      }
    }
  }
  console.log(`Component state matrix passed [OK] ${executed}/${executed}`)
})().catch((error) => {
  console.error(error && error.stack || error)
  process.exit(1)
})
