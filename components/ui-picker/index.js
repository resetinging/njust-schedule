Component({
  options: {
    multipleSlots: true,
    styleIsolation: 'apply-shared'
  },

  properties: {
    range: { type: Array, value: [] },
    rangeKey: { type: String, value: '' },
    value: { type: Number, optionalTypes: [String], value: 0 },
    title: { type: String, value: '请选择' },
    disabled: { type: Boolean, value: false }
  },

  data: {
    visible: false,
    options: [],
    pickerValue: [0]
  },

  observers: {
    'range, rangeKey': function (range, rangeKey) {
      const list = Array.isArray(range) ? range : []
      const options = list.map((item, index) => ({
        label: rangeKey && item && typeof item === 'object' ? item[rangeKey] : String(item),
        value: index
      }))
      this.setData({ options })
    },
    value(value) {
      const index = Number(value)
      this.setData({ pickerValue: [Number.isFinite(index) ? index : 0] })
    }
  },

  methods: {
    /** 上报选择器可见性，供页面统一隐藏浮动底栏（与弹层同一责任层） */
    _notify(visible) {
      this.triggerEvent('visiblechange', { visible: !!visible })
    },

    open() {
      if (!this.data.disabled) {
        this.setData({ visible: true })
        this._notify(true)
      }
    },

    onConfirm(e) {
      const columns = (e.detail && e.detail.columns) || []
      const index = columns.length ? columns[0].index : Number((e.detail.value || [0])[0])
      this.setData({ visible: false, pickerValue: [index] })
      this._notify(false)
      this.triggerEvent('change', { value: String(index) })
    },

    onCancel() {
      this.setData({ visible: false })
      this._notify(false)
      this.triggerEvent('cancel')
    },

    onVisibleChange(e) {
      const visible = !!(e.detail && e.detail.visible)
      this.setData({ visible })
      this._notify(visible)
    }
  }
})
