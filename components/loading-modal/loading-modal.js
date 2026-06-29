/**
 * 加载/进度弹窗组件
 *
 * 属性:
 *   visible: 是否显示
 *   title: 标题
 *   message: 消息文字
 *   showProgress: 显示进度条
 *   percent: 进度百分比 (0-100)
 *   spinning: 显示旋转动画
 *   done: 显示完成按钮
 *   doneText: 完成按钮文字
 *
 * 事件:
 *   bind:close → 点击完成按钮
 */

Component({
  properties: {
    visible: { type: Boolean, value: false },
    title: { type: String, value: '加载中' },
    message: { type: String, value: '' },
    showProgress: { type: Boolean, value: false },
    percent: { type: Number, value: 0 },
    spinning: { type: Boolean, value: true },
    done: { type: Boolean, value: false },
    doneText: { type: String, value: '完成' }
  },

  methods: {
    onClose() {
      this.triggerEvent('close')
    }
  }
})
