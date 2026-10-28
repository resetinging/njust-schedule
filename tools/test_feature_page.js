const assert = require('assert')
const fs = require('fs')
const path = require('path')

const ROOT = path.resolve(__dirname, '..')
const wxml = fs.readFileSync(path.join(ROOT, 'pages', 'main', 'main.wxml'), 'utf8')
const wxss = fs.readFileSync(path.join(ROOT, 'pages', 'main', 'main.wxss'), 'utf8')
const mainJs = fs.readFileSync(path.join(ROOT, 'pages', 'main', 'main.js'), 'utf8')
const scheduleJs = fs.readFileSync(path.join(ROOT, 'components', 'schedule-view', 'index.js'), 'utf8')

// 生产功能页 = main.wxml：7 个入口（研究生隐藏规则由 WXML 决定，不在此计数内）
assert.strictEqual((wxml.match(/class="feature-tile /g) || []).length, 7)

// 顶部不再有描述与下一节课摘要
assert(!wxml.includes('next-class-summary'))
assert(!mainJs.includes('nextClass'))
assert(!scheduleJs.includes('todaychange'))

// 功能页只保留一层入场：页头淡入；不再有逐项 tile 延迟与装饰圆
assert(wxss.includes('@keyframes featureHeaderIn'))
assert(!wxss.includes('@keyframes tileIn'), 'tile 逐项入场应已移除')
assert(!wxss.includes('animation-delay'), '功能页不应再有逐项错峰延迟')
assert(!wxss.includes('.feature-tile::after'), '功能入口的装饰圆应已移除')

// 7 个入口统一两列等宽卡片：末行单卡保持单列宽度，右侧自然留空（不再跨满整行）
assert(wxss.includes('grid-template-columns: repeat(2, minmax(0, 1fr))'), '功能卡片应为两列等宽网格')
assert(!wxss.includes(':last-child:nth-child(odd)'), '不应再有奇数跨满整行规则')
assert(!/\.feature-tile[^}]*grid-column/.test(wxss), '功能卡片不应跨列')
{
  const tileBlock = (wxss.match(/\.feature-tile\s*\{[^}]*\}/) || [''])[0]
  assert(!/width:\s*\d+px/.test(tileBlock), '功能卡片不应硬编码固定 px 宽度')
  assert(!/min-width:\s*\d+px/.test(tileBlock), '功能卡片宽度应交给等宽网格')
}
// 7 个入口与研究生隐藏规则保持不变
assert(wxml.includes('data-sub="eval"') && wxml.includes('wx:if="{{!isGraduate}}"'),
  '研究生隐藏教学评价的规则应保留')

// 按压反馈仍在：图标底色变化 + 箭头变淡，但不旋转、不过冲
assert(wxss.includes('.feature-tile:active .feature-icon'))
assert(wxss.includes('.feature-tile:active .feature-arrow'))
assert(!/feature-tile:active[^}]*rotate/.test(wxss), '按压不应旋转图标')
assert(!/feature-tile:active[^}]*translateY/.test(wxss), '按压不应位移整卡（缩放由基座提供）')

assert(wxss.includes('prefers-reduced-motion: reduce'))

console.log('Feature page regression test passed [OK]')
