/**
 * 自定义 tabBar — 合页方案(swiper 容器)
 * 点击 tab → 通知 main 页面切换 swiper.current(带动画)
 * 高亮状态由 main 页面通过 setData({selected}) 同步
 * 纯图标模式(无文字): emoji 图标, 未选中置灰, 选中彩色放大
 *
 * 注意: 5 个独立 tab 页(旧界面)已删除, 本组件不再是平台级 custom-tab-bar,
 * 而是 main 页面手动引用的普通组件(见 pages/main/main.wxml)。
 */
Component({
  data: {
    selected: 0,
    // 顺序必须与 main 的 tabs / swiper 下标一致
    list: [
      { name: '课表', emoji: '📅' },
      { name: '考试', emoji: '📝' },
      { name: '评教', emoji: '📋' },
      { name: '成绩', emoji: '🎓' },
      { name: '我的', emoji: '👤' }
    ]
  },

  methods: {
    onTap(e) {
      const i = Number(e.currentTarget.dataset.index)
      // main 提供 onTabTap(切换 swiper); 不短路同 Tab 点击, 以便重新激活
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
