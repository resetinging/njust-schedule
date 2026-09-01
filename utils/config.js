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

// 构建标识（git 短 hash）— 设置页显示, 用于确认线上版本
const BUILD = '8c29800'

// ============================================================
// 本地联调开关（仅开发调试用！）
// USE_LOCAL = true 时，所有请求直连本机 Flask（127.0.0.1:5000），
// 需要在微信开发者工具「详情 → 本地设置」勾选「不校验合法域名…」。
// ⚠️ 上传正式版前必须保持 false（已复位为 false）。
// ============================================================
const USE_LOCAL = false
const LOCAL_BASE = 'http://127.0.0.1:5000'

// 缓存有效期（毫秒）
const CACHE_TTL = {
  courses: 30 * 60 * 1000,    // 课表 30分钟
  exams: 30 * 60 * 1000,      // 考试 30分钟
  evaluations: 10 * 60 * 1000, // 评教 10分钟
  grades: 30 * 60 * 1000,     // 成绩 30分钟
  cet: 30 * 60 * 1000,        // 四六级 30分钟
  status: 10 * 60 * 1000      // 校历状态(第一周日期等) 10分钟
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
  BUILD,
  USE_LOCAL,
  LOCAL_BASE,
  CACHE_TTL,
  BIG_PERIOD_MAP
}
