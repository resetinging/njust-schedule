const assert = require('assert')
const path = require('path')

const ROOT = path.resolve(__dirname, '..')
const { validatePage } = require(path.join(ROOT, 'ui', 'schema'))
const { createRegistry } = require(path.join(ROOT, 'ui', 'registry'))
const { resolveToken, createCssVariables } = require(path.join(ROOT, 'ui', 'theme', 'tokens'))
const featurePage = require(path.join(ROOT, 'ui', 'pages', 'feature.ui'))

const registry = createRegistry()
const result = validatePage(featurePage, registry)
assert.strictEqual(result.valid, true, JSON.stringify(result.errors))
assert.strictEqual(registry.get('ActionCard').kind, 'macro')
assert.strictEqual(resolveToken('$token.color.brand'), '#3157D5')
assert.strictEqual(createCssVariables()['--primary'], '#3157D5')

const invalid = JSON.parse(JSON.stringify(featurePage))
const academicSection = invalid.tree.children.find((node) => node.id === 'academic-section')
academicSection.children[0].children[0].style = { color: 'red' }
const invalidResult = validatePage(invalid, registry)
assert.strictEqual(invalidResult.valid, false)
assert(invalidResult.errors.some((item) => item.message.includes('forbidden DSL field')))

console.log('UI DSL schema test passed [OK]')
