/**
 * 卡片式空状态组件 (设计规范 §3.8)
 * 白卡 + 紫色图标圆底 + 加粗标题 + 灰色副文案 + 可选操作按钮
 * 用法: <empty-state icon="📝" title="暂无考试安排" desc="2026-2027-1 暂时没有考试安排"
 *                    action-text="获取考试安排" bind:action="onRefresh" />
 */
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

  methods: {
    onAction() {
      this.triggerEvent('action')
    }
  }
})
