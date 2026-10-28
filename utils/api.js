/**
 * API 聚合（Phase 3：按域拆分到 utils/api/*，此处统一导出）
 */
const core = require('./api/core')
const auth = require('./api/auth')
const schedule = require('./api/schedule')
const exams = require('./api/exams')
const grades = require('./api/grades')
const evalApi = require('./api/eval')
const feedback = require('./api/feedback')
const settings = require('./api/settings')
const freeclass = require('./api/freeclass')
const gallery = require('./api/gallery')
const library = require('./api/library')
const refresh = require('./api/refresh')
const study = require('./api/study')
const subscribe = require('./api/subscribe')
const audit = require('./api/audit')
const sync = require('./api/sync')
const analytics = require('./api/analytics')

const api = Object.assign({}, core, auth, schedule, exams, grades, evalApi,
  feedback, settings, freeclass, gallery, library, refresh, study, subscribe, audit,
  sync, analytics)
delete api.TOKEN_KEY   // 内部常量不对外暴露(保持旧版接口集合)
module.exports = api
