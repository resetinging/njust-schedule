/**
 * 校历 & 照片墙页面
 * 通过云托管内网获取 static/gallery/ 下的图片（base64），支持全屏预览
 * 优化：base64 写入本地临时文件，setData 只传路径字符串
 *       （此前直接 setData base64（数 MB）触发"数据传输长度过长"性能警告）
 */

const api = require('../../utils/api')
const fs = wx.getFileSystemManager()

Page({
  data: {
    loading: true,
    errorMsg: '',
    images: []   // [{name, title, src: 本地临时文件路径}]
  },

  onLoad() {
    this.loadImages()
  },

  /** base64 → 本地临时文件，返回文件路径 */
  _b64ToTempFile(b64, mime, idx) {
    const ext = (mime === 'image/jpeg') ? 'jpg' : (mime === 'image/png' ? 'png' : 'img')
    const filePath = `${wx.env.USER_DATA_PATH}/gallery_${Date.now()}_${idx}.${ext}`
    fs.writeFileSync(filePath, b64, 'base64')
    return filePath
  },

  async loadImages() {
    this.setData({ loading: true, errorMsg: '' })
    try {
      const res = await api.getGalleryImages()
      if (!res.success || !res.images || res.images.length === 0) {
        this.setData({ loading: false, errorMsg: '暂无校历图片' })
        return
      }

      const images = []
      for (let i = 0; i < res.images.length; i++) {
        const name = res.images[i]
        try {
          const imgRes = await api.getGalleryImage(name)
          if (imgRes.success && imgRes.data_b64) {
            const src = this._b64ToTempFile(imgRes.data_b64, imgRes.mime, i)
            images.push({
              name,
              title: name.replace(/\.[^.]+$/, ''),
              src
            })
            // 边下载边显示（只传路径字符串，数据量极小）
            this.setData({ images: images.slice(), loading: false })
          }
        } catch (e) {
          // 单张加载失败跳过
        }
      }

      this.setData({
        loading: false,
        images,
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
