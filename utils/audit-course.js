/**
 * 蹭课课程冲突与收藏工具。
 */
const { isWeekInRange } = require('./date')

const DAY_NAMES = ['', '周一', '周二', '周三', '周四', '周五', '周六', '周日']

function numberValue(value) {
  const parsed = Number(value || 0)
  return Number.isFinite(parsed) ? parsed : 0
}

function weekTypeAllows(week, weekType) {
  const type = numberValue(weekType)
  if (type === 1 && week % 2 === 0) return false
  if (type === 2 && week % 2 === 1) return false
  return true
}

function weeksOverlap(aWeeks, aType, bWeeks, bType) {
  for (let week = 1; week <= 20; week += 1) {
    if (!weekTypeAllows(week, aType)) continue
    if (!weekTypeAllows(week, bType)) continue
    if (!isWeekInRange(week, aWeeks || '1-18')) continue
    if (!isWeekInRange(week, bWeeks || '1-18')) continue
    return true
  }
  return false
}

function periodsOverlap(aStart, aEnd, bStart, bEnd) {
  const a1 = numberValue(aStart)
  const a2 = numberValue(aEnd) || a1
  const b1 = numberValue(bStart)
  const b2 = numberValue(bEnd) || b1
  if (!a1 || !a2 || !b1 || !b2) return false
  return a1 <= b2 && b1 <= a2
}

function scheduleConflict(auditSchedule, ownCourse) {
  const auditDay = numberValue(
    auditSchedule.day || auditSchedule.day_of_week)
  const ownDay = numberValue(ownCourse.day || ownCourse.day_of_week)
  if (!auditDay || auditDay !== ownDay) return false
  if (!periodsOverlap(
    auditSchedule.start || auditSchedule.start_period,
    auditSchedule.end || auditSchedule.end_period,
    ownCourse.start || ownCourse.start_period,
    ownCourse.end || ownCourse.end_period
  )) return false
  return weeksOverlap(
    auditSchedule.weeks,
    auditSchedule.week_type || 0,
    ownCourse.weeks,
    ownCourse.week_type || 0
  )
}

function conflictForSchedule(auditSchedule, ownCourses) {
  const conflicts = []
  for (const own of (ownCourses || [])) {
    if (!scheduleConflict(auditSchedule, own)) continue
    conflicts.push(own)
  }
  return {
    hasConflict: conflicts.length > 0,
    conflicts
  }
}

function markScheduleConflicts(auditCourse, ownCourses) {
  const item = auditCourse || {}
  const schedules = (
    Array.isArray(item.schedules) && item.schedules.length
      ? item.schedules
      : [item]
  ).map(schedule => {
    const result = conflictForSchedule(schedule, ownCourses)
    return Object.assign({}, schedule, {
      _hasConflict: result.hasConflict,
      _conflictWith: result.conflicts
    })
  })
  return Object.assign({}, item, { schedules })
}

function conflictForCourse(auditCourse, ownCourses) {
  const schedules = Array.isArray(auditCourse.schedules)
    && auditCourse.schedules.length
    ? auditCourse.schedules
    : [auditCourse]
  const conflicts = []
  for (const schedule of schedules) {
    for (const own of (ownCourses || [])) {
      if (!scheduleConflict(schedule, own)) continue
      const day = numberValue(schedule.day || schedule.day_of_week)
      const start = numberValue(schedule.start || schedule.start_period)
      const end = numberValue(schedule.end || schedule.end_period) || start
      conflicts.push({
        ownName: own.name || '本人课程',
        ownTeacher: own.teacher || '',
        ownClassroom: own.classroom || '',
        day,
        dayName: DAY_NAMES[day] || '时间未知',
        start,
        end,
        weeks: own.weeks || '',
      })
    }
  }
  return {
    hasConflict: conflicts.length > 0,
    conflicts,
  }
}

function describeConflict(conflict) {
  if (!conflict || !conflict.length) return ''
  const first = conflict[0]
  return `与「${first.ownName}」冲突（${first.dayName} 第${first.start}-${first.end}节）`
}

function normalizePart(value) {
  return String(value || '').trim().replace(/\s+/g, '')
}

function favoriteKey(course) {
  const item = course || {}
  const schedules = item.schedules || []
  const signatures = schedules.map(itemSchedule => [
    normalizePart(itemSchedule.day || itemSchedule.day_of_week),
    normalizePart(itemSchedule.start || itemSchedule.start_period),
    normalizePart(itemSchedule.end || itemSchedule.end_period),
    normalizePart(itemSchedule.weeks),
    normalizePart(itemSchedule.teacher),
    normalizePart(itemSchedule.classroom)
  ].join(':')).sort()
  return [
    normalizePart(item.name),
    normalizePart(item.class_info),
    normalizePart(item.teacher),
    normalizePart(item.classroom),
    signatures.join('||')
  ].join('|')
}

function flattenFavorite(favorite) {
  const item = favorite || {}
  const schedules = Array.isArray(item.schedules) ? item.schedules : []
  return schedules
    .map(schedule => Object.assign({}, schedule, {
      name: item.name || '',
      class_info: item.class_info || '',
      teacher: schedule.teacher || item.teacher || '',
      classroom: schedule.classroom || item.classroom || '',
      day: numberValue(schedule.day || schedule.day_of_week),
      start: numberValue(schedule.start || schedule.start_period),
      end: numberValue(schedule.end || schedule.end_period),
      weeks: schedule.weeks || '1-18',
      week_type: numberValue(schedule.week_type || 0),
      _audit: true,
      _favoriteId: item.id || '',
      _favoriteKey: item.favorite_key || favoriteKey(item)
    }))
    .filter(course => course.day && course.start && course.end)
}

module.exports = {
  weeksOverlap,
  scheduleConflict,
  conflictForSchedule,
  markScheduleConflicts,
  conflictForCourse,
  describeConflict,
  favoriteKey,
  flattenFavorite
}
