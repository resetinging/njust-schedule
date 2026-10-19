const assert = require('assert')
const path = require('path')

const ROOT = path.resolve(__dirname, '..')
const store = new Map()
let now = 10000
let nextTimerId = 1
const timers = new Map()

global.wx = {
  getStorageSync(key) {
    return store.has(key) ? store.get(key) : ''
  },
  setStorageSync(key, value) {
    store.set(key, value)
  },
  removeStorageSync(key) {
    store.delete(key)
  }
}

const realNow = Date.now
const realSetTimeout = global.setTimeout
const realClearTimeout = global.clearTimeout
Date.now = () => now
global.setTimeout = (fn, delay = 0) => {
  const id = nextTimerId++
  timers.set(id, { fn, due: now + Math.max(0, Number(delay) || 0) })
  return id
}
global.clearTimeout = (id) => timers.delete(id)

function advance(ms) {
  const target = now + Math.max(0, ms)
  while (true) {
    let selectedId = null
    let selected = null
    timers.forEach((timer, id) => {
      if (timer.due <= target && (!selected || timer.due < selected.due)) {
        selectedId = id
        selected = timer
      }
    })
    if (!selected) break
    timers.delete(selectedId)
    now = selected.due
    selected.fn()
  }
  now = target
}

const apiPath = require.resolve(path.join(ROOT, 'utils', 'api'))
require.cache[apiPath] = {
  id: apiPath,
  filename: apiPath,
  loaded: true,
  exports: {
    trackEvents: () => new Promise(() => {})
  }
}

const analytics = require(path.join(ROOT, 'utils', 'analytics'))

function createContext() {
  let intersection = null
  return {
    createSelectorQuery() {
      return {
        select() {
          return {
            boundingClientRect(callback) {
              callback({ width: 300, height: 100 })
              return { exec() {} }
            }
          }
        }
      }
    },
    createIntersectionObserver() {
      return {
        relativeToViewport() { return this },
        observe(selector, callback) {
          intersection = callback
          return this
        },
        disconnect() {}
      }
    },
    emitIntersection(ratio) {
      intersection({ intersectionRatio: ratio })
    }
  }
}

function slotEvents() {
  const queue = store.get('analytics_queue') || []
  return queue.filter((event) => /^slot_/.test(event.name))
}

try {
  const ctx = createContext()
  analytics.observeSlot(ctx, 'slot-test', 'schedule', 'native')
  advance(0)

  ctx.emitIntersection(1)
  advance(999)
  assert.strictEqual(slotEvents().length, 0)
  advance(1)
  assert.deepStrictEqual(slotEvents().map((event) => event.name), [
    'slot_view',
    'slot_visible'
  ])

  ctx.emitIntersection(1)
  advance(1000)
  assert.strictEqual(slotEvents().length, 2)

  advance(3000)
  ctx.emitIntersection(0)
  const leave = slotEvents()[2]
  assert.strictEqual(leave.name, 'slot_leave')
  assert.strictEqual(leave.visible_ms, 4000)

  ctx.emitIntersection(1)
  advance(500)
  ctx.emitIntersection(0)
  assert.strictEqual(slotEvents().length, 3)

  analytics.observeSlots(ctx, [
    { id: 'slot-test', page: 'schedule', ad_type: 'native' }
  ])
  ctx.emitIntersection(1)
  advance(10000)
  assert.strictEqual(
    slotEvents().filter((event) => event.name === 'slot_view').length,
    2
  )
  advance(2000)
  analytics.disconnectSlots(ctx)
  assert.strictEqual(
    slotEvents().filter((event) => event.name === 'slot_leave').length,
    2
  )
  assert.strictEqual(slotEvents().at(-1).visible_ms, 2500)

  console.log('Analytics slot dedupe test passed [OK] 6/6')
} finally {
  Date.now = realNow
  global.setTimeout = realSetTimeout
  global.clearTimeout = realClearTimeout
}
