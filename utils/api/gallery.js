/**
 * API ???: gallery (Phase 3 ? utils/api.js ??)
 */
const { request } = require('./core')

function getGalleryImageUrl(name) {
  return config.API_BASE + '/static/gallery/' + encodeURIComponent(name)
}

/** 获取校历图片列表 */

function getGalleryImages() {
  return request('GET', '/api/gallery-images')
}

/** 获取校历图片列表 — wx.request 直链优先(避开 callContainer 通道故障), 失败回退 callContainer */

function getGalleryImagesFlex() {
  return new Promise((resolve) => {
    wx.request({
      url: config.API_BASE + '/api/gallery-images',
      method: 'GET',
      timeout: 30000,
      success: (res) => {
        if (res.statusCode === 200 && res.data) resolve(res.data)
        else resolve(request('GET', '/api/gallery-images'))
      },
      fail: () => {
        resolve(request('GET', '/api/gallery-images'))
      }
    })
  })
}

/** 获取单张校历图片的分片元信息（大图需分片下载） */

function getGalleryImageMeta(name) {
  return request('GET', '/api/gallery-image-meta', { name })
}

/** 获取单张校历图片的第 part 片（base64, part 从 0 开始）
 *  60s 超时: 云托管冷启动 + 大响应体, 30s 不够 */

function getGalleryImagePart(name, part) {
  return request('GET', '/api/gallery-image-part', { name, part }, { timeout: 60000 })
}

/** 获取单张校历图片（base64, 仅限小图: callContainer 返回包限制 ~1000KB） */

function getGalleryImage(name) {
  return request('GET', '/api/gallery-image', { name })
}

module.exports = { getGalleryImageUrl, getGalleryImages, getGalleryImagesFlex, getGalleryImageMeta, getGalleryImagePart, getGalleryImage }
