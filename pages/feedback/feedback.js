/**
 * 问题反馈页 — 提交反馈(类型/内容/联系方式)
 * 限流防重复: 发送中禁用按钮(防双击) + 客户端 10 秒冷却(与服务端一致)
 */
const api = require('../../utils/api')
const storage = require('../../utils/storage')

const COOLDOWN_MS = 10000   // 与服务端 FEEDBACK_RATE_SEC 一致

Page({
  data: {
    type: 'suggest',   // suggest 功能建议 | bug 问题/Bug | other 其他
    content: '',
    contact: '',
    sending: false
  },

  _lastTs: 0,   // 上次提交成功时间戳(客户端冷却)

  onType(e) {
    this.setData({ type: e.currentTarget.dataset.type })
  },

  onContent(e) {
    this.setData({ content: e.detail.value })
  },

  onContact(e) {
    this.setData({ contact: e.detail.value })
  },

  /** 提交反馈(防双击 + 客户端冷却 + 服务端限流兜底) */
  async onSubmit() {
    if (this.data.sending) return
    const text = (this.data.content || '').trim()
    if (!text) {
      wx.showToast({ title: '请填写反馈内容', icon: 'none' })
      return
    }
    if (!storage.isLoggedIn()) {
      wx.showToast({ title: '请先登录后再提交反馈', icon: 'none' })
      return
    }
    const now = Date.now()
    if (now - this._lastTs < COOLDOWN_MS) {
      const remain = Math.ceil((COOLDOWN_MS - (now - this._lastTs)) / 1000)
      wx.showToast({ title: `提交太频繁，请 ${remain} 秒后再试`, icon: 'none' })
      return
    }
    this.setData({ sending: true })
    try {
      const res = await api.submitFeedback(this.data.type, text, this.data.contact)
      if (res.success) {
        this._lastTs = Date.now()
        wx.showToast({ title: '反馈已提交，感谢您的建议', icon: 'success' })
        setTimeout(() => wx.navigateBack(), 1200)
      } else {
        wx.showToast({ title: res.message || '提交失败', icon: 'none' })
      }
    } catch (e) {
      wx.showToast({ title: '提交失败，请稍后再试', icon: 'none' })
    } finally {
      this.setData({ sending: false })
    }
  }
})
