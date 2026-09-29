/**
 * 像素字体: 按需子集(轻量方案)
 *
 * 思路: WXSS 里已经内联了一份"固定文案"子集(ZpixPixel), 动态文本(课程名/教师/教室)
 * 交给后端现场生成子集 —— 只有该用户用得上的字, 通常十几~几十 KB, 走云托管
 * callContainer(免域名白名单、免 CORS)。
 *
 * 流量策略:
 *   - 字符集没变 且 本地字体文件还在 → 只重新注册字体(loadFontFace 每次启动都要注册), 不发请求;
 *   - 出现新字符 → 拉一份新子集(累积字符集, 切周/换学期不会丢老字);
 *   - 请求失败 → 退避 6 小时, 期间静默用内联子集兜底, 不影响功能。
 *
 * 早期版本的"完整字体下载"通道(966KB/1.29MB)已移除: 首屏流量从约 1MB 降到几十 KB,
 * 也顺带解决了渲染层直连字体 URL 的 CORS 报错。
 */
const config = require('./config')
const storage = require('./storage')

const FAMILY = 'ZpixFull'
const CHARS_KEY = 'pixel_font_chars'      // 已拿到子集的字符集(累积)
const FAIL_KEY = 'pixel_font_fail_at'     // 最近一次失败时间
const RETRY_AFTER = 6 * 60 * 60 * 1000    // 失败后 6h 内不再重试
const MAX_CHARS = 3000                    // 与后端上限一致
const FILE_PATH = `${wx.env.USER_DATA_PATH}/pixel-font.woff`

function loadFace(source) {
  return new Promise((resolve) => {
    if (!wx.loadFontFace) return resolve(false)
    wx.loadFontFace({
      family: FAMILY,
      global: true,
      source,
      success: () => resolve(true),
      fail: () => resolve(false)
    })
  })
}

/** 本地子集文件是否还在(用户清了小程序数据就没了, 此时需要重新拉) */
function fileReady() {
  try {
    wx.getFileSystemManager().accessSync(FILE_PATH)
    return true
  } catch (e) {
    return false
  }
}

function postSubset(chars) {
  return new Promise((resolve) => {
    if (!wx.cloud || !wx.cloud.callContainer) return resolve(false)
    wx.cloud.callContainer({
      config: { env: config.CLOUD_ENV },
      path: '/api/font/subset',
      method: 'POST',
      header: { 'X-WX-SERVICE': config.CLOUD_SERVICE, 'content-type': 'application/json' },
      data: { text: chars },
      timeout: 30000,
      success: (res) => {
        const body = res && res.data
        // 202 = 后端正在后台生成子集(不阻塞请求), 这次先不换字体
        // 注意: 这不算失败, 不能走失败退避, 否则一次"正在生成"会锁死 6 小时
        if (body && body.pending) return resolve('pending')
        if (!body || !body.data) return resolve(false)
        try {
          wx.getFileSystemManager().writeFile({
            filePath: FILE_PATH,
            data: body.data,
            encoding: 'base64',
            success: () => resolve(body.partial ? 'partial' : true),
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

/**
 * 传入动态文本(课程名/教师/教室等):
 * 字符集变了才请求新子集, 否则直接用本地文件重新注册字体。
 * 永远 resolve, 不抛错——字体只是观感, 不能影响启动与功能。
 */
function loadForText(text) {
  const stored = storage.get(CHARS_KEY, '') || ''
  const set = new Set(stored.split(''))
  String(text || '').split('').forEach((ch) => {
    if (ch && ch.trim()) set.add(ch)
  })
  let chars = Array.from(set).join('')
  if (chars.length > MAX_CHARS) chars = chars.slice(-MAX_CHARS)
  if (!chars) return Promise.resolve(false)

  // 字符集没变 + 文件还在: 不发请求, 只重新注册(每次冷启动都要注册)
  if (chars === stored && fileReady()) {
    return loadFace(`url("${FILE_PATH}")`)
  }

  const failedAt = Number(storage.get(FAIL_KEY, 0)) || 0
  if (failedAt && Date.now() - failedAt < RETRY_AFTER) {
    // 退避期内: 有旧文件就先用着, 没有就交给内联子集
    return fileReady() ? loadFace(`url("${FILE_PATH}")`) : Promise.resolve(false)
  }

  return postSubset(chars)
    .then((ok) => {
      if (ok === 'pending') return false        // 后端正在生成: 不记账、不退避, 下次再来
      if (!ok) {
        storage.set(FAIL_KEY, String(Date.now()))
        return fileReady() ? loadFace(`url("${FILE_PATH}")`) : false
      }
      // 'partial' = 后端用的是近似子集(精确的那份还在后台生成), 先加载但不记账,
      // 下次进来会再请求一次, 拿到精确子集后才记住字符集
      if (ok !== 'partial') storage.set(CHARS_KEY, chars)
      storage.remove(FAIL_KEY)
      return loadFace(`url("${FILE_PATH}")`)
    })
    .catch(() => {
      storage.set(FAIL_KEY, String(Date.now()))
      return false
    })
}

module.exports = { FAMILY, loadForText }
