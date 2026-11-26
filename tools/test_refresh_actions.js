const assert = require('assert')
const fs = require('fs')
const path = require('path')

const ROOT = path.resolve(__dirname, '..')

function read(rel) {
  return fs.readFileSync(path.join(ROOT, rel), 'utf8')
}

function count(source, pattern) {
  return (source.match(pattern) || []).length
}

const contracts = [
  {
    name: '课表',
    file: 'components/schedule-view/index.wxml',
    minActions: 2,
    must: ['aria-label="刷新课表"', 'bind:action="onRefresh"']
  },
  {
    name: '考试',
    file: 'components/exams-view/index.wxml',
    minActions: 3,
    must: ['aria-label="刷新考试安排"', 'aria-label="刷新研究生考试安排"', 'bind:action="onRefresh"']
  },
  {
    name: '评教',
    file: 'components/eval-view/index.wxml',
    minActions: 2,
    must: ['aria-label="刷新教学评价"', 'bind:action="onRefresh"']
  },
  {
    name: '成绩',
    file: 'components/grades-view/index.wxml',
    minActions: 4,
    must: [
      'aria-label="刷新成绩"',
      'aria-label="刷新研究生成绩"',
      'aria-label="刷新四六级成绩"',
      'bind:action="onRefreshGrades"'
    ]
  },
  {
    name: '培养方案',
    file: 'components/credit-view/index.wxml',
    minActions: 2,
    must: ['aria-label="刷新培养方案"', 'bind:action="onRefresh"']
  }
]

for (const contract of contracts) {
  const source = read(contract.file)
  for (const token of contract.must) {
    assert(source.includes(token), `${contract.name}缺少刷新契约: ${token}`)
  }
  const bindings = count(
    source,
    /(?:bindtap|bind:action)="onRefresh(?:Grades|Cet|YjsGrades|YjsExams)?"/g
  )
  assert(
    bindings >= contract.minActions,
    `${contract.name}刷新入口不足: ${bindings} < ${contract.minActions}`
  )
}

const scheduleApi = read('utils/api/schedule.js')
assert(
  scheduleApi.includes("res.refreshed !== false && res.semester"),
  '课表刷新返回 refreshed=false 时不得覆盖当前学期'
)

for (const file of [
  'components/schedule-view/index.js',
  'components/grades-view/index.js',
  'components/eval-view/index.js',
  'components/credit-view/index.js'
]) {
  const source = read(file)
  assert(source.includes('refreshed === false'), `${file}未处理服务器快照提示`)
}

console.log('Refresh action contract test passed [OK]')
