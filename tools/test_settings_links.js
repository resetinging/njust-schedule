/**
 * 常用链接组件逻辑测试 — 在 Node 中用桩件模拟小程序运行时,
 * 真实加载 components/settings-view/index.js 并驱动它的方法。
 *
 * 运行: node tools/test_settings_links.js [小程序根目录]
 */
const path = require('path')
const fs = require('fs')

// 默认被测目录 = 本脚本上一级(即 .miniapp / miniprogram 根)
const ROOT = path.resolve(process.argv[2] || path.join(__dirname, '..'))

// ---------------- 小程序运行时桩件 ----------------
const calls = { toast: [], modal: [], clipboard: [], setData: [] }

function noop() {}

global.wx = new Proxy({}, {
  get(_t, prop) {
    if (prop === 'setClipboardData') {
      return (o) => { calls.clipboard.push(o.data); return o.success && o.success({}) }
    }
    if (prop === 'showModal') {
      return (o) => { calls.modal.push({ title: o.title, content: o.content }); return o.success && o.success({ confirm: true }) }
    }
    if (prop === 'showToast') {
      return (o) => { calls.toast.push(o.title); return o.success && o.success({}) }
    }
    if (prop === 'getStorageSync') return () => ''
    if (prop === 'getSystemInfoSync') return () => ({ platform: 'devtools', windowWidth: 375, windowHeight: 667, safeArea: { top: 0, bottom: 667 } })
    if (prop === 'getAccountInfoSync') return () => ({ miniProgram: { envVersion: 'develop' } })
    if (prop === 'createSelectorQuery') {
      return () => ({ select: () => ({ boundingClientRect: () => ({ exec: (cb) => cb && cb([{ width: 375, height: 667 }]) }) }), exec: (cb) => cb && cb([]) })
    }
    return noop
  }
})
global.getApp = () => ({ globalData: {} })
global.getCurrentPages = () => []

// 捕获组件定义
let captured = null
global.Component = (cfg) => { captured = cfg }
global.Behavior = (b) => b

// ---------------- 断言工具 ----------------
let pass = 0
let fail = 0
const failures = []

function check(name, ok, extra) {
  if (ok) {
    pass++
    console.log('  ✓ ' + name)
  } else {
    fail++
    failures.push(name)
    console.log('  ✗ ' + name + (extra ? '  → ' + extra : ''))
  }
}

// ---------------- 加载组件 ----------------
const compPath = path.join(ROOT, 'components', 'settings-view', 'index.js')
console.log('加载组件: ' + compPath + '\n')

let loadError = null
try {
  require(compPath)
} catch (e) {
  loadError = e
}

console.log('1) 组件可加载(模块级代码不抛异常)')
check('require 组件不抛异常', !loadError, loadError && loadError.message)
if (loadError) {
  console.log('\n加载失败, 终止。')
  process.exit(1)
}
check('Component() 被调用', !!captured)
if (!captured) process.exit(1)

// ---------------- 构造实例 ----------------
const data = JSON.parse(JSON.stringify(captured.data || {}))
// 去掉函数, 保留可序列化数据
const inst = {
  data: Object.assign({}, data),
  setData(patch, cb) {
    calls.setData.push(patch)
    Object.assign(this.data, patch)
    if (cb) cb()
  },
  // 合并 methods
  ...(captured.methods || {})
}

console.log('\n2) 链接数据已注入组件 data')
check('data.linkShown 存在', Array.isArray(inst.data.linkShown), 'type=' + typeof inst.data.linkShown)
const groups = inst.data.linkShown || []
const total = groups.reduce((n, g) => n + (g.items ? g.items.length : 0), 0)
check('分组数 = 2', groups.length === 2, '实际 ' + groups.length)
check('链接总数 = 20', total === 20, '实际 ' + total)
check('data.linkTotal = 20', inst.data.linkTotal === 20, '实际 ' + inst.data.linkTotal)
check('每条链接都有 name/url', groups.every(g => g.items.every(i => i.name && /^https?:\/\//.test(i.url))))
check('data.showLinks 初始为 false', inst.data.showLinks === false)

console.log('\n3) 打开弹窗')
inst.onOpenLinks()
check('onOpenLinks → showLinks=true', inst.data.showLinks === true)
check('onOpenLinks 重置搜索词', inst.data.linkKeyword === '')
check('onOpenLinks 重置为全量列表', (inst.data.linkShown || []).length === 2)

console.log('\n4) 搜索过滤')
inst.onLinkSearch({ detail: { value: '四六级' } })
const hits = (inst.data.linkShown || []).reduce((n, g) => n + g.items.length, 0)
check('搜索「四六级」命中 3 条', hits === 3, '实际 ' + hits)
check('搜索词已记录', inst.data.linkKeyword === '四六级')
inst.onLinkSearch({ detail: { value: 'neea' } })
const hits2 = (inst.data.linkShown || []).reduce((n, g) => n + g.items.length, 0)
// cet-bm×2 + cet + cjcx + ncre-bm = 5 条(.neea 域名)
check('按网址搜索「neea」命中 5 条', hits2 === 5, '实际 ' + hits2)
inst.onLinkSearch({ detail: { value: 'zzz不存在' } })
check('无匹配时返回空数组', (inst.data.linkShown || []).length === 0)
inst.onLinkClear()
check('清空搜索恢复全量', (inst.data.linkShown || []).length === 2 && inst.data.linkKeyword === '')

console.log('\n5) 点击复制')
const first = groups[0].items[0]
const clipBefore = calls.clipboard.length
const toastBefore = calls.toast.length
inst.onCopyLink({ currentTarget: { dataset: { url: first.url, name: first.name } } })
check('复制写入剪贴板', calls.clipboard[calls.clipboard.length - 1] === first.url, String(calls.clipboard[calls.clipboard.length - 1]))
// 真机 setClipboardData 自带"内容已复制"提示, 自定义 toast 只用于失败, 避免叠加
check('复制成功不叠加自定义 toast', calls.toast.length === toastBefore)
const clipAfterOk = calls.clipboard.length
inst.onCopyLink({ currentTarget: { dataset: {} } })
check('无 url 时安全返回(不复制、不报错)', calls.clipboard.length === clipAfterOk && calls.toast.length === toastBefore)

console.log('\n6) 长按查看')
inst.onShowLink({ currentTarget: { dataset: { url: first.url, name: first.name } } })
const m = calls.modal[calls.modal.length - 1]
check('长按弹出 modal', !!m)
check('modal 含完整网址', m && m.content === first.url)
check('modal 标题为链接名', m && m.title === first.name)

console.log('\n7) 关闭弹窗')
inst.onLinksClose()
check('onLinksClose → showLinks=false', inst.data.showLinks === false)

console.log('\n' + '='.repeat(52))
console.log('通过 ' + pass + ' / ' + (pass + fail))
if (fail) console.log('失败: ' + failures.join(' | '))
console.log('='.repeat(52))
process.exit(fail ? 1 : 0)
