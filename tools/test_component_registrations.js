const assert = require('assert')
const fs = require('fs')
const path = require('path')

const ROOT = path.resolve(__dirname, '..')
const SKIP_DIRS = new Set(['.git', 'node_modules', '.tmp'])

function walk(dir, out) {
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    if (entry.isDirectory() && SKIP_DIRS.has(entry.name)) continue
    const full = path.join(dir, entry.name)
    if (entry.isDirectory()) walk(full, out)
    else if (entry.isFile() && entry.name.endsWith('.wxml')) out.push(full)
  }
}

function siblingJson(wxmlPath) {
  const indexJson = path.join(path.dirname(wxmlPath), 'index.json')
  if (fs.existsSync(indexJson)) return indexJson
  return wxmlPath.replace(/\.wxml$/, '.json')
}

function checkUiPickerRegistration() {
  const files = []
  walk(ROOT, files)
  const missing = []
  const checked = []

  for (const wxmlPath of files) {
    const source = fs.readFileSync(wxmlPath, 'utf8')
    if (!/<ui-picker[\s>]/.test(source)) continue
    const jsonPath = siblingJson(wxmlPath)
    const relativeWxml = path.relative(ROOT, wxmlPath).replace(/\\/g, '/')
    assert.ok(fs.existsSync(jsonPath), relativeWxml + ': missing component json')
    const config = JSON.parse(fs.readFileSync(jsonPath, 'utf8'))
    const picker = config.usingComponents && config.usingComponents['ui-picker']
    if (!picker) missing.push(relativeWxml)
    checked.push(relativeWxml)
  }

  assert.ok(checked.length > 0, 'no ui-picker usage found')
  assert.deepStrictEqual(missing, [], 'ui-picker must be locally registered: ' + missing.join(', '))
  console.log('Component registration test passed [OK] ui-picker=' + checked.length)
}

checkUiPickerRegistration()
