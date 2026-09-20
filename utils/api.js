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

module.exports = Object.assign({}, core, auth, schedule, exams, grades, evalApi,
  feedback, settings, freeclass, gallery, refresh)
