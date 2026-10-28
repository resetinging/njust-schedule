/**
 * 考试安排状态显示回归测试（Node 桩件，不接触真实缓存/凭据/网络）
 *
 * 覆盖：
 *  A. 逐场状态：考前/开考瞬间/进行中/结束瞬间/已结束，时区固定 Asia/Shanghai
 *  B. 同日混合：组状态=有进行中优先，否则最近未开始；全部结束才 done 可折叠
 *  C. 缺/非法日期、缺时段、只有开始无结束、跨午夜、常见分隔符
 *  D. 倒计时最多 3 场、进行中不排在已结束之后、<1 小时用分钟、无负小时/NaN
 *  E. 缓存清空：非空→空数组→缺失、切学期、退出登录清掉旧数据与折叠状态
 *  F. 旧身份/旧学期迟到响应不覆盖新视图、不污染缓存；卸载后不 setData；失败保留同学期数据
 *  G. 研究生 rows 映射
 *
 * 运行: node tools/test_exams.js
 */
const assert = require('assert')
const path = require('path')

const ROOT = path.resolve(__dirname, '..')

// ---------------- 小程序运行时桩件（真实 storage，纯内存） ----------------
const store = new Map()
store.set('student_id', '20230000000')
store.set('semester', '2026-2027-1')
store.set('token', 'stub-token-not-real')
store.set('account_type', '')

const toasts = []
global.wx = {
  getStorageSync: (k) => (store.has(k) ? store.get(k) : ''),
  setStorageSync: (k, v) => { store.set(k, v) },
  removeStorageSync: (k) => { store.delete(k) },
  getStorageInfoSync: () => ({ keys: Array.from(store.keys()) }),
  showToast: (o) => { toasts.push(o) },
  nextTick: (fn) => { if (typeof fn === 'function') fn() }
}
global.getCurrentPages = () => []
global.getApp = () => ({ globalData: {} })

let componentCfg = null
global.Component = (cfg) => { componentCfg = cfg }

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
const flush = () => new Promise((r) => setTimeout(r, 0))
function deferred() {
  let resolve, reject
  const promise = new Promise((res, rej) => { resolve = res; reject = rej })
  return { promise, resolve, reject }
}
// Asia/Shanghai 墙钟 → 绝对毫秒（UTC-8h 固定的考试时区语义）
function ts(y, mo, d, h, mi, s) {
  return Date.UTC(y, mo - 1, d, h || 0, mi || 0, s || 0) - 8 * 3600 * 1000
}

