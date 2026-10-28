const assert = require('assert')
const fs = require('fs')
const path = require('path')

const ROOT = path.resolve(__dirname, '..')
const read = (file) => fs.readFileSync(path.join(ROOT, file), 'utf8')

const mainWxml = read('pages/main/main.wxml')
const mainWxss = read('pages/main/main.wxss')
const mainJs = read('pages/main/main.js')
const scheduleWxml = read('components/schedule-view/index.wxml')
const scheduleWxss = read('components/schedule-view/index.wxss')
const scheduleJs = read('components/schedule-view/index.js')
const profileWxml = read('components/settings-view/index.wxml')
const profileWxss = read('components/settings-view/index.wxss')
const profileJs = read('components/settings-view/index.js')

const count = (text, needle) => text.split(needle).length - 1

// ── 1. 三个一级视图都靠 is-active 表示当前页 ──
assert(mainWxml.includes("{{current === 0 ? 'is-active' : ''}}"), '功能页缺少 is-active 标记')
assert(mainWxml.includes("{{current === 1 ? 'is-active' : ''}}"), '课表页缺少 is-active 标记')
assert(mainWxml.includes("{{current === 2 ? 'is-active' : ''}}"), '我的页缺少 is-active 标记')

// ── 2. 切页入场只有一个责任层：main.wxss 的 tabPageIn ──
assert(mainWxss.includes('@keyframes tabPageIn'), 'main 缺少 tabPageIn 关键帧')
assert(mainWxss.includes('.tab-wrap.is-active > schedule-view'), '课表宿主播入应由 main 负责')
assert(mainWxss.includes('.tab-wrap.is-active > settings-view'), '我的宿主播入应由 main 负责')
assert.strictEqual(count(mainWxss, 'animation: tabPageIn'), 1, '切页入场只允许一处声明（多层叠加即回归）')

// ── 2b. Q 弹质感：切页只由 main 一层负责，且保留轻微超调 ──
const ds = read('styles/design-system.wxss')
assert(ds.includes('--ease-bounce: cubic-bezier(.22, 1.2, .36, 1)'), '缺少 Q 弹缓动令牌 --ease-bounce')
assert(/--motion-layer:\s*280ms/.test(ds), '缺少覆盖层时长令牌 --motion-layer: 280ms')
assert(mainWxss.includes('animation: tabPageIn var(--motion-base) var(--ease-bounce)'), '切页入场应使用 Q 弹缓动')
assert(mainWxss.includes('translateY(-2rpx)') && mainWxss.includes('scale(1.002)'), '切页入场应保留轻微超调(-2rpx / 1.002)')
const tabPageInBlock = (mainWxss.match(/\.tab-wrap\.is-active > schedule-view,[\s\S]*?@keyframes tabPageIn[\s\S]*?\n\}/) || [''])[0]
assert(tabPageInBlock && !tabPageInBlock.includes('ease-out'), '切页入场不应误用 ease-out 缓动')
const tileBlock = (mainWxss.match(/\.feature-tile\s*\{[^}]*\}/) || [''])[0]
assert(tileBlock.includes('var(--ease-bounce)'), '功能卡片按压释放应使用 Q 弹缓动')
{
  const rmIdx = mainWxss.lastIndexOf('prefers-reduced-motion')
  assert(mainWxss.slice(rmIdx).includes('.feature-tile'), '减少动态效果应关闭功能卡片回弹过渡')
}

// ── 3. 子组件不得再播放入场（本轮 review 的实际回归点）──
assert(!scheduleWxss.includes('is-entering'), '课表组件内不应再有入场类钩子')
assert(!profileWxss.includes('is-entering'), '我的组件内不应再有入场类钩子')
assert(!scheduleWxss.includes('scheduleChromeIn'), '课表组件内不应再有整页入场关键帧')
assert(!profileWxss.includes('profileItemIn'), '我的组件内不应再有内容入场关键帧')
assert.strictEqual(count(profileWxss, '@keyframes'), 0, '我的组件不应再有任何入场关键帧')
// 允许 reduced-motion 里的 animation: none，但不允许任何真实入场动画声明
const profileAnimValues = (profileWxss.match(/animation\s*:\s*([^;}]+)/g) || [])
  .map((s) => s.replace(/^animation\s*:\s*/, '').trim())
  .filter((v) => v !== 'none')
assert.deepStrictEqual(profileAnimValues, [], '我的组件不应再声明入场动画，实际: ' + profileAnimValues.join(' | '))
assert(!scheduleWxml.includes('is-entering') && !profileWxml.includes('is-entering'), 'WXML 不应再挂入场类')

// 周次切换动画保留（与切页入场是不同交互，允许存在）
assert(scheduleWxss.includes('week-in-right') && scheduleWxss.includes('week-in-left'), '周次切换动画不应被误删')

