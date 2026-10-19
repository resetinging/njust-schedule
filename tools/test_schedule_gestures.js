const assert = require('assert')
const path = require('path')

let componentConfig = null
global.Component = (config) => {
  componentConfig = config
}

require(path.join(__dirname, '..', 'components', 'schedule-view', 'index.js'))

function instantiate() {
  const component = Object.assign({}, componentConfig.methods)
  component.data = JSON.parse(JSON.stringify(componentConfig.data))
  component.setData = (patch, callback) => {
    Object.assign(component.data, patch)
    if (callback) callback()
  }
  component.weekCalls = []
  component.nextWeek = () => component.weekCalls.push('next')
  component.prevWeek = () => component.weekCalls.push('prev')
  return component
}

function point(x, y) {
  return { clientX: x, clientY: y }
}

let now = 1000
const realNow = Date.now
Date.now = () => now

function swipe(component, options) {
  const {
    dx,
    dy = 0,
    duration = 250,
    startX = 220,
    startY = 300
  } = options
  const midRatio = 0.55
  const start = point(startX, startY)
  const mid = point(startX + dx * midRatio, startY + dy * midRatio)
  const end = point(startX + dx, startY + dy)
  component.onWeekSwipeStart({ touches: [start] })
  now += duration * midRatio
  component.onWeekSwipeMove({ touches: [mid] })
  now += duration * (1 - midRatio)
  component.onWeekSwipeEnd({ changedTouches: [end] })
}

try {
  const left = instantiate()
  swipe(left, { dx: -100, dy: 3 })
  assert.deepStrictEqual(left.weekCalls, ['next'])

  const right = instantiate()
  swipe(right, { dx: 100, dy: -4 })
  assert.deepStrictEqual(right.weekCalls, ['prev'])

  const diagonal = instantiate()
  swipe(diagonal, { dx: -90, dy: -80 })
  assert.deepStrictEqual(diagonal.weekCalls, [])

  const vertical = instantiate()
  swipe(vertical, { dx: -80, dy: -180 })
  assert.deepStrictEqual(vertical.weekCalls, [])

  const nearThreshold = instantiate()
  swipe(nearThreshold, { dx: -70, dy: 2 })
  assert.deepStrictEqual(nearThreshold.weekCalls, [])

  const tooMuchVerticalDrift = instantiate()
  swipe(tooMuchVerticalDrift, { dx: -100, dy: 30 })
  assert.deepStrictEqual(tooMuchVerticalDrift.weekCalls, [])

  const tooSlow = instantiate()
  swipe(tooSlow, { dx: -120, dy: 4, duration: 900 })
  assert.deepStrictEqual(tooSlow.weekCalls, [])

  const popupOpen = instantiate()
  popupOpen.data.showDetail = true
  swipe(popupOpen, { dx: -100, dy: 3 })
  assert.deepStrictEqual(popupOpen.weekCalls, [])

  const cooldown = instantiate()
  swipe(cooldown, { dx: -100, dy: 3 })
  swipe(cooldown, { dx: -100, dy: 3 })
  assert.deepStrictEqual(cooldown.weekCalls, ['next'])

  console.log('Schedule gesture test passed [OK] 9/9')
} finally {
  Date.now = realNow
}
