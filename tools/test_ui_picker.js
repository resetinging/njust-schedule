const assert = require('assert')
const fs = require('fs')
const path = require('path')

const ROOT = path.resolve(__dirname, '..')

function walk(dir) {
  return fs.readdirSync(dir, { withFileTypes: true }).flatMap(entry => {
    if (entry.name === '.git' || entry.name === 'node_modules' ||
      entry.name === 'miniprogram_npm') return []
    const file = path.join(dir, entry.name)
    return entry.isDirectory() ? walk(file) : [file]
  })
}

const pickerPath = path.join(ROOT, 'components', 'ui-picker', 'index.wxml')
const picker = fs.readFileSync(pickerPath, 'utf8')
const portalStart = picker.indexOf('<root-portal>')
const pickerStart = picker.indexOf('<t-picker')
const pickerEnd = picker.lastIndexOf('</t-picker>')
const portalEnd = picker.lastIndexOf('</root-portal>')

assert(portalStart >= 0 && pickerStart > portalStart, 't-picker 必须放在 root-portal 内')
assert(portalEnd > pickerEnd && pickerEnd > pickerStart, 'root-portal 必须完整包裹 t-picker')

const wxmlFiles = walk(ROOT).filter(file => file.endsWith('.wxml'))
const directPickers = wxmlFiles.filter(file => {
  const relative = path.relative(ROOT, file).replace(/\\/g, '/')
  return relative !== 'components/ui-picker/index.wxml' &&
    fs.readFileSync(file, 'utf8').includes('<t-picker')
})

assert.deepStrictEqual(directPickers, [], '业务页面应统一使用 ui-picker，避免弹层被局部容器裁剪')
console.log('UI picker portal test passed [OK]')
