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
const storage = require('../../utils/storage')
const font = require('../../utils/font')
const analytics = require('../../utils/analytics')

const MAIN_TITLE = '课表助手'
const TOOL_TITLES = { freeclass: '空教室查询', gallery: '校园工具', audit: '蹭课查询' }

Page({
  data: {
    current: 1,        // 底栏选中项: 0=功能 1=课表 2=我的
    toolPage: '',      // 页面内假页: '' | freeclass | gallery | exams | eval | grades | credit
    toolVisible: false,
    isGraduate: false, // 研究生账号在功能页隐藏"教学评价"
    fontClass: '',     // 字体档位: '' 像素 | 'font-system' 系统字体
    swiperHeight: 600, // 内容区高度(px), 自适应计算(公告条可见时扣除其高度)
    visited: [true, false, false, false, false, false],  // 已挂载的常驻 Tab: 0=课表, 4=我的

    // 顶部公告条(long: 文本被单行截断, 显示"查看 ›"提示)
    ann: { visible: false, text: '', updated: '', long: false }
  },

  onLoad(options) {
    this._syncAccountType()
    this._calcHeight()
    // 首屏停在"课表"(底栏中间项)
    this._route()
    // 拉取公告(有新公告则顶部横幅展示)
    this._loadAnnouncement(true)
    // 订阅消息/外链落地: pages/main/main?feature=exams|eval|grades|credit → 直接打开对应假页
    if (options && options.feature) {
      const sub = String(options.feature)
      if (['exams', 'eval', 'grades', 'credit'].indexOf(sub) >= 0) this._pendingFeature = sub
    }
  },

  onReady() {
    // 页面渲染完成后确保当前 Tab 已激活(此时 selectComponent 必可拿到组件,
    // 解决慢设备上首屏激活重试超时导致页面空白)
    this._route()
    // 落地页参数: 首帧渲染完再切二级视图(组件此时可被 selectComponent 拿到)
    if (this._pendingFeature) {
      const sub = this._pendingFeature
      this._pendingFeature = ''
      this.goFeature(sub)
    }
    analytics.observeSlots(this, [
      { id: 'slot-feature-bottom', page: 'feature', ad_type: 'native' }
    ])
  },

  onShow() {
    this._syncAccountType()
    const fc = font.getClass()
    if (fc !== this.data.fontClass) this.setData({ fontClass: fc })
    // 从非 tab 页(如图鉴页)返回时同步全局状态到激活页(带重试)
    this._route()
    // 同步 tabBar 高亮
    this._syncTabBar()
    this._trackCurrentPage()
    // 刷新公告状态(可能刚从"我的"页标记已读, 或公告刚更新)
    this._loadAnnouncement()
  },

  _trackCurrentPage() {
    const page = this.data.current === 0
      ? 'feature'
      : (this.data.current === 1 ? 'schedule' : 'profile')
    analytics.pageView(page)
  },

  /** 研究生账号(学号 1 开头)在功能页隐藏"教学评价"入口 */
  _syncAccountType() {
    const isGrad = storage.get('account_type', '') === 'graduate'
    if (isGrad !== this.data.isGraduate) this.setData({ isGraduate: isGrad })
  },

  /** 计算内容区高度: 视口高 - tabBar 高(约 96rpx, 图标+文字) - iOS 底部安全区 - 公告条高(若可见) */
  _calcHeight() {
    try {
      // 仅取视口/安全区尺寸用于布局。不使用 getSystemInfoSync: 该接口已废弃,
      // 且属于微信隐私接口清单中的「设备信息」——本项目不采集设备信息,
      // 详见 docs/privacy-guideline.md(getWindowInfo 只返回窗口尺寸, 不涉及个人信息)
      const sys = wx.getWindowInfo()
      const ratio = sys.windowWidth / 750
      const tabH = Math.ceil(112 * ratio)
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
    if (!s || this.data.current !== 1) return
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
    // 底栏三项 → 组件索引: 1(课表)→0, 2(我的)→4; 0(功能)是一级列表, 不挂组件
    const VIEW_OF_TAB = { 1: 0, 2: 4 }
    const v = VIEW_OF_TAB[i]
    if (v !== undefined) visited[v] = true
    // 点底栏一律回到一级界面(功能页的二级视图收起)
    this.setData({ current: i, visited })
    this._route()
    this._syncTabBar()
    this._trackCurrentPage()
  },

  /** 功能页: 打开课业假页(考试/评教/成绩/学分进度) */
  onOpenFeature(e) {
    const sub = e.currentTarget.dataset.sub
    if (!sub) return
    const toolId = {
      exams: 'toolExams', eval: 'toolEval', grades: 'toolGrades', credit: 'toolCredit'
    }[sub]
    analytics.featureOpen(sub, 'feature')
    this._openToolPage(sub, toolId)
  },

  /**
   * 供其他页面调用: 切到"功能"页并直接打开课业假页(如成绩)。
   */
  goFeature(sub) {
    this.setData({ current: 0 })
    this._route()
    this._syncTabBar()
    analytics.featureOpen(sub, 'feature')
    const toolId = {
      exams: 'toolExams', eval: 'toolEval', grades: 'toolGrades', credit: 'toolCredit'
    }[sub]
    this._openToolPage(sub, toolId)
  },

  /** 功能页: 打开页面内假页(空教室 / 校历照片墙) */
  onOpenNavPage(e) {
    const page = e.currentTarget.dataset.page
    analytics.featureOpen(page, 'feature')
    this._openToolPage(page)
  },

  /**
   * 打开页面内假页。课业组件依赖 activate() 进入激活态并处理研究生分流,
   * 挂载后再查找组件实例激活; 找不到时短暂重试。
   */
  _openToolPage(page, toolId, mode) {
    const allowed = ['freeclass', 'gallery', 'audit', 'exams', 'eval', 'grades', 'credit']
    if (allowed.indexOf(page) < 0 || this.data.toolVisible) return
    analytics.pageView(page)
    if (TOOL_TITLES[page]) this._setNavTitle(TOOL_TITLES[page])
    this.setData({ toolPage: page, toolVisible: true }, () => {
      if (!toolId) return
      const activate = (retry) => {
        const comp = this.selectComponent('#' + toolId)
        const canActivate = comp && typeof comp.activate === 'function'
        const canOpenFavorites = comp &&
          typeof comp.openFavoritesView === 'function'
        if (canActivate || canOpenFavorites) {
          if (canActivate) comp.activate()
          if (mode === 'favorites' && canOpenFavorites) {
            comp.openFavoritesView()
          }
          return
        }
        if (retry < 6) setTimeout(() => activate(retry + 1), 60)
      }
      activate(0)
    })
  },

  /** 关闭页面内假页(子组件返回按钮触发) */
  onToolClose() {
    if (this.data.toolVisible) {
      this.setData({ toolVisible: false })
      this._trackCurrentPage()
    }
  },

  /** 蹭课收藏变化后同步给已挂载的课表组件。 */
  onAuditFavoriteChange() {
    const view = this.selectComponent('#tabview0')
    if (view && typeof view._loadAuditFavorites === 'function') {
      view._loadAuditFavorites()
    }
  },

  /** 课表页快捷入口: 打开蹭课收藏视图。 */
  onOpenAuditFavorites() {
    this._openToolPage('audit', 'toolAudit', 'favorites')
  },

  /** 系统返回/右滑关闭假页时, 同步受控状态 */
  onToolBeforeLeave() {
    if (this.data.toolVisible) this.setData({ toolVisible: false })
  },

  /** 退出动画结束后卸载组件, 避免常驻占用 */
  onToolAfterLeave() {
    if (!this.data.toolVisible && this.data.toolPage) {
      this.setData({ toolPage: '' })
    }
    this._setNavTitle(MAIN_TITLE)
  },

  /** 假页使用主页面原生导航栏标题, 不再重复绘制组件标题 */
  _setNavTitle(title) {
    if (typeof wx === 'undefined' || typeof wx.setNavigationBarTitle !== 'function') return
    try {
      wx.setNavigationBarTitle({ title })
    } catch (e) { /* 非原生导航栏场景忽略 */ }
  },

  /** 假页内提示登录: 关闭假页并切到"我的" */
  onToolLogin() {
    this.setData({ toolVisible: false })
    setTimeout(() => this.onTabTap(2), 340)
  },

  /**
   * 按 current 决定要激活哪个常驻 Tab 组件。
   * 组件索引保持不变: 0 课表 / 4 我的
   */
  _route() {
    const { current } = this.data
    let view = -1
    if (current === 1) view = 0
    else if (current === 2) view = 4
    if (view >= 0) this._activate(view)
  },

  _syncTabBar() {
    // 已无平台级 tabBar 配置(custom-tab-bar 由本页手动渲染), getTabBar 不可用;
    // 用 selectComponent 同步高亮
    const bar = this.selectComponent('#tabbar')
    if (bar) bar.setData({ selected: this.data.current })
  }
})
