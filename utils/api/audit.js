/**
 * 蹭课查询 API
 */
const { request } = require('./core')

function searchAuditCourses(params) {
  return request('GET', '/api/audit-courses', params || {})
}

function listAuditOptions(params) {
  return request('GET', '/api/audit-options', params || {})
}

function listAuditFavorites(params) {
  return request('GET', '/api/audit-favorites', params || {})
}

function saveAuditFavorite(course) {
  return request('POST', '/api/audit-favorites', course || {})
}

function deleteAuditFavorite(id) {
  return request('DELETE', '/api/audit-favorites/' + encodeURIComponent(id), {})
}

module.exports = {
  searchAuditCourses,
  listAuditOptions,
  listAuditFavorites,
  saveAuditFavorite,
  deleteAuditFavorite
}
