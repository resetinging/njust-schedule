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
 * 注意: 后端 buildings 实测为 [{code,name}] 对象数组(同时兼容字符串数组)
 */
function buildingLabel(prefix, buildings) {
  const list = buildings || []
  if (!prefix || !list.length) return ''
  const p = normRoman(prefix)
  const isRoman = /^[IVX]+$/i.test(p)
  for (const item of list) {
    const b = (item && typeof item === 'object') ? String(item.name || '') : String(item || '')
    if (!b) continue
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

/** 四大教学楼排最前(Ⅰ→Ⅳ), 其余按教室数量降序 */
const MAIN_TEACHING = ['I', 'II', 'III', 'IV']

function mainTeachingRank(s) {
  const t = normRoman(String(s || '').replace(/教学楼|楼/g, '')).toUpperCase()
  const i = MAIN_TEACHING.indexOf(t)
  return i >= 0 ? i : -1
}

function groupRank(g) {
  const r = mainTeachingRank(g && g.label)
  return r >= 0 ? r : mainTeachingRank(g && g.prefix)
}

/** 是否四大教学楼(Ⅰ/Ⅱ/Ⅲ/Ⅳ教学楼)分组 */
function isMainTeaching(g) {
  return groupRank(g) >= 0
}

/**
 * 分组内展示用的短名: 去掉与组名重复的楼名前缀
 * 'Ⅳ教学楼-A312' → 'A312'; '致源楼B331' → '331';
 * 无编号的整名场馆(如 '体育中心健美操房')保持原名
 */
function shortRoom(room, prefix) {
  const s = String(room || '')
  if (prefix && s.indexOf(prefix) === 0) {
    const rest = s.slice(prefix.length).replace(/^[-\s]+/, '')
    if (rest) return rest
  }
  return s
}

/**
 * 楼层: 房间号(短名)里的第一段数字, 首位即楼层
 * 'A312'→3, '101'→1; 1-2 位数字(如 '7')视为底层(0); 无数字的场馆排最后(99)
 */
function floorRank(chip) {
  const m = String(chip || '').match(/\d+/)
  if (!m) return 99
  return m[0].length >= 3 ? parseInt(m[0][0], 10) : 0
}

function byFloor(a, b) {
  const fa = floorRank(a.chip)
  const fb = floorRank(b.chip)
  if (fa !== fb) return fa - fb
  if (a.chip < b.chip) return -1
  if (a.chip > b.chip) return 1
  return 0
}

/** 分组: [{label, prefix, rooms:[...], chips:[...]}], 每个教室恰好一组 */
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
  Object.keys(idx).forEach(p => {
    const pairs = idx[p].rooms.map(r => ({ room: r, chip: shortRoom(r, p) }))
    pairs.sort(byFloor)                        // 按楼层升序, 同层按房间号
    idx[p].rooms = pairs.map(x => x.room)
    idx[p].chips = pairs.map(x => x.chip)
  })
  // 四大教学楼置顶(Ⅰ→Ⅳ), 其余按教室多的优先
  order.sort((x, y) => {
    const rx = groupRank(idx[x])
    const ry = groupRank(idx[y])
    if (rx >= 0 || ry >= 0) {
      if (rx >= 0 && ry >= 0) return rx - ry
      return rx >= 0 ? -1 : 1
    }
    return idx[y].rooms.length - idx[x].rooms.length
  })
  return order.map(p => idx[p])
}

module.exports = { groupRooms, roomPrefix, isMainTeaching }
