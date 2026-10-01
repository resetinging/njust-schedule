/**
 * 校园工具独立页 — 仅作为深链/独立页壳，主体逻辑复用 gallery-view 组件。
 */

Page({
  onClose() {
    this.goBack()
  },

  goBack() {
    wx.navigateBack({
      delta: 1,
      fail: () => wx.reLaunch({ url: '/pages/main/main' })
    })
  }
})
