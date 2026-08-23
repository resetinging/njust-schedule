/**
 * 全局配置 — 云托管环境、App 设置
 */

// 微信云托管环境 ID + 服务名（云托管控制台 → 环境列表 / 服务列表）
// 使用 wx.cloud.callContainer() 走微信内网，无需配置服务器域名白名单
const CLOUD_ENV = 'prod-d1g32cv4n1430dfb6'
const CLOUD_SERVICE = 'flask-5da7'

// 备用：云托管 HTTP 地址（仅供开发时 wx.request 使用）
const API_BASE = 'https://flask-5da7-276116-7-1448570339.sh.run.tcloudbase.com'

// 请求超时（毫秒）— 云托管冷启动较慢，给 30s 余量
const REQUEST_TIMEOUT = 30000

// 缓存有效期（毫秒）
const CACHE_TTL = {
  courses: 30 * 60 * 1000,    // 课表 30分钟
  exams: 30 * 60 * 1000,      // 考试 30分钟
  evaluations: 10 * 60 * 1000 // 评教 10分钟
}

// 大节映射（和教务系统一致）
const BIG_PERIOD_MAP = {
  '第一': { start: 1, end: 3 },
  '第二': { start: 4, end: 5 },
  '第三': { start: 6, end: 7 },
  '第四': { start: 8, end: 10 },
  '第五': { start: 11, end: 13 },
  '中午': { start: 14, end: 14 }
}

module.exports = {
  CLOUD_ENV,
  CLOUD_SERVICE,
  API_BASE,
  REQUEST_TIMEOUT,
  CACHE_TTL,
  BIG_PERIOD_MAP
}
