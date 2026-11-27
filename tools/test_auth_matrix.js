const assert = require('assert')
const path = require('path')

const ROOT = path.resolve(__dirname, '..')
const store = new Map()

let network = null
let toasts = []

global.wx = {
  getStorageSync: (key) => store.has(key) ? store.get(key) : '',
  setStorageSync: (key, value) => store.set(key, value),
  removeStorageSync: (key) => store.delete(key),
  getStorageInfoSync: () => ({ keys: Array.from(store.keys()) }),
  showToast: (payload) => toasts.push(payload),
  showModal: () => {},
  hideLoading: () => {},
  showLoading: () => {},
  getWindowInfo: () => ({ windowWidth: 375, windowHeight: 667, safeArea: { bottom: 667 } }),
  request: (options) => network.respond(options),
  cloud: {
    callContainer: (options) => network.respond(options)
  }
}

global.getApp = () => ({ globalData: {}, waitForSessionReady: () => Promise.resolve() })
global.getCurrentPages = () => []

const storage = require(path.join(ROOT, 'utils', 'storage'))
const api = require(path.join(ROOT, 'utils', 'api'))

const SEMESTER = '2026-2027-1'

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

const operations = [
  'cold_start',
  'resume',
  'enter_schedule',
  'enter_exams',
  'enter_grades',
  'audit_favorites',
  'feedback',
  'refresh_exams',
  'network_failure',
  'server_error',
  'manual_logout'
]

const caches = ['empty', 'full']

function cacheKey() {
  return 'audit_favorites_' + (storage.getStudentId() || 'guest') + '_' + (storage.getSemester() || 'default')
}

function reset(state, cacheMode) {
  store.clear()
  toasts = []
  if (state.sid) storage.setStudentId(state.sid)
  if (state.token) storage.set('token', state.token)
  if (state.password) storage.set('saved_password', state.password)
  storage.set('semester', SEMESTER)
  storage.setOffline(state.offline)
  storage.setRole(state.partner ? 'partner' : 'student')
  if (state.graduate) storage.set('account_type', 'graduate')
  if (cacheMode === 'full') {
    storage.setCached(cacheKey(), [{ id: 'favorite-1' }])
    storage.setCached('cached_grades', { success: true, grades: [{ id: 1, credit: 2, score: '90' }] })
    storage.setCached('cached_exams_' + SEMESTER, [{ course_name: '缓存考试' }])
  }
}

function successPayload(pathName) {
  const payload = {
    success: true,
    logged_in: true,
    semester: SEMESTER,
    courses: [],
    exams: [],
    grades: [],
    favorites: [],
    feedback: [],
    scores: [],
    count: 0
  }
  if (pathName.includes('login-webvpn')) {
    payload.token = 'new-token'
    payload.student_id = '924101960000'
    payload.student_name = '测试用户'
  }
  if (pathName.includes('yjs/')) payload.account_type = 'graduate'
  return payload
}

function createNetwork(state, operation) {
  let endpointAttempts = 0
  const calls = []
  return {
    calls,
    respond(options) {
      const pathName = options.path || ''
      calls.push(pathName)
      const isLogin = /\/api\/(login|logout)/.test(pathName)
      if (isLogin) {
        options.success({ statusCode: 200, data: successPayload(pathName) })
        return
      }
      if (operation === 'network_failure') {
        options.fail({ errMsg: 'network unavailable' })
        return
      }
      if (operation === 'server_error') {
        options.success({ statusCode: 500, data: { success: false, message: 'server error' } })
        return
      }
      if (state.mode === 'expired' && endpointAttempts++ === 0) {
        options.success({ statusCode: 401, data: { success: false, message: '会话失效' } })
        return
      }
      options.success({ statusCode: 200, data: successPayload(pathName) })
    }
  }
}

function isForceOperation(operation) {
  return operation === 'cold_start' || operation === 'refresh_exams'
}

function isOfflineShortCircuit(state, operation) {
  return state.offline && !isForceOperation(operation) && operation !== 'manual_logout'
}

function exercisesSessionExpiry(state, operation) {
  return state.mode === 'expired' &&
    !isOfflineShortCircuit(state, operation) &&
    operation !== 'network_failure' &&
    operation !== 'server_error' &&
    operation !== 'manual_logout'
}

