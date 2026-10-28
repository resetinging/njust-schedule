/**
 * 图书馆库存页行为测试 — Node 中模拟小程序组件运行时。
 *
 * 覆盖：提交搜索/分页/加载更多、搜索竞态、详情按需请求、校区切换与统计一致、
 * 关闭详情后的晚到响应、错误保留原列表与重试。
 *
 * 运行: node tools/test_library.js
 */
const assert = require('assert')
const path = require('path')

const ROOT = path.resolve(process.argv[2] || path.join(__dirname, '..'))

global.wx = {
  getWindowInfo() {
    return { statusBarHeight: 47, windowWidth: 390 }
  },
  getMenuButtonBoundingClientRect() {
    return { top: 51, left: 281, width: 87, height: 32 }
  },
  getStorageSync() { return '' },
  setStorageSync() {},
  removeStorageSync() {}
}

let componentConfig = null
global.Component = (config) => { componentConfig = config }

const searchCalls = []
const itemCalls = []
const tracks = []
const responses = {
  search: [],
  item: []
}
function defer() {
  let resolve
  let reject
  const promise = new Promise((res, rej) => { resolve = res; reject = rej })
  return { promise, resolve, reject }
}

const apiStub = {
  searchLibraryBooks(params) {
    searchCalls.push(params)
    const next = responses.search.shift()
    if (!next) return Promise.reject(new Error('unexpected search'))
    return next.promise
  },
  getLibraryBookItems(params) {
    itemCalls.push(params)
    const next = responses.item.shift()
    if (!next) return Promise.reject(new Error('unexpected item'))
    return next.promise
  }
}
const analyticsStub = {
  track(name, data) { tracks.push({ name, data }) },
  featureAction(feature, page, extra) { tracks.push({ name: 'feature_action', data: Object.assign({ feature, page }, extra || {}) }) }
}

// 用内存 stub 替换真实模块依赖（避免加载整棵 api/analytics 依赖）
const apiPath = require.resolve(path.join(ROOT, 'utils', 'api'))
const analyticsPath = require.resolve(path.join(ROOT, 'utils', 'analytics'))
require.cache[apiPath] = { id: apiPath, filename: apiPath, loaded: true, exports: apiStub }
require.cache[analyticsPath] = { id: analyticsPath, filename: analyticsPath, loaded: true, exports: analyticsStub }
require(path.join(ROOT, 'components', 'library-view', 'index.js'))

let pass = 0
const failures = []
function check(name, fn) {
  return Promise.resolve().then(fn).then(() => {
    pass++
    console.log('  ✓ ' + name)
  }).catch((error) => {
    failures.push(name)
    console.log('  ✗ ' + name + '  → ' + error.message)
  })
}

function makeInstance() {
  const events = []
  const instance = {
    data: JSON.parse(JSON.stringify(componentConfig.data)),
    _searchSeq: 0,
    _detailSeq: 0,
    setData(patch, callback) {
      Object.assign(this.data, patch)
      if (callback) callback()
    },
    triggerEvent(name, detail) {
      events.push({ name, detail })
    }
  }
  Object.keys(componentConfig.methods).forEach((name) => { instance[name] = componentConfig.methods[name] })
  if (componentConfig.lifetimes && componentConfig.lifetimes.attached) {
    componentConfig.lifetimes.attached.call(instance)
  }
  instance.__events = events
  return instance
}

const flush = () => new Promise((resolve) => setTimeout(resolve, 0))

