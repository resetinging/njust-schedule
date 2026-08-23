/**
 * 校历 & 照片墙页面
 * 通过云托管内网获取 static/gallery/ 下的图片（base64），支持全屏预览
 * 优化：边下载边显示（逐张追加），图片 lazy-load
 */

const api = require('../../utils/api')

Page({
  data: {
    loading: true,
    errorMsg: '',
    images: []   // [{name, src}]
  },

  onLoad() {
    this.loadImages()
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
      for (const name of res.images) {
        try {
          const imgRes = await api.getGalleryImage(name)
          if (imgRes.success && imgRes.data_b64) {
            images.push({
              name,
              src: 'data:' + (imgRes.mime || 'image/png') + ';base64,' + imgRes.data_b64
            })
            // 边下载边显示
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

  /** 点击图片 → 全屏预览 */
  onImageTap(e) {
    const idx = e.currentTarget.dataset.index
    const urls = this.data.images.map(i => i.src)
    if (urls.length > 0) {
      wx.previewImage({ current: urls[idx] || urls[0], urls })
    }
  }
})
