/**
 * API ????(Phase 3: ???? utils/api/*, ??????)
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
const refresh = require('./api/refresh')

const api = Object.assign({}, core, auth, schedule, exams, grades, evalApi,
  feedback, settings, freeclass, gallery, refresh)
delete api.TOKEN_KEY   // 内部常量不对外暴露(保持旧版 40 个接口)
module.exports = api
