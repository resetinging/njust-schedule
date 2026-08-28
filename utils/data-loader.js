/**
 * 数据加载器 — 登录后自动获取全部数据并载入本地缓存
 * 第1步: 查询接口并行(立即载入缓存, 各 Tab 页秒开)
 * 第2步: 刷新教务接口并行(最新数据, 后端限流 4 并发), 完成后再次查询写缓存
 * 任何失败静默, 不影响登录与使用
 */

const api = require('./api')
const storage = require('./storage')

function _sem() {
  return storage.getSemester() || 'default'
}

/** 并行查询全部数据并写入缓存, 返回成功项数 */
async function _queryAll() {
  const sem = storage.getSemester()
  const results = await Promise.all([
    api.getCourses(sem).then(r => {
      if (r && r.success && r.courses) {
        const cs = r.semester || sem || 'default'
        storage.setCached('cached_courses_' + cs, r.courses)
        if (r.semester) storage.setSemester(r.semester)
        return 1
      }
      return 0
    }),
    api.getExams(sem).then(r => {
      if (r && r.success && r.exams) {
        storage.setCached('cached_exams_' + (r.semester || sem || 'default'), r.exams)
        return 1
      }
      return 0
    }),
    api.getEvalBatches().then(r => {
      if (r && r.success && r.evaluations) {
        storage.setCached('cached_evaluations', r)
        return 1
      }
      return 0
    }),
    api.getGrades('__all__').then(r => {
      if (r && r.success) {
        storage.setCached('cached_grades', r)
        return 1
      }
      return 0
    }),
    api.getCetScores().then(r => {
      if (r && r.success) {
        storage.setCached('cached_cet_scores', r)
        return 1
      }
      return 0
    }),
    api.getStatus().then(r => {
      if (r && r.first_week_date) {
        const sid = storage.getStudentId() || 'guest'
        storage.setCached('cached_status_' + sid + '_' + _sem(), {
          t: Date.now(),
          first_week_date: r.first_week_date
        })
        return 1
      }
      return 0
    })
  ])
  return results.reduce((a, b) => a + b, 0)
}

/**
 * 登录成功后调用: 先查询(立即载入) → 刷新教务(最新) → 再查询(更新缓存)
 * @returns {Promise<number>} 最终成功载入的数据项数
 */
async function fetchAllData() {
  // 1) 立即载入现有数据
  try { await _queryAll() } catch (e) { /* 静默 */ }

  // 2) 刷新教务获取最新数据(4 并发, 后端教务限流 4)
  await Promise.all([
    api.refreshAll().catch(() => {}),
    api.refreshGrades().catch(() => {}),
    api.refreshCet().catch(() => {}),
    api.refreshEvaluations().catch(() => {})
  ])

  // 3) 重新查询写入最新缓存
  let ok = 0
  try { ok = await _queryAll() } catch (e) { /* 静默 */ }
  return ok
}

module.exports = { fetchAllData }
