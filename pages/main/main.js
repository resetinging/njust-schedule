/**
 * 主页面 — swiper 合页方案（方案 A）
 * 5 个 Tab(课表/考试/评教/成绩/我的) 用 swiper 承载,
 * 左右滑动原生切换 + 动画; 自定义 tabBar 点击同步切换。
 * 组件懒渲染: 激活才渲染, 切换时由本页通知 activate/deactivate。
 */

Page({
  data: {
    current: 0,       // swiper 当前索引
    swiperHeight: 600 // swiper 高度(px), 自适应计算
  },

  onLoad() {
    this._calcHeight()
    // 首屏激活第一个 Tab
    this._activate(0)
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
  },

  /** 计算 swiper 高度: 视口高 - tabBar 高(约 110rpx) - iOS 底部安全区 */
  _calcHeight() {
    try {
      const sys = wx.getSystemInfoSync()
      const tabH = Math.ceil(110 * (sys.windowWidth / 750))
      // iOS 全面屏底部安全区(tabBar 有 env(safe-area-inset-bottom) padding)
      const safeH = (sys.safeArea && sys.safeArea.bottom) ? Math.max(0, sys.windowHeight - sys.safeArea.bottom) : 0
      const h = sys.windowHeight - tabH - safeH - 2
      this.setData({ swiperHeight: h > 200 ? h : 600 })
    } catch (e) {
      this.setData({ swiperHeight: 600 })
    }
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

  /** swiper 滑动结束: 更新激活视图 + tabBar 高亮 */
  onSwiperChange(e) {
    const i = e.detail.current
    this.setData({ current: i })
    this._preActivating = null   // 复位预激活标记
    this._activate(i)
    this._syncTabBar()
  },

  /**
   * swiper 滑动进行中: 提前激活目标页(懒渲染组件此时渲染, 数据已在缓存),
   * 滑到位时内容已就绪, 消除"首次滑动进入空白页"问题
   */
  onSwiperTransition(e) {
    const dx = e.detail.dx
    if (!dx) return
    const target = dx < 0 ? this.data.current + 1 : this.data.current - 1
    if (target < 0 || target >= 5) return
    if (this._preActivating === target) return
    this._preActivating = target
    this._activate(target)
  },

  /** tabBar 点击(自定义 tabBar 组件回调): 切 swiper 带动画 */
  onTabTap(i) {
    // 即使 i === current 也重新激活(修复: 首次激活失败后再次点击无反应的死循环)
    if (i !== this.data.current) this.setData({ current: i })
    this._activate(i)
    this._syncTabBar()
  },

  _syncTabBar() {
    // main 非 tabBar list 页面, getTabBar 不可用; 用 selectComponent 同步高亮
    const bar = this.selectComponent('#tabbar')
    if (bar) bar.setData({ selected: this.data.current })
  }
})
