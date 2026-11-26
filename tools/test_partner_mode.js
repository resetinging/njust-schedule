const assert = require('assert')
const fs = require('fs')
const path = require('path')

const ROOT = path.resolve(__dirname, '..')
const values = new Map()

global.wx = {
  getStorageSync: (key) => values.has(key) ? values.get(key) : '',
  setStorageSync: (key, value) => values.set(key, value),
  removeStorageSync: (key) => values.delete(key),
  getStorageInfoSync: () => ({ keys: Array.from(values.keys()) }),
  showToast: () => {},
  showModal: (options) => { if (options && options.success) options.success({ confirm: false }) },
  request: (options) => options.success({
    statusCode: 200,
    data: {
      success: true,
      token: 'partner-token',
      student_id: 'partner-preview',
      student_name: '合作商验收',
      semester: '2026-2027-1',
      role: 'partner',
      partner_mode: true,
      capabilities: { courses: true, exams: true, grades: true, services: true }
    }
  }),
  cloud: {
    callContainer: (options) => options.success({
      statusCode: 200,
      data: {
        success: true,
        token: 'partner-token',
        student_id: 'partner-preview',
        student_name: '合作商验收',
        semester: '2026-2027-1',
        role: 'partner',
        partner_mode: true,
        capabilities: { courses: true, exams: true, grades: true, services: true }
      }
    })
  }
}

const storage = require(path.join(ROOT, 'utils', 'storage'))
const auth = require(path.join(ROOT, 'utils', 'api', 'auth'))
const mainWxml = fs.readFileSync(path.join(ROOT, 'pages', 'main', 'main.wxml'), 'utf8')
const mainJs = fs.readFileSync(path.join(ROOT, 'pages', 'main', 'main.js'), 'utf8')
const tabbar = fs.readFileSync(path.join(ROOT, 'custom-tab-bar', 'index.js'), 'utf8')
const settingsWxml = fs.readFileSync(path.join(ROOT, 'components', 'settings-view', 'index.wxml'), 'utf8')

assert(mainWxml.includes('feature-partner-tag') && mainWxml.includes('>验收<'))
assert(!mainWxml.includes('feature-section-head" wx:if="{{!isPartner}}'), '合作商应保留完整功能导航')
assert(mainWxml.includes('data-page="freeclass" bindtap="onOpenNavPage"'))
assert(!/isPartner.*ALL_TABS\.filter/.test(tabbar), '合作商应保留三个一级 Tab')
assert(tabbar.includes('const list = ALL_TABS'))
assert(mainJs.includes('syncPartnerMode()'))
assert(settingsWxml.includes('学号 / 合作商账号'))
assert(settingsWxml.includes('合作商验收账号'))
assert(settingsWxml.includes('按数据可用性显示'))

;(async () => {
  const result = await auth.loginWebvpn('partner-preview', 'preview-password')
  assert.strictEqual(result.success, true)
  assert.strictEqual(storage.getRole(), 'partner')
  assert.strictEqual(storage.isPartner(), true)
  assert.strictEqual(storage.get('student_id'), 'partner-preview')
  assert.strictEqual(storage.get('token'), 'partner-token')
  assert.deepStrictEqual(
    JSON.parse(storage.get('partner_capabilities')),
    { courses: true, exams: true, grades: true, services: true }
  )
  console.log('Partner shared-login mode test passed [OK]')
})().catch((error) => {
  console.error(error && error.stack || error)
  process.exit(1)
})
