/**
 * 验证码输入组件
 *
 * 属性:
 *   src: 验证码图片 data URI
 *
 * 事件:
 *   bind:refresh → 请求刷新验证码
 *   bind:input → 用户输入变化 { detail: { value } }
 */

Component({
  properties: {
    src: {
      type: String,
      value: ''
    },
    value: {
      type: String,
      value: ''
    }
  },

  methods: {
    onInput(e) {
      this.triggerEvent('input', { value: e.detail.value })
    },

    onRefresh() {
      this.triggerEvent('refresh')
    }
  }
})