const BOOK_A = {
  marc_no: 'MARC-A', title: '高等数学', author: '示例作者', publisher: '示例出版社',
  pub_year: '2013', isbn: '978-7-5608-5255-3', call_no: 'O13/797', doc_type: '中文图书', num: 1
}
const BOOK_B = {
  marc_no: 'MARC-B', title: '线性代数', author: '示例作者二', publisher: '示例出版社',
  pub_year: '2015', isbn: '978-7-0000-0000-0', call_no: 'O151/1', doc_type: '中文图书', num: 2
}
const COPIES_ALL = {
  success: true, scope: 'all', total: 3, available: 1,
  campus_counts: { nanjing: 1, jiangyin: 1, unknown: 1 },
  copies: [
    { call_no: 'O13/797', barcode: 'B1', volume: '2013', campus: '南京', location: '南京自科阅览室503室', status: '可借', available: true },
    { call_no: 'O13/797', barcode: 'B2', volume: '2013', campus: '江阴', location: '江阴综合书库305室', status: '借出', available: false },
    { call_no: 'O13/797', barcode: 'B3', volume: '', campus: '未知', location: '密集书库113室', status: '状态未知', available: false }
  ],
  stale: false, updated_at: 1793208600
}
const COPIES_JIANGYIN = {
  success: true, scope: 'jiangyin', total: 1, available: 0,
  campus_counts: { nanjing: 1, jiangyin: 1, unknown: 1 },
  copies: [{ call_no: 'O13/797', barcode: 'B2', volume: '2013', campus: '江阴', location: '江阴综合书库305室', status: '借出', available: false }],
  stale: false, updated_at: 1793208600
}

