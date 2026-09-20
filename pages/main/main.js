/**
 * 主页面 — 5 个 Tab(课表/考试/评教/成绩/我的)
 * - 无 swiper: 横滑不再切换页面, 翻页只由底部 tabBar 触发;
 * - 横滑手势在课表页切换周次(左滑下一周 / 右滑上一周);
 * - 组件懒渲染: 首次进入才挂载, 之后保留挂载(hidden 隐藏), 保留滚动/周次状态;
 * - 自定义 tabBar 点击同步切换与高亮。
 *
 * 顶部公告条: 管理端更新公告(updated 变化)后展示横幅,
 * 用户查看(弹窗确认/✕)后标记已读并隐藏; "我的"页公告栏可随时再读。
 */

const ann = require('../../utils/announcement')

Page({
  data: {
    current: 0,        // 当前 Tab 索引
    swiperHeight: 600, // 内容区高度(px), 自适应计算(公告条可见时扣除其高度)
    visited: [true, false, false, false, false],  // 已挂载的 Tab(懒渲染)

    // 顶部公告条(long: 文本被单行截断, 显示"查看 ›"提示)
    ann: { visible: false, text: '', updated: '', long: false }
  },

  onLoad() {
    this._calcHeight()
    // 首屏激活第一个 Tab
    this._activate(0)
    // 拉取公告(有新公告则顶部横幅展示)
    this._loadAnnouncement(true)
  },

  onReady() {
    // 页面渲染完成后确保当前 Tab 已激活(此时 selectComponent 必可拿到组件,
    // 解决慢设备上首屏激活重试超时导致页面空白)
    this._activate(this.data.current)
  },

  onShow() {
    // 从非 tab 页(如图鉴页)返回时同步全局状态到激活页(带重试)
    this._activate(this.data.current)
    // 同步 tabBar 高亮
    this._syncTabBar()
    // 刷新公告状态(可能刚从"我的"页标记已读, 或公告刚更新)
    this._loadAnnouncement()
  },

  /** 计算内容区高度: 视口高 - tabBar 高(约 88rpx) - iOS 底部安全区 - 公告条高(若可见) */
  _calcHeight() {
    try {
      // 仅取视口/安全区尺寸用于布局。不使用 getSystemInfoSync: 该接口已废弃,
      // 且属于微信隐私接口清单中的「设备信息」——本项目不采集设备信息,
      // 详见 docs/privacy-guideline.md(getWindowInfo 只返回窗口尺寸, 不涉及个人信息)
      const sys = wx.getWindowInfo()
      const ratio = sys.windowWidth / 750
      const tabH = Math.ceil(88 * ratio)
      // iOS 全面屏底部安全区(tabBar 有 env(safe-area-inset-bottom) padding)
      const safeH = (sys.safeArea && sys.safeArea.bottom) ? Math.max(0, sys.windowHeight - sys.safeArea.bottom) : 0
      let h = sys.windowHeight - tabH - safeH - 2
      if (this.data.ann.visible) h -= Math.ceil(88 * ratio)   // 公告条高 88rpx
      this.setData({ swiperHeight: h > 200 ? h : 600 })
    } catch (e) {
      this.setData({ swiperHeight: 600 })
    }
  },

  /** 拉取公告并决定横幅是否展示(仅 updated 未读时展示) */
  _loadAnnouncement(force) {
    ann.load(!!force).then(a => {
      const text = a.text || ''
      const visible = a.enabled && !!text && ann.isNew(a.updated)
      this.setData({
        'ann.visible': visible,
        'ann.text': visible ? text : '',
        'ann.updated': a.updated,
        // 横幅只有一行, 超过约 14 字会被省略号截断 → 给出"查看"提示
        'ann.long': visible && text.length > 14
      })
      this._calcHeight()
    })
  },

  /** 点击公告条: 弹窗展示全文 → 确认即标记已读并隐藏 */
  onAnnTap() {
    const a = this.data.ann
    if (!a.visible) return
    wx.showModal({
      title: '📢 公告',
      content: a.text,
      showCancel: false,
      confirmText: '知道了',
      success: () => this._dismissAnn()
    })
  },

  /** 点 ✕ 关闭(同样视为已读) */
  onAnnClose() {
    this._dismissAnn()
  },

  _dismissAnn() {
    const a = this.data.ann
    if (!a.visible) return
    ann.markSeen(a.updated)
    this.setData({ 'ann.visible': false, 'ann.text': '', 'ann.updated': '', 'ann.long': false })
    this._calcHeight()
  },

  /** "我的"页公告栏查看后回调(设置页标记已读 → 主页面横幅同步隐藏) */
  onAnnSeen() {
    if (!this.data.ann.visible) return
    const c = ann.cached()
    const text = c.text || ''
    const visible = c.enabled && !!text && ann.isNew(c.updated)
    this.setData({
      'ann.visible': visible,
      'ann.text': visible ? text : '',
      'ann.updated': c.updated,
      'ann.long': visible && text.length > 14
    })
    this._calcHeight()
  },

  /** 获取某索引的视图组件实例 */
  _view(i) {
    return this.selectComponent('#tabview' + i)
  },

  /** 激活索引 i 的视图(懒渲染 + 生命周期模拟); 组件未就绪时延迟重试 */
  _activate(i, retry) {
    const v = this._view(i)
    if (v && v.activate) {
      v.activate()
      return
    }
    // 页面首帧渲染未完成时 selectComponent 拿不到实例, 延迟重试(最多 2 秒)
    const r = retry || 0
    if (r < 20) setTimeout(() => this._activate(i, r + 1), 100)
  },

  /** 横滑手势起点(仅课表页用于周次切换) */
  onSwipeTouchStart(e) {
    const t = e.touches && e.touches[0]
    if (!t) return
    this._swipeStart = { x: t.clientX, y: t.clientY }
  },

  /**
   * 横滑手势结束: 课表页左滑下一周 / 右滑上一周。
   * 页面翻页已由 disable-touch 关闭, 此手势不再切换 Tab。
   */
  onSwipeTouchEnd(e) {
    const s = this._swipeStart
    this._swipeStart = null
    if (!s || this.data.current !== 0) return
    const t = e.changedTouches && e.changedTouches[0]
    if (!t) return
    const dx = t.clientX - s.x
    const dy = t.clientY - s.y
    // 横向位移足够大, 且明显大于纵向(避开上下滚动)
    if (Math.abs(dx) < 60 || Math.abs(dx) < Math.abs(dy) * 1.2) return
    const view = this.selectComponent('#tabview0')
    if (!view) return
    if (dx < 0 && typeof view.nextWeek === 'function') view.nextWeek()
    if (dx > 0 && typeof view.prevWeek === 'function') view.prevWeek()
  },

  /** tabBar 点击(自定义 tabBar 组件回调): 切换当前 Tab(首次进入时挂载) */
  onTabTap(i) {
    const visited = this.data.visited.slice()
    visited[i] = true
    // 即使 i === current 也重新激活(修复: 首次激活失败后再次点击无反应的死循环)
    this.setData({ current: i, visited })
    this._activate(i)
    this._syncTabBar()
  },

  _syncTabBar() {
    // 已无平台级 tabBar 配置(custom-tab-bar 由本页手动渲染), getTabBar 不可用;
    // 用 selectComponent 同步高亮
    const bar = this.selectComponent('#tabbar')
    if (bar) bar.setData({ selected: this.data.current })
  }
})
