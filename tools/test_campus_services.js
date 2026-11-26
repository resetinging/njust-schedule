const assert = require('assert')
const fs = require('fs')
const path = require('path')

const ROOT = path.resolve(__dirname, '..')
const storageValues = new Map()

global.wx = {
  getStorageSync: (key) => storageValues.has(key) ? storageValues.get(key) : '',
  setStorageSync: (key, value) => storageValues.set(key, value),
  removeStorageSync: (key) => storageValues.delete(key),
  getStorageInfoSync: () => ({ keys: Array.from(storageValues.keys()) })
}

let componentConfig = null
global.Component = (config) => { componentConfig = config }

const calls = []
const listResponses = []
const detailResponses = []
const leadResponses = []

function deferred() {
  let resolve
  let reject
  const promise = new Promise((res, rej) => { resolve = res; reject = rej })
  return { promise, resolve, reject }
}

const apiPath = require.resolve(path.join(ROOT, 'utils', 'api'))
require.cache[apiPath] = {
  id: apiPath,
  filename: apiPath,
  loaded: true,
  exports: {
    listCampusServices(options) {
      calls.push({ name: 'list', options })
      return listResponses.shift().promise
    },
    getCampusService(id) {
      calls.push({ name: 'detail', id })
      return detailResponses.shift().promise
    },
    submitCampusServiceLead(id, options) {
      calls.push({ name: 'lead', id, options })
      return leadResponses.shift().promise
    }
  }
}

const analyticsPath = require.resolve(path.join(ROOT, 'utils', 'analytics'))
require.cache[analyticsPath] = {
  id: analyticsPath,
  filename: analyticsPath,
  loaded: true,
  exports: {
    featureAction() {},
    featureOpen() {},
    pageView() {},
    refreshResult() {},
    track() {}
  }
}

const storage = require(path.join(ROOT, 'utils', 'storage'))
require(path.join(ROOT, 'components', 'campus-services-view', 'index.js'))
assert(componentConfig && componentConfig.methods, 'campus-services-view 未加载')

const baseData = typeof componentConfig.data === 'function'
  ? componentConfig.data()
  : componentConfig.data

function makeInstance() {
  const events = []
  return Object.assign({}, componentConfig.methods, {
    events,
    data: JSON.parse(JSON.stringify(baseData || {})),
    setData(patch) {
      Object.assign(this.data, patch || {})
    },
    triggerEvent(name, detail) {
      events.push({ name, detail })
    }
  })
}

function service(overrides) {
  return Object.assign({
    id: 'campus-1',
    category: 'exam',
    provider_name: '示例机构',
    title: '考研数学咨询',
    summary: '基础咨询',
    details: '包含学习规划与答疑',
    audience: '准备考研的学生',
    price_label: '按次咨询',
    campus_scope: 'all',
    qualification_note: '已核验营业执照',
    sponsored: true,
    start_date: '2026-11-24',
    end_date: '2026-12-31'
  }, overrides || {})
}

