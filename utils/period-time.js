/**
 * 南理工作息时钟(与课表网格时间列一致)
 * 每小节 45 分钟、节间 5 分钟; 大节之间休息更长。
 * 下课时间 = 该节开始 +45 分钟
 * (参考桌面端口径: 第四大节 15:50-18:15, 即 8节15:50 / 9节16:40 / 10节17:30,
 *  每节 45 分钟 → 下课 18:15)。
 */

const PERIOD_STARTS = [
  '08:00', '08:50', '09:40', '10:40', '11:30',   // 上午 第1-5节
  '14:00', '14:50', '15:50', '16:40', '17:30',   // 下午 第6-10节
  '19:00', '19:50', '20:40'                       // 晚上 第11-13节
]
const CLASS_MIN = 45

function toMin(s) {
  const p = String(s || '0:00').split(':')
  return Number(p[0]) * 60 + Number(p[1])
}

function fmtMin(m) {
  const h = Math.floor(m / 60)
  const mm = m % 60
  return String(h).padStart(2, '0') + ':' + String(mm).padStart(2, '0')
}

/** 第 p 节上课时间(1-13; 越界钳制) */
function periodStart(p) {
  const i = Math.max(1, Math.min(p || 1, PERIOD_STARTS.length)) - 1
  return PERIOD_STARTS[i]
}

/** 第 p 节下课时间(上课 +45 分钟) */
function periodEnd(p) {
  return fmtMin(toMin(periodStart(p)) + CLASS_MIN)
}

/**
 * 课程起止节次 → 上下课钟点, 如 classClock(1,3) → '08:00-10:25'
 * (跨节时下课按最后小节的整段 45 分钟计)
 */
function classClock(startPeriod, endPeriod) {
  const s = periodStart(startPeriod)
  const e = periodEnd(Math.max(endPeriod || startPeriod, startPeriod))
  return s + '-' + e
}

module.exports = { PERIOD_STARTS, CLASS_MIN, periodStart, periodEnd, classClock }
