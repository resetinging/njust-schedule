/**
 * 字体档位: pixel(内联像素字, 默认) / system(系统字)
 *
 * pixel 的子集内联在 WXSS 里(ZpixPixel), 零请求;
 * 其余中文档位走后端按需子集: POST /api/font/subset {text, font} → woff(base64)
 * → 落盘到各自文件 → wx.loadFontFace 注册成对应 family → 页面根节点 class 切换变量。
 *
 * 任何一步失败都静默回退(系统字), 不影响功能。
 */
const config = require('./config')
const storage = require('./storage')

const MODE_KEY = 'font_mode'
const CHARS_KEY = 'pixel_font_chars'      // 最近一次成功子集的字符集(按档位复用)
const FAIL_KEY = 'pixel_font_fail_at'
const RETRY_AFTER = 6 * 60 * 60 * 1000
const MAX_CHARS = 3000

const MODES = {
  pixel: { cls: '', family: '', remote: false, label: '像素点阵' },
  system: { cls: 'font-system', family: '', remote: false, label: '系统字体' }
}

function getMode() {
  const m = storage.get(MODE_KEY, 'pixel')
  return MODES[m] ? m : 'pixel'
}

function getClass() {
  return MODES[getMode()].cls
}

function applyClassToPages() {
  const pages = typeof getCurrentPages === 'function' ? getCurrentPages() : []
  pages.forEach(p => {
    if (p && typeof p.setData === 'function') p.setData({ fontClass: getClass() })
  })
}

function setMode(mode) {
  const m = MODES[mode] ? mode : 'pixel'
  storage.set(MODE_KEY, m)
  applyClassToPages()
  ensureCurrent()          // 远程档位: 后台把字体拉下来并注册
  return m
}

function fileOf(mode) {
  return `${wx.env.USER_DATA_PATH}/font-${mode}.woff`
}

function fileReady(mode) {
  try {
    wx.getFileSystemManager().accessSync(fileOf(mode))
    return true
  } catch (e) {
    return false
  }
}

function loadFace(family, path) {
  return new Promise((resolve) => {
    if (!family || !wx.loadFontFace) return resolve(false)
    wx.loadFontFace({
      family,
      global: true,
      source: `url("${path}")`,
      success: () => resolve(true),
      fail: () => resolve(false)
    })
  })
}

/** 请求某档位 + 字符集的子集, 落盘并用它的 family 注册 */
function fetchSubset(mode, chars) {
  const conf = MODES[mode]
  if (!conf.remote || !chars) return Promise.resolve(false)
  // 本地联调: 直连本机 Flask(开发者工具需勾"不校验合法域名")
  if (config.USE_LOCAL) {
    return new Promise((resolve) => {
      wx.request({
        url: config.LOCAL_BASE + '/api/font/subset',
        method: 'POST',
        data: { text: chars, font: mode },
        timeout: 30000,
        success: (res) => {
          const body = res && res.data
          if (body && body.pending) return resolve('pending')
          if (!body || !body.data) return resolve(false)
          wx.getFileSystemManager().writeFile({
            filePath: fileOf(mode),
            data: body.data,
            encoding: 'base64',
            success: () => loadFace(conf.family, fileOf(mode)).then(ok => resolve(ok ? (body.partial ? 'partial' : true) : false)),
            fail: () => resolve(false)
          })
        },
        fail: () => resolve(false)
      })
    })
  }
  if (!wx.cloud || !wx.cloud.callContainer) return Promise.resolve(false)
  return new Promise((resolve) => {
    wx.cloud.callContainer({
      config: { env: config.CLOUD_ENV },
      path: '/api/font/subset',
      method: 'POST',
      header: { 'X-WX-SERVICE': config.CLOUD_SERVICE, 'content-type': 'application/json' },
      data: { text: chars, font: mode },
      timeout: 30000,
      success: (res) => {
        const body = res && res.data
        if (body && body.pending) return resolve('pending')
        if (!body || !body.data) return resolve(false)
        try {
          wx.getFileSystemManager().writeFile({
            filePath: fileOf(mode),
            data: body.data,
            encoding: 'base64',
            success: () => loadFace(conf.family, fileOf(mode)).then(ok => resolve(ok ? (body.partial ? 'partial' : true) : false)),
            fail: () => resolve(false)
          })
        } catch (e) {
          resolve(false)
        }
      },
      fail: () => resolve(false)
    })
  })
}

/** 当前档位需要远程字体时: 有缓存直接注册, 否则按已记录的字符集请求 */
function ensureCurrent() {
  const mode = getMode()
  const conf = MODES[mode]
  if (!conf.remote) return Promise.resolve(true)
  if (fileReady(mode)) {
    return loadFace(conf.family, fileOf(mode))
  }
  const failedAt = Number(storage.get(FAIL_KEY, 0)) || 0
  if (failedAt && Date.now() - failedAt < RETRY_AFTER) return Promise.resolve(false)
  const chars = storage.get(CHARS_KEY, '') || ''
  if (!chars) return Promise.resolve(false)
  return fetchSubset(mode, chars).then(ok => {
    if (!ok || ok === 'pending') {
      if (!ok) storage.set(FAIL_KEY, String(Date.now()))
      return false
    }
    storage.remove(FAIL_KEY)
    return true
  })
}

/**
 * 课表页把课程文本交进来。
 * opts.force = 用户主动点"刷新数据"时才会向服务器要新子集;
 * 否则只用本地已缓存的那份(没有缓存就等下次刷新), 避免每次启动/切周都打网络。
 */
function loadForText(text, opts) {
  const stored = storage.get(CHARS_KEY, '') || ''
  const set = new Set(stored.split(''))
  String(text || '').split('').forEach((ch) => {
    if (ch && ch.trim()) set.add(ch)
  })
  let chars = Array.from(set).join('')
  if (chars.length > MAX_CHARS) chars = chars.slice(-MAX_CHARS)
  if (!chars) return Promise.resolve(false)
  // 关键: 不管当前是哪一档都先把字符集记下来 —— 否则用户从"像素"切到"文楷"时
  // 客户端手里没有文本可发, 切换会静默失败(表现为"点了没反应")
  if (chars !== stored) storage.set(CHARS_KEY, chars)

  const mode = getMode()
  if (!MODES[mode].remote) return Promise.resolve(false)
  const force = !!(opts && opts.force)
  // 非主动刷新: 本地有缓存就直接注册, 不发请求
  if (!force && fileReady(mode)) {
    return loadFace(MODES[mode].family, fileOf(mode))
  }
  if (!force && chars === stored && fileReady(mode)) {
    return loadFace(MODES[mode].family, fileOf(mode))
  }
  return fetchSubset(mode, chars).then(ok => {
    if (ok && ok !== 'pending') storage.set(CHARS_KEY, chars)
    return !!ok
  })
}

module.exports = { MODES, getMode, getClass, setMode, loadForText, ensureCurrent }
