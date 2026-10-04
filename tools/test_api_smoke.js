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
let lastHeaders = {}

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
  // USE_LOCAL=true(本地/素材服务器联调)时请求走 wx.request, 这里同样给桩,
  // 让冒烟测试不依赖当前的路由开关
  request: (o) => { lastHeaders = o.header || {}; o.success({
    statusCode: 200,
    data: { success: true, token: 'tok-1', student_id: '10001', student_name: '测试',
            semester: '2026-2027-1', credential_delete_token: 'del-1' }
  }) },
  cloud: {
    callContainer: (o) => { lastHeaders = o.header || {}; o.success({
      statusCode: 200,
      data: { success: true, token: 'tok-1', student_id: '10001', student_name: '测试',
              semester: '2026-2027-1', credential_delete_token: 'del-1' }
    }) }
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

  await check('导出 58 个接口(含连接测试、服务端凭据删除、同步版本、蹭课收藏与使用统计)', () => {
    assert.strictEqual(Object.keys(api).length, 58, Object.keys(api).join(','))
    assert.strictEqual(typeof api.testConnection, 'function')
    assert.strictEqual(typeof api.searchAuditCourses, 'function')
    assert.strictEqual(typeof api.listAuditOptions, 'function')
    assert.strictEqual(typeof api.listAuditFavorites, 'function')
    assert.strictEqual(typeof api.saveAuditFavorite, 'function')
    assert.strictEqual(typeof api.deleteAuditFavorite, 'function')
    assert.strictEqual(typeof api.getSyncVersions, 'function')
  })
  await check('loginWebvpn 成功路径(存 token/学号/授权密码)', async () => {
    const res = await api.loginWebvpn('10001', 'pwd', true)
    assert.ok(res && res.success, '应返回 success')
    assert.strictEqual(store.get('token'), 'tok-1')
    assert.strictEqual(store.get('student_id'), '10001')
    assert.strictEqual(store.get('credential_delete_token'), 'del-1')
    assert.strictEqual(store.get('saved_password'), 'pwd')
  })
  await check('loginWebvpn 默认保存本地密码(旧参数被忽略)', async () => {
    await api.loginWebvpn('10001', 'pwd', false)
    assert.strictEqual(store.get('saved_password'), 'pwd', 'saved_password 应默认保存')
  })
  await check('logout 清理登录态但保留本地密码', async () => {
    await api.logout()
    assert.ok(!store.get('token'), 'token 应被清除')
    assert.ok(!store.get('credential_delete_token'), '删除 token 应被清除')
    assert.strictEqual(store.get('saved_password'), 'pwd', '退出登录应保留本地密码')
  })
  await check('deleteCredential 携带独立删除 token', async () => {
    store.set('credential_delete_token', 'del-2')
    await api.deleteCredential()
    assert.strictEqual(lastHeaders['X-Credential-Delete-Token'], 'del-2')
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
  // 请求走 wx.request(USE_LOCAL) 还是 callContainer(云端) 取决于路由开关,
  // 因此每次都要同时替换两个桩, 让离线模式相关断言与开关无关
  const stubBoth = (fn) => { global.wx.request = fn; global.wx.cloud.callContainer = fn }

  await check('401 过期: 保留本地缓存并切离线模式', async () => {
    storage.setStudentId('10001')
    storage.set('token', 'tok-old')
    storage.setCached('cached_courses_demo', [{ name: '缓存课程' }])
    stubBoth((o) => o.success({
      statusCode: 401, data: { success: false, message: '尚未登录' }
    }))
    const r = await api.getCourses('demo')
    assert.ok(r && r.success === false, '应返回失败')
    assert.ok(storage.isOffline(), '应切到离线模式')
    assert.ok((storage.getCached('cached_courses_demo') || []).length === 1, '缓存数据必须保留')
    assert.ok(storage.isLoggedIn(), '学号保留(用于离线展示)')
  })
  await check('离线模式: 非登录接口短路(不打网络)', async () => {
    let called = 0
    stubBoth(() => { called++; return null })
    const r = await api.getExams('demo')
    assert.ok(r && r.offline === true, '应返回 offline 标记')
    assert.strictEqual(called, 0, '离线模式不应发起请求')
  })
  await check('离线模式: 登录接口仍可请求(可重新登录)', async () => {
    let called = 0
    stubBoth((o) => {
      called++
      return o.success({ statusCode: 200, data: { success: true, token: 'tok-new' } })
    })
    await api.loginWebvpn('10001', 'pwd')
    assert.strictEqual(called, 1, '登录类接口应正常请求')
  })
  await check('离线模式: 主动刷新可请求并触发重登', async () => {
    let called = 0
    stubBoth((o) => {
      called++
      return o.success({ statusCode: 200, data: { success: true } })
    })
    await api.refreshGrades()
    assert.strictEqual(called, 1, '主动刷新应绕过离线短路')
  })
  await check('相同 GET 在途请求复用一次网络调用', async () => {
    storage.setOffline(false)
    storage.set('token', 'tok-dedupe')
    let called = 0
    stubBoth((o) => {
      called++
      setTimeout(() => o.success({
        statusCode: 200,
        data: { success: true, logged_in: true, first_week_date: '2026-08-24' }
      }), 10)
    })
    const [a, b] = await Promise.all([api.getStatus(), api.getStatus()])
    assert.ok(a && b && a.success && b.success)
    assert.strictEqual(called, 1, '并发相同 GET 应共用同一个 Promise')
  })
  await check('轻量同步状态接口可调用', async () => {
    stubBoth((o) => o.success({
      statusCode: 200,
      data: { success: true, data_refresh: { state: 'running' } }
    }))
    const r = await api.getDataRefreshStatus()
    assert.strictEqual(r.data_refresh.state, 'running')
  })
  await check('测试连接绕过离线短路并返回 ok 状态', async () => {
    storage.setOffline(true)
    let called = 0
    stubBoth((o) => {
      called++
      o.success({ statusCode: 200, data: { ok: true, message: '' } })
    })
    const r = await api.testConnection()
    assert.ok(r && r.ok === true)
    assert.strictEqual(called, 1)
    storage.setOffline(false)
  })

  console.log('\n' + '='.repeat(52))
  console.log('通过 ' + pass + ' / ' + (pass + failures.length))
  if (failures.length) console.log('失败: ' + failures.join(' | '))
  console.log('='.repeat(52))
  process.exit(failures.length ? 1 : 0)
})()