function expectedLoginCalls(state, operation) {
  if (state.partner) return 0
  if (isOfflineShortCircuit(state, operation)) return 0
  if (exercisesSessionExpiry(state, operation) && state.password) return 1
  return 0
}

async function execute(state, cacheMode, operation) {
  reset(state, cacheMode)
  network = createNetwork(state, operation)
  let result
  switch (operation) {
    case 'cold_start': result = await api.getStatus({ force: true }); break
    case 'resume': result = await api.getStatus(); break
    case 'enter_schedule': result = await api.getCourses(SEMESTER); break
    case 'enter_exams': result = state.graduate ? await api.getYjsExams() : await api.getExams(SEMESTER); break
    case 'enter_grades': result = state.graduate ? await api.getYjsGrades() : await api.getGrades('__all__'); break
    case 'audit_favorites': result = await api.listAuditFavorites({ semester: SEMESTER }); break
    case 'feedback': result = await api.getMyFeedback(); break
    case 'refresh_exams': result = await api.refreshExams(); break
    case 'network_failure':
    case 'server_error': result = await api.getCourses(SEMESTER); break
    case 'manual_logout': result = await api.logout(); break
    default: throw new Error('unknown operation: ' + operation)
  }

  const loginCalls = network.calls.filter((item) => item.includes('/api/login-webvpn')).length
  assert.strictEqual(
    loginCalls,
    expectedLoginCalls(state, operation),
    `${state.key}/${cacheMode}/${operation}: unexpected login calls ${network.calls.join(',')}`
  )

  if (isOfflineShortCircuit(state, operation)) {
    assert.strictEqual(network.calls.length, 0, `${state.key}/${cacheMode}/${operation}: offline operation should not call network`)
    assert.ok(result && result.offline === true, `${state.key}/${cacheMode}/${operation}: should return offline result`)
  }

  if (exercisesSessionExpiry(state, operation) && state.password && !state.partner) {
    assert.strictEqual(storage.get('token'), 'new-token', `${state.key}/${cacheMode}/${operation}: token not recovered`)
    assert.strictEqual(storage.isOffline(), false, `${state.key}/${cacheMode}/${operation}: offline flag not cleared`)
  }

  if (exercisesSessionExpiry(state, operation) && !state.password && !state.partner) {
    assert.strictEqual(storage.isOffline(), true, `${state.key}/${cacheMode}/${operation}: failed recovery should enter offline mode`)
  }

  if (state.offline && cacheMode === 'full' && operation !== 'manual_logout') {
    assert.ok((storage.getCached(cacheKey()) || []).length > 0, `${state.key}/${cacheMode}/${operation}: cache must survive offline`)
  }

  if (operation === 'manual_logout') {
    assert.ok(!storage.get('token'), `${state.key}/${cacheMode}/${operation}: token should be cleared`)
    assert.strictEqual(storage.get('saved_password', ''), state.password || '', `${state.key}/${cacheMode}/${operation}: saved password should survive`)
    assert.strictEqual(storage.get('manual_logout'), true, `${state.key}/${cacheMode}/${operation}: manual logout flag missing`)
  }

  if (operation === 'network_failure' && !isOfflineShortCircuit(state, operation)) {
    assert.ok(result && result.success === false, `${state.key}/${cacheMode}/${operation}: network failure should return failure`)
    assert.strictEqual(toasts.length, 0, `${state.key}/${cacheMode}/${operation}: transport failure should not show success/offline toast`)
  }

  if (operation === 'server_error' && !isOfflineShortCircuit(state, operation)) {
    assert.ok(result && result.success === false, `${state.key}/${cacheMode}/${operation}: 500 should return failure`)
  }

  if (state.partner) {
    assert.strictEqual(loginCalls, 0, `${state.key}/${cacheMode}/${operation}: partner must never auto-relogin`)
  }
}

;(async () => {
  let executed = 0
  for (const state of states) {
    for (const cacheMode of caches) {
      for (const operation of operations) {
        await execute(state, cacheMode, operation)
        executed++
      }
    }
  }
  console.log(`Auth state matrix passed [OK] ${executed}/${executed}`)
})().catch((error) => {
  console.error(error && error.stack || error)
  process.exit(1)
})
