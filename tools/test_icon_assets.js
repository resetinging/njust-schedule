/**
 * 图标资源契约回归
 * - 通过 tools/lib/icon-contract.js 执行组件运行时真正使用的 wxs 映射（不复制实现）
 * - 枚举全部 WXML 里的 <icon> 用法（含 {{三元}} 动态 name/color 的所有分支）
 * - 断言解析结果都指向 static/icons 下真实存在的 PNG，杜绝 Failed to load image
 * - 断言新调色板到 4 档资源的归一规则（语义色 -> 品牌档、中性色 -> slate/grey、未知色不落空）
 */
const assert = require('assert')
const fs = require('fs')
const path = require('path')

const { loadIconContract, ROOT } = require('./lib/icon-contract')

const SKIP = ['node_modules', 'miniprogram_npm', '.tmp', '.git']
const TONES = ['indigo', 'slate', 'grey', 'white']

// ── 1. 运行时映射 + 真实资源清单 ──
const ico = loadIconContract()
const { assets } = ico
assert(assets.size > 0, 'static/icons 下没有 PNG 资源')

// ── 2. 枚举 WXML 用法 ──
function walk(dir, out) {
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    if (SKIP.includes(entry.name)) continue
    const full = path.join(dir, entry.name)
    if (entry.isDirectory()) walk(full, out)
    else if (entry.name.endsWith('.wxml')) out.push(full)
  }
}

function extractBranches(raw) {
  // {{cond ? '#A' : '#B'}} / {{x ? 'prev' : 'next'}} -> 所有字面量分支
  const out = []
  const re = /'([^']*)'|"([^"]*)"/g
  let m
  while ((m = re.exec(raw))) out.push(m[1] !== undefined ? m[1] : m[2])
  return out.filter((v) => v !== '')
}

const wxmlFiles = []
walk(ROOT, wxmlFiles)

const usages = []
for (const file of wxmlFiles) {
  const text = fs.readFileSync(file, 'utf8')
  const tagRe = /<icon\b([^>]*?)\/?>/g
  let tag
  while ((tag = tagRe.exec(text))) {
    const attrs = tag[1]
    const nameAttr = attrs.match(/\bname="([^"]*)"/)
    const colorAttr = attrs.match(/\bcolor="([^"]*)"/)
    const nameRaw = nameAttr ? nameAttr[1] : ''
    const colorRaw = colorAttr ? colorAttr[1] : '#64748B'   // 组件属性默认色
    const names = /\{\{/.test(nameRaw) ? extractBranches(nameRaw) : [nameRaw]
    const colors = /\{\{/.test(colorRaw) ? extractBranches(colorRaw) : [colorRaw]
    for (const name of names) {
      for (const color of colors) {
        usages.push({ file: path.relative(ROOT, file), name, color })
      }
    }
  }
}

assert(usages.length > 0, '未扫描到任何 <icon> 用法')

// ── 3. 逐项解析并校验资源存在 ──
const missing = []
const byResource = new Map()
for (const u of usages) {
  const res = ico.file(u.name, u.color)
  const tone = ico.tone(u.color)
  assert(TONES.includes(tone), `未知色调档位: ${tone} (${u.file} ${u.name} ${u.color})`)
  if (!ico.exists(res)) {
    missing.push(`${u.file}: name=${u.name} color=${u.color} -> ${res}.png 不存在`)
  }
  byResource.set(res, (byResource.get(res) || 0) + 1)
}
assert.strictEqual(missing.length, 0, '图标资源缺失:\n  ' + missing.join('\n  '))

// ── 4. 归一规则契约（新调色板 -> 4 档）──
const toneCases = [
  ['#FFFFFF', 'white'],
  ['#3157D5', 'indigo'],   // 品牌
  ['#2544B5', 'indigo'],
  ['#6C63B8', 'indigo'],   // 功能入口强调色
  ['#247B68', 'indigo'],   // 成功语义 -> 品牌档（资源只有 4 档）
  ['#A66A0B', 'indigo'],   // 提醒语义 -> 品牌档
  ['#B84750', 'indigo'],   // 危险语义 -> 品牌档
  ['#20262D', 'slate'],    // 正文
  ['#59636F', 'slate'],    // 次级
  ['#6B7684', 'slate'],    // muted
  ['#9AA4B0', 'grey'],     // hint
  ['#BFC7D1', 'grey'],
  ['#123456', 'slate']     // 未知色不落空
]
for (const [color, expectTone] of toneCases) {
  assert.strictEqual(ico.tone(color), expectTone, `色值 ${color} 应归一到 ${expectTone}`)
}

// ── 5. 兜底：未知图标名 / sync 中性档 / 别名都指向真实资源 ──
assert(ico.exists(ico.file('__not_exist__', '#6B7684')), '未知图标名必须回退到存在的资源')
assert(ico.exists(ico.file('sync', '#6B7684')), 'sync 中性档必须指向存在的资源')
assert(ico.exists(ico.file('sync', '#3157D5')), 'sync 品牌档必须指向存在的资源')
assert(ico.exists(ico.file('check', '#247B68')), 'check 必须回退到存在的资源')
assert(ico.exists(ico.file('edit', '#6B7684')), 'edit 别名必须指向存在的资源')

const names = new Set(usages.map((u) => u.name))
for (const name of names) {
  for (const color of ['#FFFFFF', '#3157D5', '#20262D', '#9AA4B0']) {
    const res = ico.file(name, color)
    assert(ico.exists(res), `图标 ${name} 在色值 ${color} 下解析到不存在的资源 ${res}`)
  }
}

console.log(
  'Icon asset test passed [OK]  ' +
  `wxml=${wxmlFiles.length} tags=${usages.length} names=${names.size} ` +
  `resources=${byResource.size}/${assets.size}`
)
