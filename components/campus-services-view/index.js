const api = require('../../utils/api')
const storage = require('../../utils/storage')
const analytics = require('../../utils/analytics')

const CATEGORIES = [
  { key: 'operator', label: '校园卡', icon: 'grid', tone: 'brand' },
  { key: 'exam', label: '考研', icon: 'clipboard', tone: 'success' },
  { key: 'graduate', label: '保研', icon: 'award', tone: 'violet' },
  { key: 'materials', label: '期末复习', icon: 'book', tone: 'signal' }
]

const CATEGORY_MAP = {
  operator: { label: '校园卡', icon: 'grid', tone: 'brand' },
  exam: { label: '考研', icon: 'clipboard', tone: 'success' },
  graduate: { label: '保研', icon: 'award', tone: 'violet' },
  materials: { label: '期末复习', icon: 'book', tone: 'signal' }
}

const CAMPUS_MAP = {
  all: '全部校区',
  nanjing: '南京校区',
  jiangyin: '江阴校区'
}

const listCache = Object.create(null)
const LIST_CACHE_TTL = 60 * 1000

function validPhone(value) {
  return /^1[3-9][0-9]{9}$/.test(String(value || '').replace(/[\s-]/g, ''))
}

function validWechat(value) {
  return /^[A-Za-z0-9][A-Za-z0-9_-]{2,39}$/.test(String(value || '').trim())
}

function canTryLead() {
  return storage.hasSession() || !!(
    storage.getStudentId() && storage.get('saved_password', '')
  )
}

