/**
 * 课程配色 — 不同课程不同柔和色块
 * 按课程名做稳定哈希取色: 同一门课(跨周/多时段/网格与列表)颜色一致,
 * 不同课尽量不同色, 便于一眼区分课程。
 */

// 柔和浅色板(浅底 + 同色系左边条 + 深色文字, 保证可读性)
const PALETTE = [
  { bg: '#FCF0D9', bar: '#E8BE70', text: '#8A6116' },   // 橙黄(保留原课表色)
  { bg: '#E3F2FD', bar: '#90CAF9', text: '#1565C0' },   // 蓝
  { bg: '#E8F5E9', bar: '#9CCC9C', text: '#2E7D32' },   // 绿
  { bg: '#F3E5F5', bar: '#CE93D8', text: '#6A1B9A' },   // 紫
  { bg: '#E0F7FA', bar: '#80DEEA', text: '#006064' },   // 青
  { bg: '#FFEBEE', bar: '#EF9A9A', text: '#C62828' },   // 红
  { bg: '#FFF8E1', bar: '#FFE082', text: '#9A6B00' },   // 金黄
  { bg: '#E8EAF6', bar: '#9FA8DA', text: '#283593' },   // 靛
  { bg: '#FCE4EC', bar: '#F48FB1', text: '#AD1457' },   // 粉
  { bg: '#E0F2F1', bar: '#80CBC4', text: '#00695C' }    // 深青
]

function hashStr(s) {
  let h = 0
  const str = String(s || '课')
  for (let i = 0; i < str.length; i++) {
    h = (h * 31 + str.charCodeAt(i)) >>> 0
  }
  return h
}

/** 按课程名取稳定配色 {bg, bar, text} */
function courseColors(name) {
  return PALETTE[hashStr(name) % PALETTE.length]
}

module.exports = { courseColors, PALETTE }
