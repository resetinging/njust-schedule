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

// 线性图标: PNG 资源由 poster/make_icons.py + make_icons.ps1 生成
// (这里路径写在 data 里, 用绝对路径指向项目根)
const _icon = (name, tone) => `/static/icons/${name}-${tone}.png`

// key 必须与 main 页面的底栏序号一致: 0=功能 1=课表 2=我的
// (考试/评教/成绩 已移到"功能"页, 评教的可见性由功能页入口控制)
const ALL_TABS = [
  { key: 0, name: '功能', icon: _icon('grid', 'grey'), iconOn: _icon('grid', 'indigo') },
  { key: 1, name: '课表', icon: _icon('calendar', 'grey'), iconOn: _icon('calendar', 'indigo') },
  { key: 2, name: '我的', icon: _icon('user', 'grey'), iconOn: _icon('user', 'indigo') }
]

Component({
  data: {
    selected: 0,
    list: ALL_TABS
  },

  attached() {
    // 三个 tab 恒定显示(考试/评教/成绩 已移入"功能"页, 不再随账号变化)
    if (this.data.list.length !== ALL_TABS.length) {
      this.setData({ list: ALL_TABS })
    }
  },

  methods: {
    /** 研究生账号没有评教(研究生系统不提供), 隐藏该项 */
    _refreshList() {
      // 三个 tab 恒定显示: 评教的隐藏已改由"功能"页入口判断
      const list = ALL_TABS
      if (list.length !== (this.data.list || []).length) {
        this.setData({ list })
      }
      // 兜底校验(30 秒节流): app 启动时页面还没创建, 拿不到 tabBar 实例,
      // 所以由 tabBar 自己在显示时向后台核对一次账号类型
      const now = Date.now()
      if (!this._lastCheck || now - this._lastCheck > 30000) {
        this._lastCheck = now
        const api = require('../utils/api')
        api.getStatus().then((res) => {
          if (res && res.account_type) {
            const changed = storage.get('account_type', '') !== res.account_type
            storage.set('account_type', res.account_type)
            if (changed) this._refreshList()
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
