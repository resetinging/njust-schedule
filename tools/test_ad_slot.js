const assert = require('assert')
const fs = require('fs')
const path = require('path')

const ROOT = path.resolve(__dirname, '..')
const componentPath = path.join(ROOT, 'components', 'ad-slot', 'index.js')
const analyticsPath = require.resolve(path.join(ROOT, 'utils', 'analytics'))
const events = []

require.cache[analyticsPath] = {
  id: analyticsPath,
  filename: analyticsPath,
  loaded: true,
  exports: {
    track(name, data) {
      events.push({ name, data })
    }
  }
}

let definition = null
global.Component = (value) => {
  definition = value
}

try {
  delete require.cache[require.resolve(componentPath)]
  require(componentPath)

  assert(definition, 'ad-slot component definition missing')
  assert(definition.properties.height, 'ad-slot height property missing')
  assert.strictEqual(definition.properties.height.type, String,
    'ad-slot height property must accept WXML dimension strings')
  const component = {
    data: {
      unitId: 'adunit-test',
      slotId: 'slot-test',
      page: 'feature',
      adType: 'native',
      loaded: false
    },
    setData(patch) {
      Object.assign(this.data, patch)
    }
  }

  definition.lifetimes.attached.call(component)
  definition.methods.onAdLoad.call(component)
  definition.methods.onAdLoad.call(component)
  definition.methods.onAdError.call(component, { detail: { errCode: 1004 } })
  definition.methods.onAdClose.call(component)

  assert.deepStrictEqual(events.map((event) => event.name), [
    'ad_request',
    'ad_loaded',
    'ad_impression',
    'ad_failed',
    'ad_close'
  ])
  assert.strictEqual(events[3].data.kind, '1004')

  const mainJSON = fs.readFileSync(path.join(ROOT, 'pages', 'main', 'main.json'), 'utf8')
  const mainWXML = fs.readFileSync(path.join(ROOT, 'pages', 'main', 'main.wxml'), 'utf8')
  const slotWXML = fs.readFileSync(path.join(ROOT, 'components', 'ad-slot', 'index.wxml'), 'utf8')
  const slotWXSS = fs.readFileSync(path.join(ROOT, 'components', 'ad-slot', 'index.wxss'), 'utf8')
  assert(mainJSON.includes('"ad-slot": "/components/ad-slot/index"'))
  assert(mainWXML.includes('id="slot-feature-bottom"'))
  assert(mainWXML.includes('unit-id="adunit-8f99eb551760e548"'))
  assert(slotWXML.includes('<ad-custom'))
  assert(slotWXML.includes('bindclose="onAdClose"'))
  assert(slotWXML.includes('style="min-height: {{height}};"'))
  assert(!/<ad-custom[\s\S]*style="height:/.test(slotWXML),
    'height must not be forced onto native ad-custom')
  assert(!slotWXSS.includes('overflow: hidden'),
    'ad-slot must not crop native ad-custom content')
  assert(slotWXSS.includes('padding-top: 16rpx'))

  const scheduleJSON = fs.readFileSync(
    path.join(ROOT, 'components', 'schedule-view', 'index.json'), 'utf8')
  const scheduleWXML = fs.readFileSync(
    path.join(ROOT, 'components', 'schedule-view', 'index.wxml'), 'utf8')
  const scheduleJS = fs.readFileSync(
    path.join(ROOT, 'components', 'schedule-view', 'index.js'), 'utf8')
  // 课表页不接入广告：不注册 ad-slot、不渲染原生广告、不留广告预留高度
  assert(!scheduleJSON.includes('"ad-slot"'), '课表不应再注册 ad-slot 组件')
  assert(!/<ad-slot\b/.test(scheduleWXML), '课表不应再有 ad-slot 实例')
  assert(!scheduleWXML.includes('slot-schedule-mid'), '课表中部广告槽位应已撤除')
  assert(!scheduleWXML.includes('unit-id="adunit-8f99eb551760e548"'), '课表不应再出现广告 unit-id')
  assert(!scheduleWXML.includes('height="160rpx"'), '课表不应保留广告预留高度')
  assert(!/<ad-custom\b/.test(scheduleWXML), '课表不应有原生 ad-custom 节点')
  // 底部历史库存统计标记保留：纯标记、无广告渲染、不占高度
  assert(scheduleWXML.includes('id="slot-schedule-bottom"'), '课表底部历史统计标记应保留')
  assert(scheduleWXML.includes('class="analytics-slot-marker"'), '课表底部统计标记应为纯标记')
  const gridStart = scheduleWXML.indexOf('<view class="grid-wrapper"')
  const todayCardStart = scheduleWXML.indexOf('<view class="today-card"')
  assert(todayCardStart >= 0 && gridStart > todayCardStart, '今日课程后应直接衔接课表内容')
  // 统计注册只保留底部历史标记，中部槽位不再注册
  assert(scheduleJS.includes("{ id: 'slot-schedule-bottom', page: 'schedule', ad_type: 'native' }"),
    '课表底部历史统计槽位应保留注册')
  assert(!scheduleJS.includes('slot-schedule-mid'), '课表中部广告统计注册应已移除')
  assert.strictEqual((scheduleJS.match(/observeSlots\(/g) || []).length, 1,
    '课表只应保留一次槽位观察注册')

  const pages = [
    ['exams-view', 'slot-exams-bottom'],
    ['eval-view', 'slot-eval-bottom'],
    ['grades-view', 'slot-grades-bottom'],
    ['credit-view', 'slot-credit-bottom'],
    ['freeclass-view', 'slot-freeclass-bottom'],
    ['gallery-view', 'slot-gallery-bottom'],
    ['audit-course-view', 'slot-audit-bottom']
  ]
  pages.forEach(([name, slot]) => {
    const pageJSON = fs.readFileSync(
      path.join(ROOT, 'components', name, 'index.json'), 'utf8')
    const pageWXML = fs.readFileSync(
      path.join(ROOT, 'components', name, 'index.wxml'), 'utf8')
    assert(pageJSON.includes('"ad-slot": "/components/ad-slot/index"'), name)
    assert(pageWXML.includes(`id="${slot}"`), name)
    assert(pageWXML.includes(`slot-id="${slot}"`), name)
    assert.strictEqual((pageWXML.match(/<ad-slot\b/g) || []).length, 1, name)
  })

  console.log('Ad slot integration test passed [OK]')
} finally {
  delete global.Component
  delete require.cache[componentPath]
}