;(async () => {
  // ---------------- 装载测试桩件 + 组件 ----------------
  const apiPath = require.resolve(path.join(ROOT, 'utils', 'api'))
  const calls = []
  const examResponses = []
  const refreshResponses = []
  const yjsResponses = []
  const apiStub = {
    getExams: (semester) => {
      calls.push('getExams:' + (semester || ''))
      const d = examResponses.shift()
      return d ? d.promise : Promise.resolve({ success: false })
    },
    refreshExams: () => {
      calls.push('refreshExams')
      const d = refreshResponses.shift()
      return d ? d.promise : Promise.resolve({ success: true, count: 1 })
    },
    getYjsExams: () => {
      calls.push('getYjsExams')
      const d = yjsResponses.shift()
      return d ? d.promise : Promise.resolve({ success: true, rows: [] })
    }
  }
  require.cache[apiPath] = { id: apiPath, filename: apiPath, loaded: true, exports: apiStub }

  const subPath = require.resolve(path.join(ROOT, 'utils', 'subscribe'))
  require.cache[subPath] = {
    id: subPath, filename: subPath, loaded: true,
    exports: {
      loadStatus: () => Promise.resolve({ enabled: true, kinds: [{ kind: 'exam', quota: 2, templateId: 'stub' }] }),
      requestGrant: () => Promise.resolve({ ok: true, quota: 1 })
    }
  }
  const anaPath = require.resolve(path.join(ROOT, 'utils', 'analytics'))
  require.cache[anaPath] = {
    id: anaPath, filename: anaPath, loaded: true,
    exports: {
      observeSlots() {}, disconnectSlots() {}, track() {}, refreshResult() {}, featureOpen() {}, pageView() {}
    }
  }

  const storage = require(path.join(ROOT, 'utils', 'storage'))
  const dateUtil = require(path.join(ROOT, 'utils', 'date'))
  require(path.join(ROOT, 'components', 'exams-view', 'index.js'))
  assert.ok(componentCfg && componentCfg.methods, '未加载 exams-view 组件配置')

  const baseData = typeof componentCfg.data === 'function' ? componentCfg.data() : componentCfg.data
  const makeInstance = () => Object.assign({}, componentCfg.methods, {
    data: JSON.parse(JSON.stringify(baseData || {})),
    setData(patch) {
      Object.assign(this.data, patch || {})
    }
  })

  const NOW = ts(2026, 10, 28, 16, 0)   // 2026-10-28 16:00 上海
  const mkExam = (o) => Object.assign({ course_name: '示例课程', date: '2026-10-28', time: '', location: 'A101', seat: '', type: '期末考试' }, o)

  // ================= 1. 时间解析 / 状态边界 / 时区 =================
  console.log('1) 逐场状态与时间解析')
  check('Asia/Shanghai 时间戳固定 UTC+8（不受宿主时区影响）', () => {
    assert.strictEqual(dateUtil.examTimestamp(2026, 10, 28, 15, 50), ts(2026, 10, 28, 15, 50))
    assert.strictEqual(dateUtil.examTimestamp(2026, 10, 28, 15, 50) - dateUtil.examTimestamp(2026, 10, 28, 14, 50), 3600000)
  })
  check('常见分隔符 - / ~ / ～ 都能解析', () => {
    for (const raw of ['15:50~17:50', '15:50-17:50', '15:50～17:50', '15:50 — 17:50']) {
      const t = dateUtil.getExamTiming(mkExam({ time: raw }), NOW)
      assert.strictEqual(t.status, 'ongoing', raw + ' → ' + t.status)
      assert.strictEqual(t.startMs, ts(2026, 10, 28, 15, 50), raw)
      assert.strictEqual(t.endMs, ts(2026, 10, 28, 17, 50), raw)
    }
  })
  const boundary = [
    ['15:49:59', ts(2026, 10, 28, 15, 49, 59), 'upcoming'],
    ['15:50:00', ts(2026, 10, 28, 15, 50, 0), 'ongoing'],
    ['16:00:00', ts(2026, 10, 28, 16, 0, 0), 'ongoing'],
    ['17:49:59', ts(2026, 10, 28, 17, 49, 59), 'ongoing'],
    ['17:50:00', ts(2026, 10, 28, 17, 50, 0), 'done']
  ]
  check('开考瞬间 ongoing、结束瞬间 done（含 16:00 进行中）', () => {
    for (const [label, now, expect] of boundary) {
      const t = dateUtil.getExamTiming(mkExam({ time: '15:50~17:50' }), now)
      assert.strictEqual(t.status, expect, label + ' → ' + t.status + ' 期望 ' + expect)
    }
  })
  check('缺/非法日期 → unknown（不 NaN、不误标 done）', () => {
    for (const bad of [undefined, '', '待定', '2026-02-30', '2026-13-01', 'abc']) {
      const t = dateUtil.getExamTiming(mkExam({ date: bad, time: '09:00~11:00' }), NOW)
      assert.strictEqual(t.status, 'unknown', String(bad))
    }
  })
  check('缺/非法时段 → unknown（保守时间待定）', () => {
    for (const bad of ['', '待定', '-', '25:00~26:00', '19:00-abc', 'abc']) {
      const t = dateUtil.getExamTiming(mkExam({ time: bad }), NOW)
      assert.strictEqual(t.status, 'unknown', JSON.stringify(bad))
    }
  })
  check('只有开始无结束：考前 upcoming，开考后 ongoing(结束待定)，次日转 unknown 而非 done', () => {
    const exam = mkExam({ date: '2026-10-28', time: '19:00' })
    assert.strictEqual(dateUtil.getExamTiming(exam, ts(2026, 10, 28, 18, 0)).status, 'upcoming')
    const during = dateUtil.getExamTiming(exam, ts(2026, 10, 28, 20, 0))
    assert.strictEqual(during.status, 'ongoing')
    assert.strictEqual(during.endUnconfirmed, true)
    const nextDay = dateUtil.getExamTiming(exam, ts(2026, 10, 29, 1, 0))
    assert.strictEqual(nextDay.status, 'unknown', '次日不得标 done')
  })
  check('尾部分隔符（19:00~ / 19:00-）按“只有开始”处理：考前 upcoming、开考后 ongoing(结束待定)', () => {
    for (const raw of ['19:00~', '19:00-']) {
      const exam = mkExam({ date: '2026-10-28', time: raw })
      assert.strictEqual(dateUtil.getExamTiming(exam, ts(2026, 10, 28, 18, 0)).status, 'upcoming', raw)
      const during = dateUtil.getExamTiming(exam, ts(2026, 10, 28, 20, 0))
      assert.strictEqual(during.status, 'ongoing', raw)
      assert.strictEqual(during.endUnconfirmed, true, raw)
    }
  })
  check('跨午夜：22:00~01:00 在 23:00/00:30 仍进行中，01:00 才结束', () => {
    const exam = mkExam({ date: '2026-10-28', time: '22:00~01:00' })
    assert.strictEqual(dateUtil.getExamTiming(exam, ts(2026, 10, 28, 23, 0)).status, 'ongoing')
    assert.strictEqual(dateUtil.getExamTiming(exam, ts(2026, 10, 29, 0, 30)).status, 'ongoing')
    assert.strictEqual(dateUtil.getExamTiming(exam, ts(2026, 10, 29, 1, 0)).status, 'done')
  })
  check('倒计时文案：<1h 用分钟、无负小时/0h/NaN', () => {
    const t30 = dateUtil.getExamTiming(mkExam({ date: '2026-10-28', time: '16:30~18:00' }), NOW)
    const cd = dateUtil.formatExamCountdown(t30, NOW)
    assert.ok(/分钟/.test(cd.bigLabel), JSON.stringify(cd))
    assert.strictEqual(parseFloat(cd.bigNum), 30)
    const ongoing = dateUtil.formatExamCountdown(dateUtil.getExamTiming(mkExam({ time: '15:50~17:50' }), NOW), NOW)
    assert.strictEqual(ongoing.bigNum, '进行中', JSON.stringify(ongoing))
    assert.ok(!/NaN|-/.test(ongoing.bigNum + ongoing.bigLabel), JSON.stringify(ongoing))
  })

  // ================= 2. 同日混合 / 组状态 / 卡片状态 =================
  console.log('\n2) 同日混合状态与分组')
  const mixed = [
    mkExam({ course_name: '上午课', time: '09:00~11:00' }),     // done
    mkExam({ course_name: '下午课', time: '15:50~17:50' }),     // ongoing @16:00
    mkExam({ course_name: '晚上课', time: '19:00~21:00' }),     // upcoming
    mkExam({ course_name: '时间待定课', time: '' })             // unknown
  ]
  let inst = makeInstance()
  inst._processExams(mixed, NOW)
  check('同日组状态：有进行中 → ongoing（不因第一场已结束而整组 done）', () => {
    assert.strictEqual(inst.data.dayGroups.length, 1)
    assert.strictEqual(inst.data.dayGroups[0].urgency, 'ongoing', JSON.stringify(inst.data.dayGroups[0].urgency))
  })
  check('组件默认时钟（Date.now）下同样按进行中判定，避免依赖实时日期', () => {
    const realNow = Date.now
    Date.now = () => NOW
    try {
      const i = makeInstance()
      i._processExams([mkExam({ time: '15:50~17:50' })])
      assert.strictEqual(i.data.dayGroups[0].urgency, 'ongoing')
      assert.strictEqual(i.data.countdowns[0].bigNum, '进行中')
    } finally {
      Date.now = realNow
    }
  })
  check('每张卡片状态取自身：done/ongoing/upcoming/unknown 不继承组状态', () => {
    const cards = inst.data.dayGroups[0].exams
    const byName = {}
    cards.forEach(c => { byName[c.course_name] = c })
    assert.strictEqual(byName['上午课'].cardClass, 'exam-done')
    assert.strictEqual(byName['下午课'].cardClass, 'exam-ongoing')
    assert.ok(byName['晚上课'].status === 'upcoming')
    assert.ok(byName['时间待定课'].status === 'unknown')
    assert.strictEqual(byName['时间待定课'].cardClass, 'exam-unknown')
  })
  check('组内有进行中时不可折叠（data-done 语义=全部结束）', () => {
    assert.notStrictEqual(inst.data.dayGroups[0].urgency, 'done')
  })
  check('倒计时最多 3 场，进行中优先且不含已结束', () => {
    const cd = inst.data.countdowns
    assert.ok(cd.length <= 3, String(cd.length))
    assert.strictEqual(cd[0].course_name, '下午课', JSON.stringify(cd.map(x => x.course_name)))
    assert.ok(!cd.some(x => x.course_name === '上午课'), '倒计时不应出现已结束')
    assert.ok(!cd.some(x => x.course_name === '时间待定课'), '倒计时不含时间待定')
  })
  check('全部结束的日期组 → done 且允许折叠', () => {
    const inst2 = makeInstance()
    inst2._processExams([mkExam({ time: '09:00~11:00' }), mkExam({ course_name: '另一场', time: '13:00~15:00' })], NOW)
    assert.strictEqual(inst2.data.dayGroups[0].urgency, 'done')
    inst2.onToggleGroup({ currentTarget: { dataset: { date: '2026-10-28', done: true } } })
    assert.strictEqual(inst2.data.collapsedDates['2026-10-28'], true)
  })
  check('含无法判断时间的记录不能被折叠为 done', () => {
    const inst3 = makeInstance()
    inst3._processExams([mkExam({ time: '09:00~11:00' }), mkExam({ course_name: '待定', time: '待定' })], NOW)
    assert.notStrictEqual(inst3.data.dayGroups[0].urgency, 'done')
  })
  check('组内按开始时间排序，未知时间排最后', () => {
    const inst4 = makeInstance()
    inst4._processExams([mkExam({ course_name: '晚', time: '19:00~21:00' }), mkExam({ course_name: '待定', time: '' }), mkExam({ course_name: '早', time: '09:00~11:00' })], NOW)
    assert.deepStrictEqual(inst4.data.dayGroups[0].exams.map(x => x.course_name), ['早', '晚', '待定'])
  })

  // ================= 3. 缓存应用 / 清空 / 切学期 / 退出 =================
  console.log('\n3) 缓存应用与清空')
  const keyA = 'cached_exams_2026-2027-1'
  storage.setCached(keyA, [mkExam({ time: '15:50~17:50' })])
  inst = makeInstance()
  // 固定时钟覆盖组件默认 Date.now：避免真实日期变化令倒计时断言飘移
  const realNowForCache = Date.now
  Date.now = () => NOW
  try {
    inst.loadCachedData()
  } finally {
    Date.now = realNowForCache
  }
  check('缓存非空 → 渲染并计算状态', () => {
    assert.strictEqual(inst.data.exams.length, 1)
    assert.ok(inst.data.dayGroups.length === 1)
    assert.strictEqual(inst.data.dayGroups[0].urgency, 'ongoing')
    assert.strictEqual(inst.data.countdowns.length, 1)
    assert.strictEqual(inst.data.countdowns[0].bigNum, '进行中')
  })
  inst.setData({ collapsedDates: { '2026-10-28': true } })
  storage.setCached(keyA, [])
  inst.loadCachedData()
  check('缓存变为空数组 → 清空 exams/countdowns/dayGroups/collapsedDates', () => {
    assert.deepStrictEqual(inst.data.exams, [])
    assert.deepStrictEqual(inst.data.countdowns, [])
    assert.deepStrictEqual(inst.data.dayGroups, [])
    assert.deepStrictEqual(inst.data.collapsedDates, {})
  })
  inst.setData({ exams: [mkExam({})], countdowns: [{}], dayGroups: [{}] })
  store.delete(keyA)
  inst.loadCachedData()
  check('缓存缺失 → 同样清空旧数据', () => {
    assert.deepStrictEqual(inst.data.exams, [])
    assert.deepStrictEqual(inst.data.dayGroups, [])
  })
  store.set('semester', '2026-2027-2')
  storage.setCached('cached_exams_2026-2027-2', [mkExam({ date: '2027-01-05', time: '09:00~11:00' })])
  inst = makeInstance()
  inst.setData({ exams: [mkExam({})], collapsedDates: { '2026-10-28': true } })
  inst.loadCachedData()
  check('切学期 → 读取新学期缓存并清折叠状态', () => {
    assert.strictEqual(inst.data.semester, '2026-2027-2')
    assert.strictEqual(inst.data.exams.length, 1)
    assert.strictEqual(inst.data.exams[0].date, '2027-01-05')
    assert.deepStrictEqual(inst.data.collapsedDates, {})
  })
  store.set('semester', '2026-2027-1')
  store.delete('student_id')
  inst = makeInstance()
  inst.setData({ exams: [mkExam({})], countdowns: [{}], dayGroups: [{}], collapsedDates: { x: true }, examRows: [{ i: 0, cells: [] }] })
  inst.activate()
  check('退出登录 → 统一清空考试视图（含研究生 rows）', () => {
    assert.deepStrictEqual(inst.data.exams, [])
    assert.deepStrictEqual(inst.data.countdowns, [])
    assert.deepStrictEqual(inst.data.dayGroups, [])
    assert.deepStrictEqual(inst.data.collapsedDates, {})
    assert.deepStrictEqual(inst.data.examRows, [])
  })
  store.set('student_id', '20230000000')

  // ================= 4. 异步竞态 / 卸载 / 失败保留 =================
  console.log('\n4) 异步竞态与失败保留')
  store.set('semester', '2026-2027-1')
  const cacheBeforeStale = storage.getCached('cached_exams_2026-2027-2')   // 快照：此前可能已有有效缓存
  const d1 = deferred()
  examResponses.push(d1)
  inst = makeInstance()
  const p1 = inst.loadFromServer(true)
  store.set('semester', '2026-2027-2')                       // 学期在请求途中变化
  d1.resolve({ success: true, exams: [mkExam({ course_name: '旧学期迟到数据', time: '15:50~17:50' })], semester: '2026-2027-1' })
  await p1
  check('旧学期迟到响应不覆盖视图、不污染新学期缓存', () => {
    assert.deepStrictEqual(inst.data.exams, [], '不应写入 exams: ' + JSON.stringify(inst.data.exams))
    assert.deepStrictEqual(storage.getCached('cached_exams_2026-2027-2'), cacheBeforeStale,
      '旧学期响应不得改写新学期缓存')
  })
  store.set('semester', '2026-2027-1')
  const d2 = deferred()
  examResponses.push(d2)
  inst = makeInstance()
  const p2 = inst.loadFromServer(true)
  store.delete('student_id')                                 // 账号在请求途中退出
  d2.resolve({ success: true, exams: [mkExam({ course_name: '旧账号迟到数据' })], semester: '2026-2027-1' })
  await p2
  check('旧账号迟到响应不覆盖视图', () => {
    assert.deepStrictEqual(inst.data.exams, [])
  })
  store.set('student_id', '20230000000')

  const d3 = deferred()
  examResponses.push(d3)
  inst = makeInstance()
  const p3 = inst.loadFromServer(true)
  if (componentCfg.lifetimes && componentCfg.lifetimes.detached) componentCfg.lifetimes.detached.call(inst)
  d3.resolve({ success: true, exams: [mkExam({ course_name: '卸载后数据' })] })
  await p3
  check('组件卸载后不再 setData', () => {
    assert.deepStrictEqual(inst.data.exams, [])
  })

  const d4 = deferred()
  examResponses.push(d4)
  inst = makeInstance()
  inst.setData({ exams: [mkExam({ course_name: '已有数据' })], semester: '2026-2027-1' })
  const p4 = inst.loadFromServer(false)
  d4.reject(new Error('network down'))
  await p4
  check('请求失败保留同学期已有数据、loading 归位', () => {
    assert.strictEqual(inst.data.exams.length, 1)
    assert.strictEqual(inst.data.exams[0].course_name, '已有数据')
    assert.strictEqual(inst.data.loading, false)
  })

  // ================= 5. 研究生 rows / 折叠按钮 =================
  console.log('\n5) 研究生与折叠交互')
  check('研究生 rows 映射为 examRows（本地优先形态）', () => {
    const i5 = makeInstance()
    i5._applyYjsExams({ success: true, rows: [['课程A', '2026-10-30'], ['课程B', '2026-11-01']] })
    assert.strictEqual(i5.data.examRows.length, 2)
    assert.deepStrictEqual(i5.data.examRows[0], { i: 0, cells: ['课程A', '2026-10-30'] })
    assert.deepStrictEqual(i5.data.examRows[1], { i: 1, cells: ['课程B', '2026-11-01'] })
  })
  check('未结束组不可折叠（data-done=false 时忽略）', () => {
    const i6 = makeInstance()
    i6.setData({ collapsedDates: {} })
    i6.onToggleGroup({ currentTarget: { dataset: { date: '2026-10-28', done: false } } })
    assert.deepStrictEqual(i6.data.collapsedDates, {})
  })

  // ================= 6. 研究生分流 / 请求绑定 / 状态复位 =================
  console.log('\n6) 研究生分流 / 请求绑定 / 复位')
  store.set('account_type', 'graduate')
  store.set('semester', '2026-2027-1')
  store.delete('cached_exams_2026-2027-1')
  store.delete('cached_yjs_exams')
  {
    const i = makeInstance()
    const before = calls.length
    componentCfg.lifetimes.attached.call(i)
    await flush()
    check('研究生 attached 不触本科接口，只走 getYjsExams', () => {
      const fresh = calls.slice(before)
      assert.ok(fresh.every((c) => !String(c).startsWith('getExams')), JSON.stringify(fresh))
      assert.ok(fresh.some((c) => String(c).startsWith('getYjsExams')), JSON.stringify(fresh))
      assert.strictEqual(i.data.isGraduate, true)
      assert.strictEqual(storage.getCached('cached_exams_2026-2027-1'), null)
    })
  }
  storage.setCached('cached_yjs_exams', { success: true, rows: [['课程A']] })
  {
    const i = makeInstance()
    const before = calls.length
    componentCfg.lifetimes.attached.call(i)
    await flush()
    check('研究生已有 cached_yjs_exams 时 attached 不发请求', () => {
      assert.strictEqual(calls.length, before, JSON.stringify(calls.slice(before)))
      assert.deepStrictEqual(i.data.examRows.map((r) => r.cells[0]), ['课程A'])
    })
  }
  store.delete('cached_yjs_exams')
  {
    const i = makeInstance()
    const d = deferred()
    yjsResponses.push(d)
    const p = i.onRefreshYjsExams()
    store.set('semester', '2026-2027-2')
    toasts.length = 0
    d.resolve({ success: true, rows: [['旧学期研究生']] })
    await p
    check('研究生旧学期刷新：不写缓存、不 toast', () => {
      assert.strictEqual(storage.getCached('cached_yjs_exams'), null)
      assert.deepStrictEqual(toasts, [])
    })
  }
  store.set('semester', '2026-2027-1')
  {
    const i = makeInstance()
    const d = deferred()
    yjsResponses.push(d)
    const p = i.onRefreshYjsExams()
    store.delete('student_id')
    toasts.length = 0
    d.reject(new Error('old identity'))
    await p
    check('研究生旧身份刷新错误：不 toast', () => {
      assert.deepStrictEqual(toasts, [])
    })
  }
  store.set('student_id', '20230000000')
  store.set('account_type', '')
  {
    const i = makeInstance()
    const d = deferred()
    refreshResponses.push(d)
    const p = i.onRefresh()
    store.set('semester', '2026-2027-2')
    toasts.length = 0
    const beforeCalls = calls.length
    d.resolve({ success: true, count: 3 })
    await p
    await flush()
    check('本科旧学期刷新成功：不 toast、不链式加载', () => {
      assert.deepStrictEqual(toasts, [])
      assert.strictEqual(calls.length, beforeCalls, JSON.stringify(calls.slice(beforeCalls)))
    })
  }
  {
    const i = makeInstance()
    const d = deferred()
    refreshResponses.push(d)
    const p = i.onRefresh()
    store.delete('student_id')
    toasts.length = 0
    d.reject(new Error('old identity'))
    await p
    await flush()
    check('本科旧账号刷新错误：不 toast、不链式加载', () => {
      assert.deepStrictEqual(toasts, [])
    })
  }
  store.set('student_id', '20230000000')
  store.set('semester', '2026-2027-1')

  {
    const i = makeInstance()
    const dSilent = deferred()
    examResponses.push(dSilent)
    const pSilent = i.loadFromServer(true)
    const dRefresh = deferred()
    refreshResponses.push(dRefresh)
    const pRefresh = i.onRefresh()
    const dChain = deferred()
    examResponses.push(dChain)
    dRefresh.resolve({ success: true, count: 1 })
    await pRefresh
    dChain.resolve({ success: true, exams: [mkExam({ course_name: '刷新后数据', time: '15:50~17:50' })], semester: '2026-2027-1' })
    await flush()
    dSilent.resolve({ success: true, exams: [mkExam({ course_name: '旧静默数据' })], semester: '2026-2027-1' })
    await pSilent
    check('同身份刷新使旧静默加载失效（旧响应不覆盖新视图）', () => {
      assert.deepStrictEqual(i.data.exams.map((e) => e.course_name), ['刷新后数据'], JSON.stringify(i.data.exams))
    })
  }
  {
    const i = makeInstance()
    i.setData({ exams: [mkExam({ course_name: '现有数据' })], semester: '2026-2027-1' })
    const d = deferred()
    examResponses.push(d)
    const p = i.loadFromServer(false)
    d.resolve({ success: true, exams: [mkExam({ course_name: '错误学期数据' })], semester: '2025-2026-2' })
    await p
    check('响应学期与请求学期不一致 → 丢弃，不覆盖视图/缓存', () => {
      assert.deepStrictEqual(i.data.exams.map((e) => e.course_name), ['现有数据'])
      assert.strictEqual(storage.getCached('cached_exams_2025-2026-2'), null)
      assert.strictEqual(i.data.loading, false)
    })
  }
  {
    const i = makeInstance()
    i.setData({ exams: [mkExam({})], collapsedDates: { '2026-10-28': true }, semester: '2026-2027-1' })
    const d = deferred()
    examResponses.push(d)
    const p = i.loadFromServer(false)
    d.resolve({ success: true, exams: [], semester: '2026-2027-1' })
    await p
    check('服务器返回空列表 → 清 dayGroups/countdowns/collapsedDates 并同步学期', () => {
      assert.deepStrictEqual(i.data.dayGroups, [])
      assert.deepStrictEqual(i.data.countdowns, [])
      assert.deepStrictEqual(i.data.collapsedDates, {})
      assert.strictEqual(i.data.semester, '2026-2027-1')
    })
  }
  {
    const i = makeInstance()
    i.setData({ loading: true, refreshing: true, errorMsg: '旧错误', subExam: { quota: 1 }, exams: [mkExam({})], collapsedDates: { x: true } })
    store.delete('student_id')
    i.activate()
    check('退出登录复位 busy/error/subExam 并清空视图', () => {
      assert.strictEqual(i.data.loading, false)
      assert.strictEqual(i.data.refreshing, false)
      assert.strictEqual(i.data.errorMsg, '')
      assert.strictEqual(i.data.subExam, null)
      assert.deepStrictEqual(i.data.exams, [])
    })
    store.set('student_id', '20230000000')
  }
  {
    const i = makeInstance()
    const dOld = deferred()
    examResponses.push(dOld)
    const pOld = i.loadFromServer(false)            // 旧请求（loading=true）
    const dNew = deferred()
    examResponses.push(dNew)
    const pNew = i.loadFromServer(true)             // 同身份新请求 → 旧请求失效
    i.setData({ loading: true })                    // 模拟新操作自己的 loading
    dOld.resolve({ success: false, message: '旧失败' })
    await pOld
    check('旧请求失败不清新操作的 loading', () => {
      assert.strictEqual(i.data.loading, true)
    })
    dNew.resolve({ success: false })
    await pNew
  }

  // ================= 7. pageLifetimes.show 本地重算 =================
  console.log('\n7) 页面重新显示（本地重算，不发请求）')
  check('pageLifetimes.show 按当前时间本地重算', () => {
    const i = makeInstance()
    i.setData({ active: true, isGraduate: false, exams: [mkExam({ time: '15:50~17:50' })] })
    const before = calls.length
    const realNow = Date.now
    Date.now = () => NOW
    try {
      componentCfg.pageLifetimes.show.call(i)
    } finally {
      Date.now = realNow
    }
    assert.strictEqual(calls.length, before, '不应发网络请求')
    assert.strictEqual(i.data.dayGroups[0].urgency, 'ongoing')
  })
  check('研究生重新显示不触发本科重算', () => {
    const i = makeInstance()
    i.setData({ active: true, isGraduate: true, exams: [mkExam({ time: '15:50~17:50' })] })
    componentCfg.pageLifetimes.show.call(i)
    assert.deepStrictEqual(i.data.dayGroups, [])
  })

  // ================= 8. 时间边界 =================
  console.log('\n8) 时间边界（相等起止 / 单开始日界）')
  check('开始==结束：结束待定，不臆造 24 小时跨午夜', () => {
    const exam = mkExam({ date: '2026-10-28', time: '15:50~15:50' })
    assert.strictEqual(dateUtil.getExamTiming(exam, ts(2026, 10, 28, 15, 0)).status, 'upcoming')
    const during = dateUtil.getExamTiming(exam, ts(2026, 10, 28, 16, 0))
    assert.strictEqual(during.status, 'ongoing')
    assert.strictEqual(during.endUnconfirmed, true)
    assert.strictEqual(during.endMs, null, '不得补成 24 小时')
    assert.strictEqual(dateUtil.getExamTiming(exam, ts(2026, 10, 29, 0, 0)).status, 'unknown')
  })
  check('只有开始：当天 23:59:59.999 仍进行中，次日 00:00 转 unknown', () => {
    const exam = mkExam({ date: '2026-10-28', time: '19:00' })
    assert.strictEqual(dateUtil.getExamTiming(exam, ts(2026, 10, 28, 23, 59, 59) + 999).status, 'ongoing')
    assert.strictEqual(dateUtil.getExamTiming(exam, ts(2026, 10, 29, 0, 0, 0)).status, 'unknown')
  })

  console.log('\n' + '='.repeat(52))
  console.log('通过 ' + pass + ' / ' + (pass + failures.length))
  if (failures.length) console.log('失败: ' + failures.join(' | '))
  console.log('='.repeat(52))
  process.exit(failures.length ? 1 : 0)
})().catch((e) => {
  console.error('测试运行异常: ' + (e && e.stack || e))
  process.exit(1)
})
