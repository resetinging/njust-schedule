/**
 * 周课表网格组件
 *
 * 输入:
 *   courses: [{day, start, end, name, classroom, teacher, week_type, weeks, ...}]
 *   currentWeek: 当前周次 (number)
 *
 * 输出:
 *   bind:coursetap → 点击课程事件
 */

const { WEEKDAY_NAMES } = require('../../utils/date')

// 课程颜色方案（循环使用）
const COURSE_COLORS = [
  '#5B3CC4', '#3F51B5', '#009688', '#4CAF50',
  '#FF9800', '#E91E63', '#00BCD4', '#8BC34A',
  '#FF5722', '#673AB7', '#795548', '#607D8B'
]

Component({
  properties: {
    courses: {
      type: Array,
      value: [],
      observer: '_buildLayout'
    },
    currentWeek: {
      type: Number,
      value: 1
    }
  },

  data: {
    weekdays: WEEKDAY_NAMES.slice(1), // 周一~周日
    periods: ['1', '2', '3', '4', '5', '6', '7', '8', '9', '10', '11', '12', '13'],
    weekSlots: []  // {period: {courseObj}} 二维映射
  },

  lifetimes: {
    attached() {
      this._buildLayout()
    }
  },

  methods: {
    /** 构建课程网格布局 */
    _buildLayout() {
      const courses = this.properties.courses || []
      const week = this.properties.currentWeek

      // 过滤当前周的课程
      const visible = courses.filter(c => {
        if (c.week_type === 1 && week % 2 === 0) return false
        if (c.week_type === 2 && week % 2 === 1) return false
        const parts = (c.weeks || '1-18').split('-')
        const start = parseInt(parts[0]) || 1
        const end = parseInt(parts[1] || parts[0]) || 18
        return week >= start && week <= end
      })

      // 构建 7天 × 13节 的插槽映射
      // weekSlots: [{ periodNum: { courseObj with _height, _color }, _day: N }]
      const weekSlots = []
      for (let day = 1; day <= 7; day++) {
        const slot = { _day: day }
        visible
          .filter(c => (c.day || c.day_of_week) === day)
          .forEach(c => {
            const start = c.start || c.start_period || 1
            const end = c.end || c.end_period || 2
            // 只在起始节次放课程块，并计算高度
            const height = (end - start + 1) * 62  // 每节 62rpx
            // 给课程分配颜色
            const colorIdx = courses.indexOf(c) % COURSE_COLORS.length
            slot[start] = { ...c, _height: height, _color: COURSE_COLORS[colorIdx] }
          })
        weekSlots.push(slot)
      }

      this.setData({ weekSlots })
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
