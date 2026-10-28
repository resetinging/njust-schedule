/**
 * 图书馆公共馆藏查询页（页面内二级视图）
 * - 检索：书名/作者/ISBN/索书号，明确提交后才请求；服务端分页，支持加载更多/重试/无结果；
 * - 详情：点击书目后才按需请求逐册馆藏；支持全部/南京/江阴筛选，统计与明细一致；
 * - 竞态：搜索与详情各用请求序号守卫，旧响应不覆盖新搜索/已关闭详情；
 * - 数据：仅内存态，不落用户缓存；不保存搜索词。
 */
const api = require('../../utils/api')
const analytics = require('../../utils/analytics')

const FIELDS = [
  { key: 'title', label: '书名', placeholder: '如：高等数学' },
  { key: 'author', label: '作者', placeholder: '如：杨海涛' },
  { key: 'isbn', label: 'ISBN', placeholder: '如：978-7-5608-5255-3' },
  { key: 'callno', label: '索书号', placeholder: '如：O13/797' }
]

const CAMPUS_OPTIONS = [
  { key: 'all', label: '全部' },
  { key: 'nanjing', label: '南京' },
  { key: 'jiangyin', label: '江阴' }
]

function pad2(value) {
  return value < 10 ? '0' + value : '' + value
}

function formatUpdatedAt(unixSeconds) {
  const ts = Number(unixSeconds) || 0
  if (!ts) return ''
  try {
    const d = new Date(ts * 1000)
    return (d.getMonth() + 1) + '-' + pad2(d.getDate()) + ' ' + pad2(d.getHours()) + ':' + pad2(d.getMinutes())
  } catch (e) {
    return ''
  }
}

function safeMessage(res, fallback) {
  if (res && typeof res.message === 'string' && res.message) return res.message
  return fallback
}

