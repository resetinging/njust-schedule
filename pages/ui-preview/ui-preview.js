Page({
  data: {
    state: {
      loggedIn: true,
      accountType: 'undergraduate'
    },
    pageData: {
      semester: '2026-2027-1'
    },
    computed: {
      entranceCount: 7
    },
    env: {
      isPreview: true
    }
  },

  onAction(e) {
    const detail = e.detail || {}
    const action = detail.action || 'unknown'
    const data = detail.data || {}
    wx.showToast({
      title: action + (data.sub ? ': ' + data.sub : (data.page ? ': ' + data.page : '')),
      icon: 'none'
    })
  }
})
