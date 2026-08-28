/**
 * 校历 & 照片墙页面
 * 缓存策略: 图片下载后保存到本地文件(USER_DATA_PATH);
 * 渲染时优先检索本地文件, 命中则零网络请求直接显示;
 * 本地缺失(或图片列表缓存过期 24h)才向服务器请求列表, 且只下载缺失的图片。
 */

const api = require('../../utils/api')
const storage = require('../../utils/storage')
const fs = wx.getFileSystemManager()

const GALLERY_META_KEY = 'cached_gallery_meta'   // {t: 时间戳, names: [文件名]}
const META_TTL = 24 * 60 * 60 * 1000            // 图片列表缓存 24h(已下载文件不再重传)
const GALLERY_DIR = wx.env.USER_DATA_PATH

Page({
  data: {
    loading: true,
    errorMsg: '',
    images: [],        // [{name, title, src: 本地文件路径}]
    downloadMsg: '',   // 下载进度文案
    downloadPercent: 0 // 下载进度 0-100
  },

  onLoad() {
    this.loadImages()
  },

  /** 图片名 → 本地文件路径 */
  _localPath(name) {
    return `${GALLERY_DIR}/gallery_${name}`
  },

  /** base64 → 本地文件, 返回路径 */
  _b64ToLocal(name, b64) {
    const fp = this._localPath(name)
    fs.writeFileSync(fp, b64, 'base64')
    return fp
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
    this.setData({ loading: true, errorMsg: '' })

    // ── 1) 优先本地: 上次下载的图片文件仍在 → 直接渲染, 零网络请求 ──
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
    const metaFresh = !!meta && (Date.now() - (meta.t || 0) < META_TTL)
    if (local.length > 0 && metaFresh) {
      // 全部命中且列表未过期: 不再访问服务器
      this.setData({ images: local, loading: false })
      return
    }

    // ── 2) 本地缺失或列表过期: 请求服务器列表, 只下载缺失的图片 ──
    try {
      const res = await api.getGalleryImages()
      if (!res.success || !res.images || res.images.length === 0) {
        if (local.length > 0) {
          this.setData({ images: local, loading: false })
        } else {
          this.setData({ loading: false, errorMsg: '暂无校历图片' })
        }
        return
      }

      const images = local.slice()                      // 保留本地命中的
      const have = new Set(images.map(i => i.name))
      const serverNames = res.images.slice().sort()
      const need = serverNames.filter(n => !have.has(n))
      if (need.length > 0) {
        // 大图(高清地图等)优先传输: 显示下载进度
        this.setData({ downloadMsg: `正在下载高清图片 (0/${need.length})…`, downloadPercent: 0 })
      }

      for (let i = 0; i < serverNames.length; i++) {
        const name = serverNames[i]
        if (have.has(name)) continue
        try {
          const imgRes = await api.getGalleryImage(name)
          if (imgRes.success && imgRes.data_b64) {
            const src = this._b64ToLocal(name, imgRes.data_b64)
            images.push({
              name,
              title: name.replace(/\.[^.]+$/, ''),
              src
            })
            have.add(name)
            this.setData({
              images: images.slice(),
              loading: false,
              downloadMsg: `正在下载高清图片 (${i + 1}/${need.length})…`,
              downloadPercent: Math.round(((i + 1) / need.length) * 100)
            })
          }
        } catch (e) {
          // 单张失败跳过
        }
      }

      // 更新本地元数据(已下载文件名列表)
      storage.setCached(GALLERY_META_KEY, { t: Date.now(), names: images.map(i => i.name) })
      this.setData({
        loading: false,
        images,
        downloadMsg: '',
        downloadPercent: 0,
        errorMsg: images.length === 0 ? '图片加载失败' : ''
      })
    } catch (e) {
      this.setData({ loading: false, errorMsg: '加载失败，请稍后重试' })
    }
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
