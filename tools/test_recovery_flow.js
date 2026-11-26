const assert = require('assert')
const fs = require('fs')
const path = require('path')

const ROOT = path.resolve(__dirname, '..')

function read(rel) {
  return fs.readFileSync(path.join(ROOT, rel), 'utf8')
}

const app = read('app.js')
assert(app.includes('api.getStatus({ force: true })'), '启动状态校验必须绕过离线短路')
assert(app.includes('_resumeAfterSessionRecovery()'), '自动重登后必须恢复当前页面')
assert(app.includes('this._prefetchAll()'), '会话恢复后必须重新预取数据')
assert(app.includes('current.onShow()'), '会话恢复后必须重新激活当前视图')
assert(app.includes('task.then(activateAfterPrefetch, activateAfterPrefetch)'), '数据预取完成后应再次激活当前视图')

const grades = read('components/grades-view/index.js')
assert(
  /activate\(\)[\s\S]*?loadCached\(\)[\s\S]*?storage\.hasSession\(\)[\s\S]*?this\.loadGrades\(true\)/.test(grades),
  '成绩页激活时必须在缓存为空且会话有效的情况下补拉'
)

const exams = read('components/exams-view/index.js')
assert(exams.includes('EXAM_AUTO_REFRESH_MS'), '考试页缺少自动刷新时间窗')
assert(exams.includes('_maybeAutoRefresh()'), '考试页激活时应检查自动刷新')
assert(exams.includes('this.onRefresh(true)'), '自动刷新应静默执行')
assert(exams.includes('quiet === true'), '仅内部自动刷新应静默，不能吞掉手动刷新提示')

const settings = read('components/settings-view/index.js')
assert(settings.includes('this._loadMyFeedback(false)'), '会话恢复回到我的页时必须刷新反馈未读状态')

console.log('Session recovery flow test passed [OK]')
