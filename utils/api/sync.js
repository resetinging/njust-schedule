/**
 * 多数据域版本检查
 */
const { request } = require('./core')

function getSyncVersions(semester) {
  const params = {}
  if (semester) params.semester = semester
  return request('GET', '/api/sync/versions', params)
}

module.exports = { getSyncVersions }
