/**
 * 全局配置 — 服务器地址、App 设置
 * 发布前修改 API_BASE 为实际服务器地址
 */

// 🔧 开发/发布时修改此地址
// 本地调试: http://localhost:5000
// 云服务器: https://your-domain.com
const API_BASE = 'https://flask-5da7-276116-7-1448570339.sh.run.tcloudbase.com'

// 请求超时（毫秒）— 云托管冷启动较慢，给 30s 余量
const REQUEST_TIMEOUT = 30000

// 轮询间隔（批量评教进度查询）
const POLL_INTERVAL = 2000

// 批量评教轮询最大次数（600次 × 2s = 20分钟）
const MAX_POLL_RETRIES = 600

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
  API_BASE,
  REQUEST_TIMEOUT,
  POLL_INTERVAL,
  MAX_POLL_RETRIES,
  CACHE_TTL,
  BIG_PERIOD_MAP
}