;(async () => {
  await check('无关键词不请求，提示输入', async () => {
    const vm = makeInstance()
    vm.data.keyword = '   '
    vm.onSearch()
    await flush()
    assert.strictEqual(searchCalls.length, 0)
    assert.ok(vm.data.errorMsg.indexOf('请输入') >= 0)
  })

  await check('提交搜索：字段/关键词/页码透传，结果去除旧记录', async () => {
    const vm = makeInstance()
    vm.data.keyword = '高等数学'
    vm.data.fieldIndex = 0
    const d = defer()
    responses.search.push(d)
    vm.onSearch()
    await flush()
    assert.deepStrictEqual(searchCalls[searchCalls.length - 1], { field: 'title', q: '高等数学', page: 1 })
    d.resolve({ success: true, total: 2582, page: 1, page_size: 20, has_more: true, records: [BOOK_A, BOOK_B], stale: false, updated_at: 1793208600 })
    await flush()
    assert.strictEqual(vm.data.loading, false)
    assert.strictEqual(vm.data.total, 2582)
    assert.strictEqual(vm.data.hasMore, true)
    assert.strictEqual(vm.data.records.length, 2)
    assert.strictEqual(vm.data.records[0].marcNo, 'MARC-A')
    assert.ok(vm.data.records[0].metaText.indexOf('示例作者') >= 0)
    assert.ok(vm.data.searchUpdatedText.length > 0)
    assert.strictEqual(vm.data.searchStale, false)
    assert.ok(tracks.some((t) => t.name === 'feature_action' && t.data.feature === 'library' && t.data.action === 'search' && t.data.field === 'title'))
  })

  await check('加载更多：页码递增并追加；重复点击不重复请求', async () => {
    const vm = makeInstance()
    vm.data.keyword = '高等数学'
    vm.data.searched = true
    vm.data.hasMore = true
    vm.data.page = 1
    vm.data.records = [vm._decorateRecord(BOOK_A)]
    const d = defer()
    responses.search.push(d)
    const before = searchCalls.length
    vm.onLoadMore()
    vm.onLoadMore()
    await flush()
    assert.strictEqual(searchCalls.length - before, 1)
    assert.strictEqual(searchCalls[before].page, 2)
    d.resolve({ success: true, total: 25, page: 2, page_size: 20, has_more: false, records: [BOOK_B], stale: false, updated_at: 1793208600 })
    await flush()
    assert.strictEqual(vm.data.page, 2)
    assert.strictEqual(vm.data.records.length, 2)
    assert.strictEqual(vm.data.hasMore, false)
  })

  await check('切换检索字段：在途旧字段响应失效，不套到新字段下', async () => {
    const vm = makeInstance()
    vm.data.keyword = '高等数学'
    const stale = defer()
    responses.search.push(stale)
    vm.onSearch()
    await flush()
    vm.onFieldTap({ currentTarget: { dataset: { index: 1 } } })
    assert.strictEqual(vm.data.fieldIndex, 1)
    assert.strictEqual(vm.data.loading, false)
    stale.resolve({ success: true, total: 1, page: 1, page_size: 20, has_more: false, records: [BOOK_A], stale: false, updated_at: 1793208600 })
    await flush()
    assert.strictEqual(vm.data.records.length, 0, '旧字段响应不得写入')
  })

  await check('搜索竞态：新搜索后旧加载更多响应不得覆盖', async () => {
    const vm = makeInstance()
    vm.data.keyword = '高等数学'
    vm.data.searched = true
    vm.data.hasMore = true
    vm.data.page = 1
    vm.data.records = [vm._decorateRecord(BOOK_A)]
    const oldLoad = defer()
    responses.search.push(oldLoad)
    vm.onLoadMore()
    await flush()

    const newSearch = defer()
    responses.search.push(newSearch)
    const beforeNew = searchCalls.length
    vm.onSearch()
    await flush()
    assert.strictEqual(searchCalls.length - beforeNew, 1, '新搜索应能覆盖在途加载更多')
    newSearch.resolve({ success: true, total: 1, page: 1, page_size: 20, has_more: false, records: [BOOK_B], stale: false, updated_at: 1793208601 })
    await flush()
    assert.strictEqual(vm.data.records.length, 1)
    assert.strictEqual(vm.data.records[0].marcNo, 'MARC-B')

    oldLoad.resolve({ success: true, total: 25, page: 2, page_size: 20, has_more: true, records: [BOOK_A], stale: false, updated_at: 1793208600 })
    await flush()
    assert.strictEqual(vm.data.records.length, 1)
    assert.strictEqual(vm.data.records[0].marcNo, 'MARC-B')
    assert.strictEqual(vm.data.total, 1)
  })

  await check('详情按需请求：只请求点选书目，展示统计/状态类/校区计数', async () => {
    const vm = makeInstance()
    vm.data.records = [vm._decorateRecord(BOOK_A)]
    const d = defer()
    responses.item.push(d)
    const beforeItem = itemCalls.length
    vm.onOpenDetail({ currentTarget: { dataset: { index: 0 } } })
    await flush()
    assert.deepStrictEqual(itemCalls[beforeItem], { marcNo: 'MARC-A', campus: 'all' })
    assert.strictEqual(vm.data.showDetail, true)
    assert.strictEqual(vm.data.detailLoading, true)
    d.resolve(COPIES_ALL)
    await flush()
    assert.strictEqual(vm.data.detailLoading, false)
    assert.strictEqual(vm.data.detailTotal, 3)
    assert.strictEqual(vm.data.detailAvailable, 1)
    assert.strictEqual(vm.data.copies.length, 3)
    assert.strictEqual(vm.data.copies[0].statusClass, 'is-available')
    assert.strictEqual(vm.data.copies[1].statusClass, 'is-unavailable')
    assert.deepStrictEqual(vm.data.campusCounts, { all: 3, nanjing: 1, jiangyin: 1, unknown: 1 })
    assert.ok(vm.__events.some((e) => e.name === 'popupstate' && e.detail.open === true))
  })

  await check('校区切换：请求对应校区并更新统计/明细；统计与明细一致', async () => {
    const vm = makeInstance()
    vm.data.records = [vm._decorateRecord(BOOK_A)]
    const first = defer()
    responses.item.push(first)
    vm.onOpenDetail({ currentTarget: { dataset: { index: 0 } } })
    await flush()
    first.resolve(COPIES_ALL)
    await flush()

    const jiangyin = defer()
    responses.item.push(jiangyin)
    const beforeCampus = itemCalls.length
    vm.onCampusTap({ currentTarget: { dataset: { scope: 'jiangyin' } } })
    await flush()
    assert.strictEqual(itemCalls[beforeCampus].campus, 'jiangyin')
    jiangyin.resolve(COPIES_JIANGYIN)
    await flush()
    assert.strictEqual(vm.data.campusScope, 'jiangyin')
    assert.strictEqual(vm.data.detailTotal, 1)
    assert.strictEqual(vm.data.detailAvailable, 0)
    assert.strictEqual(vm.data.copies.length, 1)
    assert.strictEqual(vm.data.copies[0].campus, '江阴')
  })

  await check('详情竞态：快速切校区时旧响应不得覆盖新校区', async () => {
    const vm = makeInstance()
    vm.data.records = [vm._decorateRecord(BOOK_A)]
    const open = defer()
    responses.item.push(open)
    vm.onOpenDetail({ currentTarget: { dataset: { index: 0 } } })
    await flush()
    open.resolve(COPIES_ALL)
    await flush()

    const oldScope = defer()
    responses.item.push(oldScope)
    vm.onCampusTap({ currentTarget: { dataset: { scope: 'nanjing' } } })
    await flush()
    const newScope = defer()
    responses.item.push(newScope)
    vm.onCampusTap({ currentTarget: { dataset: { scope: 'jiangyin' } } })
    await flush()

    newScope.resolve(COPIES_JIANGYIN)
    await flush()
    oldScope.resolve(COPIES_ALL)
    await flush()
    assert.strictEqual(vm.data.campusScope, 'jiangyin')
    assert.strictEqual(vm.data.copies.length, 1)
    assert.strictEqual(vm.data.copies[0].campus, '江阴')
  })

  await check('关闭详情：晚到响应不重新打开、不写数据、popupstate=false', async () => {
    const vm = makeInstance()
    vm.data.records = [vm._decorateRecord(BOOK_A)]
    const d = defer()
    responses.item.push(d)
    vm.onOpenDetail({ currentTarget: { dataset: { index: 0 } } })
    await flush()
    vm.onDetailClose()
    assert.strictEqual(vm.data.showDetail, false)
    assert.ok(vm.__events.some((e) => e.name === 'popupstate' && e.detail.open === false))

    d.resolve(COPIES_ALL)
    await flush()
    assert.strictEqual(vm.data.showDetail, false)
    assert.strictEqual(vm.data.copies.length, 0)
  })

  await check('错误：保留已有列表并提示；重试失败页仍可再次请求', async () => {
    const vm = makeInstance()
    vm.data.keyword = '高等数学'
    vm.data.searched = true
    vm.data.page = 2
    vm.data.hasMore = true
    vm.data.records = [vm._decorateRecord(BOOK_A)]
    const bad = defer()
    responses.search.push(bad)
    vm.onLoadMore()
    await flush()
    bad.resolve({ success: false, message: '图书馆检索服务暂时不可用，请稍后再试' })
    await flush()
    assert.strictEqual(vm.data.loading, false)
    assert.strictEqual(vm.data.records.length, 1)
    assert.ok(vm.data.errorMsg.indexOf('暂时不可用') >= 0)

    const retry = defer()
    responses.search.push(retry)
    vm.onRetry()
    await flush()
    assert.strictEqual(searchCalls[searchCalls.length - 1].page, 2)
    retry.resolve({ success: true, total: 25, page: 2, page_size: 20, has_more: true, records: [BOOK_B], stale: true, updated_at: 1793208600 })
    await flush()
    assert.strictEqual(vm.data.records.length, 2)
    assert.strictEqual(vm.data.errorMsg, '')
    assert.strictEqual(vm.data.searchStale, true)
  })

  await check('详情错误：显示错误并可重试', async () => {
    const vm = makeInstance()
    vm.data.records = [vm._decorateRecord(BOOK_A)]
    const bad = defer()
    responses.item.push(bad)
    vm.onOpenDetail({ currentTarget: { dataset: { index: 0 } } })
    await flush()
    bad.resolve({ success: false, message: '图书馆馆藏服务暂时不可用，请稍后再试' })
    await flush()
    assert.strictEqual(vm.data.detailError.indexOf('暂时不可用') >= 0, true)
    assert.strictEqual(vm.data.detailLoading, false)

    const retry = defer()
    responses.item.push(retry)
    vm.onDetailRetry()
    await flush()
    retry.resolve(COPIES_ALL)
    await flush()
    assert.strictEqual(vm.data.detailError, '')
    assert.strictEqual(vm.data.copies.length, 3)
  })

  // 收起测试依赖
  const total = pass + failures.length
  console.log('\n通过 ' + pass + '/' + total + ' 项')
  if (failures.length) {
    console.log('失败: ' + failures.join(', '))
    process.exit(1)
  }
})().catch((error) => { console.error(error); process.exit(1) })
