/**
 * 留言板页面 — 查看/发布留言
 * 登录可读可发; 未登录提示去登录
 */

const api = require('../../utils/api')
const storage = require('../../utils/storage')

Page({
  data: {
    loading: true,
    messages: [],      // 留言列表(时间倒序)
    hasMore: false,
    content: '',       // 输入框内容
    sending: false,
    errorMsg: ''
  },

  onLoad() {
    this.loadMessages()
  },

  onPullDownRefresh() {
    this.loadMessages().finally(() => wx.stopPullDownRefresh())
  },

  /** 加载最新一页 */
  async loadMessages() {
    if (!storage.isLoggedIn()) {
      this.setData({ loading: false, errorMsg: '请先登录后查看留言板', messages: [] })
      return
    }
    this.setData({ loading: true, errorMsg: '' })
    try {
      const res = await api.getBoardMessages(0)
      if (res.success) {
        this.setData({
          loading: false,
          messages: res.messages || [],
          hasMore: !!res.has_more,
          errorMsg: (res.messages || []).length ? '' : '还没有留言，快来抢沙发～'
        })
      } else {
        this.setData({ loading: false, errorMsg: res.message || '加载失败' })
      }
    } catch (e) {
      this.setData({ loading: false, errorMsg: '加载失败' })
    }
  },

  /** 加载更早的留言 */
  async loadMore() {
    if (!this.data.hasMore || this.data.loading) return
    const last = this.data.messages[this.data.messages.length - 1]
    if (!last) return
    this.setData({ loading: true })
    try {
      const res = await api.getBoardMessages(last.id)
      if (res.success) {
        this.setData({
          loading: false,
          messages: this.data.messages.concat(res.messages || []),
          hasMore: !!res.has_more
        })
      } else {
        this.setData({ loading: false })
      }
    } catch (e) {
      this.setData({ loading: false })
    }
  },

  onInput(e) {
    this.setData({ content: e.detail.value })
  },

  /** 发布留言 */
  async onSend() {
    if (!storage.isLoggedIn()) {
      wx.showToast({ title: '请先登录', icon: 'none' })
      return
    }
    const content = (this.data.content || '').trim()
    if (!content) {
      wx.showToast({ title: '请输入内容', icon: 'none' })
      return
    }
    if (this.data.sending) return
    this.setData({ sending: true })
    try {
      const res = await api.postBoardMessage(content)
      if (res.success) {
        wx.showToast({ title: '发布成功', icon: 'success' })
        this.setData({ content: '' })
        this.loadMessages()   // 刷新列表
      } else {
        wx.showToast({ title: res.message || '发布失败', icon: 'none' })
      }
    } catch (e) {
      wx.showToast({ title: '发布失败', icon: 'none' })
    } finally {
      this.setData({ sending: false })
    }
  },

  onReachBottom() {
    this.loadMore()
  },

  goLogin() {
    wx.switchTab({ url: '/pages/settings/settings' })
  }
})
