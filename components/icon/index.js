/**
 * 线性图标组件 — 线性描边图标(清透课堂)
 * 用法: <icon name="refresh" size="32" color="#2563EB" />
 * color 只用于选色调档位(grey/slate/indigo/white), 详见 index.wxml 的 wxs
 */
// 图标资源: poster/make_icons.py 生成 SVG 网格 → make_icons.ps1 渲染裁剪成
// .miniapp/static/icons/<name>-<tone>.png (小程序 image 对 data-URI SVG 支持不稳)
const PATHS = {
  // 刷新: 圆弧 + 箭头
  refresh: "<path d='M20 12a8 8 0 1 1-2.3-5.6'/%3E<path d='M20 4v5h-5'/%3E",
  plus: "<path d='M12 5v14M5 12h14'/%3E",
  prev: "<path d='M15 5l-7 7 7 7'/%3E",
  next: "<path d='M9 5l7 7-7 7'/%3E",
  back: "<path d='M19 12H5M11 6l-6 6 6 6'/%3E",
  close: "<path d='M6 6l12 12M18 6L6 18'/%3E",
  search: "<circle cx='11' cy='11' r='7'/%3E<path d='M20 20l-4-4'/%3E",
  edit: "<path d='M4 20h4L19 9l-4-4L4 16v4z'/%3E<path d='M14 6l4 4'/%3E",
  megaphone: "<path d='M4 10v4h3l5 3V7L7 10H4z'/%3E<path d='M16 9a4 4 0 0 1 0 6'/%3E",
  clock: "<circle cx='12' cy='12' r='8'/%3E<path d='M12 7v5l3 2'/%3E",
  calendar: "<rect x='4' y='5' width='16' height='15' rx='2'/%3E<path d='M4 10h16M9 3v4M15 3v4'/%3E",
  building: "<path d='M4 21V6l8-3 8 3v15'/%3E<path d='M9 21v-6h6v6M8 10h.01M12 10h.01M16 10h.01'/%3E",
  doc: "<rect x='5' y='3' width='14' height='18' rx='2'/%3E<path d='M9 8h6M9 12h6M9 16h4'/%3E",
  clipboard: "<rect x='5' y='5' width='14' height='16' rx='2'/%3E<path d='M9 5h6v3H9zM9.5 14l2 2 3.5-4'/%3E",
  image: "<rect x='3' y='5' width='18' height='14' rx='2'/%3E<circle cx='9' cy='10' r='1.6'/%3E<path d='M4 18l5-5 4 4 3-3 4 4'/%3E",
  lock: "<rect x='5' y='11' width='14' height='9' rx='2'/%3E<path d='M8 11V8a4 4 0 0 1 8 0v3'/%3E",
  hourglass: "<path d='M7 4h10M7 20h10M8 4c0 4 8 4 8 8s-8 4-8 8'/%3E",
  award: "<circle cx='12' cy='9' r='5'/%3E<path d='M9 14l-1 7 4-2 4 2-1-7'/%3E",
  user: "<circle cx='12' cy='8' r='3.5'/%3E<path d='M4.5 20c1.5-3.6 4.2-5.2 7.5-5.2s6 1.6 7.5 5.2'/%3E",
  check: "<path d='M5 12l5 5 9-10'/%3E",
  trash: "<path d='M5 7h14M9 7V5h6v2M7 7l1 13h8l1-13'/%3E",
  link: "<path d='M10 13a4 4 0 0 0 6 0l2-2a4 4 0 0 0-6-6l-1 1'/%3E<path d='M14 11a4 4 0 0 0-6 0l-2 2a4 4 0 0 0 6 6l1-1'/%3E",
  logout: "<path d='M14 5H7a2 2 0 0 0-2 2v10a2 2 0 0 0 2 2h7'/%3E<path d='M17 8l4 4-4 4M21 12h-9'/%3E",
  more: "<circle cx='6' cy='12' r='1.4'/%3E<circle cx='12' cy='12' r='1.4'/%3E<circle cx='18' cy='12' r='1.4'/%3E",
  sync: "<path d='M4 12a8 8 0 0 1 13.7-5.7'/%3E<path d='M20 12a8 8 0 0 1-13.7 5.7'/%3E<path d='M18 3v4h-4M6 21v-4h4'/%3E"
}

function build(name, color) {
  const body = PATHS[name] || PATHS.more
  const c = String(color || '#64748B').replace('#', '%23')
  return "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24'"
    + " fill='none' stroke='" + c + "' stroke-width='1.7' stroke-linecap='round'"
    + " stroke-linejoin='round'%3E" + body + "%3C/svg%3E"
}

Component({
  properties: {
    name: { type: String, value: '' },
    size: { type: Number, value: 32 },        // rpx
    color: { type: String, value: '#64748B' }
  },

  // 路径拼接放在 wxml 里(见 index.wxml): observer 在初始化阶段不保证触发
  data: {}
})
