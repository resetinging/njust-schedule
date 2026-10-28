const assert = require('assert')
const fs = require('fs')
const path = require('path')

const ROOT = path.resolve(__dirname, '..')
const values = new Map()

global.wx = {
  getStorageSync: key => values.has(key) ? values.get(key) : '',
  setStorageSync: (key, value) => values.set(key, value),
  removeStorageSync: key => values.delete(key),
  getStorageInfoSync: () => ({ keys: Array.from(values.keys()) })
}

const storage = require(path.join(ROOT, 'utils', 'storage'))

assert.strictEqual(storage.hasSession(), false)
storage.setStudentId('924101960123')
assert.strictEqual(storage.hasSession(), false, '只有学号时不得发起受保护请求')
storage.set('token', 'token-1')
assert.strictEqual(storage.hasSession(), true)
storage.setOffline(true)
assert.strictEqual(storage.hasSession(), false, '离线模式不得发起受保护请求')

const schedule = fs.readFileSync(path.join(ROOT, 'components', 'schedule-view', 'index.js'), 'utf8')
const audit = fs.readFileSync(path.join(ROOT, 'components', 'audit-course-view', 'index.js'), 'utf8')
assert(schedule.includes("if (!storage.hasSession()) return"), '课表收藏请求缺少会话守卫')
assert(audit.includes("if (!storage.hasSession())"), '蹭课收藏请求缺少会话守卫')
assert.strictEqual((schedule.match(/storage\.hasSession\(\)/g) || []).length, 3)
assert.strictEqual((audit.match(/storage\.hasSession\(\)/g) || []).length, 4)

console.log('Session guard test passed [OK]')
