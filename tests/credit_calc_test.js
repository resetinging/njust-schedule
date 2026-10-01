/**
 * 学分进度计算单测(纯 node, 不依赖小程序运行时)
 *
 * 运行: node tests/credit_calc_test.js   (在 miniprogram 目录下执行)
 * 说明: /tests 已加入 project.config.json 的 packOptions.ignore, 不会打进小程序包。
 */
const { computeCredit, isPassed } = require('../utils/credit')

const plan = [
  { semester: '2024-2025-1', code: 'A1', name: '高等数学', credit: 5, attribute: '必修' },
  { semester: '2024-2025-1', code: 'A2', name: 'C++', credit: 4, attribute: '必修' },
  { semester: '2024-2025-2', code: 'B1', name: '机器人实战', credit: 1.5, attribute: '任选' },
  { semester: '2024-2025-2', code: 'E1', name: '专用英语-听说', credit: 2, attribute: '限选' },
  { semester: '2024-2025-2', code: 'E2', name: '专用英语-读写', credit: 2, attribute: '限选' },
  { semester: '2024-2025-2', code: 'E3', name: '专用英语-口译', credit: 2, attribute: '限选' },
  { semester: '2026-2027-1', code: 'C1', name: '嵌入式系统', credit: 2, attribute: '必修' },
  { semester: '2027-2028-1', code: 'D1', name: '毕业设计', credit: 8, attribute: '必修' },
]
const grades = [
  { course_code: 'A1', course_name: '高等数学', credit: 5, score: '85', grade_point: 3.7 },
  { course_code: 'A2', course_name: 'C++', credit: 4, score: '55', grade_point: 0 },
  { course_code: 'B1', course_name: '机器人实战', credit: 1.5, score: '良+', grade_point: 0 },
  { course_code: 'E1', course_name: '专用英语-听说', credit: 2, score: '良', grade_point: 0 },
  { course_code: 'C9', course_name: '计划外选修', credit: 2, score: '90', grade_point: 4.0 },
  { course_code: 'F1', course_name: '缓考课', credit: 3, score: '缓考', grade_point: 0 },
]

const v = computeCredit(plan, grades, '2026-2027-1')
const checks = [
  ['应修 = 22.5(选修池按已选 2 学分)', v.totalRequired === 22.5],
  ['已修 = 8.5(含等级制 良+/良)', v.totalEarned === 8.5],
  ['必修 5/19', v.rows[0].name === '必修' && v.rows[0].earned === 5 && v.rows[0].required === 19],
  ['限选 2/2(池内已选)', v.rows[1].name === '限选' && v.rows[1].required === 2 && v.rows[1].earned === 2],
  ['任选 1.5/1.5', v.rows[2].name === '任选' && v.rows[2].earned === 1.5],
  ['未通过 = 历史学期挂科 1 门 / 4 学分', v.failed.count === 1 && v.failed.credits === 4],
  ['本学期 1 门 / 2 学分', v.current.count === 1 && v.current.credits === 2],
  ['后续未开课 1 门 / 8 学分', v.upcoming.count === 1 && v.upcoming.credits === 8],
  ['同组其他选项 2 门 / 4 学分', v.alternativesCount === 2 && v.alternativesCredits === 4],
  ['计划外 1 门 / 2 学分', v.unplannedCount === 1 && v.unplannedCredits === 2],
  ['等级制 良+/优-/中+ 均算通过',
    isPassed({ score: '良+', grade_point: 0 }) === true
    && isPassed({ score: '优-', grade_point: 0 }) === true
    && isPassed({ score: '中+', grade_point: 0 }) === true],
  ['不及格/缓考 不算通过',
    isPassed({ score: '不及格', grade_point: 0 }) === false
    && isPassed({ score: '缓考', grade_point: 0 }) === false],
  ['60 分算通过 / 59 不算',
    isPassed({ score: '60', grade_point: 0 }) === true
    && isPassed({ score: '59', grade_point: 0 }) === false],
  ['空数据不报错', computeCredit([], [], '').totalRequired === 0],
]

let bad = 0
checks.forEach(([name, ok]) => {
  console.log((ok ? '  [PASS] ' : '  [FAIL] ') + name)
  if (!ok) bad++
})
console.log(bad ? '失败 ' + bad + ' 项' : '学分计算校验通过 [OK]')
process.exit(bad ? 1 : 0)
