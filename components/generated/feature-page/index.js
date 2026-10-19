Component({
  options: { styleIsolation: 'apply-shared' },
  properties: {
    state: { type: Object, value: {} },
    pageData: { type: Object, value: {} },
    computed: { type: Object, value: {} },
    env: { type: Object, value: {} }
  },
  methods: {
    onAction(e) {
      const data = Object.assign({}, e.currentTarget.dataset || {})
      const action = data.action || ''
      delete data.action
      this.triggerEvent('action', { action, data })
    }
  }
})
