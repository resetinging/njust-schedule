/**
 * 空教室查询页 — 查教务"全校性教室课表"空闲教室
 * 筛选: 校区/星期/周次/起止时段(可跨官方大节, 时间段内全空闲才算); 需登录
 * - 本地缓存优先: 命中缓存立即渲染(秒开), 60s 内不重复请求, 过期后后台静默刷新
 * - 星期选"今天"、周次选"本周"时省略参数, 由后端按当天/第一周设置推算
 * - 结果按教学楼分组纯展示(不调用剪贴板)
 * - 选择器确认后自动查询(不做下拉刷新)
 */

const api = require('../../utils/api')
const storage = require('../../utils/storage')
const { groupRooms } = require('../../utils/room-group')

const WEEKDAY_LIST = ['今天', '星期一', '星期二', '星期三', '星期四', '星期五', '星期六', '星期日']
// 官方大节(key/展示名/起止节号); 起止时段各选一个, 发送节号范围
const SLOT_LIST = [
  { key: '1-3', label: '第1-3节', j1: 1, j2: 3 },
  { key: '4-5', label: '第4-5节', j1: 4, j2: 5 },
  { key: '6-7', label: '第6-7节', j1: 6, j2: 7 },
  { key: '8-10', label: '第8-10节', j1: 8, j2: 10 },
  { key: '11-13', label: '第11-13节', j1: 11, j2: 13 }
]
const CAMPUS_LIST = ['孝陵卫', '江阴']
const WEEK_LIST = (() => {
  const arr = ['本周']
  for (let i = 1; i <= 20; i++) arr.push('第' + i + '周')
  return arr
})()

// ---- 本地缓存: 按筛选条件缓存结果(15 分钟有效, 60 秒内免请求) ----
const CACHE_KEY = 'freeclass_cache'
const CACHE_MAX_ITEMS = 20
const NO_REQUEST_AGE = 60 * 1000     // 缓存 60s 内: 直接展示不再请求

function cacheKeyOf(params) {
  return [params.campus, params.weekday || 0, params.week || 0, params.jc1, params.jc2].join('|')
}

function readCache(key) {
  try {
    const box = storage.getCached(CACHE_KEY) || {}
    const item = (box.items || {})[key]
    return item && item.data ? { t: item.t || 0, data: item.data } : null
  } catch (e) {
    return null
  }
}

function writeCache(key, data) {
  try {
    const box = storage.getCached(CACHE_KEY) || {}
    if (!box.items) box.items = {}
    box.items[key] = { t: Date.now(), data }
    // 容量上限: 淘汰最旧
    const keys = Object.keys(box.items)
    if (keys.length > CACHE_MAX_ITEMS) {
      keys.sort((a, b) => (box.items[a].t || 0) - (box.items[b].t || 0))
      keys.slice(0, keys.length - CACHE_MAX_ITEMS).forEach(k => delete box.items[k])
    }
    storage.setCached(CACHE_KEY, box)
  } catch (e) {
    // 缓存写入失败忽略(不影响主流程)
  }
}

function fmtTime(ts) {
  const d = new Date(ts || Date.now())
  const p = n => (n < 10 ? '0' : '') + n
  return p(d.getHours()) + ':' + p(d.getMinutes())
}

