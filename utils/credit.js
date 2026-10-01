/**
 * 学分进度计算 —— 培养方案(应修) × 成绩(已修, 按课程代码匹配)
 *
 * 纯函数, 便于本地用 node 验证(后端只存原始数据, 计算在前端)。
 *
 * 三个口径说明:
 *  1) 通过判定兼容教务三种记法: 绩点>0 / 百分制>=60 / 等级制(优-、良+、中+…);
 *  2) 未通过区分"已开课学期(需要补)"与"后续学期(未开课)"; 本学期课程单独归类;
 *  3) 同名选修池(同学期同前缀 >=3 门, 如"专用英语-XXX"系列): 已选其中若干门时,
 *     其余按"同组其他选项"处理, 不计入未通过; 应修学分按已选课程计(未选则取池内最小单课学分)。
 */
const FAIL_WORDS = ['不及格', '不通过', '未通过', '未及格', '缓考', '缺考',
                    '作弊', '违纪', '取消', '旷考', '休学']
const PASS_LEVELS = ['优秀', '良好', '中等', '优', '良', '中', '及格', '合格', '通过']
const POOL_MIN = 3           // 同名选修池的最少门数(避免把 Ⅰ/Ⅱ 两门课误判为一组)
const ATTR_ORDER = ['必修', '限选', '任选', '公选', '进阶', '其它', '其他', '计划外']

function _num(v) { const n = parseFloat(v); return isNaN(n) ? 0 : n }
function _round1(v) { return Math.round(v * 10) / 10 }
function _code(c) { return String((c && c.code) || '').trim() }
function _attrIndex(name) { const i = ATTR_ORDER.indexOf(name); return i < 0 ? 99 : i }

/** 课程名前缀(按 '-' / '（' 切分), 用于识别同名选修池 */
function _prefix(name) {
  const s = String(name || '').trim()
  const seps = ['-', '—', '（', '(']
  for (let i = 0; i < seps.length; i++) {
    const idx = s.indexOf(seps[i])
    if (idx > 0) return s.slice(0, idx).trim()
  }
  return s
}

/** 成绩是否通过(兼容 绩点/百分制/等级制; 缓考、缺考等不算; 免修算通过) */
function isPassed(g) {
  const s = String(g.score == null ? '' : g.score).trim()
  if (FAIL_WORDS.some(k => s.indexOf(k) >= 0)) return false
  if (_num(g.grade_point) > 0) return true
  const n = parseFloat(s)
  if (!isNaN(n)) return n >= 60
  if (!s) return false
  if (s.indexOf('免修') >= 0) return true
  return PASS_LEVELS.some(k => s.indexOf(k) >= 0)
}

/**
 * @param {Array} plan   培养方案课程 [{semester, code, name, credit, attribute}]
 * @param {Array} grades 成绩 [{course_code, score, grade_point, credit, ...}]
 * @param {string} currentSemester 当前学期(如 '2026-2027-1'), 用于区分 未通过/本学期/未开课
 */
function computeCredit(plan, grades, currentSemester) {
  const list = plan || []
  const byCode = {}
  list.forEach(c => { if (_code(c)) byCode[_code(c)] = c })

  const passed = {}
  const unplanned = []
  ;(grades || []).forEach(g => {
    if (!isPassed(g)) return
    const code = String(g.course_code == null ? '' : g.course_code).trim()
    if (code && byCode[code]) passed[code] = true
    else unplanned.push(g)
  })

  // 同名选修池: 同学期 + 同前缀 + 至少 POOL_MIN 门
  const pools = {}
  list.forEach(c => {
    const key = (c.semester || '') + '|' + _prefix(c.name)
    if (!pools[key]) pools[key] = []
    pools[key].push(c)
  })
  const poolOf = {}          // code -> poolKey(仅多门组)
  Object.keys(pools).forEach(k => {
    if (pools[k].length >= POOL_MIN) pools[k].forEach(c => { poolOf[_code(c)] = k })
  })

  // 统计用课程(池按"已选课程"或"最小单课学分"折算)
  const effective = []
  const seenPool = {}
  list.forEach(c => {
    const key = poolOf[_code(c)]
    if (!key) { effective.push({ c: c, credit: _num(c.credit) }); return }
    if (seenPool[key]) return
    seenPool[key] = true
    const items = pools[key]
    const taken = items.filter(x => passed[_code(x)])
    if (taken.length) {
      taken.forEach(x => effective.push({ c: x, credit: _num(x.credit) }))
    } else {
      let min = Infinity
      items.forEach(x => { min = Math.min(min, _num(x.credit)) })
      effective.push({ c: items[0], credit: isFinite(min) ? min : 0 })
    }
  })

  // 分类别统计
  const groups = {}
  effective.forEach(({ c, credit }) => {
    const attr = (c.attribute || '其他').trim() || '其他'
    if (!groups[attr]) groups[attr] = { name: attr, required: 0, earned: 0, total: 0, done: 0 }
    const g = groups[attr]
    g.required += credit
    g.total += 1
    if (passed[_code(c)]) { g.earned += credit; g.done += 1 }
  })
  const rows = Object.keys(groups).map(k => {
    const g = groups[k]
    g.required = _round1(g.required)
    g.earned = _round1(g.earned)
    g.percent = g.required > 0 ? Math.min(100, Math.round(g.earned / g.required * 100)) : 0
    return g
  }).sort((a, b) => _attrIndex(a.name) - _attrIndex(b.name) || a.name.localeCompare(b.name, 'zh'))

  const totalRequired = _round1(rows.reduce((s, g) => s + g.required, 0))
  const totalEarned = _round1(rows.reduce((s, g) => s + g.earned, 0))

  // 未通过 / 本学期 / 后续学期; 池内未选的其他选项单列
  const cur = String(currentSemester || '').trim()
  const buckets = { failed: {}, current: {}, upcoming: {} }
  const alternatives = []
  list.forEach(c => {
    const code = _code(c)
    if (!code || passed[code]) return
    const key = poolOf[code]
    if (key) { alternatives.push(c); return }        // 同组其他选项(组内已选)
    const sem = c.semester || '未知学期'
    const bucket = !cur ? 'failed' : (sem < cur ? 'failed' : (sem === cur ? 'current' : 'upcoming'))
    if (!buckets[bucket][sem]) buckets[bucket][sem] = []
    buckets[bucket][sem].push(c)
  })

  function _pack(map) {
    const groupsList = Object.keys(map).sort().map(sem => ({
      semester: sem,
      count: map[sem].length,
      credits: _round1(map[sem].reduce((s, c) => s + _num(c.credit), 0)),
      courses: map[sem].map(c => ({ name: c.name, code: c.code, credit: c.credit }))
    }))
    return {
      groups: groupsList,
      count: groupsList.reduce((s, g) => s + g.count, 0),
      credits: _round1(groupsList.reduce((s, g) => s + g.credits, 0))
    }
  }

  const failed = _pack(buckets.failed)
  const current = _pack(buckets.current)
  const upcoming = _pack(buckets.upcoming)

  return {
    rows,
    totalRequired,
    totalEarned,
    totalPercent: totalRequired > 0 ? Math.min(100, Math.round(totalEarned / totalRequired * 100)) : 0,
    planCount: list.length,
    failed,
    current,
    upcoming,
    remainingCount: failed.count,
    alternativesCount: alternatives.length,
    alternativesCredits: _round1(alternatives.reduce((s, c) => s + _num(c.credit), 0)),
    unplannedCount: unplanned.length,
    unplannedCredits: _round1(unplanned.reduce((s, g) => s + _num(g.credit), 0))
  }
}

module.exports = { computeCredit, isPassed }
