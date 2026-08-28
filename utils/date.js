/**
 * 日期工具 — 学期周次计算、日期格式化
 */

/**
 * 根据学期起始日期计算当前是第几周
 * @param {string} semesterStart - 学期起始日期 "YYYY-MM-DD"
 * @returns {number} 当前周次 (1-based)
 */
function getCurrentWeek(semesterStart) {
  if (!semesterStart) return 1
  const start = new Date(semesterStart)
  const now = new Date()
  const diff = now - start
  const week = Math.floor(diff / (7 * 24 * 60 * 60 * 1000)) + 1
  return Math.max(1, Math.min(week, 20))
}

/** 格式化日期 YYYY-MM-DD */
function formatDate(d) {
  const date = d || new Date()
  const y = date.getFullYear()
  const m = String(date.getMonth() + 1).padStart(2, '0')
  const day = String(date.getDate()).padStart(2, '0')
  return `${y}-${m}-${day}`
}

/** 格式化时间 HH:mm */
function formatTime(d) {
  const date = d || new Date()
  const h = String(date.getHours()).padStart(2, '0')
  const m = String(date.getMinutes()).padStart(2, '0')
  return `${h}:${m}`
}

/** 周次转中文 */
function weekToChinese(w) {
  const map = ['零', '一', '二', '三', '四', '五', '六', '七', '八', '九',
    '十', '十一', '十二', '十三', '十四', '十五', '十六', '十七', '十八', '十九', '二十']
  return map[w] || `第${w}周`
}

/**
 * 判断给定周次是否在 weeks 字符串范围内
 * 支持三种格式:
 *   "1-16"          → 连续区间
 *   "1-8,10-17"     → 分段区间
 *   "1,3,5,7,9"     → 离散周次
 * @param {number} week - 待判断的周次
 * @param {string} weeksStr - 周次描述字符串
 * @returns {boolean}
 */
function isWeekInRange(week, weeksStr) {
  const weeks = weeksStr || '1-18'
  const segments = weeks.split(',')
  for (const seg of segments) {
    const trimmed = seg.trim()
    if (trimmed.includes('-')) {
      const parts = trimmed.split('-')
      const start = parseInt(parts[0]) || 1
      const end = parseInt(parts[1]) || 18
      if (week >= start && week <= end) return true
    } else {
      if (parseInt(trimmed) === week) return true
    }
  }
  return false
}

/**
 * 从 weeks 字符串中提取所有区间的最大、最小时段
 * 用于估算当前学期所处的周次
 * @param {string} weeksStr
 * @returns {{ min: number, max: number }}
 */
function getWeekBounds(weeksStr) {
  const weeks = weeksStr || '1-18'
  let min = Infinity
  let max = -Infinity
  const segments = weeks.split(',')
  for (const seg of segments) {
    const trimmed = seg.trim()
    if (trimmed.includes('-')) {
      const parts = trimmed.split('-')
      const s = parseInt(parts[0]) || 1
      const e = parseInt(parts[1]) || 18
      if (s < min) min = s
      if (e > max) max = e
    } else {
      const n = parseInt(trimmed)
      if (n < min) min = n
      if (n > max) max = n
    }
  }
  return { min: min === Infinity ? 1 : min, max: max === -Infinity ? 18 : max }
}

/** 星期几转中文 */
const WEEKDAY_NAMES = ['', '周一', '周二', '周三', '周四', '周五', '周六', '周日']

/**
 * 计算距目标日期的可读时间差
 * 参考桌面端 static/js/exams.js timeUntil()
 * @param {string} dateStr - 目标日期 "YYYY-MM-DD"
 * @param {string} timeStr - 可选时间段 "HH:mm~HH:mm"，取开始时间
 * @returns {{ text: string, cls: string }} cls: 'urgent' | 'warning' | 'done' | ''
 */
