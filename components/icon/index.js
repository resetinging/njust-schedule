/**
 * 线性图标组件 — 资源来自 .miniapp/static/icons/<name>-<tone>.png
 *
 * 用法: <icon name="refresh" size="32" color="#3157D5" />
 * color 只用于选择色调档位(grey/slate/indigo/white)；具体档位与资源兜底策略
 * 在 index.wxml 的 wxs 里（tone/file），并由 tools/test_icon_assets.js 回归：
 * 枚举全部 WXML 用法，校验解析结果都指向真实存在的 PNG。
 *
 * 注意：小程序 image 对 data-URI SVG 支持不稳定，因此这里不做内联 SVG 渲染。
 */
Component({
  properties: {
    name: { type: String, value: '' },
    size: { type: Number, value: 32 },        // rpx
    color: { type: String, value: '#64748B' }
  },

  // 路径拼接放在 wxml 里(见 index.wxml): observer 在初始化阶段不保证触发
  data: {}
})
