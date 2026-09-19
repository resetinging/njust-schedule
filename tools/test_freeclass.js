/**
 * 空教室页逻辑测试 — 在 Node 中用桩件模拟小程序运行时,
 * 真实加载 pages/freeclass/freeclass.js 并驱动它的 search()。
 *
 * 覆盖本次修复:
 *   1. 请求竞态: 快速切换筛选时, 先发的慢响应不得覆盖后发的结果
 *   2. 缓存键: 含学期; 且响应回来后同时按"后端解析后的实际条件"再存一份
 *      (今天/本周 → 具体星期/周次), 使等价查询能复用缓存
 *   3. 楼名映射: 后端 buildings 是 [{code,name}] 对象数组, 前缀应映射成"Ⅳ教学楼"
 *
 * 运行: node tools/test_freeclass.js [小程序根目录]
 */
const assert = require('assert')
const path = require('path')

const ROOT = path.resolve(process.argv[2] || path.join(__dirname, '..'))

// ---------------- 小程序运行时桩件(带真实存储, 让缓存逻辑真正跑起来) ----------------
const store = new Map()
store.set('student_id', '924101960123')
store.set('semester', '2026-2027-1')

global.wx = new Proxy({}, {
  get(_t, prop) {
    if (prop === 'getStorageSync') return (k) => (store.has(k) ? store.get(k) : '')
    if (prop === 'setStorageSync') return (k, v) => { store.set(k, v) }
    if (prop === 'removeStorageSync') return (k) => { store.delete(k) }
    if (prop === 'getStorageInfoSync') return () => ({ keys: Array.from(store.keys()) })
    return () => undefined
  }
})
global.getCurrentPages = () => []
global.getApp = () => ({ globalData: {} })

let pageCfg = null
global.Page = (cfg) => { pageCfg = cfg }

let pass = 0
const failures = []
function check(name, fn) {
  try {
    fn()
    pass++
    console.log('  ✓ ' + name)
  } catch (e) {
    failures.push(name)
    console.log('  ✗ ' + name + '  → ' + e.message)
  }
}

function deferred() {
  let resolve
  const promise = new Promise(r => { resolve = r })
  return { promise, resolve }
}

