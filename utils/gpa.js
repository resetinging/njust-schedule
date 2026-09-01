/**
 * GPA 计算工具 — 从服务端 gpa.py 移植到前端（方案 A）
 * NJUST 4.0 量表、学期/总 GPA、CET 折算、保研模式
 */

// 非正式成绩状态（不参与绩点计算）
const NON_GRADE_STATUS = ['缓考', '缺考', '免修', '作弊', '违纪', '取消', '旷考', '休学']

// 不计入 GPA 的课程性质（NJUST 教务统一口径：通识公共选修课不参与评奖/保研绩点）
const NON_GPA_NATURES = ['通识教育选修课']

// 文字等级（NJUST 五级制 + 带加减的扩展等级）
const LEVEL_MAP = {
  '优': 4.0, '优秀': 4.0, '优+': 4.0, '优秀+': 4.0,
  '优-': 3.7, '优秀-': 3.7,
  '良+': 3.3, '良好+': 3.3,
  '良': 3.0, '良好': 3.0,
  '良-': 2.7, '良好-': 2.7,
  '中+': 2.3, '中等+': 2.3,
  '中': 2.0, '中等': 2.0,
  '中-': 1.5, '中等-': 1.5,
  '及格': 1.0, '通过': 1.0,
  '不及格': 0, '不通过': 0
}

// 等级制 → 百分制折算(与参考 App 一致, 用于平均分):
// 优=90 优-=87 良+=83 良=80 良-=76 中+=73 中=70 中-=66 及格=60
const LEVEL_PCT = {
  '优': 90, '优秀': 90, '优+': 90, '优秀+': 90,
  '优-': 87, '优秀-': 87,
  '良+': 83, '良好+': 83,
  '良': 80, '良好': 80,
  '良-': 76, '良好-': 76,
  '中+': 73, '中等+': 73,
  '中': 70, '中等': 70,
  '中-': 66, '中等-': 66,
  '及格': 60, '通过': 60,
  '不及格': 0, '不通过': 0
}

/** 判断课程是否计入平均学分绩点（评奖、保研、学籍审核） */
function isGpaCourse(courseNature) {
  return !NON_GPA_NATURES.includes((courseNature || '').trim())
}

/** 百分制/等级制成绩 → 绩点（NJUST 4.0 量表）；非正式成绩返回 -1 */
function scoreToGp(score) {
  const s = String(score == null ? '' : score).trim()
  if (s in LEVEL_MAP) return LEVEL_MAP[s]
  if (NON_GRADE_STATUS.includes(s)) return -1
  const v = parseFloat(s)
  if (isNaN(v)) return -1
  if (v >= 90) return 4.0
  if (v >= 85) return 3.7
  if (v >= 82) return 3.3
  if (v >= 78) return 3.0
  if (v >= 75) return 2.7
  if (v >= 72) return 2.3
  if (v >= 68) return 2.0
  if (v >= 64) return 1.5
  if (v >= 60) return 1.0
  return 0
}

function _round(v, digits) {
  const n = parseFloat(v)
  return isNaN(n) ? 0 : Math.round(n * Math.pow(10, digits || 2)) / Math.pow(10, digits || 2)
}

/** 等级制/百分制成绩 → 百分制数值(等级按参考 App 折算表); 非正式成绩返回 null */
function scoreToPct(score) {
  const s = String(score == null ? '' : score).trim()
  if (s in LEVEL_PCT) return LEVEL_PCT[s]
  if (NON_GRADE_STATUS.includes(s)) return null
  const v = parseFloat(s)
  return isNaN(v) ? null : v
}

/**
 * 平均分 = Σ(百分制成绩 × 学分) / Σ学分(学分加权, 等级制折算参与)
 * 与参考 App 口径一致; 无有效成绩时返回 0
 */
function calcAvg(grades) {
  let weighted = 0
  let credits = 0
  for (const g of grades || []) {
    const pct = scoreToPct(g.score)
    if (pct == null) continue
    const credit = parseFloat(g.credit) || 0
    const wc = credit > 0 ? credit : 1   // 无学分课程按 1 计(与参考 App 一致)
    weighted += pct * wc
    if (credit > 0) credits += credit
  }
  if (credits > 0) return _round(weighted / credits)
  return weighted > 0 ? _round(weighted / (grades || []).length) : 0
}

/**
 * 加权平均绩点 Σ(学分×绩点) / Σ学分
 * 不及格（绩点=0）计入分母；缓考/缺考/免修（绩点=-1）不计入
 * @param {Array} grades 成绩列表，每项含 credit, grade_point, score, course_nature
 * @param {boolean} gpaOnly true 时排除通识教育选修课（评奖/保研口径）
 */
function calcGpa(grades, gpaOnly) {
  let totalWeighted = 0
  let totalCredits = 0
  for (const g of grades || []) {
    if (gpaOnly && !isGpaCourse(g.course_nature)) continue
    const credit = parseFloat(g.credit) || 0
    if (credit <= 0) continue
    let gp = parseFloat(g.grade_point) || 0
    if (gp === 0) gp = scoreToGp(g.score)
    if (gp >= 0) {
      totalWeighted += credit * gp
      totalCredits += credit
    }
  }
  return totalCredits > 0 ? _round(totalWeighted / totalCredits) : 0
}

/** 四六级总分 → 百分制折算(参考 App 公式: 总分/710×100, 下限 60); 无效分数返回 0 */
function cetToPercentage(cetScore, cetType) {
  const score = parseFloat(cetScore) || 0
  if (score <= 0) return 0
  const pct = score / 710 * 100
  return _round(Math.min(100, Math.max(60, pct)), 1)
}

/** 判断是否为英语课（保研模式中被 CET 替换） */
function isEnglishCourse(courseName) {
  const name = (courseName || '').trim()
  return name === '通用英语' || name.indexOf('专用英语-') === 0
}

/**
 * 保研/推免模式绩点: 四六级折算成绩以 8 学分附加计入(参考 App 口径,
 * 不替换英语课; 原英语课成绩保留参与计算)
 * 优先级: CET6 > CET4
 */
function calcGpaBaoyan(grades, cetScores, gpaOnly) {
  const list = grades || []
  if (list.length === 0) return 0

  let cet4 = 0
  let cet6 = 0
  for (const cs of (cetScores || [])) {
    const score = parseFloat(cs.score) || 0
    if (cs.type === 'CET4') cet4 = Math.max(cet4, score)
    else if (cs.type === 'CET6') cet6 = Math.max(cet6, score)
  }

  let pct = 0
  if (cet6 >= 425) pct = cetToPercentage(cet6, 'CET6')
  else if (cet4 >= 425) pct = cetToPercentage(cet4, 'CET4')

  let calcGrades = list
  if (pct > 0) {
    calcGrades = list.concat([{
      course_name: 'CET折算(8学分)',
      score: String(pct),
      credit: 8,
      grade_point: scoreToGp(pct),
      course_nature: 'CET'
    }])
  }
  return calcGpa(calcGrades, gpaOnly === undefined ? true : gpaOnly)
}

module.exports = {
  isGpaCourse,
  scoreToGp,
  scoreToPct,
  calcAvg,
  calcGpa,
  cetToPercentage,
  isEnglishCourse,
  calcGpaBaoyan
}
