/**
 * 校历 & 照片墙页面
 * 缓存策略: 图片下载后保存到本地文件(USER_DATA_PATH);
 * 渲染时优先检索本地文件 → 秒开零等待;
 * 同时后台静默检查服务器列表, 补齐缺失图片(新图/失败重试自动生效)。
 */

const api = require('../../utils/api')
const storage = require('../../utils/storage')
const fs = wx.getFileSystemManager()

const GALLERY_META_KEY = 'cached_gallery_meta'   // {t: 时间戳, names: [文件名]}
const GALLERY_DIR = wx.env.USER_DATA_PATH

Page({
  data: {
    loading: true,
    errorMsg: '',
    images: [],        // [{name, title, src: 本地文件路径}]
    downloadMsg: '',   // 下载进度文案
    downloadPercent: 0,// 下载进度 0-100
    diag: ''           // 诊断信息(排查问题用, 正常时为空)
  },

  onLoad() {
    this.loadImages()
  },

  /** 图片名 → 本地文件路径（URL 编码文件名: 中文文件名会导致 image 组件渲染失败） */
  _localPath(name) {
    return `${GALLERY_DIR}/gallery_${encodeURIComponent(name)}`
  },

  /** base64 → 本地文件, 返回路径 */
  _b64ToLocal(name, b64) {
    const fp = this._localPath(name)
    fs.writeFileSync(fp, b64, 'base64')
    return fp
  },

  /**
   * 直链二进制下载（优先）: wx.downloadFile 直接拉取后端静态文件。
   * filePath 参数直接落盘到本地缓存路径(基础库 2.10+), 避免临时文件兼容问题。
   * 不走 callContainer — 该通道在部分环境会 ERR_CONNECTION_CLOSED /
   * 受返回包 ~1000KB 限制, 且 base64 有 4/3 体积膨胀。
   * @param {string} name 图片文件名
   * @returns {Promise<string>} 本地文件路径
   */
  _downloadDirect(name) {
    const fp = this._localPath(name)
    return new Promise((resolve, reject) => {
      wx.downloadFile({
        url: api.getGalleryImageUrl(name),
        filePath: fp,             // 直接下载到缓存路径, 同名自动覆盖
        timeout: 60000,
        success: (res) => {
          if (res.statusCode === 200) resolve(fp)
          else reject(new Error('HTTP ' + (res.statusCode || '未知')))
        },
        fail: (err) => {
          reject(new Error((err && err.errMsg) || '直链下载失败'))
        }
      })
    })
  },

  /**
   * 下载图片 → 本地文件。优先直链二进制下载, 失败自动回退分片下载:
   * callContainer 返回包限制约 1000KB, 高清图(base64 >700KB)必须分片;
   * 每片失败自动重试(冷启动/网络抖动导致超时常见), 重试 2 次仍失败才放弃。
   * @param {string} name 图片文件名
   * @param {Function} onProgress (done, total) 进度回调
   */
  async _downloadImage(name, onProgress) {
    // 1) 直链优先（开发者工具 urlCheck=false 可直接用; 真机需配置合法域名）
    try {
      return await this._downloadDirect(name)
    } catch (directErr) {
      console.warn('[gallery] 直链下载失败, 回退分片:', name, directErr && directErr.message)
      // 2) 直链失败 → 分片下载兜底
    }

    const meta = await api.getGalleryImageMeta(name)
    if (!meta || !meta.success || !meta.parts) {
      // meta 失败(旧版后端/网关异常): 兜底尝试整图接口一次
      const whole = await api.getGalleryImage(name)
      if (whole && whole.success && whole.data_b64) {
        return this._b64ToLocal(name, whole.data_b64)
      }
      throw new Error('获取图片信息失败')
    }
    const parts = meta.parts
    let b64 = ''
    for (let p = 0; p < parts; p++) {
      let res = null
      for (let tryN = 0; tryN < 3; tryN++) {
        try {
          res = await api.getGalleryImagePart(name, p)
          if (res && res.success && res.data_b64) break
        } catch (e) {
          res = null
        }
        // 重试前等待: 冷启动通常在首个请求后完成, 后续重试间隔递增
        if (tryN < 2) await new Promise(r => setTimeout(r, 600 * (tryN + 1)))
      }
      if (!res || !res.success || !res.data_b64) {
        throw new Error(`分片 ${p + 1}/${parts} 下载失败${res && res.message ? ': ' + res.message : ''}`)
      }
      b64 += res.data_b64
      if (onProgress) onProgress(p + 1, parts)
    }
    return this._b64ToLocal(name, b64)
  },

  /** 本地文件是否存在 */
  _localExists(name) {
    try {
      fs.accessSync(this._localPath(name))
      return true
    } catch (e) {
      return false
    }
  },

  async loadImages() {
    this.setData({ loading: true, errorMsg: '', diag: '' })

    // ── 1) 本地缓存立即渲染（秒开; 即使列表过期也先显示已有图片）──
    const meta = storage.getCached(GALLERY_META_KEY)
    let local = []
    if (meta && meta.names && meta.names.length) {
      local = meta.names
        .filter(name => this._localExists(name))
        .map(name => ({
          name,
          title: name.replace(/\.[^.]+$/, ''),
          src: this._localPath(name)
        }))
    }
    if (local.length > 0) {
      this.setData({ images: local, loading: false })
    }

    // ── 2) 后台静默检查服务器列表, 补齐缺失图片 ──
    // (修复: 旧逻辑 24h 内命中缓存直接返回, 服务器新增图片永远不出现)
    try {
      const res = await api.getGalleryImagesFlex()
      if (!res || !res.success || !res.images || res.images.length === 0) {
        if (local.length === 0) {
          this.setData({ loading: false, errorMsg: '暂无校历图片' })
        }
        return
      }

      const have = new Set(local.map(i => i.name))
      const serverNames = res.images.slice().sort()
      const need = serverNames.filter(n => !have.has(n))
      const images = local.slice()

      if (need.length > 0) {
        this.setData({ downloadMsg: `正在下载图片 (0/${need.length})…`, downloadPercent: 0 })
        for (let i = 0; i < need.length; i++) {
          const name = need[i]
          try {
            const src = await this._downloadImage(name, (done, total) => {
              this.setData({
                downloadMsg: `正在下载图片 ${i + 1}/${need.length}${total > 1 ? ` (分片 ${done}/${total})` : ''}…`,
                downloadPercent: Math.round(((i + done / total) / need.length) * 100)
              })
            })
            images.push({ name, title: name.replace(/\.[^.]+$/, ''), src })
            this.setData({ images: images.slice(), downloadMsg: '', downloadPercent: 0, errorMsg: '' })
          } catch (e) {
            // 单张失败不阻断其余图片; 错误累积显示在页面底部诊断区
            const errLine = `「${name}」下载失败: ${(e && e.message) || '网络错误'}`
            this.setData({
              diag: this.data.diag ? this.data.diag + '；' + errLine : errLine
            })
          }
        }
      }

      // 元数据以服务器列表为准; 失败项不写入 → 下次进入自动重试
      storage.setCached(GALLERY_META_KEY, { t: Date.now(), names: images.map(i => i.name) })
    } catch (e) {
      // 列表检查失败(网络/通道问题): 已有缓存继续显示, 无缓存显示错误
      if (local.length === 0) {
        this.setData({ loading: false, errorMsg: '加载失败，请稍后重试' })
      }
    }

    if (local.length === 0) this.setData({ loading: false })
  },

  /** 点击图片 → 全屏预览（本地路径直接可用） */
  onImageTap(e) {
    const idx = e.currentTarget.dataset.index
    const urls = this.data.images.map(i => i.src)
    if (urls.length > 0) {
      wx.previewImage({ current: urls[idx] || urls[0], urls })
    }
  }
})
