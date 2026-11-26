/**
 * 图书馆库存页行为测试 — Node 中模拟小程序组件运行时。
 *
 * 覆盖：草稿/提交条件分离、翻页/刷新绑定已提交条件、失败页精确重试、
 * 新搜索竞态、字段切换、详情校区/关闭竞态、截断状态。
 *
 * 运行: node tools/test_library.js
 */
const assert = require('assert')
const path = require('path')

const ROOT = path.resolve(process.argv[2] || path.join(__dirname, '..'))
global.wx = {
  getWindowInfo() { return { statusBarHeight: 47, windowWidth: 390 } },
  getMenuButtonBoundingClientRect() { return { top: 51, left: 281, width: 87, height: 32 } }
}

let componentConfig = null
global.Component = (config) => { componentConfig = config }

const searchCalls = []
const itemCalls = []
const tracks = []
const responses = { search: [], item: [] }

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
const analyticsStub = { featureAction(feature, page, extra) { tracks.push({ feature, page, extra }) } }

const apiPath = require.resolve(path.join(ROOT, 'utils', 'api'))
const analyticsPath = require.resolve(path.join(ROOT, 'utils', 'analytics'))
require.cache[apiPath] = { id: apiPath, filename: apiPath, loaded: true, exports: apiStub }
require.cache[analyticsPath] = { id: analyticsPath, filename: analyticsPath, loaded: true, exports: analyticsStub }
require(path.join(ROOT, 'components', 'library-view', 'index.js'))

let pass = 0
const failures = []
async function check(name, fn) {
  try {
    await fn()
    pass++
    console.log('  ✓ ' + name)
  } catch (error) {
    failures.push(name)
    console.log('  ✗ ' + name + '  → ' + error.message)
  }
}

function makeInstance() {
  const events = []
  const instance = {
    data: JSON.parse(JSON.stringify(componentConfig.data)),
    setData(patch) { Object.assign(this.data, patch) },
    triggerEvent(name, detail) { events.push({ name, detail }) }
  }
  Object.keys(componentConfig.methods).forEach((name) => { instance[name] = componentConfig.methods[name] })
  componentConfig.lifetimes.attached.call(instance)
  instance.__events = events
  return instance
}

const flush = () => new Promise((resolve) => setTimeout(resolve, 0))

