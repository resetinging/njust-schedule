/**
 * API 模块冒烟 — 用 wx 桩件跑通登录/退出等关键路径,
 * 防止 utils/api.js 拆分后再次出现"遗漏依赖(ReferenceError)"类问题。
 *
 * 用法: node tools/test_api_smoke.js [仓库根目录]
 */
const assert = require('assert')
const path = require('path')

const ROOT = path.resolve(process.argv[2] || path.join(__dirname, '..'))
const store = new Map()

global.wx = {
  getStorageSync: (k) => (store.has(k) ? store.get(k) : ''),
  setStorageSync: (k, v) => { store.set(k, v) },
  removeStorageSync: (k) => { store.delete(k) },
  getStorageInfoSync: () => ({ keys: Array.from(store.keys()) }),
  showToast: () => {},
  hideLoading: () => {},
  showLoading: () => {},
  showModal: (o) => { if (o && o.success) o.success({ confirm: false }) },
  getWindowInfo: () => ({ windowWidth: 375, windowHeight: 667, safeArea: { bottom: 667 } }),
  cloud: {
    callContainer: (o) => o.success({
      statusCode: 200,
      data: { success: true, token: 'tok-1', student_id: '10001', student_name: '测试', semester: '2026-2027-1' }
    })
  }
}

let pass = 0
const failures = []
async function check(name, fn) {
  try {
    await fn()
    pass++
    console.log('  ✓ ' + name)
  } catch (e) {
    failures.push(name)
    console.log('  ✗ ' + name + '  → ' + e.message)
  }
}

;(async () => {
  const api = require(path.join(ROOT, 'utils', 'api'))

  await check('导出 38 个接口(含微信扫码登录 3 个)', () => {
    assert.strictEqual(Object.keys(api).length, 38, Object.keys(api).join(','))
  })
  await check('loginWebvpn 成功路径(存 token/学号)', async () => {
    const res = await api.loginWebvpn('10001', 'pwd')
    assert.ok(res && res.success, '应返回 success')
    assert.strictEqual(store.get('token'), 'tok-1')
    assert.strictEqual(store.get('student_id'), '10001')
  })
  await check('logout 清理本地登录态', async () => {
    await api.logout()
    assert.ok(!store.get('token'), 'token 应被清除')
  })
  await check('教务直连/第二步登录接口已移除, 智慧理工一步登录可用', async () => {
    assert.strictEqual(typeof api.login, 'undefined', 'login 应已移除')
    assert.strictEqual(typeof api.loginAuto, 'undefined', 'loginAuto 应已移除')
    assert.strictEqual(typeof api.getCaptcha, 'undefined', 'getCaptcha 应已移除')
    assert.strictEqual(typeof api.getWebvpnCaptcha, 'undefined', 'getWebvpnCaptcha 应已移除')
    assert.strictEqual(typeof api.loginWebvpnManual, 'undefined', 'loginWebvpnManual 应已移除')
    await api.loginWebvpn('10001', 'pwd')
  })

  // ── 离线模式: 登录失效后保留本地缓存继续展示 ──
  const storage = require(path.join(ROOT, 'utils', 'storage'))
  await check('401 过期: 保留本地缓存并切离线模式', async () => {
    storage.setStudentId('10001')
    storage.set('token', 'tok-old')
    storage.setCached('cached_courses_demo', [{ name: '缓存课程' }])
    global.wx.cloud.callContainer = (o) => o.success({
      statusCode: 401, data: { success: false, message: '尚未登录' }
    })
    const r = await api.getCourses('demo')
    assert.ok(r && r.success === false, '应返回失败')
    assert.ok(storage.isOffline(), '应切到离线模式')
    assert.ok((storage.getCached('cached_courses_demo') || []).length === 1, '缓存数据必须保留')
    assert.ok(storage.isLoggedIn(), '学号保留(用于离线展示)')
  })
  await check('离线模式: 非登录接口短路(不打网络)', async () => {
    let called = 0
    global.wx.cloud.callContainer = () => { called++; return null }
    const r = await api.getExams('demo')
    assert.ok(r && r.offline === true, '应返回 offline 标记')
    assert.strictEqual(called, 0, '离线模式不应发起请求')
  })
  await check('离线模式: 登录接口仍可请求(可重新登录)', async () => {
    let called = 0
    global.wx.cloud.callContainer = (o) => {
      called++
      return o.success({ statusCode: 200, data: { success: true, token: 'tok-new' } })
    }
    await api.loginWebvpn('10001', 'pwd')
    assert.strictEqual(called, 1, '登录类接口应正常请求')
  })

  console.log('\n' + '='.repeat(52))
  console.log('通过 ' + pass + ' / ' + (pass + failures.length))
  if (failures.length) console.log('失败: ' + failures.join(' | '))
  console.log('='.repeat(52))
  process.exit(failures.length ? 1 : 0)
})()
