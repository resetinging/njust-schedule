/**
 * 日期工具 — 学期周次计算、日期格式化
 */

const config = require('./config')

/**
 * 当前日期(联调可覆盖)。
 * config.DEBUG_TODAY 非空时(如 '2026-09-30')把"今天"钉在该日期,
 * 但保留真实的时分秒 —— 便于查看某天的今日课程卡片, 又不影响"下一节"判断。
 */
function nowDate() {
  const real = new Date()
  const d = config.DEBUG_TODAY
  if (d) {
    const p = String(d).split('-').map(Number)
    if (p.length === 3 && p[0] && p[1] && p[2]) {
      return new Date(p[0], p[1] - 1, p[2], real.getHours(), real.getMinutes(), real.getSeconds())
    }
  }
  return real
}

/**
 * 格式化日期 YYYY-MM-DD
 */
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
  if (!endDateStr) return { text: '未知', cls: '' }
  const end = parseDateStr(endDateStr)
  if (!end) return { text: '未知', cls: '' }
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
  // 兼容 "2025-12-01" / "2025/12/01" / "2025-12-01 00:00:00" / "2025-12-01T00:00:00"
  const datePart = String(str).split(/[ T]/)[0]
  const parts = datePart.split(/[-/]/).map(Number)
  if (parts.length >= 3 && parts[0] > 1900 &&
      parts[1] >= 1 && parts[1] <= 12 &&
      parts[2] >= 1 && parts[2] <= 31) {
    return new Date(parts[0], parts[1] - 1, parts[2])
  }
  return null
}

/**
 * 默认第一周周一日期: 未设置校历时, 取当前日期所在周的周一。
 * 学期初使用即等于真实第一周, 学期中设置后会自动校正。
 * @returns {string} "YYYY-MM-DD"
 */
function getDefaultFirstWeekDate() {
  const now = new Date()
  const day = now.getDay() || 7            // 1=周一 ... 7=周日
  const monday = new Date(now.getFullYear(), now.getMonth(), now.getDate() - (day - 1))
  const y = monday.getFullYear()
  const m = String(monday.getMonth() + 1).padStart(2, '0')
  const d = String(monday.getDate()).padStart(2, '0')
  return `${y}-${m}-${d}`
}

/**
 * 根据学期第一周周一日期计算当前教学周
 * @param {string} firstWeekDate - "YYYY-MM-DD"
 * @returns {number} 当前周次 (1-based，限制在 1-20)
 */
function calcCurrentWeek(firstWeekDate) {
  const firstMonday = parseDateStr(firstWeekDate)
  if (!firstMonday || isNaN(firstMonday.getTime())) return 1
  const now = nowDate()
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
  const day = nowDate().getDay()
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
  if (!firstMonday || isNaN(firstMonday.getTime())) return ''
  const date = new Date(firstMonday)
  date.setDate(date.getDate() + (weekNum - 1) * 7 + (dayOfWeek - 1))
  return `${date.getMonth() + 1}.${date.getDate()}`
}

/**
 * ============================================================
 * 考试时间与状态（限定考试领域，不改变周次/评教函数语义）
 * ------------------------------------------------------------
 * - 考试时刻按 Asia/Shanghai（UTC+8，无夏令时）解释：用 UTC 数学构造，
 *   不依赖宿主系统时区，因此 Node 测试与真机结果一致。
 * - 缺日期 / 非法日期 / 缺时段 / 非法时段 → unknown（“时间待定”），绝不臆测 done。
 * - 只有开始没有结束 → 考前 upcoming；开考后 ongoing（结束待定）；当天结束仍未确认 → unknown，
 *   不把“未确认结束”的考试标成 done。
 * - 结束时间早于开始时间 → 视为跨午夜，结束落在次日。
 * ============================================================ */

const EXAM_TZ_OFFSET_MINUTES = 8 * 60

/** 上海墙钟 → 绝对毫秒（秒可选） */
function examTimestamp(year, month, day, hour, minute, second) {
  return Date.UTC(year, month - 1, day, hour || 0, minute || 0, second || 0) -
    EXAM_TZ_OFFSET_MINUTES * 60 * 1000
}