function timeUntil(dateStr, timeStr) {
  if (!dateStr) return { text: '', cls: '' }
  const parts = dateStr.split('-')
  if (parts.length !== 3) return { text: '', cls: '' }
  const target = new Date(parseInt(parts[0]), parseInt(parts[1]) - 1, parseInt(parts[2]))

  // 如果有时间段，取开始时间
  if (timeStr) {
    const m = timeStr.match(/(\d{1,2}):(\d{2})/)
    if (m) {
      target.setHours(parseInt(m[1]), parseInt(m[2]), 0, 0)
    }
  }

  const now = new Date()
  const diffMs = target - now
  const totalHours = diffMs / (1000 * 60 * 60)
  const totalDays = Math.floor(totalHours / 24)
  const remainHours = Math.floor(totalHours % 24)

  if (totalHours < 0) {
    const pastHours = Math.abs(totalHours)
    if (pastHours < 1) return { text: '刚刚结束', cls: 'done' }
    if (pastHours < 24) return { text: Math.floor(pastHours) + '小时前', cls: 'done' }
    return { text: Math.floor(pastHours / 24) + '天前', cls: 'done' }
  }
  if (totalHours < 1) {
    const mins = Math.floor(totalHours * 60)
    return { text: '还有 ' + mins + ' 分钟', cls: 'urgent' }
  }
  if (totalHours < 24) {
    return { text: '还有 ' + Math.floor(totalHours) + ' 小时', cls: 'urgent' }
  }
  if (totalDays <= 3) {
    return { text: '还有 ' + totalDays + '天' + remainHours + '小时', cls: 'urgent' }
  }
  if (totalDays <= 7) {
    return { text: '还有 ' + totalDays + '天' + remainHours + '小时', cls: 'warning' }
  }
  return { text: '还有 ' + totalDays + ' 天', cls: '' }
}

/**
 * 计算距截止日期的可读时间（用于评教）
 * 参考桌面端 static/js/evaluations.js timeUntilDeadline()
 */
function timeUntilDeadline(endDateStr) {
  if (!endDateStr) return { text: '', cls: '' }
  const end = parseDateStr(endDateStr)
  if (!end) return { text: '', cls: '' }
  end.setHours(23, 59, 59, 0)
  const now = new Date()
  const diffMs = end - now
  const totalHours = diffMs / (1000 * 60 * 60)
  const totalDays = Math.floor(totalHours / 24)

  if (totalHours < 0) return { text: '已截止', cls: 'done' }
  if (totalHours < 24) return { text: Math.floor(totalHours) + '小时后截止', cls: 'urgent' }
  if (totalDays <= 3) return { text: '还有 ' + totalDays + ' 天截止', cls: 'urgent' }
  if (totalDays <= 7) return { text: '还有 ' + totalDays + ' 天', cls: 'warning' }
  return { text: '还有 ' + totalDays + ' 天', cls: '' }
}

/** 解析 "YYYY-MM-DD" / "YYYY/MM/DD" → Date
 *  （用年/月/日构造本地时间, 避免 "YYYY/MM/DDTHH:mm" 等非标准
 *    字符串被内核判为 Invalid Date 导致 NaN 显示）
 */
function parseDateStr(str) {
  if (!str) return null
  const parts = String(str).split(/[-/]/).map(Number)
  if (parts.length >= 3 && parts[0] > 1900 &&
      parts[1] >= 1 && parts[1] <= 12 &&
      parts[2] >= 1 && parts[2] <= 31) {
    return new Date(parts[0], parts[1] - 1, parts[2])
  }
  return null
}

/**
 * 根据学期第一周周一日期计算当前教学周
 * @param {string} firstWeekDate - "YYYY-MM-DD"
 * @returns {number} 当前周次 (1-based，限制在 1-20)
 */
function calcCurrentWeek(firstWeekDate) {
  const firstMonday = parseDateStr(firstWeekDate)
  if (!firstMonday) return 1
  const now = new Date()
  const diffMs = now.getTime() - firstMonday.getTime()
  const diffDays = Math.floor(diffMs / (1000 * 60 * 60 * 24))
  const week = Math.floor(diffDays / 7) + 1
  return Math.max(1, Math.min(week, 20))
}

/**
 * 计算今天是星期几
 * @returns {number} 1=周一 ... 7=周日
 */
function calcTodayDay() {
  const day = new Date().getDay()
  return day === 0 ? 7 : day
}

/**
 * 计算某教学周某天的日期
 * @param {string} firstWeekDate - 第一周周一日期 "YYYY-MM-DD"
 * @param {number} weekNum - 教学周次
 * @param {number} dayOfWeek - 1=周一 ... 7=周日
 * @returns {string} "M/D" 格式日期
 */
function getDateLabel(firstWeekDate, weekNum, dayOfWeek) {
  const firstMonday = parseDateStr(firstWeekDate)
  if (!firstMonday) return ''
  const date = new Date(firstMonday)
  date.setDate(date.getDate() + (weekNum - 1) * 7 + (dayOfWeek - 1))
  return `${date.getMonth() + 1}/${date.getDate()}`
}

module.exports = {
  getCurrentWeek,
  calcCurrentWeek,
  calcTodayDay,
  getDateLabel,
  formatDate,
  formatTime,
  weekToChinese,
  isWeekInRange,
  getWeekBounds,
  timeUntil,
  timeUntilDeadline,
  parseDateStr,
  WEEKDAY_NAMES
}
