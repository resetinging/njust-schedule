/**
 * 周课表网格组件 — 小节行布局(复刻目标 UI)
 * 14 个小节行 × 7 天, 课程块按开始小节绝对定位, 高度=跨节数
 */

const { WEEKDAY_NAMES, isWeekInRange } = require('../../utils/date')
const { courseColors } = require('../../utils/course-color')
const { PERIOD_STARTS, periodStart, periodEnd } = require('../../utils/period-time')

// 每小节行高(rpx); 第14节显示"网课"
// 节次开始时间与桌面端 BIG_PERIODS 一致(学校官方作息:
// 第四大节 15:50-18:15 → 8节15:50/9节16:40/10节17:30; 每节45分钟)
const ROW_H = 80
const PERIOD_COUNT = 14

// 课程块配色: 按课程名分配(不同课不同色, 同一课跨周/多时段同色)
const COURSE_COLOR = { bg: 'var(--c1-bg)', bar: 'var(--c1-bar)', text: 'var(--c1-fg)' }   // 兜底
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
    },
    actualWeek: {
      type: Number,
      value: 0        // 实际教学周: 只有显示的是本周时才高亮"今天"
    }
  },

  data: {
    // 表头: 星期 + 本周日期(今天高亮)
    weekdays: GRID_WEEKDAYS.map(n => ({ name: n, date: '', today: false })),
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
      this._buildHeader(week)

      // 1. 过滤当前周课程(单双周 + 周次范围)
      const visible = courses.filter(c => {
        if (c.week_type === 1 && week % 2 === 0) return false
        if (c.week_type === 2 && week % 2 === 1) return false
        return isWeekInRange(week, c.weeks)
      })
      // 2. 时间列: 每节显示 节号 + 上课 + 下课(45分钟/节; 样式 xx.xx)
      const timeRows = []
      for (let i = 0; i < PERIOD_COUNT; i++) {
        const idx = i + 1
        if (idx <= PERIOD_STARTS.length) {
          timeRows.push({ index: idx, time: periodStart(idx), end: periodEnd(idx), label: '' })
        } else {
          timeRows.push({ index: idx, time: '', end: '', label: '网课' })  // 第14行
        }
      }

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

          // 课程配色(优先外部装饰字段, 保证与列表视图一致)
          const pal = (c._bg && c._bar && c._text)
            ? { bg: c._bg, bar: c._bar, text: c._text }
            : courseColors(c.name)

          // 上下课钟点(仅显示上课时间 xx.xx)
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
            _bg: pal.bg,
            _bar: pal.bar,
            _text: pal.text,
            _clockStart: periodStart(cs),
            _range: cs === ce ? `${cs}节` : `${cs}-${ce}节`,
            _cid: c._cid || '',
            _custom: !!c._custom,
            _audit: !!c._audit,
            _favoriteId: c._favoriteId || '',
            _hasConflict: !!c._hasConflict,
            _conflictWith: c._conflictWith || []
          })
        }
        blocks.sort((a, b) => a._top - b._top)
        // 翻到别的周不该有"今天"高亮
        const isThisWeek = !this.properties.actualWeek || (week || 0) === this.properties.actualWeek
        dayCols.push({ day: d, blocks, today: isThisWeek && d === (this.properties.todayDay || 0) })
      }

      this.setData({ timeRows, dayCols })
    },

    /** 表头: 星期 + 本周日期(由 firstWeekDate 推算, 今天高亮) */
    _buildHeader(week) {
      const fwd = (this.properties.firstWeekDate || '').trim()
      // 同上: 只有当前显示的周 == 实际教学周时才高亮
      const isThisWeek = !this.properties.actualWeek || (week || 0) === this.properties.actualWeek
      const today = isThisWeek ? (this.properties.todayDay || 0) : 0
      const m = /^(\d{4})-(\d{1,2})-(\d{1,2})$/.exec(fwd)
      const baseMs = m
        ? new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3])).getTime()
        : 0
      const heads = []
      for (let d = 1; d <= 7; d++) {
        let date = ''
        if (baseMs) {
          const dt = new Date(baseMs + ((((week || 1) - 1) * 7) + (d - 1)) * 86400000)
          date = String(dt.getDate())
        }
        heads.push({ name: GRID_WEEKDAYS[d - 1], date, today: d === today })
      }
      this.setData({ weekdays: heads })
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
