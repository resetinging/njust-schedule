/**
 * 自定义 tabBar — 合页方案(swiper 容器)
 * 点击 tab → 通知 main 页面切换 swiper.current(带动画)
 * 高亮状态由 main 页面通过 getTabBar().setData({selected}) 同步
 */
Component({
  data: {
    selected: 0,
    list: [
      { pagePath: 'pages/schedule/schedule', text: '课表', iconPath: '/static/icons/schedule.png', selectedIconPath: '/static/icons/schedule-active.png' },
      { pagePath: 'pages/exams/exams', text: '考试', iconPath: '/static/icons/exam.png', selectedIconPath: '/static/icons/exam-active.png' },
      { pagePath: 'pages/eval/eval', text: '评教', iconPath: '/static/icons/eval.png', selectedIconPath: '/static/icons/eval-active.png' },
      { pagePath: 'pages/grades/grades', text: '成绩', iconPath: '/static/icons/grades.png', selectedIconPath: '/static/icons/grades-active.png' },
      { pagePath: 'pages/settings/settings', text: '我的', iconPath: '/static/icons/settings.png', selectedIconPath: '/static/icons/settings-active.png' }
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
