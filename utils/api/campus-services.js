const { request } = require('./core')

function listCampusServices(options) {
  const value = options || {}
  const params = {}
  if (value.category) params.category = value.category
  if (value.campus) params.campus = value.campus
  if (value.page) params.page = value.page
  if (value.pageSize) params.page_size = value.pageSize
  return request('GET', '/api/campus-services', params)
}

function getCampusService(id) {
  return request('GET', '/api/campus-services/' + encodeURIComponent(id || ''))
}

function submitCampusServiceLead(id, options) {
  const value = options || {}
  return request('POST', '/api/campus-services/' + encodeURIComponent(id || '') + '/leads', {
    contact_type: value.contactType || '',
    contact: value.contact || '',
    note: value.note || '',
    consent: value.consent === true
  }, { force: true })
}

module.exports = { listCampusServices, getCampusService, submitCampusServiceLead }