Component({
  options: { styleIsolation: 'apply-shared' },

  properties: {
    embedded: { type: Boolean, value: true }
  },

  data: {
    categories: CATEGORIES,
    skeletonRows: [1, 2, 3],
    activeCategory: CATEGORIES[0].key,
    services: [],
    loading: true,
    loaded: false,
    errorMsg: '',
    total: 0,
    page: 1,
    pageSize: 30,
    hasMore: false,

    showSheet: false,
    sheetMode: 'detail',
    selectedService: null,
    detailLoading: false,
    detailError: '',

    contactType: 'phone',
    contact: '',
    note: '',
    consent: false,
    submitting: false,
    submitError: ''
  },

  lifetimes: {
    attached() {
      this._listSeq = 0
      this._detailSeq = 0
      this._leadSeq = 0
    },
    detached() {
      this._listSeq = (this._listSeq || 0) + 1
      this._detailSeq = (this._detailSeq || 0) + 1
      this._leadSeq = (this._leadSeq || 0) + 1
    }
  },

  methods: {
    activate() {
      if (!this.data.loaded || this.data.errorMsg) this.loadServices(true)
    },

    onBack() {
      this._closeSheet()
      this.triggerEvent('close')
    },

    onCategoryTap(e) {
      const category = e.currentTarget.dataset.category || CATEGORIES[0].key
      if (category === this.data.activeCategory) return
      this.setData({ activeCategory: category })
      analytics.featureAction('services', 'services', {
        action: 'category',
        kind: category
      })
      this.loadServices(true)
    },

    loadServices(reset) {
      const category = this.data.activeCategory || CATEGORIES[0].key
      const page = reset ? 1 : this.data.page + 1
      const cacheKey = category
      let showedCache = false
      if (reset) {
        const cached = listCache[cacheKey]
        if (cached && Date.now() - cached.at < LIST_CACHE_TTL) {
          this._applyServices(cached.items, cached.total, 1, !!cached.hasMore)
          showedCache = true
        }
      }
      const seq = (this._listSeq || 0) + 1
      this._listSeq = seq
      const patch = {
        loading: true,
        errorMsg: ''
      }
      if (reset && !showedCache) {
        patch.services = []
        patch.total = 0
        patch.page = 1
        patch.hasMore = false
        patch.loaded = false
      }
      this.setData(patch)
      api.listCampusServices({
        category,
        page,
        pageSize: this.data.pageSize
      }).then((res) => {
        if (seq !== this._listSeq) return
        if (!res || res.success === false) {
          this.setData({
            loading: false,
            loaded: !!this.data.loaded,
            errorMsg: (res && res.message) || '校园服务加载失败，请稍后重试'
          })
          return
        }
        const incoming = (res.services || []).map((item) => this._decorateService(item))
        const items = reset ? incoming : this.data.services.concat(incoming)
        listCache[cacheKey] = {
          at: Date.now(),
          items,
          total: Number(res.total) || 0,
          hasMore: !!res.has_more
        }
        this._applyServices(items, res.total, page, res.has_more)
      }).catch(() => {
        if (seq !== this._listSeq) return
        this.setData({
          loading: false,
          loaded: !!this.data.loaded,
          errorMsg: '网络异常，请稍后再试'
        })
      })
    },

    _applyServices(items, total, page, hasMore) {
      this.setData({
        services: items || [],
        total: Number(total) || 0,
        page: Number(page) || 1,
        hasMore: !!hasMore,
        loading: false,
        loaded: true,
        errorMsg: ''
      })
    },

    _decorateService(item) {
      const value = item || {}
      const category = CATEGORY_MAP[value.category] || {
        label: '校园服务', icon: 'grid', tone: 'brand'
      }
      return Object.assign({}, value, {
        categoryLabel: category.label,
        categoryIcon: category.icon,
        categoryTone: category.tone,
        campusText: CAMPUS_MAP[value.campus_scope] || '全部校区',
        validityText: value.end_date ? '有效至 ' + value.end_date : '长期有效'
      })
    },

    onRefresh() {
      if (this.data.loading) return
      delete listCache[this.data.activeCategory || CATEGORIES[0].key]
      this.loadServices(true)
    },

    onRetry() {
      if (!this.data.loading) this.loadServices(true)
    },

    onScrollToLower() {
      if (!this.data.loading && this.data.hasMore) this.loadServices(false)
    },

    onOpenService(e) {
      const index = Number(e.currentTarget.dataset.index)
      const summary = this.data.services[index]
      if (!summary || !summary.id) return
      const seq = (this._detailSeq || 0) + 1
      this._detailSeq = seq
      this.setData({
        showSheet: true,
        sheetMode: 'detail',
        selectedService: summary,
        detailLoading: true,
        detailError: '',
        submitting: false,
        submitError: ''
      })
      this._syncPopupState(true)
      analytics.featureAction('services', 'services', {
        action: 'service_open',
        kind: summary.category || 'unknown'
      })
      api.getCampusService(summary.id).then((res) => {
        if (seq !== this._detailSeq) return
        if (!res || res.success === false) {
          this.setData({
            detailLoading: false,
            detailError: (res && res.message) || '服务详情加载失败'
          })
          return
        }
        const detail = this._decorateService(res.service || summary)
        this.setData({
          selectedService: detail,
          detailLoading: false,
          detailError: ''
        })
      }).catch(() => {
        if (seq !== this._detailSeq) return
        this.setData({ detailLoading: false, detailError: '网络异常，请稍后再试' })
      })
    },

    onDetailRetry() {
      const service = this.data.selectedService
      if (!service || !service.id || this.data.detailLoading) return
      this.onOpenService({ currentTarget: { dataset: {
        index: this.data.services.findIndex((item) => item.id === service.id)
      } } })
    },

    onCloseSheet() {
      this._closeSheet()
    },

    onSheetVisibleChange(e) {
      if (!(e && e.detail && e.detail.visible)) this._closeSheet()
    },

    _closeSheet() {
      if (!this.data.showSheet) return
      this._detailSeq = (this._detailSeq || 0) + 1
      this._leadSeq = (this._leadSeq || 0) + 1
      this.setData({
        showSheet: false,
        detailLoading: false,
        detailError: '',
        submitting: false,
        submitError: ''
      })
      this._syncPopupState(false)
    },

    _syncPopupState(open) {
      this.triggerEvent('popupstate', { open: !!open })
    },

    onStartLead() {
      if (!this.data.selectedService) return
      if (!canTryLead()) {
        analytics.featureAction('services', 'services', { action: 'login_required' })
        this._closeSheet()
        this.triggerEvent('login')
        return
      }
      this.setData({
        sheetMode: 'lead',
        contactType: 'phone',
        contact: '',
        note: '',
        consent: false,
        submitting: false,
        submitError: ''
      })
      analytics.featureAction('services', 'services', { action: 'lead_open' })
    },

    onBackToDetail() {
      if (this.data.submitting) return
      this.setData({ sheetMode: 'detail', submitError: '' })
    },

    onContactTypeTap(e) {
      const type = e.currentTarget.dataset.type
      if (type !== 'phone' && type !== 'wechat') return
      this.setData({ contactType: type, contact: '', submitError: '' })
    },

    onContactInput(e) {
      this.setData({ contact: (e.detail && e.detail.value) || '', submitError: '' })
    },

    onNoteInput(e) {
      this.setData({ note: (e.detail && e.detail.value) || '' })
    },

    onToggleConsent() {
      this.setData({ consent: !this.data.consent, submitError: '' })
    },

    onSubmitLead() {
      if (this.data.submitting || !this.data.selectedService) return
      const contact = String(this.data.contact || '').trim()
      if (this.data.contactType === 'phone' ? !validPhone(contact) : !validWechat(contact)) {
        this.setData({
          submitError: this.data.contactType === 'phone'
            ? '请输入有效的 11 位手机号'
            : '微信号需为 3-40 位字母、数字、下划线或短横线'
        })
        return
      }
      if (!this.data.consent) {
        this.setData({ submitError: '请先同意将联系方式提供给该服务商' })
        return
      }
      const seq = (this._leadSeq || 0) + 1
      this._leadSeq = seq
      this.setData({ submitting: true, submitError: '' })
      api.submitCampusServiceLead(this.data.selectedService.id, {
        contactType: this.data.contactType,
        contact,
        note: String(this.data.note || '').trim(),
        consent: true
      }).then((res) => {
        if (seq !== this._leadSeq) return
        if (!res || res.success === false) {
          if (res && res.offline) {
            this._closeSheet()
            this.triggerEvent('login')
            return
          }
          this.setData({
            submitting: false,
            submitError: (res && res.message) || '咨询提交失败，请稍后再试'
          })
          return
        }
        this.setData({ submitting: false, sheetMode: 'success' })
        analytics.featureAction('services', 'services', {
          action: 'lead_submit',
          kind: this.data.selectedService.category || 'unknown'
        })
      }).catch(() => {
        if (seq !== this._leadSeq) return
        this.setData({ submitting: false, submitError: '网络异常，请稍后再试' })
      })
    }
  }
})
