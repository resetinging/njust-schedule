const content = require('../../utils/content-board')

function formatUpdated(value) {
  const text = String(value || '')
  return text.length >= 16 ? text.slice(5, 16) : text
}

Component({
  options: {
    styleIsolation: 'apply-shared'
  },

  data: {
    activeTab: 'announcements',
    loading: true,
    errorMsg: '',
    updated: '',
    announcements: [],
    featured: null,
    announcementRest: [],
    changelog: [],
    community: { name: '', qq: '', note: '' },
    expandedID: '',
    copied: false
  },

  lifetimes: {
    attached() {
      this._load(true)
    },
    detached() {
      if (this._copyTimer) clearTimeout(this._copyTimer)
    }
  },

  methods: {
    activate() {
      // 二级页入场动画由 main 的 tool-layer 统一播放；这里保留空实现
      // 以便 main 的激活握手（typeof comp.activate === 'function'）一次成功、不触发重试。
    },

    onBack() {
      this.triggerEvent('close')
    },

    onTab(e) {
      const tab = e.currentTarget.dataset.tab
      if (tab && tab !== this.data.activeTab) this.setData({ activeTab: tab })
    },

    onToggleAnnouncement(e) {
      const id = e.currentTarget.dataset.id
      if (!id) return
      this.setData({ expandedID: this.data.expandedID === id ? '' : id })
    },

    onCopyQQ() {
      const qq = this.data.community.qq
      if (!qq) return
      wx.setClipboardData({
        data: qq,
        success: () => {
          if (this._copyTimer) clearTimeout(this._copyTimer)
          this.setData({ copied: true })
          this._copyTimer = setTimeout(() => {
            this._copyTimer = null
            this.setData({ copied: false })
          }, 1400)
        }
      })
    },

    onRetry() {
      this._load(true)
    },

    _load(force) {
      if (!this.data.announcements.length) this.setData({ loading: true, errorMsg: '' })
      content.load(force).then(board => {
        const announcements = (board.announcements || []).map(item => Object.assign({}, item, {
          long: String(item.body || '').length > 80
        }))
        const featured = announcements.find(item =>
          item.priority === 'important' || item.priority === 'urgent' || item.pinned
        ) || null
        const announcementRest = featured
          ? announcements.filter(item => item.id !== featured.id)
          : announcements
        const community = board.community || { name: '', qq: '', note: '' }
        this.setData({
          loading: false,
          errorMsg: announcements.length || board.changelog.length || community.qq
            ? ''
            : '暂无内容',
          updated: formatUpdated(board.updated),
          announcements,
          featured,
          announcementRest,
          changelog: board.changelog || [],
          community
        })
        if (board.updated) {
          content.markSeen(board.updated)
          this.triggerEvent('seen', { updated: board.updated })
        }
      }).catch(() => {
        this.setData({
          loading: false,
          errorMsg: '信息加载失败'
        })
      })
    }
  }
})