;(async () => {
  const mainWxml = fs.readFileSync(path.join(ROOT, 'pages', 'main', 'main.wxml'), 'utf8')
  const mainJs = fs.readFileSync(path.join(ROOT, 'pages', 'main', 'main.js'), 'utf8')
  const wxml = fs.readFileSync(path.join(ROOT, 'components', 'campus-services-view', 'index.wxml'), 'utf8')
  const wxss = fs.readFileSync(path.join(ROOT, 'components', 'campus-services-view', 'index.wxss'), 'utf8')

  assert(mainWxml.includes('data-page="services"'), '功能页缺少校园服务入口')
  assert(mainWxml.includes('toolPage === \'services\''), '主页面缺少校园服务容器')
  assert(mainJs.includes("'services'"), '主页面路由缺少 services')
  assert.strictEqual((wxml.match(/<t-popup/g) || []).length, 1, '只允许一个服务弹层实例')
  assert(!wxml.includes('page-container'), '不得新增 page-container')
  assert(wxml.includes('获取咨询方式') && wxml.includes('同意将联系方式'))
  assert(!wxml.includes('合作服务'), '页面不应出现合作服务字样')
  assert(!wxml.includes('coop-tag'), '不应保留合作标签')
  assert(!wxml.includes('项服务'), '标题行不应显示服务数量')
  assert(!wxml.includes('均为已审核条目'), '标题行不应显示审核提示')
  assert(wxml.includes('aria-label="刷新校园服务"'), '刷新入口应保留')
  assert(!wxml.includes('result-head'), '不应保留独立刷新标题行')
  assert(wxml.includes('custom-nav-refresh'), '刷新入口应位于顶部导航栏')
  assert(!wxml.includes('service-ledger-refresh'), '服务列表内不应保留刷新入口')
  assert(!wxml.includes('is-first'), '第一条服务不应再为刷新按钮避让')
  assert(
    /\.custom-nav-refresh\s*\{[^}]*position:\s*absolute[^}]*top:\s*0[^}]*right:\s*0/s.test(wxss),
    '刷新按钮应与返回按钮同高并靠右'
  )

  const instance = makeInstance()
  assert.deepStrictEqual(
    instance.data.categories.map((item) => item.label),
    ['校园卡', '考研', '保研', '期末复习'],
    '分类顺序应为校园卡、考研、保研、期末复习'
  )
  assert(!instance.data.categories.some((item) => item.label === '全部'), '不应保留全部栏')
  assert.strictEqual(instance.data.activeCategory, 'operator', '默认应进入校园卡分类')
  const listDeferred = deferred()
  listResponses.push(listDeferred)
  instance.activate()
  assert.strictEqual(instance.data.loading, true)
  assert.strictEqual(calls[calls.length - 1].options.category, 'operator')
  listDeferred.resolve({
    success: true,
    services: [service()],
    total: 1,
    page: 1,
    has_more: false
  })
  await new Promise((resolve) => setTimeout(resolve, 0))
  assert.strictEqual(instance.data.services.length, 1)
  assert.strictEqual(instance.data.services[0].categoryLabel, '考研')
  assert.strictEqual(instance.data.services[0].validityText, '有效至 2026-12-31')

  const categoryDeferred = deferred()
  listResponses.push(categoryDeferred)
  instance.onCategoryTap({ currentTarget: { dataset: { category: 'materials' } } })
  assert.strictEqual(instance.data.activeCategory, 'materials')
  assert.strictEqual(calls[calls.length - 1].options.category, 'materials')
  categoryDeferred.resolve({ success: true, services: [], total: 0, has_more: false })
  await new Promise((resolve) => setTimeout(resolve, 0))

  instance.setData({ activeCategory: 'operator', services: [instance._decorateService(service())] })
  const detailDeferred = deferred()
  detailResponses.push(detailDeferred)
  instance.onOpenService({ currentTarget: { dataset: { index: 0 } } })
  assert.strictEqual(instance.data.showSheet, true)
  assert(instance.events.some((event) => event.name === 'popupstate' && event.detail.open === true))
  detailDeferred.resolve({ success: true, service: service() })
  await new Promise((resolve) => setTimeout(resolve, 0))
  assert.strictEqual(instance.data.detailLoading, false)
  assert.strictEqual(instance.data.selectedService.details, '包含学习规划与答疑')

  storage.setStudentId('')
  storage.remove('token')
  instance.onStartLead()
  assert(instance.events.some((event) => event.name === 'login'))
  assert.strictEqual(instance.data.showSheet, false)

  storage.setStudentId('924101960123')
  storage.set('token', 'test-token')
  instance.setData({
    showSheet: true,
    sheetMode: 'lead',
    selectedService: instance._decorateService(service()),
    contactType: 'phone'
  })
  instance.onContactInput({ detail: { value: '123' } })
  instance.onToggleConsent()
  instance.onSubmitLead()
  assert(instance.data.submitError.includes('手机号'))

  instance.onContactInput({ detail: { value: '13800138000' } })
  const leadDeferred = deferred()
  leadResponses.push(leadDeferred)
  instance.onSubmitLead()
  assert.strictEqual(instance.data.submitting, true)
  leadDeferred.resolve({ success: true, lead_id: 7 })
  await new Promise((resolve) => setTimeout(resolve, 0))
  assert.strictEqual(instance.data.sheetMode, 'success')
  assert.strictEqual(calls[calls.length - 1].options.consent, true)

  instance.onCloseSheet()
  assert.strictEqual(instance.data.showSheet, false)
  assert(instance.events.some((event) => event.name === 'popupstate' && event.detail.open === false))

  console.log('Campus services frontend test passed [OK]')
})().catch((error) => {
  console.error(error && error.stack || error)
  process.exit(1)
})