;(async () => {
  // ---------------- 装载 api 桩件 + 页面 ----------------
  const api = require(path.join(ROOT, 'utils', 'api'))
  const calls = []
  let nextDeferred = null
  api.getFreeClassrooms = (params) => {
    calls.push(params)
    const d = nextDeferred
    nextDeferred = null
    return d ? d.promise : Promise.resolve(null)
  }
  require(path.join(ROOT, 'pages', 'freeclass', 'freeclass.js'))

  const inst = Object.assign({}, pageCfg, {
    data: JSON.parse(JSON.stringify(pageCfg.data)),
    setData(patch) { Object.assign(this.data, patch) }
  })

  console.log('加载页面: ' + path.join(ROOT, 'pages/freeclass/freeclass.js') + '\n')
  check('周次列表覆盖教务借用页 1-30 周', () => {
    assert.strictEqual(inst.data.weekList.length, 31, JSON.stringify(inst.data.weekList.length))
    assert.ok(inst.data.weekList.indexOf('第30周') >= 0)
  })
  console.log('1) 请求竞态: 慢响应不得覆盖新结果')
  const dA = deferred()
  nextDeferred = dA
  const pA = inst.search()                       // A: 默认(今天/本周/第6-7节)
  inst.setData({ weekdayIndex: 3, weekIndex: 5, startIndex: 0, endIndex: 0 })
  const dB = deferred()
  nextDeferred = dB
  const pB = inst.search()                       // B: 星期三/第5周/第1-3节
  dB.resolve({ success: true, campus: '孝陵卫', weekday: 3, week: 5, jc1: 1, jc2: 3,
    weekday_name: '星期三', time_text: '第1-3节', count: 2,
    rooms: ['Ⅳ教学楼-B201', 'Ⅳ教学楼-B202'], buildings: [],
    semester: '2026-2027-1', updated_at: 111 })
  await pB
  dA.resolve({ success: true, campus: '孝陵卫', weekday: 6, week: 3, jc1: 1, jc2: 3,
    weekday_name: '星期六', time_text: '第1-3节', count: 99,
    rooms: ['Ⅳ教学楼-A101'], buildings: [], semester: '2026-2027-1', updated_at: 222 })
  await pA
  check('过期响应被丢弃(仍是星期三的结果)', () => {
    assert.strictEqual(inst.data.result.count, 2)
    assert.ok(inst.data.result.summary.indexOf('星期三') >= 0, inst.data.result.summary)
  })
  check('请求参数含学期(供后端/缓存键使用)', () => {
    assert.strictEqual(calls[calls.length - 1].semester, '2026-2027-1')
  })

  console.log('\n2) 缓存键: 含学期 + 解析后条件各存一份')
  check('结果按楼名前缀分组(后端已映射楼名)', () => {
    const g = inst.data.groups.find(x => x.prefix === 'Ⅳ教学楼')
    assert.ok(g && g.label === 'Ⅳ教学楼' && g.rooms.length === 2, JSON.stringify(inst.data.groups))
  })
  const box = JSON.parse(store.get('freeclass_cache_v2') || '{}')
  const keys = Object.keys(box.items || {})
  check('键含学期', () => {
    assert.ok(keys.length > 0 && keys.every(k => k.indexOf('2026-2027-1') >= 0), JSON.stringify(keys))
  })
  check('被丢弃的 A 请求没有写缓存', () => {
    assert.strictEqual(keys.indexOf('孝陵卫|0|0|6|7|2026-2027-1'), -1, JSON.stringify(keys))
  })
  check('B 的结果已缓存(请求键 == 解析键)', () => {
    assert.ok(keys.indexOf('孝陵卫|3|5|1|3|2026-2027-1') >= 0, JSON.stringify(keys))
  })

  console.log('\n2b) 今天/本周: 请求键(0/0)与后端解析键(6/3)各存一份')
  inst.setData({ weekdayIndex: 0, weekIndex: 0, startIndex: 0, endIndex: 0 })
  const dC = deferred()
  nextDeferred = dC
  const pC = inst.search()
  dC.resolve({ success: true, campus: '孝陵卫', weekday: 6, week: 3, jc1: 1, jc2: 3,
    weekday_name: '星期六', time_text: '第1-3节', count: 7,
    rooms: ['东区平房-101'], buildings: [], semester: '2026-2027-1', updated_at: 333 })
  await pC
  check('映射楼名(东区平房-101)分组正确', () => {
    const g = inst.data.groups.find(x => x.prefix === '东区平房')
    assert.ok(g && g.label === '东区平房', JSON.stringify(inst.data.groups))
  })
  const box2 = JSON.parse(store.get('freeclass_cache_v2') || '{}')
  const keys2 = Object.keys(box2.items || {})
  check('请求键(今天/本周)已缓存', () => {
    assert.ok(keys2.indexOf('孝陵卫|0|0|1|3|2026-2027-1') >= 0, JSON.stringify(keys2))
  })
  check('解析键(星期六/第3周)也已缓存', () => {
    assert.ok(keys2.indexOf('孝陵卫|6|3|1|3|2026-2027-1') >= 0, JSON.stringify(keys2))
  })

  console.log('\n3) 等价查询命中缓存(不再重复请求)')
  inst.setData({ weekdayIndex: 3, weekIndex: 5, startIndex: 0, endIndex: 0 })
  let before = calls.length
  await inst.search()                            // 同样 星期三/第5周/第1-3节
  check('命中解析后条件的缓存, 未产生新请求', () => {
    assert.strictEqual(calls.length, before, '多发了 ' + (calls.length - before) + ' 次请求')
  })
  check('缓存命中即渲染(2 间, 摘要为星期三)', () => {
    assert.strictEqual(inst.data.result.count, 2)
    assert.ok(inst.data.result.summary.indexOf('星期三') >= 0, inst.data.result.summary)
  })
  inst.setData({ weekdayIndex: 6, weekIndex: 3, startIndex: 0, endIndex: 0 })
  before = calls.length
  await inst.search()                            // 显式星期六/第3周 → 命中 2b 的解析键
  check('"今天"与"显式同一星期"共用同一份缓存', () => {
    assert.strictEqual(calls.length, before, '多发了 ' + (calls.length - before) + ' 次请求')
    assert.strictEqual(inst.data.result.count, 7)
  })

  console.log('\n4) 楼名映射: buildings 为 [{code,name}] 对象数组')
  const { groupRooms } = require(path.join(ROOT, 'utils', 'room-group'))
  const g1 = groupRooms(['Ⅳ-A101', 'Ⅳ-B202', '江阴致知B103'],
    [{ code: 'x', name: 'Ⅳ教学楼' }, { code: 'y', name: '致知楼B' }])
  check('罗马数字前缀 → 教学楼名(Ⅳ → Ⅳ教学楼)', () => {
    const hit = g1.find(x => x.prefix === 'Ⅳ')
    assert.ok(hit && hit.label === 'Ⅳ教学楼', JSON.stringify(g1.map(x => x.label)))
    assert.strictEqual(hit.rooms.length, 2)
  })
  check('汉字前缀 → 教学楼名(江阴致知B → 致知楼B)', () => {
    const hit = g1.find(x => x.prefix === '江阴致知B')
    assert.ok(hit && hit.label === '致知楼B', JSON.stringify(g1.map(x => x.label)))
  })
  check('兼容字符串数组形态', () => {
    const g2 = groupRooms(['I-201'], ['Ⅰ教学楼'])
    assert.strictEqual(g2[0].label, 'Ⅰ教学楼')
  })
  check('映射失败时回退原始前缀(不崩)', () => {
    const g3 = groupRooms(['Z-101'], [{ code: 'z', name: '未知楼' }])
    assert.strictEqual(g3[0].label, 'Z')
  })

  console.log('\n' + '='.repeat(52))
  console.log('通过 ' + pass + ' / ' + (pass + failures.length))
  if (failures.length) console.log('失败: ' + failures.join(' | '))
  console.log('='.repeat(52))
  process.exit(failures.length ? 1 : 0)
})()
