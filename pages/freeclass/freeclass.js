/**
 * 空教室查询独立页 — 仅作为深链/独立页壳，主体逻辑复用 freeclass-view 组件。
 */

Page({
  onClose() {
    this.goBack()
  },

  onLogin() {
    wx.navigateBack({ delta: 1 })
    const pages = getCurrentPages()
    const main = pages.find(p => p && typeof p.onTabTap === 'function')
    if (main) setTimeout(() => main.onTabTap(2), 300)
  },

  goBack() {
    wx.navigateBack({
      delta: 1,
      fail: () => wx.reLaunch({ url: '/pages/main/main' })
    })
  }
})
