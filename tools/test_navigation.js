/**
 * 主页面导航状态机测试。
 * 不依赖微信运行时，用桩件验证 page-container 单例、关闭竞态和 Tab 切换。
 */
const assert = require('assert')
const path = require('path')

const ROOT = path.resolve(__dirname, '..')
const store = new Map()

global.wx = {
  getStorageSync: (key) => (store.has(key) ? store.get(key) : ''),
  setStorageSync: (key, value) => store.set(key, value),
  removeStorageSync: (key) => store.delete(key),
  getStorageInfoSync: () => ({ keys: Array.from(store.keys()) }),
  getWindowInfo: () => ({
    windowWidth: 390,
    windowHeight: 844,
    safeArea: { bottom: 844 }
  }),
  nextTick: (fn) => fn(),
  setNavigationBarTitle: () => {},
  enableAlertBeforeUnload: () => {},
  disableAlertBeforeUnload: () => {}
}
global.getCurrentPages = () => []

let pageConfig = null
global.Page = (config) => {
  pageConfig = config
}

require(path.join(ROOT, 'pages', 'main', 'main.js'))

function instantiate() {
  const page = Object.assign({}, pageConfig)
  page.data = JSON.parse(JSON.stringify(pageConfig.data))
  page.setData = function setData(patch, callback) {
    Object.assign(this.data, patch)
    if (callback) callback()
  }
  page.selectComponent = () => ({
    data: { active: true },
    activate: (done) => { if (done) done() },
    openFavoritesView: () => {},
    setData: () => {}
  })
  return page
}

let passed = 0
async function check(name, fn) {
  await fn()
  passed += 1
  console.log('  ✓ ' + name)
}

;(async () => {
  await check('打开工具页先挂载再显示', () => {
    const page = instantiate()
    page._openToolPage('grades', 'toolGrades')
    assert.strictEqual(page.data.toolRendered, true)
    assert.strictEqual(page.data.toolVisible, true)
    assert.strictEqual(page.data.toolPage, 'grades')
  })

  await check('Tab 切换前先关闭工具页', async () => {
    const page = instantiate()
    page._openToolPage('grades', 'toolGrades')
    page.onTabTap(2)
    assert.strictEqual(page.data.toolClosing, true)
    assert.strictEqual(page.data.toolVisible, false)
    page.onToolAfterLeave()
    await new Promise((resolve) => setTimeout(resolve, 0))
    assert.strictEqual(page.data.current, 2)
    assert.strictEqual(page.data.toolRendered, false)
  })

  await check('系统返回关闭后完全释放容器', () => {
    const page = instantiate()
    page._openToolPage('freeclass')
    page.onToolBeforeLeave()
    page.onToolAfterLeave()
    assert.strictEqual(page.data.toolRendered, false)
    assert.strictEqual(page.data.toolPage, '')
  })

  await check('页面隐藏立即释放容器，避免重复实例', () => {
    const page = instantiate()
    page._openToolPage('gallery')
    page.onHide()
    assert.strictEqual(page.data.toolRendered, false)
    assert.strictEqual(page.data.toolVisible, false)
  })

  await check('工具页登录提示关闭后切到我的', async () => {
    const page = instantiate()
    page._openToolPage('freeclass')
    page.onToolLogin()
    page.onToolAfterLeave()
    await new Promise((resolve) => setTimeout(resolve, 0))
    assert.strictEqual(page.data.current, 2)
    assert.strictEqual(page.data.toolRendered, false)
  })

  await check('关闭动画中再次关闭会保留最后一次跳转', async () => {
    const page = instantiate()
    page._openToolPage('grades', 'toolGrades')
    page.onToolClose()
    page.onTabTap(1)
    page.onToolAfterLeave()
    await new Promise((resolve) => setTimeout(resolve, 0))
    assert.strictEqual(page.data.current, 1)
  })

  await check('首次进入我的页面时先隐藏激活再切换', () => {
    const page = instantiate()
    let releaseActivation = null
    page.selectComponent = (selector) => {
      if (selector === '#tabview4') {
        return {
          data: { active: false },
          activate: (done) => { releaseActivation = done },
          setData: () => {}
        }
      }
      return {
        data: { active: true },
        activate: (done) => { if (done) done() },
        setData: () => {}
      }
    }

    page.onTabTap(2)
    assert.strictEqual(page.data.current, 1)
    assert.strictEqual(page.data.visited[4], true)
    assert.strictEqual(typeof releaseActivation, 'function')

    releaseActivation()
    assert.strictEqual(page.data.current, 2)
  })

  await check('我的预激活期间切换其他 Tab 会取消旧跳转', () => {
    const page = instantiate()
    let releaseActivation = null
    page.selectComponent = (selector) => {
      if (selector === '#tabview4') {
        return {
          data: { active: false },
          activate: (done) => { releaseActivation = done },
          setData: () => {}
        }
      }
      return {
        data: { active: true },
        activate: (done) => { if (done) done() },
        setData: () => {}
      }
    }

    page.onTabTap(2)
    page.onTabTap(0)
    releaseActivation()
    assert.strictEqual(page.data.current, 0)
  })

  console.log('\n导航状态机测试通过 [OK] ' + passed + '/' + passed)
})().catch((error) => {
  console.error(error)
  process.exit(1)
})
