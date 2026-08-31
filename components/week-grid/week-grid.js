/**
 * 周课表网格组件 — 小节行布局(复刻目标 UI)
 * 14 个小节行 × 7 天, 课程块按开始小节绝对定位, 高度=跨节数
 */

const { WEEKDAY_NAMES, isWeekInRange } = require('../../utils/date')

// 每小节行高(rpx); 第14节显示"网课"
// 节次开始时间与桌面端 BIG_PERIODS 一致(南理工官方作息:
// 第四大节 15:50-18:15 → 8节15:50/9节16:40/10节17:30)
const ROW_H = 112
const PERIOD_COUNT = 14
const TIME_ROWS = [
  '08:00', '08:50', '09:40', '10:40', '11:30',
  '14:00', '14:50', '15:50', '16:40', '17:30',
  '19:00', '19:50', '20:40', '网课'
]

// 课程块统一橙黄色(参考目标 UI: 一周课程均为橙黄长条)
const COURSE_COLOR = { bg: '#FCF0D9', bar: '#F5D9A0', text: '#8A6116' }
// 表头简洁日期名(参考目标 UI: 一 二 三 四 五 六 日)
const GRID_WEEKDAYS = ['一', '二', '三', '四', '五', '六', '日']

Component({
  properties: {
    courses: {
      type: Array,
      value: [],
      observer: '_buildLayout'
    },
    currentWeek: {
      type: Number,
      value: 1,
      observer: '_buildLayout'
    },
    firstWeekDate: {
      type: String,
      value: ''
    },
    todayDay: {
      type: Number,
      value: 0
    }
  },

  data: {
    weekdays: GRID_WEEKDAYS, // 一~日(目标 UI 简洁表头)
    timeRows: [],
    dayCols: []
  },

  lifetimes: {
    attached() {
      this._buildLayout()
    }
  },

  methods: {
    /** 构建节次行 × 7 天 矩阵 */
    _buildLayout() {
      const courses = this.properties.courses || []
      const week = this.properties.currentWeek

      // 1. 过滤当前周课程(单双周 + 周次范围)
      const visible = courses.filter(c => {
        if (c.week_type === 1 && week % 2 === 0) return false
        if (c.week_type === 2 && week % 2 === 1) return false
        return isWeekInRange(week, c.weeks)
      })
      // 2. 时间列
      const timeRows = TIME_ROWS.map((t, i) => ({ index: i + 1, time: t }))

      // 3. 每天一列, 课程块绝对定位(按开始节/跨节数)
      const dayCols = []
      for (let d = 1; d <= 7; d++) {
        const seen = new Set()
        const blocks = []
        for (const c of visible) {
          const day = c.day || c.day_of_week
          if (day !== d) continue

          const cs = c.start || c.start_period || 1
          const ce = c.end || c.end_period || 2
          if (cs < 1 || cs > PERIOD_COUNT) continue
          if (ce < cs || ce > PERIOD_COUNT) continue

          // 单元格内去重(跨大节课程在 kbtable 各格产生相同条目)
          const key = `${c.name}|${cs}|${ce}|${c.teacher || ''}|${c.weeks || ''}`
          if (seen.has(key)) continue
          seen.add(key)

          blocks.push({
            name: c.name,
            teacher: c.teacher || c.instructor || '',
            classroom: c.classroom || c.room || '',
            weeks: c.weeks || '1-18周',
            week_type: c.week_type || 0,
            day: day,
            start: cs,
            end: ce,
            credits: c.credits || '',
            course_type: c.course_type || '',
            _top: (cs - 1) * ROW_H + 4,
            _height: (ce - cs + 1) * ROW_H - 8,
            _bg: COURSE_COLOR.bg,
            _bar: COURSE_COLOR.bar,
            _text: COURSE_COLOR.text,
            _range: cs === ce ? `${cs}节` : `${cs}-${ce}节`
          })
        }
        blocks.sort((a, b) => a._top - b._top)
        dayCols.push({ day: d, blocks })
      }

      this.setData({ timeRows, dayCols })
    },

    /** 点击课程块 */
    onCourseTap(e) {
      const course = e.currentTarget.dataset.course
      if (course) {
        this.triggerEvent('coursetap', course)
      }
    }
  }
})
