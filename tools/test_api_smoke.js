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

  await check('导出 40 个接口', () => {
    assert.strictEqual(Object.keys(api).length, 40, Object.keys(api).join(','))
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
  await check('直连登录/loginAuto 不抛依赖错误', async () => {
    await api.loginAuto('10001', 'pwd')
    await api.login('10001', 'pwd', 'abcd', 'cid-1')
    await api.getWebvpnCaptcha('10001', 'pwd')
    await api.loginWebvpnManual('10001', 'pwd', 'abcd', 'cid-1')
  })

  console.log('\n' + '='.repeat(52))
  console.log('通过 ' + pass + ' / ' + (pass + failures.length))
  if (failures.length) console.log('失败: ' + failures.join(' | '))
  console.log('='.repeat(52))
  process.exit(failures.length ? 1 : 0)
})()
