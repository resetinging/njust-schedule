/**
 * 空教室查询独立页 — 仅作为深链/独立页壳，主体逻辑复用 freeclass-view 组件。
 */

Page({
  onClose() {
    this.goBack()
  },

  onLogin() {
    const goProfile = () => {
      const pages = getCurrentPages()
      for (let i = pages.length - 1; i >= 0; i--) {
        const page = pages[i]
        if (page && typeof page.onTabTap === 'function') {
          page.onTabTap(2)
          return
        }
      }
      wx.reLaunch({ url: '/pages/main/main?tab=profile' })
    }
    wx.navigateBack({
      delta: 1,
      success: () => setTimeout(goProfile, 120),
      fail: goProfile
    })
  },

  goBack() {
    wx.navigateBack({
      delta: 1,
      fail: () => wx.reLaunch({ url: '/pages/main/main' })
    })
  }
})
