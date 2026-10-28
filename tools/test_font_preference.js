/**
 * 字体偏好回归（pixel / system 两档必须真正改变正文字体）
 *
 * 背景：utils/font.js 的设计是「pixel = 根节点无 class（走默认变量）」「system = 根节点挂 .font-system」。
 * 因此 styles/design-system.wxss 的默认 --font-body 必须是内联像素字体，
 * 系统字只能由 app.wxss 的 .font-system 覆盖 —— 该不变量此前被样式统一改坏过，用本测试锁死。
 */
const assert = require('assert')
const fs = require('fs')
const path = require('path')

const ROOT = path.resolve(__dirname, '..')
const read = (file) => fs.readFileSync(path.join(ROOT, file), 'utf8')

const ds = read('styles/design-system.wxss')
const app = read('app.wxss')
const fontPixel = read('styles/font-pixel.wxss')
const fontJs = read('utils/font.js')
const settingsWxss = read('components/settings-view/index.wxss')
const settingsWxml = read('components/settings-view/index.wxml')

// ── 1. 默认档 = 内联像素字体（pixel 模式靠默认变量生效）──
assert(/--font-pixel:\s*"ZpixPixel"/.test(ds), '缺少 --font-pixel 默认档，且必须以 ZpixPixel 开头')
assert(/--font-body:\s*var\(--font-pixel\)/.test(ds), '默认 --font-body 必须指向 --font-pixel')
assert(/--font-display:\s*var\(--font-pixel\)/.test(ds), '默认 --font-display 必须指向 --font-pixel')
assert(!/--font-body:\s*-apple-system/.test(ds), '默认 --font-body 不得写成系统字（否则像素档无效）')
assert(!/--font-display:\s*-apple-system/.test(ds), '默认 --font-display 不得写成系统字（否则像素档无效）')

// 数字走独立数字字体，且不随档位切换
assert(/--font-num:\s*"DIN Alternate"/.test(ds), '--font-num 应保留数字字体')
assert(/--font-body:\s*var\(--font-pixel\)[\s\S]*?--font-num:/.test(ds) || ds.includes('--font-num: "DIN Alternate"'), '缺少数字字体令牌')

// ── 2. 页面根节点与 TDesign 映射都引用 --font-body（切换才能全站生效）──
assert(/font-family:\s*var\(--font-body\)/.test(ds), 'page 根未声明 font-family: var(--font-body)')
assert(/--td-font-family:\s*var\(--font-body\)/.test(ds), 'TDesign --td-font-family 未映射到 --font-body')
assert(/--td-font-family-medium:\s*var\(--font-body\)/.test(ds), 'TDesign --td-font-family-medium 未映射')

// ── 3. system 档：.font-system 覆盖变量并重新声明 font-family（否则子树继承不到）──
assert(/\.font-system\s*\{[\s\S]*?--font-body:\s*-apple-system/.test(app), '.font-system 未覆盖 --font-body 为系统字')
assert(/\.font-system\s*\{[\s\S]*?--font-display:\s*-apple-system/.test(app), '.font-system 未覆盖 --font-display')
assert(/\.font-system\s*\{[\s\S]*?font-family:\s*var\(--font-body\)/.test(app), '.font-system 必须在覆盖变量后重新声明 font-family')
assert(!/\.font-system\s*\{[\s\S]*?ZpixPixel[\s\S]*?\}/.test(app), '.font-system 内不应残留像素字体')

// ── 3b. page 上已替换成像素字面量的派生令牌，必须在 .font-system 内重新赋值 ──
// （自定义属性在声明处就会把 var(--font-body) 替换掉，只在子树改 --font-body 不会回灌；
//   TDesign 组件消费的是 --td-font-family，漏改会导致系统字档下组件仍是像素字）
for (const token of ['--font-plain', '--font-ann', '--td-font-family', '--td-font-family-medium']) {
  assert(new RegExp('\\.font-system\\s*\\{[\\s\\S]*?' + token + ':\\s*-apple-system').test(app),
    '.font-system 缺少 ' + token + ' 覆盖（page 上已替换为像素字面量，不回灌）')
}

// ── 4. 像素字体必须内联（零网络），不得依赖外链 ──
assert(/font-family:\s*'ZpixPixel'/.test(fontPixel), '未找到 ZpixPixel 的 @font-face')
assert(fontPixel.includes('base64,'), 'ZpixPixel 应为 base64 内联，避免额外下载')
assert(!/https?:\/\//.test(fontPixel), '像素字体不得依赖网络字体链接')
assert(/font-display:\s*swap/.test(fontPixel), '像素字体应设置 font-display: swap 以便回退')

// ── 5. 档位契约不变：pixel 空 class / system .font-system / 默认 system ──
assert(/pixel:\s*\{[^}]*cls:\s*''/.test(fontJs), 'pixel 档应为空 class（走默认变量）')
assert(/system:\s*\{[^}]*cls:\s*'font-system'/.test(fontJs), 'system 档应为 .font-system')
assert(/storage\.get\(MODE_KEY,\s*'system'\)/.test(fontJs), '默认档应保持 system（既有基线，不随样式改动）')

// ── 6. 页面/组件根节点确实挂 fontClass ──
for (const rel of ['pages/main/main.wxml', 'components/freeclass-view/index.wxml', 'components/gallery-view/index.wxml']) {
  assert(read(rel).includes('fontClass'), rel + ' 未挂 fontClass，档位切换不会作用到该页')
}

// ── 7. 切换时的轻微短淡入淡出存在、且尊重减少动态效果；不引入切页入场 ──
assert(settingsWxml.includes('font-switching'), '设置页根节点未绑定 font-switching')
assert(/\.font-switching\s*\{[^}]*opacity:/.test(settingsWxss), '.font-switching 缺少透明淡入淡出')
assert(/\.view-root\s*\{[^}]*transition:\s*opacity/.test(settingsWxss), '根节点须常驻 opacity 过渡，确保加类和移除类两个方向都平滑')
assert(!/\.font-switching\s*\{[^}]*transition:/.test(settingsWxss), '过渡不能只放在临时类上，否则移除类时会瞬间恢复')
assert(!/\.font-switching\s*\{[^}]*animation:/.test(settingsWxss), '.font-switching 不应引入动画（避免与切页入场叠加）')
const rmTail = settingsWxss.slice(settingsWxss.lastIndexOf('prefers-reduced-motion'))
assert(rmTail.includes('.font-switching'), '减少动态效果下应关闭字体切换过渡')
assert(/\.view-root\s*\{[^}]*transition:\s*none/.test(rmTail), '减少动态效果下须关闭常驻根节点过渡')

console.log('Font preference regression test passed [OK]')
