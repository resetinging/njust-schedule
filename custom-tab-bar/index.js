/**
 * 自定义 tabBar — 合页方案(swiper 容器)
 * 点击 tab → 通知 main 页面切换 swiper.current(带动画)
 * 高亮状态由 main 页面通过 setData({selected}) 同步
 * 纯图标模式(无文字): emoji 图标, 未选中置灰, 选中彩色放大
 *
 * 注意: 5 个独立 tab 页(旧界面)已删除, 本组件不再是平台级 custom-tab-bar,
 * 而是 main 页面手动引用的普通组件(见 pages/main/main.wxml)。
 */
const storage = require('../utils/storage')

// key 必须与 main 页面的 Tab 序号一致(0课表 1考试 2评教 3成绩 4我的)
const ALL_TABS = [
  { key: 0, name: '课表', emoji: '📅' },
  { key: 1, name: '考试', emoji: '📝' },
  { key: 2, name: '评教', emoji: '📋' },
  { key: 3, name: '成绩', emoji: '🎓' },
  { key: 4, name: '我的', emoji: '👤' }
]

Component({
  data: {
    selected: 0,
    list: ALL_TABS
  },

  attached() {
    this._refreshList()
  },

  pageLifetimes: {
    // 登录/切换账号后(页面重新显示)再算一次, 研究生隐藏评教
    show() {
      this._refreshList()
    }
  },

  methods: {
    /** 研究生账号没有评教(研究生系统不提供), 隐藏该项 */
    _refreshList() {
      const isGrad = storage.get('account_type', '') === 'graduate'
      const list = ALL_TABS.filter(t => !(isGrad && t.key === 2))
      if (list.length !== (this.data.list || []).length) {
        this.setData({ list })
      }
      // 老会话可能还没记录账号类型: 向后台补一次, 拿到后立刻刷新列表
      if (!storage.get('account_type', '')) {
        const api = require('../utils/api')
        api.getStatus().then((res) => {
          if (res && res.account_type) {
            storage.set('account_type', res.account_type)
            this._refreshList()
          }
        }).catch(() => {})
      }
    },

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
