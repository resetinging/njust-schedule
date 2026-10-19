const assert = require('assert')
const path = require('path')

const ROOT = path.resolve(__dirname, '..')
const { createRegistry } = require(path.join(ROOT, 'ui', 'registry'))
const { compilePage } = require(path.join(ROOT, 'ui', 'compiler'))
const featurePage = require(path.join(ROOT, 'ui', 'pages', 'feature.ui'))

const output = compilePage(featurePage, createRegistry())
assert(output.wxml.includes('ui-action-card'))
assert(!output.wxml.includes('ui-hero-summary'))
assert.strictEqual((output.wxml.match(/class="ui-action-card /g) || []).length, 7)
assert(output.wxml.includes('ui-tabbar'))
assert(output.wxml.includes('data-action="openFeature"'))
assert(output.wxml.includes('data-sub="exams"'))
assert(!output.wxml.includes('data-suppressed'))
assert(output.json.includes('"icon"'))
assert(output.wxss.includes('--primary: #3157D5'))

const again = compilePage(featurePage, createRegistry())
assert.deepStrictEqual(again, output, 'compiler output must be deterministic')

console.log('UI DSL compiler test passed [OK]')
