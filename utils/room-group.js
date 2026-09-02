/**
 * 空闲教室 → 按教学楼分组(展示用)
 * 教室代码形如: Ⅳ-A411 / I-201 / III-304 / 345-104 / 江阴致知B103
 * 分组键 = 首个 '-' 前的段(罗马数字原样), 或汉字前缀(如 江阴致知B);
 * 组标题优先映射教务"教学楼"名称(Ⅰ教学楼/致知楼B…), 映射失败时显示原始前缀。
 */

// Unicode 罗马数字 → ASCII(教务楼名用 Ⅰ/Ⅱ/Ⅲ…, 教室代码混用 I/III/Ⅳ…)
const ROMAN = {
  'Ⅰ': 'I', 'Ⅱ': 'II', 'Ⅲ': 'III', 'Ⅳ': 'IV', 'Ⅴ': 'V',
  'Ⅵ': 'VI', 'Ⅶ': 'VII', 'Ⅷ': 'VIII', 'Ⅸ': 'IX', 'Ⅹ': 'X'
}

function normRoman(s) {
  return String(s || '').replace(/[Ⅰ-Ⅹ]/g, c => ROMAN[c] || c)
}

/** 提取教室前缀: 'Ⅳ-A411'→'Ⅳ' | '江阴致知B103'→'江阴致知B' */
function roomPrefix(room) {
  const r = String(room || '')
  const dash = r.indexOf('-')
  if (dash > 0) return r.slice(0, dash)
  const m = r.match(/^(\D+?)(?=\d)/)   // 数字前的非数字段
  return m ? m[1] : r
}

/**
 * 尽力把前缀映射成教学楼显示名
 * - 罗马数字前缀 → 匹配 "X教学楼"(忽略 教学楼/楼 后缀, 归一罗马数字)
 * - 汉字前缀(江阴致知B) → 剥离校区词后与楼名匹配
 */
function buildingLabel(prefix, buildings) {
  const list = buildings || []
  if (!prefix || !list.length) return ''
  const p = normRoman(prefix)
  const isRoman = /^[IVX]+$/i.test(p)
  for (const b of list) {
    if (b === prefix) return b
    const bn = normRoman(b).replace(/教学楼|楼/g, '')
    if (!bn) continue
    if (isRoman) {
      if (bn.toUpperCase() === p.toUpperCase()) return b
    } else {
      // 汉字: '江阴致知B' → 去'江阴' → '致知B' 对比 '致知楼B'→'致知B'
      const p2 = p.replace(/^江阴/, '')
      if (p2 && (p2 === bn || bn.startsWith(p2) || p2.startsWith(bn))) return b
    }
  }
  return ''
}

/** 分组: [{label, prefix, rooms:[...]}], 按首次出现顺序, 每个教室恰好一组 */
function groupRooms(rooms, buildings) {
  const order = []
  const idx = {}
  ;(rooms || []).forEach(room => {
    const prefix = roomPrefix(room)
    if (!idx[prefix]) {
      idx[prefix] = {
        label: buildingLabel(prefix, buildings) || prefix,
        prefix,
        rooms: []
      }
      order.push(prefix)
    }
    idx[prefix].rooms.push(room)
  })
  // 教室多的楼在前(常见目标优先), 其余按出现顺序
  order.sort((x, y) => idx[y].rooms.length - idx[x].rooms.length)
  return order.map(p => idx[p])
}

module.exports = { groupRooms, roomPrefix }
