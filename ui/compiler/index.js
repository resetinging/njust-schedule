'use strict'

const fs = require('fs')
const path = require('path')
const { validatePage } = require('../schema')
const { resolveToken, createCssVariables } = require('../theme/tokens')

const EXPR_MAP = {
  state: 'state',
  data: 'pageData',
  computed: 'computed',
  props: 'props',
  env: 'env'
}

function escapeAttr(value) {
  return String(value)
    .replace(/&/g, '&amp;')
    .replace(/"/g, '&quot;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
}

function expressionPath(value, context) {
  const text = String(value || '')
  if (!text.startsWith('$')) return null
  if (text === '$index') return context.index || 'index'
  if (text.startsWith('$item.')) return `${context.item || 'item'}.${text.slice(6)}`
  if (text === '$item') return context.item || 'item'
  const dot = text.indexOf('.')
  const root = dot === -1 ? text.slice(1) : text.slice(1, dot)
  const mapped = EXPR_MAP[root] || root
  return mapped + (dot === -1 ? '' : text.slice(dot))
}

function valueExpression(value, context) {
  if (typeof value === 'string' && value.startsWith('$token.')) {
    const tokenValue = resolveToken(value)
    if (tokenValue === undefined) throw new Error(`unknown token: ${value}`)
    return { static: true, value: tokenValue }
  }
  const pathValue = expressionPath(value, context)
  if (pathValue !== null) return { static: false, value: pathValue }
  return { static: true, value }
}

function attr(name, value, context, options) {
  if (value === undefined || value === null || value === false) return ''
  if (value === true) return ` ${name}`
  const resolved = valueExpression(value, context)
  if (resolved.static) {
    if (resolved.value === '') return ''
    if (options && options.boolean) {
      return resolved.value ? ` ${name}` : ''
    }
    return ` ${name}="${escapeAttr(resolved.value)}"`
  }
  return ` ${name}="{{${escapeAttr(resolved.value)}}}"`
}

function eventAttrs(node, context) {
  const attrs = []
  const events = node.events || {}
  let eventIndex = 0
  Object.keys(events).forEach((eventName) => {
    const action = events[eventName] || {}
    attrs.push(` bind:${eventName}="onAction"`)
    attrs.push(` data-action="${escapeAttr(action.action || '')}"`)
    eventIndex += 1
    if (eventIndex > 1) {
      throw new Error(`${node.type} only supports one action handler per node`)
    }
    Object.entries(action.data || {}).forEach(([key, value]) => {
      const safeKey = key.replace(/[^A-Za-z0-9_]/g, '_')
      const resolved = valueExpression(value, context)
      if (resolved.static) {
        attrs.push(` data-${safeKey}="${escapeAttr(resolved.value)}"`)
      } else {
        attrs.push(` data-${safeKey}="{{${escapeAttr(resolved.value)}}}"`)
      }
    })
  })
  return attrs.join('')
}

function controlAttrs(node, context) {
  const attrs = []
  if (node.when !== undefined) {
    const resolved = valueExpression(node.when, context)
    if (resolved.static) throw new Error('when must be a dynamic expression')
    attrs.push(` wx:if="{{${escapeAttr(resolved.value)}}}"`)
  }
  if (node.each !== undefined) {
    const each = node.each
    const source = valueExpression(each.in, context)
    if (source.static) throw new Error('each.in must be a dynamic expression')
    const itemName = each.as || 'item'
    const indexName = each.index || 'index'
    const key = valueExpression(each.key, {
      ...context,
      item: itemName,
      index: indexName
    })
    if (key.static) throw new Error('each.key must be a dynamic expression')
    attrs.push(` wx:for="{{${escapeAttr(source.value)}}}"`)
    attrs.push(` wx:for-item="${escapeAttr(itemName)}"`)
    attrs.push(` wx:for-index="${escapeAttr(indexName)}"`)
    attrs.push(` wx:key="{{${escapeAttr(key.value)}}}"`)
  }
  return attrs.join('')
}

function nodeIndent(depth) {
  return '  '.repeat(depth)
}

function emitChildren(node, context, depth) {
  return (node.children || [])
    .map((child) => emitNode(child, context, depth))
    .join('\n')
}

function emitSlots(node, context, depth) {
  const slots = node.slots || {}
  return Object.entries(slots).map(([slotName, children]) => {
    const body = (children || [])
      .map((child) => emitNode(child, context, depth + 1))
      .join('\n')
    const slotAttr = slotName === 'default' ? '' : ` slot="${escapeAttr(slotName)}"`
    return `${nodeIndent(depth)}<view${slotAttr}>\n${body}\n${nodeIndent(depth)}</view>`
  }).join('\n')
}

function emitSection(node, context, depth) {
  const title = node.props && node.props.title
  const titleLine = title
    ? `${nodeIndent(depth + 1)}<view class="ui-section-title">${attrValueText(title, context)}</view>\n`
    : ''
  return `${nodeIndent(depth)}<view${controlAttrs(node, context)}${attr('id', node.id, context)} class="ui-section">\n`
    + titleLine
    + emitChildren(node, context, depth + 1)
    + `\n${nodeIndent(depth)}</view>`
}

function attrValueText(value, context) {
  const resolved = valueExpression(value, context)
  return resolved.static ? escapeAttr(resolved.value) : `{{${escapeAttr(resolved.value)}}}`
}

function emitActionCard(node, context, depth) {
  const props = node.props || {}
  const tone = props.tone || 'brand'
  const title = props.title || ''
  const icon = props.icon || 'more'
  const classes = `ui-action-card ui-tone-${tone}`
  return `${nodeIndent(depth)}<view${controlAttrs(node, context)}${attr('id', node.id, context)} class="${classes}"${eventAttrs(node, context)}>\n`
    + `${nodeIndent(depth + 1)}<view class="ui-action-card-icon"><icon name="${escapeAttr(attrValueText(icon, context))}" size="36" color="#2563EB" /></view>\n`
    + `${nodeIndent(depth + 1)}<view class="ui-action-card-title">${attrValueText(title, context)}</view>\n`
    + `${nodeIndent(depth)}</view>`
}

function emitGrid(node, context, depth) {
  const columns = (node.props && node.props.columns) || 2
  return `${nodeIndent(depth)}<view${controlAttrs(node, context)}${attr('id', node.id, context)} class="ui-grid ui-grid-${escapeAttr(columns)}">\n`
    + emitChildren(node, context, depth + 1)
    + `\n${nodeIndent(depth)}</view>`
}

function emitPage(node, context, depth) {
  const surface = (node.props && node.props.surface) || 'page'
  return `${nodeIndent(depth)}<view${controlAttrs(node, context)}${attr('id', node.id, context)} class="ui-page ui-surface-${escapeAttr(surface)}">\n`
    + emitChildren(node, context, depth + 1)
    + `\n${nodeIndent(depth)}</view>`
}

function emitHeroSummary(node, context, depth) {
  const props = node.props || {}
  return `${nodeIndent(depth)}<view${controlAttrs(node, context)}${attr('id', node.id, context)} class="ui-hero-summary">\n`
    + `${nodeIndent(depth + 1)}<view class="ui-hero-badge">${attrValueText(props.badge || '课', context)}</view>\n`
    + `${nodeIndent(depth + 1)}<view class="ui-hero-copy">\n`
    + `${nodeIndent(depth + 2)}<view class="ui-hero-label">${attrValueText(props.label || '', context)}</view>\n`
    + `${nodeIndent(depth + 2)}<view class="ui-hero-meta">${attrValueText(props.meta || '', context)}</view>\n`
    + `${nodeIndent(depth + 1)}</view>\n`
    + `${nodeIndent(depth + 1)}<view class="ui-hero-time">${attrValueText(props.time || '', context)}</view>\n`
    + `${nodeIndent(depth)}</view>`
}

function emitTabBar(node, context, depth) {
  const active = (node.props && node.props.active) || 'feature'
  const tabs = [
    { key: 'feature', icon: 'grid', label: '功能' },
    { key: 'schedule', icon: 'calendar', label: '课表' },
    { key: 'profile', icon: 'user', label: '我的' }
  ]
  const items = tabs.map((tab) => {
    const on = tab.key === active ? ' is-on' : ''
    const color = tab.key === active ? '#2563EB' : '#94A3B8'
    return `${nodeIndent(depth + 1)}<view class="ui-tab${on}"><icon name="${tab.icon}" size="30" color="${color}" /><text>${tab.label}</text></view>`
  }).join('\n')
  return `${nodeIndent(depth)}<view${controlAttrs(node, context)}${attr('id', node.id, context)} class="ui-tabbar">\n${items}\n${nodeIndent(depth)}</view>`
}

function emitGeneric(node, context, depth, spec) {
  const attrs = [
    controlAttrs(node, context),
    attr('id', node.id, context),
    eventAttrs(node, context)
  ].join('')
  const propAttrs = Object.entries(node.props || {}).map(([key, value]) => {
    if (key === 'title' && node.type === 'Page') return ''
    if (spec.kind === 'tdesign') {
      const mapped = {
        tone: 'theme',
        variant: 'variant',
        size: 'size'
      }[key] || key
      return attr(mapped, value, context)
    }
    return attr(key, value, context)
  }).join('')
  const children = emitChildren(node, context, depth + 1)
  const slots = emitSlots(node, context, depth + 1)
  const body = [children, slots].filter(Boolean).join('\n')
  return `${nodeIndent(depth)}<${spec.tag}${attrs}${propAttrs}>`
    + (body ? `\n${body}\n${nodeIndent(depth)}` : '')
    + `</${spec.tag}>`
}

function emitNode(node, context, depth) {
  if (!node || typeof node !== 'object') return ''
  if (node.type === 'Page') return emitPage(node, context, depth)
  if (node.type === 'Section') return emitSection(node, context, depth)
  if (node.type === 'Grid') return emitGrid(node, context, depth)
  if (node.type === 'ActionCard') return emitActionCard(node, context, depth)
  if (node.type === 'HeroSummary') return emitHeroSummary(node, context, depth)
  if (node.type === 'TabBar') return emitTabBar(node, context, depth)
  const spec = context.registry.get(node.type)
  if (!spec) throw new Error(`unknown component: ${node.type}`)
  return emitGeneric(node, context, depth, spec)
}

function collectDependencies(node, registry, dependencies) {
  const spec = registry.get(node.type)
  if (!spec) return
  if (spec.import) dependencies.add(`${spec.tag}:${spec.import}`)
  if (node.type === 'ActionCard') {
    dependencies.add('icon:/components/icon/index')
  } else if (node.type === 'HeroSummary' || node.type === 'TabBar') {
    dependencies.add('icon:/components/icon/index')
  } else if (spec.kind === 'local' && spec.tag === 'icon') {
    dependencies.add('icon:/components/icon/index')
  }
  ;(node.children || []).forEach((child) => collectDependencies(child, registry, dependencies))
  Object.values(node.slots || {}).forEach((items) =>
    (items || []).forEach((child) => collectDependencies(child, registry, dependencies)))
}

function emitJson(tree, registry) {
  const dependencies = new Set()
  collectDependencies(tree, registry, dependencies)
  const usingComponents = {}
  dependencies.forEach((entry) => {
    const [tag, target] = entry.split(':')
    usingComponents[tag] = target
  })
  return JSON.stringify({
    component: true,
    styleIsolation: 'apply-shared',
    usingComponents
  }, null, 2) + '\n'
}

function emitWxml(tree, registry) {
  return emitNode(tree, { registry, item: 'item', index: 'index' }, 0) + '\n'
}

function emitJs() {
  return `Component({\n`
    + `  options: { styleIsolation: 'apply-shared' },\n`
    + `  properties: {\n`
    + `    state: { type: Object, value: {} },\n`
    + `    pageData: { type: Object, value: {} },\n`
    + `    computed: { type: Object, value: {} },\n`
    + `    env: { type: Object, value: {} }\n`
    + `  },\n`
    + `  methods: {\n`
    + `    onAction(e) {\n`
    + `      const data = Object.assign({}, e.currentTarget.dataset || {})\n`
    + `      const action = data.action || ''\n`
    + `      delete data.action\n`
    + `      this.triggerEvent('action', { action, data })\n`
    + `    }\n`
    + `  }\n`
    + `})\n`
}

function emitWxss() {
  const vars = createCssVariables()
  const lines = [':host {']
  Object.entries(vars).forEach(([key, value]) => lines.push(`  ${key}: ${value};`))
  lines.push('  display: block;')
  lines.push('  min-height: 100vh;')
  lines.push('  background: var(--bg-page);')
  lines.push('  color: var(--text-primary);')
  lines.push('}')
  lines.push('.ui-page { display: flex; flex-direction: column; min-height: 100vh; padding: 24rpx 24rpx 140rpx; }')
  lines.push('.ui-surface-page { background: var(--bg-page); }')
  lines.push('.ui-hero-summary { display: grid; grid-template-columns: 64rpx 1fr auto; gap: 18rpx; align-items: center; margin-bottom: 26rpx; padding: 22rpx; border: 1rpx solid rgba(18,33,28,.09); border-radius: 22rpx; background: var(--bg-card); box-shadow: 0 16rpx 40rpx rgba(29,45,39,.08); }')
  lines.push('.ui-hero-badge { display: grid; place-items: center; width: 64rpx; height: 64rpx; border-radius: 20rpx; color: var(--primary); background: var(--primary-soft); font-size: 22rpx; font-weight: 700; }')
  lines.push('.ui-hero-label { font-size: 28rpx; font-weight: 650; }')
  lines.push('.ui-hero-meta { margin-top: 5rpx; color: var(--text-muted); font-size: 22rpx; }')
  lines.push('.ui-hero-time { color: var(--signal); font-family: var(--font-num); font-size: 24rpx; font-weight: 650; }')
  lines.push('.ui-section { margin: 0 0 20rpx; }')
  lines.push('.ui-section-title { margin: 0 0 12rpx 4rpx; color: var(--text-muted); font-size: 22rpx; font-weight: 600; }')
  lines.push('.ui-grid { display: grid; gap: 14rpx; }')
  lines.push('.ui-grid-2 { grid-template-columns: repeat(2, minmax(0, 1fr)); }')
  lines.push('.ui-grid-3 { grid-template-columns: repeat(3, minmax(0, 1fr)); }')
  lines.push('.ui-action-card { min-height: 124rpx; padding: 20rpx; border: 1rpx solid rgba(18,33,28,.09); border-radius: 20rpx; background: var(--bg-card); box-shadow: 0 12rpx 32rpx rgba(29,45,39,.06); }')
  lines.push('.ui-action-card-icon { display: grid; place-items: center; width: 52rpx; height: 52rpx; margin-bottom: 14rpx; border-radius: 16rpx; background: var(--primary-soft); }')
  lines.push('.ui-action-card-title { font-size: 27rpx; font-weight: 600; }')
  lines.push('.ui-tone-violet .ui-action-card-icon { background: #f0edff; }')
  lines.push('.ui-tone-signal .ui-action-card-icon { background: var(--signal-soft); }')
  lines.push('.ui-tone-success .ui-action-card-icon { background: var(--success-soft); }')
  lines.push('.ui-tabbar { display: grid; grid-template-columns: repeat(3, 1fr); gap: 8rpx; margin-top: auto; padding: 12rpx 12rpx 18rpx; border: 1rpx solid rgba(255,255,255,.72); border-radius: 26rpx; background: rgba(255,255,255,.82); box-shadow: 0 18rpx 44rpx rgba(29,45,39,.12); -webkit-backdrop-filter: blur(24rpx) saturate(170%); backdrop-filter: blur(24rpx) saturate(170%); }')
  lines.push('.ui-tab { display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 4rpx; min-height: 72rpx; color: var(--text-muted); font-size: 19rpx; }')
  lines.push('.ui-tab.is-on { color: var(--primary); font-weight: 650; }')
  return lines.join('\n') + '\n'
}

function compilePage(page, registry) {
  const validation = validatePage(page, registry)
  if (!validation.valid) {
    const error = new Error('DSL validation failed')
    error.details = validation.errors
    throw error
  }
  const tree = page.tree
  return {
    wxml: emitWxml(tree, registry),
    json: emitJson(tree, registry),
    js: emitJs(),
    wxss: emitWxss()
  }
}

function writeOutput(output, outDir) {
  fs.mkdirSync(outDir, { recursive: true })
  for (const [ext, content] of Object.entries(output)) {
    fs.writeFileSync(path.join(outDir, `index.${ext}`), content, 'utf8')
  }
}

module.exports = {
  compilePage,
  writeOutput,
  expressionPath,
  valueExpression
}
