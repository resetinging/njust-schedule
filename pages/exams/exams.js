/**
 * 考试安排页面
 */

const api = require('../../utils/api')
const storage = require('../../utils/storage')

Page({
  data: {
    exams: [],
    loading: false
  },

  onLoad() {
    this.loadCachedData()
    this.loadFromServer()
  },

  /** 从缓存加载 */
  loadCachedData() {
    const exams = storage.getCached('cached_exams')
    if (exams) {
      this.setData({ exams })
    }
  },

  /** 从服务器加载 */
  async loadFromServer() {
    if (!storage.isLoggedIn()) {
      return
    }
    this.setData({ loading: true })
    try {
      const res = await api.getExams()
      if (res.success && res.exams) {
        this.setData({ exams: res.exams, loading: false })
        storage.setCached('cached_exams', res.exams)
      } else {
        this.setData({ loading: false })
      }
    } catch (e) {
      this.setData({ loading: false })
      wx.showToast({ title: '加载失败', icon: 'none' })
    }
  },

  /** 刷新 */
  async onRefresh() {
    if (!storage.isLoggedIn()) {
      wx.showToast({ title: '请先在"我的"页面登录', icon: 'none' })
      return
    }
    this.setData({ loading: true })
    try {
      const res = await api.refreshExams()
      this.setData({ loading: false })
      if (res.success) {
        wx.showToast({ title: `已刷新 ${res.count || 0} 场考试`, icon: 'success' })
        this.loadFromServer()
      } else {
        wx.showToast({ title: res.message || '刷新失败', icon: 'none' })
      }
    } catch (e) {
      this.setData({ loading: false })
      wx.showToast({ title: '刷新失败', icon: 'none' })
    }
  },

  onPullDownRefresh() {
    this.onRefresh()
    wx.stopPullDownRefresh()
  }
})
