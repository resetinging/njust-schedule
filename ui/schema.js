'use strict'

const DSL_VERSION = 1
const FORBIDDEN_NODE_KEYS = new Set([
  'style', 'class', 'fn', 'eval', 'request', 'setState'
])
const EXPR_ROOTS = new Set([
  '$state', '$data', '$computed', '$item', '$index', '$props', '$token', '$env'
])
const STYLE_AXES = Object.freeze({
  tone: new Set(['brand', 'neutral', 'signal', 'success', 'warning', 'danger', 'violet']),
  surface: new Set(['page', 'card', 'glass', 'plain']),
  size: new Set(['sm', 'md', 'lg']),
  variant: new Set(['solid', 'outline', 'ghost', 'text']),
  density: new Set(['compact', 'comfortable']),
  radius: new Set(['control', 'card', 'pill'])
})

function issue(path, message) {
  return { path, message }
}

function isPlainObject(value) {
  return !!value && typeof value === 'object' && !Array.isArray(value)
}

function validateExpression(value, path, errors) {
  if (typeof value !== 'string') {
    errors.push(issue(path, 'expression must be a string'))
    return
  }
  const root = value.trim().split(/[.[]/, 1)[0]
  if (!EXPR_ROOTS.has(root)) {
    errors.push(issue(path, `unsupported expression root: ${root || '(empty)'}`))
  }
}

function validateAction(value, path, errors) {
  if (!isPlainObject(value)) {
    errors.push(issue(path, 'event action must be an object'))
    return
  }
  if (typeof value.action !== 'string' || !value.action.trim()) {
    errors.push(issue(path + '.action', 'action name is required'))
  }
  if (value.data !== undefined && !isPlainObject(value.data)) {
    errors.push(issue(path + '.data', 'event data must be an object'))
  }
}

function validateStyleAxes(props, path, errors) {
  for (const [axis, allowed] of Object.entries(STYLE_AXES)) {
    if (props[axis] !== undefined && !allowed.has(props[axis])) {
      errors.push(issue(`${path}.${axis}`, `unsupported ${axis}: ${props[axis]}`))
    }
  }
}

function validateNode(node, path, registry, errors, ids) {
  if (!isPlainObject(node)) {
    errors.push(issue(path, 'node must be an object'))
    return
  }
  for (const key of Object.keys(node)) {
    if (FORBIDDEN_NODE_KEYS.has(key)) {
      errors.push(issue(`${path}.${key}`, `forbidden DSL field: ${key}`))
    }
  }
  if (typeof node.type !== 'string' || !node.type.trim()) {
    errors.push(issue(path + '.type', 'node type is required'))
    return
  }
  if (registry && !registry.has(node.type)) {
    errors.push(issue(path + '.type', `unknown component: ${node.type}`))
  }
  if (node.id !== undefined) {
    if (typeof node.id !== 'string' || !node.id.trim()) {
      errors.push(issue(path + '.id', 'id must be a non-empty string'))
    } else if (ids.has(node.id)) {
      errors.push(issue(path + '.id', `duplicate id: ${node.id}`))
    } else {
      ids.add(node.id)
    }
  }
  if (node.props !== undefined && !isPlainObject(node.props)) {
    errors.push(issue(path + '.props', 'props must be an object'))
  } else if (node.props) {
    validateStyleAxes(node.props, path + '.props', errors)
  }
  if (node.bind !== undefined) {
    if (!isPlainObject(node.bind)) {
      errors.push(issue(path + '.bind', 'bind must be an object'))
    } else {
      for (const [key, value] of Object.entries(node.bind)) {
        validateExpression(value, `${path}.bind.${key}`, errors)
      }
    }
  }
  if (node.events !== undefined) {
    if (!isPlainObject(node.events)) {
      errors.push(issue(path + '.events', 'events must be an object'))
    } else {
      for (const [key, value] of Object.entries(node.events)) {
        validateAction(value, `${path}.events.${key}`, errors)
      }
    }
  }
  if (node.when !== undefined) validateExpression(node.when, path + '.when', errors)
  if (node.each !== undefined) {
    if (!isPlainObject(node.each)) {
      errors.push(issue(path + '.each', 'each must be an object'))
    } else {
      validateExpression(node.each.in, path + '.each.in', errors)
      if (typeof node.each.as !== 'string' || !node.each.as.trim()) {
        errors.push(issue(path + '.each.as', 'each.as is required'))
      }
      if (node.each.key === undefined) {
        errors.push(issue(path + '.each.key', 'each.key is required'))
      } else {
        validateExpression(node.each.key, path + '.each.key', errors)
      }
    }
  }
  for (const key of ['children', 'slots']) {
    if (node[key] === undefined) continue
    if (key === 'children') {
      if (!Array.isArray(node[key])) {
        errors.push(issue(path + '.children', 'children must be an array'))
      } else {
        node[key].forEach((child, index) =>
          validateNode(child, `${path}.children[${index}]`, registry, errors, ids))
      }
    } else if (!isPlainObject(node[key])) {
      errors.push(issue(path + '.slots', 'slots must be an object'))
    } else {
      for (const [slot, items] of Object.entries(node[key])) {
        if (!Array.isArray(items)) {
          errors.push(issue(`${path}.slots.${slot}`, 'slot must be an array'))
          continue
        }
        items.forEach((child, index) =>
          validateNode(child, `${path}.slots.${slot}[${index}]`, registry, errors, ids))
      }
    }
  }
}

function validatePage(page, registry) {
  const errors = []
  if (!isPlainObject(page)) {
    return { valid: false, errors: [issue('$', 'page must be an object')] }
  }
  if (page.version !== DSL_VERSION) {
    errors.push(issue('$.version', `expected DSL version ${DSL_VERSION}`))
  }
  if (typeof page.page !== 'string' || !page.page.trim()) {
    errors.push(issue('$.page', 'page path is required'))
  }
  if (!isPlainObject(page.tree)) {
    errors.push(issue('$.tree', 'tree is required'))
  } else {
    validateNode(page.tree, '$.tree', registry, errors, new Set())
  }
  return { valid: errors.length === 0, errors }
}

module.exports = {
  DSL_VERSION,
  EXPR_ROOTS,
  FORBIDDEN_NODE_KEYS,
  STYLE_AXES,
  validateExpression,
  validatePage
}
