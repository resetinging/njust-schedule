/**
 * 留言板视图组件 — 方案A 合页 swiper 的第 6 个 Tab
 * 顶部: 系统公告(置顶); 下方: 留言列表 + 发布框
 * 生命周期: attached 首次挂载; activate 每次激活(刷新留言与公告)
 */

const api = require('../../utils/api')
const storage = require('../../utils/storage')

Component({
  options: {
    styleIsolation: 'apply-shared'
  },

  data: {
    active: false,        // 懒渲染
    loading: true,
    messages: [],
    hasMore: false,
    content: '',
    sending: false,
    errorMsg: '',
    announcement: ''     // 置顶公告(公开, 未登录也显示)
  },

  lifetimes: {
    attached() {
      this._loadAnnouncement()
      if (storage.isLoggedIn()) {
        this.loadMessages()
      } else {
        this.setData({ loading: false, errorMsg: '请先登录后查看留言板' })
      }
    }
  },

  methods: {
    /** 由 main 页面调用: 每次激活 */
    activate() {
      this.setData({ active: true })
      this._loadAnnouncement()   // 公告置顶, 公开刷新
      if (storage.isLoggedIn()) {
        this.loadMessages()      // 每次进入刷新留言
      } else {
        this.setData({ loading: false, errorMsg: '请先登录后查看留言板', messages: [] })
      }
    },

    /** 加载置顶公告(公开接口; 缓存兜底) */
    _loadAnnouncement() {
      const cached = storage.getCached('cached_announcement')
      if (cached && cached.enabled && cached.text && !this.data.announcement) {
        this.setData({ announcement: cached.text })
      }
      api.getAnnouncement().then(res => {
        if (res && res.success) {
          storage.setCached('cached_announcement', { t: Date.now(), enabled: res.enabled, text: res.text })
          this.setData({ announcement: (res.enabled && res.text) ? res.text : '' })
        }
      }).catch(() => {})
    },

    /** 加载最新一页留言 */
    async loadMessages() {
      this.setData({ loading: true, errorMsg: '' })
      try {
        const res = await api.getBoardMessages(0)
        if (res.success) {
          this.setData({
            loading: false,
            messages: res.messages || [],
            hasMore: !!res.has_more,
            errorMsg: (res.messages || []).length ? '' : '还没有留言，快来抢沙发～'
          })
        } else {
          this.setData({ loading: false, errorMsg: res.message || '加载失败' })
        }
      } catch (e) {
        this.setData({ loading: false, errorMsg: '加载失败' })
      }
    },

    /** 滚动到底加载更早留言 */
    async loadMore() {
      if (!this.data.hasMore || this.data.loading) return
      const last = this.data.messages[this.data.messages.length - 1]
      if (!last) return
      this.setData({ loading: true })
      try {
        const res = await api.getBoardMessages(last.id)
        if (res.success) {
          this.setData({
            loading: false,
            messages: this.data.messages.concat(res.messages || []),
            hasMore: !!res.has_more
          })
        } else {
          this.setData({ loading: false })
        }
      } catch (e) {
        this.setData({ loading: false })
      }
    },

    onInput(e) {
      this.setData({ content: e.detail.value })
    },

    /** 发布留言 */
    async onSend() {
      if (!storage.isLoggedIn()) {
        wx.showToast({ title: '请先在"我的"页面登录', icon: 'none' })
        return
      }
      const content = (this.data.content || '').trim()
      if (!content) {
        wx.showToast({ title: '请输入内容', icon: 'none' })
        return
      }
      if (this.data.sending) return
      this.setData({ sending: true })
      try {
        const res = await api.postBoardMessage(content)
        if (res.success) {
          wx.showToast({ title: '发布成功', icon: 'success' })
          this.setData({ content: '' })
          this.loadMessages()
        } else {
          wx.showToast({ title: res.message || '发布失败', icon: 'none' })
        }
      } catch (e) {
        wx.showToast({ title: '发布失败', icon: 'none' })
      } finally {
        this.setData({ sending: false })
      }
    },

    goLogin() {
      // 通知 main 切到"我的" Tab
      const pages = getCurrentPages()
      const page = pages[pages.length - 1]
      if (page && typeof page.onTabTap === 'function') {
        page.onTabTap(5)
      }
    }
  }
})
