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
    open() {
      if (!this.data.disabled) this.setData({ visible: true })
    },

    onConfirm(e) {
      const columns = (e.detail && e.detail.columns) || []
      const index = columns.length ? columns[0].index : Number((e.detail.value || [0])[0])
      this.setData({ visible: false, pickerValue: [index] })
      this.triggerEvent('change', { value: String(index) })
    },

    onCancel() {
      this.setData({ visible: false })
      this.triggerEvent('cancel')
    },

    onVisibleChange(e) {
      this.setData({ visible: !!(e.detail && e.detail.visible) })
    }
  }
})
