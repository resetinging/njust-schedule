/**
 * Tab 页面间左右滑动切换 + 切换动画
 * 用法: 页面 onLoad 中 swipeNav.attach(this, 'pages/schedule/schedule')
 * 页面需提供:
 *   - data.swipeX: 0            (根容器 style 绑定 transform 跟手平移)
 *   - data.swipeTrans: false    (回弹/滑出时过渡动画)
 *   - data.animClass: ''        (新页面滑入动画类)
 *   - data.showDetail: 可选     (弹窗打开时忽略手势)
 *   - onShow 中调用 swipeNav.playEnterAnim(this) 播放滑入动画
 * wxml 根容器绑定: bindtouchstart="onSwipeTouchStart" bindtouchmove="onSwipeTouchMove" bindtouchend="onSwipeTouchEnd" bindtouchcancel="onSwipeTouchCancel"
 * 根容器 style:  transform: translateX({{swipeX}}px);
 * 根容器 class:  container {{animClass}} {{swipeTrans ? 'swipe-rebound' : ''}}
 */

const TABS = [
  'pages/schedule/schedule',
  'pages/exams/exams',
  'pages/eval/eval',
  'pages/grades/grades',
  'pages/settings/settings'
]

const THRESHOLD = 40    // px: 松手切换阈值
const FAST_PX = 20      // px: 快速滑动(400ms内)的最低位移
const SPEED_MS = 400    // 快速滑动判定时间窗
const ACTIVATE_PX = 8   // 手势激活所需横向位移
const DIR_RATIO = 1.2   // 横向/纵向主导比例
const SET_THROTTLE = 16 // ms: touchmove setData 节流(≈60fps)
const ANIM_DELAY = 30   // ms: 进入动画延迟(等页面首帧稳定, 避免闪现)
const ANIM_CLEAR = 300  // ms: 动画播完清除类

/**
 * 绑定滑动切换手势到页面
 * @param {object} page Page 实例
 * @param {string} currentTab 当前页路径 (TABS 之一)
 */
function attach(page, currentTab) {
  const idx = TABS.indexOf(currentTab)

  page.onSwipeTouchStart = function (e) {
    // 页面可自定义 _swipeDisabled() 控制禁用; 默认弹窗打开时禁用
    const disabled = typeof this._swipeDisabled === 'function'
      ? this._swipeDisabled()
      : !!this.data.showDetail
    if (disabled) return
    const t = e.touches && e.touches[0]
    if (!t) return
    this._swipe = { x: t.clientX, y: t.clientY, t: Date.now(), active: false, dx: 0, lastSet: 0 }
  }

  page.onSwipeTouchMove = function (e) {
    const s = this._swipe
    if (!s || idx < 0) return
    const t = e.touches && e.touches[0]
    if (!t) return
    const dx = t.clientX - s.x
    const dy = t.clientY - s.y

    if (!s.active) {
      // 纵向位移主导 → 放弃(页面滚动)
      if (Math.abs(dy) > ACTIVATE_PX && Math.abs(dy) > Math.abs(dx) * DIR_RATIO) {
        this._swipe = null
        return
      }
      if (Math.abs(dx) > ACTIVATE_PX && Math.abs(dx) > Math.abs(dy) * DIR_RATIO) {
        s.active = true
        // 记录横滑激活时间: 用于下拉刷新防误触(横滑后短暂忽略下拉)
        this._lastSwipeActiveT = Date.now()
      } else {
        return
      }
    }
    // 边界: 最左页不能右滑, 最右页不能左滑
    if ((dx > 0 && idx === 0) || (dx < 0 && idx === TABS.length - 1)) return
    s.dx = dx
    // 节流: 16ms 且位移变化 ≥2px 才 setData, 避免高频渲染卡顿
    const now = Date.now()
    if (now - s.lastSet < SET_THROTTLE || Math.abs(dx - (this.data.swipeX || 0)) < 2) return
    s.lastSet = now
    this.setData({ swipeX: dx, swipeTrans: false })   // 跟手平移(即时, 无过渡)
  }

  page.onSwipeTouchEnd = function (e) {
    const s = this._swipe
    this._swipe = null
    if (!s || !s.active) return
    const dx = s.dx
    const dt = Date.now() - s.t
    const over = Math.abs(dx) > THRESHOLD || (dt < SPEED_MS && Math.abs(dx) > FAST_PX)
    const next = dx < 0 ? idx + 1 : idx - 1
    if (!over || next < 0 || next >= TABS.length) {
      // 未超阈值或边界: 平滑回弹
      this.setData({ swipeX: 0, swipeTrans: true })
      return
    }
    // 立即切换: 跟手已提供拖拽反馈, 新页滑入动画负责过渡;
    // 不做"滑出延迟后切换", 避免旧页滑出后空白闪现(目标页首次创建慢时更明显)
    this.setData({ swipeX: 0, swipeTrans: false })   // 复位防残留
    getApp().globalData.swipeDir = dx < 0 ? 1 : -1   // 左滑(下一页) → 新页从右滑入
    wx.switchTab({ url: '/' + TABS[next] })
  }

  // 手势被系统中断(来电/下拉/滚动接管): 立即复位, 防止页面偏出屏幕
  page.onSwipeTouchCancel = function () {
    if (this._swipe && this._swipe.active) {
      this.setData({ swipeX: 0, swipeTrans: true })
    }
    this._swipe = null
  }
}

/**
 * 判断最近是否刚进行过横滑切换手势(用于下拉刷新防误触:
 * 横滑激活后 ms 毫秒内的下拉视为误触, 应忽略)
 * @param {object} page Page 实例
 * @param {number} ms 时间窗(默认 600)
 */
function wasSwiping(page, ms) {
  const win = ms || 600
  return !!(page._lastSwipeActiveT && Date.now() - page._lastSwipeActiveT < win)
}

/**
 * 播放滑入动画: 在页面 onShow 中调用。
 * 仅当由滑动切换进入(globalData.swipeDir 已设置)时播放对应方向动画。
 * 同时强制复位 swipeX/animClass, 防止上次残留的 transform 导致页面偏出屏幕。
 */
function playEnterAnim(page) {
  const app = getApp()
  const dir = app.globalData.swipeDir || 0
  app.globalData.swipeDir = 0
  page.setData({ swipeX: 0, swipeTrans: false, animClass: '' })
  if (!dir) return
  // 等页面首帧渲染稳定后再播动画, 避免与页面数据渲染竞态导致闪现
  setTimeout(() => {
    page.setData({ animClass: dir > 0 ? 'anim-slide-in-right' : 'anim-slide-in-left' })
    // 动画播完自动清除 class, 避免残留类影响后续手势样式
    setTimeout(() => {
      page.setData({ animClass: '' })
    }, ANIM_CLEAR)
  }, ANIM_DELAY)
}

module.exports = { attach, playEnterAnim, wasSwiping, TABS }