/** 严格解析考试日期 "YYYY-MM-DD" / "YYYY/MM/DD"（校验真实日历，拒绝 2026-02-30） */
function parseExamDate(str) {
  if (str === null || str === undefined) return null
  const text = String(str).trim()
  const m = text.match(/^(\d{4})[-/](\d{1,2})[-/](\d{1,2})$/)
  if (!m) return null
  const y = Number(m[1])
  const mo = Number(m[2])
  const d = Number(m[3])
  if (y < 1900 || y > 2999 || mo < 1 || mo > 12 || d < 1 || d > 31) return null
  const dt = new Date(Date.UTC(y, mo - 1, d))
  if (dt.getUTCFullYear() !== y || dt.getUTCMonth() !== mo - 1 || dt.getUTCDate() !== d) return null
  return { y, mo, d }
}

function isValidHm(hour, minute) {
  return Number.isInteger(hour) && hour >= 0 && hour <= 23 &&
    Number.isInteger(minute) && minute >= 0 && minute <= 59
}

/**
 * 解析考试时段，兼容教务实际返回：
 *   "15:50~17:50" / "19:00-21:00" / "15:50～17:50" / "15:50 — 17:50"
 *   单开始 "19:00"、只有开始 "19:00-"（结束待定）
 * 返回 { start:{h,mi}, end:{h,mi}|null } 或 null（不可判断）
 */
function parseExamTimeRange(str) {
  if (str === null || str === undefined) return null
  const text = String(str).trim()
  if (!text || text === '-' || text === '—' || text === '–') return null
  if (/待定|未知|未定|待确认/.test(text)) return null
  const m = text.match(/(\d{1,2})\s*[:：]\s*(\d{2})\s*(?:[-~～—–至]\s*(\d{1,2})\s*[:：]\s*(\d{2}))?/)
  if (!m) return null
  const sh = Number(m[1])
  const sm = Number(m[2])
  if (!isValidHm(sh, sm)) return null
  // 匹配后残留的非分隔符内容视为脏数据（如 "19:00-abc"），保守按不可判断处理
  const prefix = text.slice(0, m.index).trim()
  const suffix = text.slice(m.index + m[0].length).trim()
  if (prefix) return null
  if (suffix && !/^[-~～—–至]+$/.test(suffix)) return null
  let end = null
  if (m[3] !== undefined && m[4] !== undefined) {
    const eh = Number(m[3])
    const em = Number(m[4])
    if (!isValidHm(eh, em)) return null
    end = { h: eh, mi: em }
  }
  return { start: { h: sh, mi: sm }, end }
}

/**
 * 单场考试状态。
 * @param {{date?:string,time?:string}} exam
 * @param {number} [nowMs] 固定时钟（毫秒），缺省 Date.now()
 * @returns {{status:'upcoming'|'ongoing'|'done'|'unknown', hasDate:boolean, hasTime:boolean,
 *   startMs:number|null, endMs:number|null, crossMidnight:boolean, endUnconfirmed:boolean}}
 */
function getExamTiming(exam, nowMs) {
  const now = Number.isFinite(nowMs) ? nowMs : Date.now()
  const base = {
    status: 'unknown', hasDate: false, hasTime: false,
    startMs: null, endMs: null, crossMidnight: false, endUnconfirmed: false
  }
  const d = parseExamDate(exam && exam.date)
  if (!d) return base
  base.hasDate = true
  const range = parseExamTimeRange(exam && exam.time)
  if (!range) return base
  base.hasTime = true
  const startMs = examTimestamp(d.y, d.mo, d.d, range.start.h, range.start.mi, 0)
  base.startMs = startMs
  if (!range.end) {
    base.endUnconfirmed = true
    if (now < startMs) {
      base.status = 'upcoming'
      return base
    }
    // 当天终点 = 次日 00:00:00（不含）：在此之前视为进行中（结束待定）
    const dayEnd = examTimestamp(d.y, d.mo, d.d, 0, 0, 0) + 24 * 60 * 60 * 1000
    base.status = now < dayEnd ? 'ongoing' : 'unknown'
    return base
  }
  if (range.end.h === range.start.h && range.end.mi === range.start.mi) {
    // 开始==结束：时长不可判断（不臆造 24 小时跨午夜），保守按“结束待定”处理
    base.endUnconfirmed = true
    if (now < startMs) {
      base.status = 'upcoming'
      return base
    }
    const dayEnd = examTimestamp(d.y, d.mo, d.d, 0, 0, 0) + 24 * 60 * 60 * 1000
    base.status = now < dayEnd ? 'ongoing' : 'unknown'
    return base
  }
  let endMs = examTimestamp(d.y, d.mo, d.d, range.end.h, range.end.mi, 0)
  if (endMs < startMs) {
    // 仅“结束早于开始”才视为跨午夜；相等已在上面保守处理
    endMs += 24 * 60 * 60 * 1000
    base.crossMidnight = true
  }
  base.endMs = endMs
  if (now < startMs) base.status = 'upcoming'
  else if (now < endMs) base.status = 'ongoing'
  else base.status = 'done'
  return base
}