// ── 4. 我的页「准备好再显示」回调必须保留（main 依赖它避免闪空壳/登录态）──
assert(profileJs.includes('activate(done)'), '我的页 activate 必须保留 done 回调参数')
assert(profileJs.includes("if (typeof done === 'function') done()"), '必须在数据准备好后调用 done()')
assert(!profileJs.includes('_playEntrance'), '入场播放器应已移除')
assert(mainJs.includes('v.activate(finish)'), 'main 应把就绪回调传给子组件')
assert(mainJs.includes('fallback = setTimeout(finish, 600)'), '就绪回调必须有超时兜底')
assert(mainJs.includes('_prepareProfileThenSwitch'), '我的首次挂载应先隐藏渲染再切 Tab')

// ── 5. 不得再出现逐项错峰延迟 ──
assert(!/animation-delay/.test(mainWxss), 'main 不应有错峰延迟')
assert(!/animation-delay/.test(scheduleWxss), '课表不应有错峰延迟')

// ── 6. 功能页入场同样只有一层（main 内的页头）──
assert(mainWxss.includes('.feat-page.is-active .feature-header'), '功能页入场应由页头承担')
assert.strictEqual(count(mainWxss, 'animation: featureHeaderIn'), 1, '功能页入场只允许一处声明')

// ── 7. 二级页运动只由 main 的 tool-layer 管理 ──
assert(mainWxss.includes('.tool-layer'))
assert(mainWxss.includes('is-closing'))
assert(!scheduleWxss.includes('tool-layer') && !profileWxss.includes('tool-layer'), '子组件不应自建二级页层')

// ── 7b. 二级页 Q 弹：44rpx 起步 + 280ms 回弹，进入/退出对称，仍只有 tool-layer 一层 ──
assert.strictEqual(count(mainWxss, 'translateY(44rpx)'), 2, '二级页应从 44rpx 起步且进入/退出对称')
assert(mainWxss.includes('transform var(--motion-layer) var(--ease-bounce)'), '二级页过渡应为 280ms + Q 弹缓动')
assert(/\.tool-layer\.is-visible\s*\{[^}]*transform:\s*translateY\(0\)/.test(mainWxss), '二级页打开终点应为 translateY(0)')
assert(!/translateY\(44rpx\)[^}]*animation/.test(mainWxss), '二级页不应同时使用 animation 与 transition')

// ── 7c. TDesign 弹层：唯一过渡层 + 统一 Q 弹缓动，内容不得再叠动画 ──
for (const [file, expected] of [
  ['components/schedule-view/index.wxss', 1],
  ['components/settings-view/index.wxss', 1],
  ['components/audit-course-view/index.wxss', 2]
]) {
  const text = read(file)
  assert.strictEqual(
    count(text, '--td-popup-transition: all var(--motion-sheet) var(--ease-bounce)'),
    expected,
    file + ' 弹层过渡应为统一 Q 弹曲线'
  )
  const anims = (text.match(/animation\s*:\s*([^;}]+)/g) || [])
    .map((s) => s.replace(/^animation\s*:\s*/, '').trim())
    .filter((v) => v !== 'none')
  assert.deepStrictEqual(anims, [], file + ' 弹层文件不应再有第二层动画: ' + anims.join(' | '))
}

// ── 7d. 刷新按钮：旋转独立，不叠加 Q 弹 ──
{
  const busy = (ds.match(/\.refresh-action\.is-busy\s*\{[^}]*\}/) || [''])[0]
  assert(busy.includes('ico-spin'), '刷新忙碌态应使用独立旋转')
  assert(!busy.includes('ease-bounce'), '刷新忙碌态不应叠加 Q 弹缓动')
  assert(/@media\s*\(prefers-reduced-motion:\s*reduce\)[\s\S]*?\.refresh-action\.is-busy\s*\{[\s\S]*?animation:\s*none/.test(ds), '减少动态效果应关闭刷新旋转')
}

// ── 8. 快速重复开关不锁死、不残留（静态契约 + DevTools 10 次实测另行记录）──
assert(mainJs.includes('toolClosing'), '缺少 toolClosing 关闭中状态')
assert(mainJs.includes('this.data.toolClosing || this.data.toolRendered) return'), '打开二级页缺少重复进入守卫')
assert(mainJs.includes('_toolTransitionSeq'), '缺少过渡序号，无法丢弃过期回调')
assert(scheduleJs.includes('if (this._weekAnimTimer) clearTimeout(this._weekAnimTimer)'), '课表未清理周切换定时器')
assert(profileJs.includes('this._stopQrPoll()'), '我的未停止扫码轮询')
assert(profileJs.includes('if (this._fontTimer) clearTimeout(this._fontTimer)'), '我的未清理字体定时器')

// ── 9. 减少动态效果：三处样式都必须保留 ──
assert(mainWxss.includes('prefers-reduced-motion: reduce'), 'main 缺少减少动态效果支持')
assert(scheduleWxss.includes('prefers-reduced-motion: reduce'), '课表缺少减少动态效果支持')
assert(profileWxss.includes('prefers-reduced-motion: reduce'), '我的缺少减少动态效果支持')

console.log('Page animation regression test passed [OK]')
