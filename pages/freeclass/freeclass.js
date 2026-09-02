/**
 * 空教室查询页 — 查教务"全校性教室课表"空闲教室
 * 筛选: 校区/星期/时段(官方大节)/周次/教学楼; 需登录
 * - 星期选"今天"、周次选"本周"时省略参数, 由后端按当天/第一周设置推算
 * - 教学楼选项来自教务联动接口, 随每次查询响应返回(首次默认"全部")
 * - 选择器确认后自动查询(30s 服务端缓存兜底); 下拉可刷新
 * - 点击教室名复制, 便于分享
 */

const api = require('../../utils/api')
const storage = require('../../utils/storage')

const WEEKDAY_LIST = ['今天', '星期一', '星期二', '星期三', '星期四', '星期五', '星期六', '星期日']
const SLOT_LIST = [
  { key: '1-3', label: '第1-3节' },
  { key: '4-5', label: '第4-5节' },
  { key: '6-7', label: '第6-7节' },
  { key: '8-10', label: '第8-10节' },
  { key: '11-13', label: '第11-13节' }
]
const CAMPUS_LIST = ['孝陵卫', '江阴']
const WEEK_LIST = (() => {
  const arr = ['本周']
  for (let i = 1; i <= 20; i++) arr.push('第' + i + '周')
  return arr
})()

Page({
  data: {
    loggedIn: true,
    loading: false,
    errorMsg: '',
    searched: false,       // 是否完成过查询(区分首屏空状态)

    // 筛选状态(picker 索引)
    campusIndex: 0,
    weekdayIndex: 0,       // 0 = 今天
    slotIndex: 2,          // 默认 第6-7节
    weekIndex: 0,          // 0 = 本周
    buildingIndex: 0,      // 0 = 全部

    campusList: CAMPUS_LIST,
    weekdayList: WEEKDAY_LIST,
    slotList: SLOT_LIST,
    weekList: WEEK_LIST,
    buildingList: ['全部'],

    // 结果
    result: null,          // {summary, count}
    rooms: []
  },

  onLoad() {
    if (!storage.isLoggedIn()) {
      this.setData({ loggedIn: false })
      return
    }
    // 默认条件首查(顺带带回教学楼选项)
    this.search()
  },

  onPullDownRefresh() {
    this.search().finally(() => wx.stopPullDownRefresh())
  },

  onCampusChange(e) {
    this.setData({
      campusIndex: Number(e.detail.value),
      buildingIndex: 0,            // 换校区清空教学楼
      result: null, rooms: []
    })
    this.search()
  },

  onWeekdayChange(e) {
    this.setData({ weekdayIndex: Number(e.detail.value) })
    this.search()
  },

  onSlotChange(e) {
    this.setData({ slotIndex: Number(e.detail.value) })
    this.search()
  },

  onWeekChange(e) {
    this.setData({ weekIndex: Number(e.detail.value) })
    this.search()
  },

  onBuildingChange(e) {
    this.setData({ buildingIndex: Number(e.detail.value) })
    this.search()
  },

  /** 按当前筛选查询空闲教室 */
  search() {
    if (!storage.isLoggedIn()) return Promise.resolve()
    const d = this.data
    const params = {
      campus: d.campusList[d.campusIndex],
      slot: d.slotList[d.slotIndex].key
    }
    if (d.weekdayIndex > 0) params.weekday = d.weekdayIndex
    if (d.weekIndex > 0) params.week = d.weekIndex
    if (d.buildingIndex > 0) params.building = d.buildingList[d.buildingIndex]

    this.setData({ loading: true, errorMsg: '' })
    return api.getFreeClassrooms(params)
      .then(res => {
        if (!res || !res.success) {
          this.setData({
            loading: false,
            searched: true,
            rooms: [],
            errorMsg: (res && res.message) || '查询失败，请稍后再试'
          })
          return
        }
        // 教学楼选项随响应刷新(去重, 保留当前选中)
        const seen = {}
        const blds = ['全部']
        ;(res.buildings || []).forEach(b => {
          const n = b && b.name
          if (n && !seen[n]) { seen[n] = true; blds.push(n) }
        })
        let bi = 0
        if (params.building) {
          const i = blds.indexOf(params.building)
          bi = i > 0 ? i : 0
        }
        this.setData({
          loading: false,
          searched: true,
          errorMsg: '',
          rooms: res.rooms || [],
          buildingList: blds,
          buildingIndex: bi,
          result: {
            summary: [res.campus, res.weekday_name, '第' + res.week + '周', res.slot_name]
              .concat(res.building ? [res.building] : []).join(' · '),
            count: res.count || 0
          }
        })
      })
      .catch(() => {
        this.setData({ loading: false, searched: true, errorMsg: '网络异常，请稍后再试' })
      })
  },

  /** 点击教室名复制 */
  onCopyRoom(e) {
    const room = e.currentTarget.dataset.room
    if (!room) return
    wx.setClipboardData({
      data: room,
      success: () => wx.showToast({ title: '已复制 ' + room, icon: 'none' })
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
