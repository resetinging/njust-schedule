/**
 * 留言板视图组件(第6个Tab) — 贴吧式
 * 顶部公告置顶; 排序切换(最新/最热); 留言点赞+评论+匿名
 */

const api = require('../../utils/api')
const storage = require('../../utils/storage')

Component({
  options: {
    styleIsolation: 'apply-shared'
  },

  data: {
    active: false,
    loading: true,
    messages: [],
    hasMore: false,
    sort: 'time',          // 'time' 最新 | 'likes' 最热
    content: '',
    sending: false,
    errorMsg: '',
    announcement: '',
    annExpanded: false,   // 公告默认折叠为一行, 点击展开全部
    annLong: false,       // 公告是否长到需要折叠(短公告不显示展开提示)

    // 评论弹窗
    showComments: false,
    commentMsgId: 0,
    comments: [],
    commentText: '',
    commentSending: false
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
    activate() {
      this.setData({ active: true })
      this._loadAnnouncement()
      if (storage.isLoggedIn()) {
        this.loadMessages()
      } else {
        this.setData({ loading: false, errorMsg: '请先登录后查看留言板', messages: [] })
      }
    },

    _loadAnnouncement() {
      const cached = storage.getCached('cached_announcement')
      if (cached && cached.enabled && cached.text && !this.data.announcement) {
        this._setAnnouncement(cached.text)
      }
      api.getAnnouncement().then(res => {
        if (res && res.success) {
          storage.setCached('cached_announcement', { t: Date.now(), enabled: res.enabled, text: res.text })
          this._setAnnouncement((res.enabled && res.text) ? res.text : '')
        }
      }).catch(() => {})
    },

    /** 设置公告: 超过 20 字默认折叠为一行(点击展开) */
    _setAnnouncement(text) {
      this.setData({
        announcement: text || '',
        annLong: (text || '').length > 20,
        annExpanded: false
      })
    },

    /** 点击公告切换展开/收起 */
    onToggleAnnounce() {
      if (!this.data.annLong) return
      this.setData({ annExpanded: !this.data.annExpanded })
    },

    /** 加载留言(当前排序) */
    async loadMessages() {
      this.setData({ loading: true, errorMsg: '' })
      try {
        const res = await api.getBoardMessages(0, this.data.sort)
        if (res.success) {
          this.setData({
            loading: false,
            messages: res.messages || [],
            hasMore: !!res.has_more,
            errorMsg: ''
          })
        } else {
          this.setData({ loading: false, errorMsg: res.message || '加载失败' })
        }
      } catch (e) {
        this.setData({ loading: false, errorMsg: '加载失败' })
      }
    },

    async loadMore() {
      if (!this.data.hasMore || this.data.loading) return
      const last = this.data.messages[this.data.messages.length - 1]
      if (!last) return
      this.setData({ loading: true })
      try {
        const res = await api.getBoardMessages(last.id, this.data.sort)
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

    /** 排序切换: 最新 / 最热 */
    onSortChange(e) {
      const sort = e.currentTarget.dataset.sort
      if (sort === this.data.sort) return
      this.setData({ sort })
      this.loadMessages()
    },

    onInput(e) {
      this.setData({ content: e.detail.value })
    },

    /** 发布留言(强制匿名) */
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

    /** 点赞/取消 */
    async onLike(e) {
      if (!storage.isLoggedIn()) {
        wx.showToast({ title: '请先登录', icon: 'none' })
        return
      }
      const id = e.currentTarget.dataset.id
      try {
        const res = await api.toggleBoardLike(id)
        if (res.success) {
          // 本地更新该条点赞状态
          const messages = this.data.messages.map(m =>
            m.id === id ? { ...m, likes: res.likes, liked_by_me: res.liked } : m)
          this.setData({ messages })
        } else {
          wx.showToast({ title: res.message || '操作失败', icon: 'none' })
        }
      } catch (e) {
        wx.showToast({ title: '网络异常，请重试', icon: 'none' })
      }
    },

    /** 打开评论弹窗 */
    async onOpenComments(e) {
      if (!storage.isLoggedIn()) {
        wx.showToast({ title: '请先登录', icon: 'none' })
        return
      }
      const id = e.currentTarget.dataset.id
      this.setData({ showComments: true, commentMsgId: id, comments: [], commentText: '' })
      try {
        const res = await api.getBoardComments(id)
        if (res.success) {
          this.setData({ comments: res.comments || [] })
        }
      } catch (e) {
        // 忽略
      }
    },

    closeComments() {
      this.setData({ showComments: false, commentMsgId: 0, comments: [] })
    },

    onCommentInput(e) {
      this.setData({ commentText: e.detail.value })
    },

    /** 发表评论(强制匿名) */
    async onSendComment() {
      const content = (this.data.commentText || '').trim()
      if (!content) {
        wx.showToast({ title: '请输入评论内容', icon: 'none' })
        return
      }
      if (this.data.commentSending) return
      this.setData({ commentSending: true })
      try {
        const res = await api.postBoardComment(this.data.commentMsgId, content)
        if (res.success) {
          this.setData({
            commentText: '',
            comments: this.data.comments.concat([res.comment])
          })
          // 更新列表评论数
          const messages = this.data.messages.map(m =>
            m.id === this.data.commentMsgId ? { ...m, comments: (m.comments || 0) + 1 } : m)
          this.setData({ messages })
          wx.showToast({ title: '评论成功', icon: 'success' })
        } else {
          wx.showToast({ title: res.message || '评论失败', icon: 'none' })
        }
      } catch (e) {
        wx.showToast({ title: '评论失败', icon: 'none' })
      } finally {
        this.setData({ commentSending: false })
      }
    },

    goLogin() {
      const pages = getCurrentPages()
      const page = pages[pages.length - 1]
      if (page && typeof page.onTabTap === 'function') {
        page.onTabTap(5)
      }
    },

    /** 空操作: 阻止弹窗内点击冒泡关闭(catchtap 需要真实方法) */
    noop() {}
  }
})
