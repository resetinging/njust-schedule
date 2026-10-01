/**
 * API 封装: 订阅消息(考试提醒等)
 *
 * 微信规则: 一次性订阅 —— 用户授权一次, 服务端只能发一条;
 * 授权结果由小程序调用 /api/subscribe/grant 上报, 后端据此保存额度与 openid。
 */
const { request } = require('./core')

/** 各提醒类型的模板可用性 + 剩余额度 */
function getSubscribeStatus() {
  return request('GET', '/api/subscribe/status')
}

/** 授权成功后上报(每次 +1 条额度) */
function grantSubscribe(kind, count) {
  return request('POST', '/api/subscribe/grant', { kind, count: count || 1 })
}

/** 发送一条样例提醒(验证配置; 会消耗 1 次额度) */
function sendSubscribeTest() {
  return request('POST', '/api/subscribe/test-send')
}

module.exports = { getSubscribeStatus, grantSubscribe, sendSubscribeTest }