function book(id) {
  return {
    marc_no: String(id), title: '示例书目 ' + id, author: '示例作者', publisher: '示例出版社',
    pub_year: '2013', isbn: '978-7-0000-0000-0', call_no: 'O13/797', doc_type: '中文图书', num: 1
  }
}
function records(from, to) {
  const out = []
  for (let i = from; i <= to; i++) out.push(book(i))
  return out
}
function pageResponse({ records: recs, total, page, hasMore = false, truncated = false, maxPage = 200, stale = false }) {
  return {
    success: true, records: recs, total, page, page_size: 20,
    has_more: hasMore, truncated, max_page: maxPage, stale, updated_at: 1793208600
  }
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

async function commitSearch(vm, keyword, fieldIndex) {
  vm.data.keyword = keyword
  if (fieldIndex !== undefined) vm.data.fieldIndex = fieldIndex
  vm.onSearch()
  await flush()
}

;(async () => {
  await check('无关键词不请求，提示输入', async () => {
    const vm = makeInstance()
    const before = searchCalls.length
    vm.data.keyword = '   '
    vm.onSearch()
    await flush()
    assert.strictEqual(searchCalls.length, before)
    assert.ok(vm.data.errorMsg.indexOf('请输入') >= 0)
  })

  await check('提交搜索：记录提交快照，列表使用提交条件', async () => {
    const vm = makeInstance()
    const d = defer()
    responses.search.push(d)
    const before = searchCalls.length
    await commitSearch(vm, '高等数学')
    assert.deepStrictEqual(searchCalls[before], { field: 'title', q: '高等数学', page: 1 })
    d.resolve(pageResponse({ records: records(1, 20), total: 45, page: 1, hasMore: true }))
    await flush()
    assert.strictEqual(vm.data.committedKeyword, '高等数学')
    assert.strictEqual(vm.data.committedFieldKey, 'title')
    assert.strictEqual(vm.data.records.length, 20)
    assert.strictEqual(vm.data.hasMore, true)
    assert.ok(tracks.some((t) => t.extra.action === 'search'))
  })

  await check('草稿改变后加载更多仍绑定已提交条件（不 append 草稿结果）', async () => {
    const vm = makeInstance()
    const first = defer()
    responses.search.push(first)
    await commitSearch(vm, 'Math')
    first.resolve(pageResponse({ records: records(1, 20), total: 45, page: 1, hasMore: true }))
    await flush()

    vm.onKeywordInput({ detail: { value: 'Physics' } })
    const second = defer()
    responses.search.push(second)
    const before = searchCalls.length
    vm.onLoadMore()
    await flush()
    assert.deepStrictEqual(searchCalls[before], { field: 'title', q: 'Math', page: 2 })
    second.resolve(pageResponse({ records: records(21, 40), total: 45, page: 2, hasMore: true }))
    await flush()
    assert.strictEqual(vm.data.records.length, 40)
    assert.strictEqual(vm.data.records[0].title, '示例书目 1')
    assert.strictEqual(vm.data.records[39].title, '示例书目 40')
  })

  await check('字段切换清空旧列表，且未提交前不再翻页', async () => {
    const vm = makeInstance()
    const d = defer()
    responses.search.push(d)
    await commitSearch(vm, 'Math')
    d.resolve(pageResponse({ records: records(1, 20), total: 45, page: 1, hasMore: true }))
    await flush()

    vm.onFieldTap({ currentTarget: { dataset: { index: 1 } } })
    assert.strictEqual(vm.data.records.length, 0)
    assert.strictEqual(vm.data.searched, false)
    assert.strictEqual(vm.data.committedKeyword, '')
    const before = searchCalls.length
    vm.onLoadMore()
    await flush()
    assert.strictEqual(searchCalls.length, before)

    const authorSearch = defer()
    responses.search.push(authorSearch)
    await commitSearch(vm, '杨海涛', 1)
    assert.deepStrictEqual(searchCalls[searchCalls.length - 1], { field: 'author', q: '杨海涛', page: 1 })
    authorSearch.resolve(pageResponse({ records: records(1, 1), total: 1, page: 1 }))
    await flush()
    assert.strictEqual(vm.data.records.length, 1)
    assert.strictEqual(vm.data.committedFieldKey, 'author')
  })

  await check('第 3 页失败后重试原页，不重复 append 第 2 页', async () => {
    const vm = makeInstance()
    const p1 = defer()
    responses.search.push(p1)
    await commitSearch(vm, 'Math')
    p1.resolve(pageResponse({ records: records(1, 20), total: 45, page: 1, hasMore: true }))
    await flush()
    const p2 = defer()
    responses.search.push(p2)
    vm.onLoadMore()
    await flush()
    p2.resolve(pageResponse({ records: records(21, 40), total: 45, page: 2, hasMore: true }))
    await flush()
    const p3 = defer()
    responses.search.push(p3)
    vm.onLoadMore()
    await flush()
    p3.resolve({ success: false, message: '第3页失败' })
    await flush()
    assert.strictEqual(vm.data.records.length, 40)
    assert.strictEqual(vm.data.page, 2)
    assert.ok(vm.data.errorMsg.indexOf('失败') >= 0)

    const retry = defer()
    responses.search.push(retry)
    const before = searchCalls.length
    vm.onRetry()
    await flush()
    assert.deepStrictEqual(searchCalls[before], { field: 'title', q: 'Math', page: 3 })
    retry.resolve(pageResponse({ records: records(41, 45), total: 45, page: 3, hasMore: false }))
    await flush()
    assert.strictEqual(vm.data.records.length, 45)
    assert.deepStrictEqual(vm.data.records.map((r) => r.marcNo).slice(40), ['41', '42', '43', '44', '45'])
    assert.strictEqual(vm.data.hasMore, false)
    assert.strictEqual(vm.data.errorMsg, '')
  })

  await check('首屏失败重试原始第 1 页（替换而不是 append）', async () => {
    const vm = makeInstance()
    const fail = defer()
    responses.search.push(fail)
    await commitSearch(vm, 'Linear')
    fail.resolve({ success: false, message: '首屏失败' })
    await flush()
    assert.strictEqual(vm.data.records.length, 0)

    const retry = defer()
    responses.search.push(retry)
    const before = searchCalls.length
    vm.onRetry()
    await flush()
    assert.deepStrictEqual(searchCalls[before], { field: 'title', q: 'Linear', page: 1 })
    retry.resolve(pageResponse({ records: records(1, 20), total: 45, page: 1, hasMore: true }))
    await flush()
    assert.strictEqual(vm.data.records.length, 20)
    assert.strictEqual(vm.data.records[0].marcNo, '1')
  })

  await check('刷新复用已提交条件，不使用输入框新草稿', async () => {
    const vm = makeInstance()
    const first = defer()
    responses.search.push(first)
    await commitSearch(vm, 'Math')
    first.resolve(pageResponse({ records: records(1, 20), total: 45, page: 1, hasMore: true }))
    await flush()

    vm.onKeywordInput({ detail: { value: 'Physics' } })
    const refresh = defer()
    responses.search.push(refresh)
    const before = searchCalls.length
    vm.onRefresh()
    await flush()
    assert.deepStrictEqual(searchCalls[before], { field: 'title', q: 'Math', page: 1 })
    refresh.resolve(pageResponse({ records: records(1, 20), total: 45, page: 1, hasMore: true }))
    await flush()
    assert.strictEqual(vm.data.records.length, 20)
    assert.strictEqual(vm.data.committedKeyword, 'Math')
  })

  await check('新搜索失效旧加载更多响应', async () => {
    const vm = makeInstance()
    const p1 = defer()
    responses.search.push(p1)
    await commitSearch(vm, 'Math')
    p1.resolve(pageResponse({ records: records(1, 20), total: 45, page: 1, hasMore: true }))
    await flush()

    const oldMore = defer()
    responses.search.push(oldMore)
    vm.onLoadMore()
    await flush()

    const newSearch = defer()
    responses.search.push(newSearch)
    await commitSearch(vm, 'Physics')
    newSearch.resolve(pageResponse({ records: records(101, 102), total: 2, page: 1, hasMore: false }))
    await flush()
    oldMore.resolve(pageResponse({ records: records(21, 40), total: 45, page: 2, hasMore: true }))
    await flush()
    assert.strictEqual(vm.data.records.length, 2)
    assert.strictEqual(vm.data.records[0].marcNo, '101')
    assert.strictEqual(vm.data.committedKeyword, 'Physics')
  })

  await check('服务端截断：has_more=false 时保留真实 total 并标记 truncated', async () => {
    const vm = makeInstance()
    const d = defer()
    responses.search.push(d)
    await commitSearch(vm, 'Math')
    d.resolve(pageResponse({ records: records(1, 20), total: 100000, page: 200, hasMore: false, truncated: true, maxPage: 200 }))
    await flush()
    assert.strictEqual(vm.data.hasMore, false)
    assert.strictEqual(vm.data.truncated, true)
    assert.strictEqual(vm.data.total, 100000)
    assert.strictEqual(vm.data.maxPage, 200)
  })

  await check('详情按需请求：展示统计/状态类/校区计数', async () => {
    const vm = makeInstance()
    vm.data.records = [vm._decorateRecord(book(1))]
    const d = defer()
    responses.item.push(d)
    const before = itemCalls.length
    vm.onOpenDetail({ currentTarget: { dataset: { index: 0 } } })
    await flush()
    assert.deepStrictEqual(itemCalls[before], { marcNo: '1', campus: 'all' })
    assert.strictEqual(vm.data.showDetail, true)
    d.resolve(COPIES_ALL)
    await flush()
    assert.strictEqual(vm.data.detailTotal, 3)
    assert.strictEqual(vm.data.detailAvailable, 1)
    assert.strictEqual(vm.data.copies.length, 3)
    assert.strictEqual(vm.data.copies[0].statusClass, 'is-available')
    assert.deepStrictEqual(vm.data.campusCounts, { all: 3, nanjing: 1, jiangyin: 1, unknown: 1 })
    assert.ok(vm.__events.some((e) => e.name === 'popupstate' && e.detail.open === true))
  })

  await check('校区切换与详情竞态、关闭后晚到响应被忽略', async () => {
    const vm = makeInstance()
    vm.data.records = [vm._decorateRecord(book(1))]
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

    const late = defer()
    responses.item.push(late)
    vm.onCampusTap({ currentTarget: { dataset: { scope: 'all' } } })
    await flush()
    vm.onDetailClose()
    late.resolve(COPIES_ALL)
    await flush()
    assert.strictEqual(vm.data.showDetail, false)
    assert.strictEqual(vm.data.copies.length, 0)
    assert.ok(vm.__events.some((e) => e.name === 'popupstate' && e.detail.open === false))
  })

  const total = pass + failures.length
  console.log('\n通过 ' + pass + '/' + total + ' 项')
  if (failures.length) {
    console.log('失败: ' + failures.join(', '))
    process.exit(1)
  }
})().catch((error) => { console.error(error); process.exit(1) })
