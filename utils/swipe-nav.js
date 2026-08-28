/**
 * Tab 页面间左右滑动切换 + 切换动画
 * 用法: 页面 onLoad 中 swipeNav.attach(this, 'pages/schedule/schedule')
 * 页面需提供:
 *   - data.swipeX: 0            (根容器 style 绑定 transform 跟手平移)
 *   - data.swipeTrans: false    (回弹时过渡动画)
 *   - data.animClass: ''        (新页面滑入动画类)
 *   - data.showDetail: 可选     (弹窗打开时忽略手势)
 *   - onShow 中调用 swipeNav.playEnterAnim(this) 播放滑入动画
 * wxml 根容器绑定: bindtouchstart="onSwipeTouchStart" bindtouchmove="onSwipeTouchMove" bindtouchend="onSwipeTouchEnd"
 * 根容器 style: transform: translateX({{swipeX}}px); {{swipeTrans ? 'transition: transform .2s ease-out;' : ''}}
 * 根容器 class: container {{animClass}}
 */

const TABS = [
  'pages/schedule/schedule',
  'pages/exams/exams',
  'pages/eval/eval',
  'pages/grades/grades',
  'pages/settings/settings'
]

const THRESHOLD = 60   // px: 松手切换阈值
const FAST_PX = 30     // px: 快速滑动(500ms内)的最低位移
const SPEED_MS = 500   // 快速滑动判定时间窗
const ACTIVATE_PX = 12 // 手势激活所需横向位移
const DIR_RATIO = 1.2  // 横向/纵向主导比例

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
    this._swipe = { x: t.clientX, y: t.clientY, t: Date.now(), active: false, dx: 0 }
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
      } else {
        return
      }
    }
    // 边界: 最左页不能右滑, 最右页不能左滑
    if ((dx > 0 && idx === 0) || (dx < 0 && idx === TABS.length - 1)) return
    s.dx = dx
    this.setData({ swipeX: dx, swipeTrans: false })   // 跟手平移(即时, 无过渡)
  }

  page.onSwipeTouchEnd = function (e) {
    const s = this._swipe
    this._swipe = null
    if (!s || !s.active) return
    const dx = s.dx
    const dt = Date.now() - s.t
    const over = Math.abs(dx) > THRESHOLD || (dt < SPEED_MS && Math.abs(dx) > FAST_PX)
    this.setData({ swipeX: 0, swipeTrans: true })     // 回弹(带过渡)
    if (!over) return
    const next = dx < 0 ? idx + 1 : idx - 1
    if (next < 0 || next >= TABS.length) return
    // 记录滑入方向: 左滑(下一页) → 新页从右滑入(dir=1); 右滑 → 从左滑入(dir=-1)
    getApp().globalData.swipeDir = dx < 0 ? 1 : -1
    wx.switchTab({ url: '/' + TABS[next] })
  }
}

/**
 * 播放滑入动画: 在页面 onShow 中调用。
 * 仅当由滑动切换进入(globalData.swipeDir 已设置)时播放对应方向动画。
 */
function playEnterAnim(page) {
  const app = getApp()
  const dir = app.globalData.swipeDir || 0
  app.globalData.swipeDir = 0
  if (!dir) return
  page.setData({ animClass: '' })
  wx.nextTick(() => {
    page.setData({ animClass: dir > 0 ? 'anim-slide-in-right' : 'anim-slide-in-left' })
  })
}

module.exports = { attach, playEnterAnim, TABS }
