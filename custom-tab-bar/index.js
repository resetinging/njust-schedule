/**
 * 自定义 tabBar — 合页方案(swiper 容器)
 * 点击 tab → 通知 main 页面切换 swiper.current(带动画)
 * 高亮状态由 main 页面通过 setData({selected}) 同步
 * 纯图标模式(无文字): emoji 图标, 未选中置灰, 选中彩色放大
 */
Component({
  data: {
    selected: 0,
    list: [
      { pagePath: 'pages/schedule/schedule', emoji: '📅' },
      { pagePath: 'pages/exams/exams', emoji: '📝' },
      { pagePath: 'pages/eval/eval', emoji: '📋' },
      { pagePath: 'pages/grades/grades', emoji: '🎓' },
      { pagePath: 'pages/board/board', emoji: '💬' },
      { pagePath: 'pages/settings/settings', emoji: '👤' }
    ]
  },

  methods: {
    onTap(e) {
      const i = Number(e.currentTarget.dataset.index)
      // 不短路同 Tab 点击: main.onTabTap 对"已当前页但激活失败"会重新激活
      const pages = getCurrentPages()
      const page = pages[pages.length - 1]
      if (page && typeof page.onTabTap === 'function') {
        page.onTabTap(i)
      } else {
        this.setData({ selected: i })
      }
    }
  }
})
