/**
 * 课程配色 — 按课程名做稳定哈希取"第几号色"
 *
 * 这里只决定用第几组颜色, 具体色值交给主题变量(--c1..--c10-bg/fg/bar):
 * 同一门课在三套外观(清透/最初版/像素)下位置一致, 颜色随主题整体变化。
 */

const COUNT = 10

function hashStr(s) {
  let h = 0
  const str = String(s || '课')
  for (let i = 0; i < str.length; i++) {
    h = (h * 31 + str.charCodeAt(i)) >>> 0
  }
  return h
}

/** 按课程名取稳定的配色变量名 {bg, bar, text} */
function courseColors(name) {
  const i = (hashStr(name) % COUNT) + 1
  return {
    bg: `var(--c${i}-bg)`,
    bar: `var(--c${i}-bar)`,
    text: `var(--c${i}-fg)`
  }
}

module.exports = { courseColors, COUNT }
