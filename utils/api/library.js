/**
 * 图书馆公共馆藏查询（匿名 OPAC，经本服务转发；需本服务登录态）。
 * 只传检索条件，不接受任何上游 URL。
 */
const { request } = require('./core')

/**
 * @param {{field?:string, q:string, page?:number, pageSize?:number}} opts
 * field: title | author | isbn | callno
 */
function searchLibraryBooks(opts) {
  const o = opts || {}
  const params = { q: o.q }
  if (o.field) params.field = o.field
  if (o.page) params.page = o.page
  if (o.pageSize) params.page_size = o.pageSize
  return request('GET', '/api/library/search', params)
}

/**
 * 单本逐册馆藏（用户点选后才请求）。
 * @param {{marcNo:string, campus?:'all'|'nanjing'|'jiangyin'}} opts
 */
function getLibraryBookItems(opts) {
  const o = opts || {}
  const params = { marc_no: o.marcNo }
  if (o.campus && o.campus !== 'all') params.campus = o.campus
  return request('GET', '/api/library/item', params)
}

module.exports = { searchLibraryBooks, getLibraryBookItems }
