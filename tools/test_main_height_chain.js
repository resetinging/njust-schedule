const assert = require('assert')
const fs = require('fs')
const path = require('path')

const ROOT = path.resolve(__dirname, '..')
const read = (file) => fs.readFileSync(path.join(ROOT, file), 'utf8')

const main = read('pages/main/main.wxss')
const mainJs = read('pages/main/main.js')
const mainWxml = read('pages/main/main.wxml')
const schedule = read('components/schedule-view/index.wxss')
const settings = read('components/settings-view/index.wxss')
const scheduleJs = read('components/schedule-view/index.js')
const scheduleWxml = read('components/schedule-view/index.wxml')
const pickerJs = read('components/ui-picker/index.js')
const ds = read('styles/design-system.wxss')

/** 取行首锚定的规则块（同名规则有组合选择器时取最后一个完整定义） */
function blockAtLineStart(text, selector) {
  const re = new RegExp('^' + selector.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + '\\s*\\{([^}]*)\\}', 'gms')
  let last = ''
  let m
  while ((m = re.exec(text)) !== null) last = m[1]
  return last
}

// ── 1. flex 高度链：宿主只填满父级，不再二次滚动/内边距/固定高度 ──
const hosts = main.match(/\.tab-wrap > schedule-view,[\s\S]*?\.tab-wrap > \.feat-page\s*\{([^}]*)\}/)
assert(hosts, '缺少 .tab-wrap > 一级视图宿主规则')
assert(/flex:\s*1/.test(hosts[1]), '宿主必须 flex:1 填满父级')
assert(/min-height:\s*0/.test(hosts[1]), '宿主必须 min-height:0')
assert(!/overflow/.test(hosts[1]), '宿主不得加滚动（会造成二次滚动/截断）')
assert(!/\bpadding\b/.test(hosts[1]), '宿主不得加内边距（会缩小可视区域）')
assert(!/height:\s*100%/.test(hosts[1]), '宿主高度应由 flex 决定，不写 height:100%')

// 功能页不是组件：自己滚动 + 底部留白落在可滚内容尾部
const feat = blockAtLineStart(main, '.feat-page')
assert(/overflow-y:\s*auto/.test(feat), '功能页应自己滚动')
assert(/padding:\s*24rpx var\(--space-page\) calc\(140rpx \+ env\(safe-area-inset-bottom\)\)/.test(feat),
  '功能页底部留白应为 calc(140rpx + 安全区)')

// 课表/我的：只有内部 scroll-view 滚动，且底部留白在滚动内容内
for (const [name, text] of [['课表', schedule], ['我的', settings]]) {
  const sc = blockAtLineStart(text, '.view-scroll')
  assert(sc, name + ' 缺少 .view-scroll 规则')
  assert(/height:\s*100%/.test(sc), name + ' scroll-view 应填满宿主')
  assert(/padding-bottom:\s*calc\(140rpx \+ env\(safe-area-inset-bottom\)\)/.test(sc),
    name + ' scroll-view 需要 140rpx + 安全区尾部留白')
  const host = blockAtLineStart(text, '.view-root')
  assert(/height:\s*100%/.test(host) && /min-height:\s*0/.test(host), name + ' view-root 应填满宿主')
}

// ── 2. 不允许 JS 写死高度 ──
assert(!/swiperHeight/.test(mainJs), 'main.js 不应再计算 swiperHeight')
assert(!/swiperHeight/.test(mainWxml), 'main.wxml 不应绑定固定 px 高度')

// ── 3. 课表操作岛：两块完整圆角岛 + 12rpx 呼吸间距 ──
const weekbar = blockAtLineStart(schedule, '.weekbar')
assert(/border-radius:\s*var\(--radius-island\)/.test(weekbar), 'weekbar 应为完整圆角岛')
assert(/margin:\s*12rpx 20rpx 12rpx/.test(weekbar), 'weekbar 与 topbar 之间应有 12rpx 间距')

// ── 4. picker 打开时同一责任层隐藏浮动底栏 ──
assert(/_pickerOpen/.test(scheduleJs), '课表 popupstate 应纳入 picker 可见性')
assert(/onPickerVisibleChange/.test(scheduleJs), '课表应处理 ui-picker 可见性事件')
const pickerTags = (scheduleWxml.match(/<ui-picker\b/g) || []).length
const boundTags = (scheduleWxml.match(/bind:visiblechange="onPickerVisibleChange"/g) || []).length
assert(pickerTags > 0 && pickerTags === boundTags, '每个 ui-picker 都应挂 visiblechange（' + boundTags + '/' + pickerTags + '）')
assert(/_notify\(true\)/.test(pickerJs) && /_notify\(false\)/.test(pickerJs), 'ui-picker 打开/关闭都应上报可见性')

// ── 5. TDesign 主操作按钮 / 分段控件胶囊化（变量级，不是只改 .btn） ──
assert(/--td-button-border-radius:\s*var\(--radius-pill\)/.test(ds),
  'TDesign 按钮需通过 --td-button-border-radius 映射为胶囊')
const fontSeg = blockAtLineStart(settings, '.font-seg')
assert(/border-radius:\s*var\(--radius-pill\)/.test(fontSeg), '字体分段轨道应为胶囊')
const fontChoiceOn = blockAtLineStart(settings, '.font-choice.on')
assert(/border-radius:\s*var\(--radius-pill\)/.test(fontChoiceOn), '字体分段选中态应为胶囊')

console.log('Main height chain & island contract test passed [OK]')
