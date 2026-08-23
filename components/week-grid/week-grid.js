/**
 * 周课表网格组件
 *
 * 采用 NJUST 大节分组（与桌面端一致），课程按重叠比例显示在各节内
 *
 * 输入:
 *   courses: [{day, start, end, name, classroom, teacher, week_type, weeks, ...}]
 *   currentWeek: 当前周次 (number)
 *   firstWeekDate: 学期第一周周一日期 (string "YYYY-MM-DD")
 *   todayDay: 今天星期几 (number, 1-7)
 *
 * 输出:
 *   bind:coursetap → 点击课程事件
 */

const { WEEKDAY_NAMES, isWeekInRange, getDateLabel } = require('../../utils/date')

// NJUST 大节定义（与桌面端 static/js/schedule.js 保持一致）
const BIG_PERIODS = [
  { label: '第一大节', periods: [1, 2, 3], time: '08:00-10:25' },
  { label: '第二大节', periods: [4, 5], time: '10:40-12:15' },
  { label: '中午', periods: [14], time: '12:30-13:15' },
  { label: '第三大节', periods: [6, 7], time: '14:00-15:35' },
  { label: '第四大节', periods: [8, 9, 10], time: '15:50-18:15' },
  { label: '第五大节', periods: [11, 12, 13], time: '19:00-21:25' }
]

// 每小节基础高度（rpx）
const PERIOD_HEIGHT = 85

// 课程颜色方案
const COURSE_COLORS = [
  '#5B3CC4', '#3F51B5', '#009688', '#4CAF50',
  '#FF9800', '#E91E63', '#00BCD4', '#8BC34A',
  '#FF5722', '#673AB7', '#795548', '#607D8B'
]

/**
 * 按课程名取稳定颜色（简单 djb2 hash）
 */
function getCourseColor(name) {
  let hash = 5381
  for (let i = 0; i < name.length; i++) {
    hash = ((hash << 5) + hash) + name.charCodeAt(i)
  }
  return COURSE_COLORS[Math.abs(hash) % COURSE_COLORS.length]
}

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
      value: '',
      observer: '_buildLayout'
    },
    todayDay: {
      type: Number,
      value: 0
    }
  },

  data: {
    weekdays: WEEKDAY_NAMES.slice(1), // 周一~周日
    dateLabels: [],                    // 日期标签 ["9/1", "9/2", ...]
    bigPeriodRows: []                  // [{label, time, height, days: [{courses}]}]
  },

  lifetimes: {
    attached() {
      this._buildLayout()
    }
  },

  methods: {
    /** 构建大节分组网格 */
    _buildLayout() {
      const courses = this.properties.courses || []
      const week = this.properties.currentWeek
      const firstWeekDate = this.properties.firstWeekDate

      // 构建日期标签
      const dateLabels = []
      for (let d = 1; d <= 7; d++) {
        dateLabels.push(getDateLabel(firstWeekDate, week, d))
      }

      // 1. 过滤当前周课程
      const visible = courses.filter(c => {
        if (c.week_type === 1 && week % 2 === 0) return false
        if (c.week_type === 2 && week % 2 === 1) return false
        return isWeekInRange(week, c.weeks)
      })

      // 2. 构建大节行 × 7天 矩阵
      const bigPeriodRows = BIG_PERIODS.map(bp => {
        const rowHeight = bp.periods.length * PERIOD_HEIGHT
        const totalPeriods = bp.periods.length
        const firstPeriod = bp.periods[0]
        const lastPeriod = bp.periods[totalPeriods - 1]

        const days = []
        for (let d = 1; d <= 7; d++) {
          const dayCourses = []
          const seenKeys = new Set()

          for (const c of visible) {
            const day = c.day || c.day_of_week
            if (day !== d) continue

            const cs = c.start || c.start_period || 1
            const ce = c.end || c.end_period || 2

            // 检查课程与当前大节是否有重叠
            const overlapStart = Math.max(cs, firstPeriod)
            const overlapEnd = Math.min(ce, lastPeriod)
            if (overlapStart > overlapEnd) continue

            // 单元格内去重: 跨大节课程在 kbtable 每个大节格产生相同条目,
            // 防止同名同节次的重复块堆叠溢出(与后端去重双保险)
            const dedupeKey = `${c.name}|${cs}|${ce}|${c.teacher || ''}|${c.weeks || ''}`
            if (seenKeys.has(dedupeKey)) continue
            seenKeys.add(dedupeKey)

            // 按重叠小节数计算绝对高度（rpx），避免百分比依赖父级明确 height
            const overlapCount = overlapEnd - overlapStart + 1
            const courseHeight = overlapCount * PERIOD_HEIGHT

            // CSS class: type-odd（单周）/ type-even（双周）
            let cssClass = ''
            if (c.week_type === 1) cssClass = 'type-odd'
            else if (c.week_type === 2) cssClass = 'type-even'

            dayCourses.push({
              name: c.name,
              teacher: c.teacher || c.instructor || '',
              classroom: c.classroom || c.room || '',
              weeks: c.weeks || '1-18周',
              week_type: c.week_type || 0,
              day_of_week: day,
              day: day,
              start_period: cs,
              end_period: ce,
              start: cs,
              end: ce,
              credits: c.credits || '',
              type: c.type || c.course_type || '',
              _height: courseHeight,
              // 课程不从大节顶部开始时，先插入空白占位(与桌面端 renderTable 一致)
              // 例: 2-3节的课在"第一大节(1-3)"中显示在下方,不再误认为1-2节
              _offsetHeight: Math.max(0, (cs - firstPeriod) * PERIOD_HEIGHT),
              _color: getCourseColor(c.name),
              _cssClass: cssClass,
              // 只在第一个大节段显示完整文本，后续段只显示课程名
              _isFirst: cs >= firstPeriod && cs <= lastPeriod
            })
          }

          // 按起始节次排序
          dayCourses.sort((a, b) => a.start_period - b.start_period)
          days.push({ courses: dayCourses })
        }

        return {
          label: bp.label,
          time: bp.time,
          height: rowHeight,
          days
        }
      })

      this.setData({ bigPeriodRows, dateLabels })
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