/** 可读倒计时（<1 小时用分钟；不出现负小时/0h/NaN） */
function formatExamCountdown(timing, nowMs) {
  const now = Number.isFinite(nowMs) ? nowMs : Date.now()
  if (!timing || timing.status === 'unknown') {
    return { bigNum: '--', bigLabel: '时间待定', statusText: '时间待定', cls: 'unknown' }
  }
  if (timing.status === 'done') {
    return { bigNum: '✓', bigLabel: '已结束', statusText: '已结束', cls: 'done' }
  }
  if (timing.status === 'ongoing') {
    return {
      bigNum: '进行中',
      bigLabel: timing.endUnconfirmed ? '结束待定' : '考试中',
      statusText: timing.endUnconfirmed ? '已开始（结束待定）' : '进行中',
      cls: 'ongoing'
    }
  }
  const diff = timing.startMs - now
  const mins = Math.max(1, Math.ceil(diff / 60000))
  if (diff < 60 * 60 * 1000) {
    return { bigNum: String(mins), bigLabel: '分钟后开始', statusText: '还有 ' + mins + ' 分钟', cls: 'urgent' }
  }
  const hours = Math.floor(diff / (60 * 60 * 1000))
  if (hours < 24) {
    return { bigNum: String(hours), bigLabel: '小时后开始', statusText: '还有 ' + hours + ' 小时', cls: 'urgent' }
  }
  const days = Math.floor(diff / (24 * 60 * 60 * 1000))
  const remainHours = Math.floor((diff % (24 * 60 * 60 * 1000)) / (60 * 60 * 1000))
  if (days <= 3) {
    return { bigNum: String(days), bigLabel: '天后开始', statusText: '还有 ' + days + '天' + remainHours + '小时', cls: 'urgent' }
  }
  if (days <= 7) {
    return { bigNum: String(days), bigLabel: '天后开始', statusText: '还有 ' + days + '天' + remainHours + '小时', cls: 'warning' }
  }
  return { bigNum: String(days), bigLabel: '天后开始', statusText: '还有 ' + days + ' 天', cls: '' }
}

/**
 * 同日分组的整体状态：
 *  - 有任何 ongoing → ongoing（优先展示进行中，不可折叠）
 *  - 全部 done（且至少一场）→ done（允许折叠）
 *  - 否则取最近一场 upcoming 的文案
 *  - 其余（含无法判断时间的记录、或只有 unknown+done 混合）→ unknown
 */
function getExamGroupStatus(timings, nowMs) {
  const list = Array.isArray(timings) ? timings : []
  if (!list.length) return { status: 'unknown', text: '时间待定' }
  const ongoing = list.find(t => t.status === 'ongoing')
  if (ongoing) {
    const cd = formatExamCountdown(ongoing, nowMs)
    return { status: 'ongoing', text: cd.statusText }
  }
  if (list.every(t => t.status === 'done')) return { status: 'done', text: '已结束' }
  const upcoming = list.filter(t => t.status === 'upcoming').sort((a, b) => a.startMs - b.startMs)[0]
  if (upcoming) {
    const cd = formatExamCountdown(upcoming, nowMs)
    return { status: 'upcoming', text: cd.statusText }
  }
  return { status: 'unknown', text: '时间待定' }
}

module.exports = {
  nowDate,
  calcCurrentWeek,
  calcTodayDay,
  getDateLabel,
  getDefaultFirstWeekDate,
  formatDate,
  formatTime,
  weekToChinese,
  isWeekInRange,
  getWeekBounds,
  timeUntil,
  timeUntilDeadline,
  parseDateStr,
  WEEKDAY_NAMES,
  examTimestamp,
  parseExamDate,
  parseExamTimeRange,
  getExamTiming,
  formatExamCountdown,
  getExamGroupStatus
}