Page({
  data: {
    loggedIn: true,
    loading: false,
    errorMsg: '',
    searched: false,       // 是否完成过查询(区分首屏空状态)
    cacheNote: '',         // 数据来源提示(缓存/更新中/离线)

    // 筛选状态(picker 索引)
    campusIndex: 0,
    weekdayIndex: 0,       // 0 = 今天
    weekIndex: 0,          // 0 = 本周
    startIndex: 2,         // 开始时段(默认 第6-7节)
    endIndex: 2,           // 结束时段

    campusList: CAMPUS_LIST,
    weekdayList: WEEKDAY_LIST,
    weekList: WEEK_LIST,
    slotList: SLOT_LIST,

    // 结果: 按教学楼分组
    result: null,          // {summary, count}
    groups: []
  },

  onLoad() {
    if (!storage.isLoggedIn()) {
      this.setData({ loggedIn: false })
      return
    }
    // 默认条件首查(有缓存则秒开)
    this.search()
  },

  onCampusChange(e) {
    this.setData({
      campusIndex: Number(e.detail.value),
      result: null, groups: []
    })
    this.search()
  },

  onWeekdayChange(e) {
    this.setData({ weekdayIndex: Number(e.detail.value) })
    this.search()
  },

  onWeekChange(e) {
    this.setData({ weekIndex: Number(e.detail.value) })
    this.search()
  },

  onStartChange(e) {
    this._updateRange(Number(e.detail.value), this.data.endIndex)
  },

  onEndChange(e) {
    this._updateRange(this.data.startIndex, Number(e.detail.value))
  },

  /** 起止时段: 若起 > 止则自动交换, 保证时间段有效 */
  _updateRange(start, end) {
    const patch = start > end ? { startIndex: end, endIndex: start } : { startIndex: start, endIndex: end }
    this.setData(patch)
    this.search()
  },

  /** 渲染结果(缓存或网络数据共用) */
  _applyResult(res) {
    this.setData({
      searched: true,
      errorMsg: '',
      groups: groupRooms(res.rooms || [], res.buildings),
      result: {
        summary: [res.campus, res.weekday_name, '第' + res.week + '周', res.time_text]
          .join(' · '),
        count: res.count || 0
      }
    })
  },

  /** 按当前筛选查询空闲教室(优先本地缓存, 后台静默刷新) */
  search() {
    if (!storage.isLoggedIn()) return Promise.resolve()
    const d = this.data
    const s = d.slotList[d.startIndex]
    const e = d.slotList[d.endIndex]
    const params = {
      campus: d.campusList[d.campusIndex],
      jc1: s.j1,
      jc2: e.j2
    }
    if (d.weekdayIndex > 0) params.weekday = d.weekdayIndex
    if (d.weekIndex > 0) params.week = d.weekIndex
    const key = cacheKeyOf(params)

    // ── 1) 命中本地缓存: 立即渲染, 秒开 ──
    const hit = readCache(key)
    let fromCache = false
    if (hit) {
      fromCache = true
      this._applyResult(hit.data)
      const age = Date.now() - hit.t
      if (age < NO_REQUEST_AGE) {
        // 缓存足够新: 不再请求
        this.setData({ loading: false, errorMsg: '', cacheNote: '' })
        return Promise.resolve()
      }
      this.setData({ loading: false, errorMsg: '', cacheNote: '缓存 ' + fmtTime(hit.t) + ' · 更新中…' })
    } else {
      this.setData({ loading: true, errorMsg: '', cacheNote: '' })
    }

    // ── 2) 请求最新数据(成功后覆盖缓存与界面) ──
    return api.getFreeClassrooms(params)
      .then(res => {
        if (!res || !res.success) {
          if (fromCache) {
            // 网络失败: 保留缓存展示, 标注离线
            this.setData({ loading: false, cacheNote: '网络不可用 · 显示缓存数据' })
            return
          }
          this.setData({
            loading: false,
            searched: true,
            groups: [],
            errorMsg: (res && res.message) || '查询失败，请稍后再试'
          })
          return
        }
        writeCache(key, res)
        this._applyResult(res)
        this.setData({ loading: false, cacheNote: '' })
      })
      .catch(() => {
        if (fromCache) {
          this.setData({ loading: false, cacheNote: '网络不可用 · 显示缓存数据' })
          return
        }
        this.setData({ loading: false, searched: true, errorMsg: '网络异常，请稍后再试' })
      })
  },

  /** 未登录: 返回"我的"页登录 */
  goLogin() {
    const pages = getCurrentPages()
    const main = pages.find(p => p && typeof p.onTabTap === 'function')
    wx.navigateBack({ delta: 1 })
    if (main) setTimeout(() => main.onTabTap(4), 300)
  }
})
