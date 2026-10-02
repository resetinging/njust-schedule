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
  // 无 token 时后端只会返回 401: 直接跳过, 避免每次启动一串无效请求
  if (!storage.get('token', '')) return 0
  // 研究生账号: 课表 + 成绩(学分进度), 其余数据源不适用
  if (storage.get('account_type', '') === 'graduate') {
    const results = await Promise.all([
      api.getCourses(storage.getSemester()).then(r => {
        if (r && r.success && r.courses) {
          const cs = r.semester || storage.getSemester() || 'default'
          storage.setCached('cached_courses_' + cs, r.courses)
          if (r.semester) storage.setSemester(r.semester)
          return 1
        }
        return 0
      }),
      api.getYjsGrades().then(r => {
        if (r && r.success) {
          storage.setCached('cached_yjs_grades', r)
          return 1
        }
        return 0
      }),
      api.getYjsExams().then(r => {
        if (r && r.success) {
          storage.setCached('cached_yjs_exams', r)
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

async function _queryAllChanged(versions) {
  const sid = storage.getStudentId() || 'guest'
  const sem = storage.getSemester() || 'default'
  const versionKey = 'cached_sync_versions_' + sid + '_' + sem
  const previous = storage.getCached(versionKey) || {}
  const next = Object.assign({}, previous)
  const unversioned = []

  const load = (name, cacheKey, loader, save) => {
    const cached = storage.getCached(cacheKey)
    const version = versions[name]
    if (cached && version !== undefined && previous[name] === version) {
      return Promise.resolve(1)
    }
    return loader().then(res => {
      if (res && res.success) {
        save(res)
        if (version !== undefined) next[name] = version
        return 1
      }
      return 0
    }).catch(() => 0)
  }

  const tasks = [
    load('courses', 'cached_courses_' + sem,
      () => api.getCourses(sem),
      res => {
        const cs = res.semester || sem
        storage.setCached('cached_courses_' + cs, res.courses || [])
        if (res.semester) storage.setSemester(res.semester)
      }),
    load('exams', 'cached_exams_' + sem,
      () => api.getExams(sem),
      res => storage.setCached(
        'cached_exams_' + (res.semester || sem), res.exams || [])),
    load('evaluations', 'cached_evaluations',
      () => api.getEvalBatches(),
      res => storage.setCached('cached_evaluations', res)),
    load('grades', 'cached_grades',
      () => api.getGrades('__all__'),
      res => storage.setCached('cached_grades', res)),
    load('cet_scores', 'cached_cet_scores',
      () => api.getCetScores(),
      res => storage.setCached('cached_cet_scores', res))
  ]

  unversioned.push(api.getStatus().then(res => {
    if (res && res.first_week_date) {
      storage.setCached('cached_status_' + sid + '_' + sem, {
        t: Date.now(),
        first_week_date: res.first_week_date
      })
      return 1
    }
    return 0
  }).catch(() => 0))

  const results = await Promise.all(tasks.concat(unversioned))
  storage.setCached(versionKey, next)
  return results.reduce((a, b) => a + b, 0)
}

async function _queryAllSmart() {
  if (typeof api.getSyncVersions !== 'function') return _queryAll()
  try {
    const res = await api.getSyncVersions(storage.getSemester())
    if (res && res.success && res.versions) {
      return _queryAllChanged(res.versions)
    }
  } catch (e) {
    // 旧后端不支持版本接口时回退全量读取。
  }
  return _queryAll()
}

/**
 * 等待服务端在新会话建立后完成一次全量教务同步。
 * 旧后端没有 data_refresh 字段时立即返回, 保持兼容。
 */
async function _waitForDataRefresh(maxMs = 45000) {
  const startedAt = Date.now()
  let delay = 500
  while (Date.now() - startedAt < maxMs) {
    let state = ''
    try {
      if (typeof api.getDataRefreshStatus === 'function') {
        const light = await api.getDataRefreshStatus()
        state = light && light.data_refresh && light.data_refresh.state
      }
      // 兼容旧后端: 轻量接口不存在时回退到 /api/status。
      if (!state) {
        const res = await api.getStatus()
        state = res && res.data_refresh && res.data_refresh.state
      }
    } catch (e) {
      return false
    }
    if (!state || state === 'idle' || state === 'done' ||
        state === 'partial' || state === 'failed') {
      return state !== 'failed'
    }
    await new Promise(resolve => setTimeout(resolve, delay))
    delay = Math.min(3000, Math.round(delay * 1.6))
  }
  return false
}

/**
 * 读取全部数据到本地缓存。
 * - 新会话: 等服务端后台同步完成后读取, 不重复刷新教务
 * - 用户主动刷新(force=true): 立刻刷新教务并重新读取
 *
 * @returns {Promise<number>} 最终成功载入的数据项数
 */
async function fetchAllData(options) {
  const force = !!(options && options.force)
  if (!storage.get('token', '')) {
    // 后端会话可能在重启/部署后失效(本地凭证已被清), 此时直接 return 会让
    // "刷新数据"毫无反应。这里先解除离线态, 有记忆密码就静默重登一次再继续。
    if (storage.isOffline()) storage.setOffline(false)
    if (!storage.get('saved_password', '')) return 0
    try { await api.getStatus() } catch (e) { /* 交给下面的请求再次触发重登 */ }
    if (!storage.get('token', '')) return 0
  }
  // 研究生账号: 只有课表 + 成绩两个数据源, 各拉一次写缓存(之后靠本地渲染)
  if (storage.get('account_type', '') === 'graduate') {
    let ok = 0
    try { ok = await _queryAll() } catch (e) { /* 静默 */ }
    if (!force) {
      await _waitForDataRefresh()
      try { ok = await _queryAll() } catch (e) { /* 静默 */ }
    }
    return ok
  }
  // 1) 立即载入现有数据
  try { await _queryAllSmart() } catch (e) { /* 静默 */ }

  if (!force) {
    // 登录/自动重登由服务端统一刷新一次; 前端只等待并读取结果。
    await _waitForDataRefresh()
    let ok = 0
    try { ok = await _queryAllSmart() } catch (e) { /* 静默 */ }
    return ok
  }

  // 2) 刷新教务获取最新数据(4 并发, 后端教务限流 4)
  await Promise.all([
    api.refreshAll().catch(() => {}),
    api.refreshGrades().catch(() => {}),
    api.refreshCet().catch(() => {}),
    api.refreshEvaluations().catch(() => {})
  ])

  // 3) 重新查询写入最新缓存
  let ok = 0
  try { ok = await _queryAllSmart() } catch (e) { /* 静默 */ }
  return ok
}

module.exports = { fetchAllData }
