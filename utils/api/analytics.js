/**
 * 小程序使用统计上报。
 */
const { request } = require('./core')

function trackEvents(events, visitorId) {
  return request('POST', '/api/analytics/events', {
    consent: true,
    visitor_id: visitorId || '',
    events: events || []
  }, { force: true })
}

module.exports = { trackEvents }
