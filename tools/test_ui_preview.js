const assert = require('assert')
const fs = require('fs')
const path = require('path')

const ROOT = path.resolve(__dirname, '..')
const app = JSON.parse(fs.readFileSync(path.join(ROOT, 'app.json'), 'utf8'))
assert(app.pages.includes('pages/ui-preview/ui-preview'))

let pageConfig = null
global.Page = (config) => {
  pageConfig = config
}
require(path.join(ROOT, 'pages', 'ui-preview', 'ui-preview.js'))
assert(pageConfig && pageConfig.data)
assert.strictEqual(pageConfig.data.state.loggedIn, true)

const previewJson = JSON.parse(fs.readFileSync(
  path.join(ROOT, 'pages', 'ui-preview', 'ui-preview.json'), 'utf8'))
assert.strictEqual(
  previewJson.usingComponents['feature-page'],
  '/components/generated/feature-page/index')

console.log('UI preview integration test passed [OK]')
