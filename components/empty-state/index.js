/**
 * 卡片式空状态组件 (设计规范 §3.8)
 * 白卡 + 淡蓝图标圆底 + 加粗标题 + 灰色副文案 + 可选操作按钮
 * 用法: <empty-state icon="doc" title="暂无考试安排" desc="2026-2027-1 暂时没有考试安排"
 *                    action-text="获取考试安排" bind:action="onRefresh" />
 * (旧调用传 emoji 时会自动映射成线性图标, 见 EMOJI_MAP)
 */
const EMOJI_MAP = {
  '📝': 'file', '📋': 'file', '⏳': 'hourglass', '🖼️': 'image', '🖼': 'image',
  '🔎': 'search', '📊': 'chart',
  '🏫': 'building', '🔐': 'secured', '🎓': 'certificate', '📢': 'notification',
  '✏️': 'edit', '✏': 'edit', '👤': 'user', '⏰': 'time', '📅': 'calendar',
  doc: 'file', clipboard: 'file', lock: 'secured', award: 'star',
  megaphone: 'notification', clock: 'time'
}

Component({
  options: {
    styleIsolation: 'apply-shared'
  },

  properties: {
    icon: { type: String, value: '📋' },
    title: { type: String, value: '' },
    desc: { type: String, value: '' },
    actionText: { type: String, value: '' },
    showAction: { type: Boolean, value: true }
  },

  data: { iconName: 'more' },

  observers: {
    icon(v) {
      this.setData({ iconName: EMOJI_MAP[v] || v || 'more' })
    }
  },

  methods: {
    onAction() {
      this.triggerEvent('action')
    }
  }
})
