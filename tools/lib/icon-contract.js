/**
 * 图标资源契约加载器（供 tools 下的测试复用）
 *
 * 直接执行 components/icon/index.wxml 里运行时真正使用的 wxs 映射，
 * 并给出 static/icons 下真实存在的资源集合，避免测试复制一份实现而与运行时漂移。
 */
const fs = require('fs')
const path = require('path')
const vm = require('vm')

const ROOT = path.resolve(__dirname, '..', '..')
const ICONS_DIR = path.join(ROOT, 'static', 'icons')

function loadIconContract() {
  const compWxml = fs.readFileSync(path.join(ROOT, 'components', 'icon', 'index.wxml'), 'utf8')
  const match = compWxml.match(/<wxs module="ico">([\s\S]*?)<\/wxs>/)
  if (!match) throw new Error('icon 组件缺少 wxs 映射')

  const sandbox = { module: { exports: {} } }
  vm.runInNewContext(match[1], sandbox, { filename: 'icon.wxs' })

  const ico = sandbox.module.exports
  if (typeof ico.tone !== 'function' || typeof ico.file !== 'function') {
    throw new Error('icon wxs 未导出 tone/file')
  }

  const assets = new Set(
    fs.readdirSync(ICONS_DIR)
      .filter((f) => f.endsWith('.png'))
      .map((f) => f.slice(0, -4))
  )

  return {
    tone: ico.tone,
    file: ico.file,
    assets,
    exists: (resource) => assets.has(resource)
  }
}

module.exports = { loadIconContract, ROOT, ICONS_DIR }