Component({
  options: { styleIsolation: 'apply-shared' },

  properties: {
    embedded: { type: Boolean, value: true }
  },

  data: {
    statusBarHeight: 20,
    navBarHeight: 44,
    navRight: 96,
    fields: FIELDS,
    fieldIndex: 0,
    keyword: '',
    loading: false,
    searched: false,
    errorMsg: '',
    total: 0,
    page: 1,
    pageSize: 20,
    hasMore: false,
    records: [],
    searchStale: false,
    searchUpdatedText: '',

    // 详情弹层
    showDetail: false,
    detailLoading: false,
    detailError: '',
    detailRecord: null,
    detailTotal: 0,
    detailAvailable: 0,
    detailStale: false,
    detailUpdatedText: '',
    campusScope: 'all',
    campusOptions: CAMPUS_OPTIONS,
    campusCounts: { all: 0, nanjing: 0, jiangyin: 0, unknown: 0 },
    copies: []
  },

  lifetimes: {
    attached() {
      this._searchSeq = 0
      this._detailSeq = 0
      let statusBarHeight = 20
      let navBarHeight = 44
      let navRight = 96
      try {
        const win = wx.getWindowInfo()
        const menu = wx.getMenuButtonBoundingClientRect()
        statusBarHeight = win.statusBarHeight || statusBarHeight
        if (menu && menu.height && menu.top) {
          navBarHeight = (menu.top - statusBarHeight) * 2 + menu.height
          navRight = Math.max(88, win.windowWidth - menu.left + 8)
        }
      } catch (e) { /* 使用安全默认值 */ }
      this.setData({ statusBarHeight, navBarHeight, navRight })
    },
    detached() {
      // 组件卸载后任何晚到响应都不得再 setData
      this._searchSeq = (this._searchSeq || 0) + 1
      this._detailSeq = (this._detailSeq || 0) + 1
    }
  },

  methods: {
    /** main 打开假页后调用；本页不自动联网，等用户明确提交搜索。 */
    activate() {},

    onBack() {
      this.triggerEvent('close')
    },

    onFieldTap(e) {
      const index = Number(e.currentTarget.dataset.index)
      if (!(index >= 0) || index >= FIELDS.length || index === this.data.fieldIndex) return
      // 检索条件变化：页码复位，并使在途搜索失效，避免旧字段结果套在新字段下。
      // 旧列表保留到新搜索返回（避免闪烁），但不会被视为当前条件结果。
      this._searchSeq = (this._searchSeq || 0) + 1
      this.setData({ fieldIndex: index, page: 1, hasMore: false, loading: false, errorMsg: '' })
    },

    onKeywordInput(e) {
      this.setData({ keyword: (e && e.detail && e.detail.value) || '' })
    },

    onKeywordConfirm() {
      this._runSearch(1)
    },

    onSearch() {
      this._runSearch(1)
    },

    onLoadMore() {
      if (this.data.loading || !this.data.hasMore) return
      this._runSearch(this.data.page + 1)
    },

    onScrollToLower() {
      this.onLoadMore()
    },

    /** 手动刷新：只请求本服务（缓存策略由服务端决定），不构造绕过缓存的参数。 */
    onRefresh() {
      if (this.data.loading) return
      this._runSearch(1)
    },

    onRetry() {
      this._runSearch(this.data.searched ? Math.max(1, this.data.page) : 1)
    },

    _runSearch(page) {
      const keyword = String(this.data.keyword || '').trim()
      if (!keyword) {
        this.setData({ errorMsg: '请输入书名、作者、ISBN 或索书号关键词' })
        return
      }
      // 页码 >1 的加载更多在请求中不重复触发；但新搜索(页码=1)允许覆盖在途请求，
      // 由请求序号保证旧响应不覆盖新结果。
      if (this.data.loading && page > 1) return
      const field = FIELDS[this.data.fieldIndex] || FIELDS[0]
      const seq = (this._searchSeq || 0) + 1
      this._searchSeq = seq
      const patch = { loading: true, errorMsg: '', searched: true }
      if (page === 1) {
        patch.page = 1
        patch.total = 0
        patch.hasMore = false
        patch.records = []
        patch.searchStale = false
        patch.searchUpdatedText = ''
      }
      this.setData(patch)
      api.searchLibraryBooks({ field: field.key, q: keyword, page: page }).then((res) => {
        if (seq !== this._searchSeq) return
        if (!res || res.success === false) {
          this.setData({ loading: false, errorMsg: safeMessage(res, '查询失败，请稍后再试') })
          return
        }
        const incoming = (res.records || []).map((item) => this._decorateRecord(item))
        const records = page === 1 ? incoming : this.data.records.concat(incoming)
        this.setData({
          loading: false,
          searched: true,
          page: page,
          total: Number(res.total) || 0,
          hasMore: !!res.has_more,
          records: records,
          searchStale: !!res.stale,
          searchUpdatedText: formatUpdatedAt(res.updated_at)
        })
        analytics.featureAction('library', 'feature', { action: 'search', field: field.key })
      }).catch(() => {
        if (seq !== this._searchSeq) return
        this.setData({ loading: false, errorMsg: '网络异常，请稍后再试' })
      })
    },

    _decorateRecord(item) {
      const record = item || {}
      const meta = [record.author, record.publisher, record.pub_year ? record.pub_year + '年' : '']
        .filter(Boolean).join(' · ')
      const call = [record.call_no ? '索书号 ' + record.call_no : '', record.isbn ? 'ISBN ' + record.isbn : '']
        .filter(Boolean).join(' · ')
      return {
        marcNo: record.marc_no || '',
        title: record.title || '未命名书目',
        author: record.author || '',
        publisher: record.publisher || '',
        pubYear: record.pub_year || '',
        isbn: record.isbn || '',
        callNo: record.call_no || '',
        docType: record.doc_type || '图书',
        num: Number(record.num) || 0,
        metaText: meta || '出版信息未注明',
        callText: call
      }
    },

    onOpenDetail(e) {
      const index = Number(e.currentTarget.dataset.index)
      const record = this.data.records[index]
      if (!record) return
      this.setData({
        showDetail: true,
        detailRecord: record,
        detailLoading: false,
        detailError: '',
        detailTotal: 0,
        detailAvailable: 0,
        detailStale: false,
        detailUpdatedText: '',
        campusScope: 'all',
        campusCounts: { all: 0, nanjing: 0, jiangyin: 0, unknown: 0 },
        copies: []
      })
      this._syncPopupState(true)
      analytics.featureAction('library', 'feature', { action: 'item_view' })
      this._loadDetail(record, 'all')
    },

    onCampusTap(e) {
      const scope = e.currentTarget.dataset.scope
      if (!scope || !this.data.detailRecord || scope === this.data.campusScope) return
      this._loadDetail(this.data.detailRecord, scope)
    },

    _loadDetail(record, scope) {
      const seq = (this._detailSeq || 0) + 1
      this._detailSeq = seq
      this.setData({ detailLoading: true, detailError: '', campusScope: scope })
      api.getLibraryBookItems({ marcNo: record.marcNo, campus: scope }).then((res) => {
        if (seq !== this._detailSeq) return
        if (!res || res.success === false) {
          this.setData({ detailLoading: false, detailError: safeMessage(res, '馆藏加载失败，请稍后重试') })
          return
        }
        const copies = (res.copies || []).map((item) => {
          const available = !!item.available
          return {
            callNo: item.call_no || '',
            barcode: item.barcode || '',
            volume: item.volume || '',
            campus: item.campus || '未知',
            location: item.location || '馆藏地未注明',
            status: item.status || '状态未注明',
            available: available,
            statusClass: available ? 'is-available' : 'is-unavailable'
          }
        })
        const counts = res.campus_counts || {}
        const nanjing = Number(counts.nanjing) || 0
        const jiangyin = Number(counts.jiangyin) || 0
        const unknown = Number(counts.unknown) || 0
        this.setData({
          detailLoading: false,
          detailError: '',
          detailTotal: Number(res.total) || 0,
          detailAvailable: Number(res.available) || 0,
          detailStale: !!res.stale,
          detailUpdatedText: formatUpdatedAt(res.updated_at),
          campusCounts: { all: nanjing + jiangyin + unknown, nanjing: nanjing, jiangyin: jiangyin, unknown: unknown },
          copies: copies
        })
      }).catch(() => {
        if (seq !== this._detailSeq) return
        this.setData({ detailLoading: false, detailError: '网络异常，请稍后再试' })
      })
    },

    onDetailRetry() {
      if (this.data.detailLoading || !this.data.detailRecord) return
      this._loadDetail(this.data.detailRecord, this.data.campusScope)
    },

    onDetailClose() {
      if (!this.data.showDetail) return
      // 关闭后使在途详情响应失效，避免晚到响应重新打开/覆盖详情。
      this._detailSeq = (this._detailSeq || 0) + 1
      this.setData({
        showDetail: false,
        detailLoading: false,
        detailError: '',
        copies: [],
        detailRecord: null
      })
      this._syncPopupState(false)
    },

    onDetailVisibleChange(e) {
      const visible = !!(e && e.detail && e.detail.visible)
      if (!visible) this.onDetailClose()
    },

    _syncPopupState(open) {
      this.triggerEvent('popupstate', { open: !!open })
    }
  }
})
