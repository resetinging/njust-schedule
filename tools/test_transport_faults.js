const assert = require('assert')
const path = require('path')

const ROOT = path.resolve(__dirname, '..')
const store = new Map()

let handler = null
let calls = []
let toasts = []

global.wx = {
  getStorageSync: (key) => store.has(key) ? store.get(key) : '',
  setStorageSync: (key, value) => store.set(key, value),
  removeStorageSync: (key) => store.delete(key),
  getStorageInfoSync: () => ({ keys: Array.from(store.keys()) }),
  showToast: (payload) => toasts.push(payload),
  cloud: {
    callContainer: (options) => handler(options)
  }
}
global.getApp = () => ({ globalData: {} })
global.getCurrentPages = () => []

const storage = require(path.join(ROOT, 'utils', 'storage'))
const api = require(path.join(ROOT, 'utils', 'api'))

function reset(savedPassword) {
  store.clear()
  calls = []
  toasts = []
  storage.setStudentId('924101960000')
  storage.set('token', 'old-token')
  storage.set('semester', '2026-2027-1')
  storage.setOffline(false)
  if (savedPassword) storage.set('saved_password', savedPassword)
}

function success(options, data, statusCode) {
  options.success({ statusCode: statusCode || 200, data })
}

function fail(options, message) {
  options.fail({ errMsg: message || 'request:fail' })
}

async function run() {
  reset('pwd')
  handler = (options) => {
    calls.push({ path: options.path, method: options.method })
    fail(options, 'request:fail timeout')
  }
  let result = await api.getCourses('2026-2027-1')
  assert.strictEqual(result.success, false)
  assert.strictEqual(calls.length, 1)
  assert.ok(!calls.some((item) => item.path.includes('/api/login-webvpn')))
  assert.strictEqual(storage.isOffline(), false, 'transport timeout must not masquerade as session expiry')
  assert.strictEqual(toasts.length, 0, 'transport timeout must not show offline/session toast')

  reset('pwd')
  handler = (options) => {
    calls.push({ path: options.path, method: options.method })
    success(options, { success: false, message: 'gateway unavailable' }, 502)
  }
  result = await api.getCourses('2026-2027-1')
  assert.strictEqual(result.success, false)
  assert.strictEqual(calls.length, 1)
  assert.strictEqual(storage.get('token'), 'old-token')
  assert.strictEqual(storage.isOffline(), false)

  reset('pwd')
  handler = (options) => {
    calls.push({ path: options.path, method: options.method })
    if (options.path === '/api/login-webvpn') {
      success(options, {
        success: true,
        token: 'new-token',
        student_id: '924101960000',
        semester: '2026-2027-1',
        role: 'student',
        account_type: 'undergraduate'
      })
      return
    }
    if (storage.get('token') === 'old-token') {
      success(options, { success: false, message: '会话失效' }, 401)
      return
    }
    success(options, { success: true, courses: [] })
  }
  result = await api.getCourses('2026-2027-1')
  assert.strictEqual(result.success, true)
  assert.strictEqual(storage.get('token'), 'new-token')
  assert.strictEqual(calls.filter((item) => item.path === '/api/login-webvpn').length, 1)
  assert.strictEqual(calls.filter((item) => item.path === '/api/courses').length, 2)

  reset('pwd')
  let loginPromise = null
  handler = (options) => {
    calls.push({ path: options.path, method: options.method })
    if (options.path === '/api/login-webvpn') {
      if (!loginPromise) {
        loginPromise = new Promise((resolve) => {
          setTimeout(() => {
            success(options, {
              success: true,
              token: 'new-token',
              student_id: '924101960000',
              semester: '2026-2027-1',
              role: 'student',
              account_type: 'undergraduate'
            })
            resolve()
          }, 20)
        })
      }
      return
    }
    if (storage.get('token') === 'old-token') {
      success(options, { success: false, message: '会话失效' }, 401)
      return
    }
    success(options, { success: true, courses: [], exams: [] })
  }
  const [courses, exams] = await Promise.all([
    api.getCourses('semester-a'),
    api.getExams('semester-a')
  ])
  assert.strictEqual(courses.success, true)
  assert.strictEqual(exams.success, true)
  assert.strictEqual(
    calls.filter((item) => item.path === '/api/login-webvpn').length,
    1,
    'concurrent 401 responses must share one relogin'
  )

  reset('pwd')
  handler = (options) => {
    calls.push({ path: options.path, method: options.method })
    if (options.path === '/api/login-webvpn') {
      success(options, { success: false, message: 'too many requests' }, 429)
      return
    }
    success(options, { success: false, message: '会话失效' }, 401)
  }
  result = await api.getCourses('2026-2027-1')
  assert.strictEqual(result.success, false)
  assert.strictEqual(calls.filter((item) => item.path === '/api/login-webvpn').length, 1)
  assert.strictEqual(storage.isOffline(), true)
  assert.ok(!storage.get('token'))

  reset('pwd')
  handler = (options) => {
    calls.push({ path: options.path, method: options.method })
    fail(options, 'request:fail connection reset')
  }
  result = await api.submitFeedback('bug', 'transport fault test')
  assert.strictEqual(result.success, false)
  assert.strictEqual(calls.filter((item) => item.path === '/api/feedback').length, 1,
    'failed POST must not be retried automatically')
  assert.ok(!calls.some((item) => item.path === '/api/login-webvpn'))

  console.log('Transport fault tests passed [OK] 6/6')
}

run().catch((error) => {
  console.error(error && error.stack || error)
  process.exit(1)
})
