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

/** 星期几转中文 */
const WEEKDAY_NAMES = ['', '周一', '周二', '周三', '周四', '周五', '周六', '周日']

module.exports = {
  getCurrentWeek,
  formatDate,
  formatTime,
  weekToChinese,
  WEEKDAY_NAMES
}
