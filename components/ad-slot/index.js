const analytics = require('../../utils/analytics')

const NO_FILL_ERROR = 1004

function eventContext(component) {
  return {
    slot_id: component.data.slotId,
    page: component.data.page,
    ad_type: component.data.adType
  }
}

Component({
  options: {
    styleIsolation: 'apply-shared'
  },

  properties: {
    unitId: { type: String, value: '' },
    slotId: { type: String, value: '' },
    page: { type: String, value: '' },
    adType: { type: String, value: 'native' },
    // 只控制广告槽位最小高度，原生广告内部版式仍由微信广告平台决定。
    height: { type: String, value: '' }
  },

  data: {
    loaded: false
  },

  lifetimes: {
    attached() {
      if (!this.data.unitId) return
      analytics.track('ad_request', eventContext(this))
    }
  },

  methods: {
    onAdLoad() {
      if (this.data.loaded) return
      this.setData({ loaded: true })
      analytics.track('ad_loaded', eventContext(this))
      analytics.track('ad_impression', eventContext(this))
    },

    onAdError(event) {
      const detail = event && event.detail ? event.detail : {}
      const code = Number(detail.errCode) || 0
      analytics.track('ad_failed', Object.assign(eventContext(this), {
        result: 'error',
        kind: String(code),
        source: 'ad-custom'
      }))
      if (code !== NO_FILL_ERROR) {
        console.warn('[ad-slot] 广告加载失败', this.data.slotId, code)
      }
    },

    onAdClose() {
      analytics.track('ad_close', eventContext(this))
    }
  }
})
