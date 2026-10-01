/**
 * 课表助手 — 小程序入口
 */

const api = require('./utils/api')
const storage = require('./utils/storage')
const config = require('./utils/config')
const freeclassCache = require('./utils/freeclass-cache')
const { BIG_SECTION_START_PERIODS, PERIOD_STARTS, bigSectionIndex } = require('./utils/period-time')

App({
  globalData: {
    isLoggedIn: false,
    studentName: '',
    semester: ''
  },

  onLaunch() {
    // 初始化微信云开发（用于云托管免域名调用）
    if (wx.cloud) {
      wx.cloud.init({
        env: config.CLOUD_ENV,
        traceUser: false
      })
    }

    // 启动时检查本地是否保存过学号（登录态以学号为准）
    if (storage.getStudentId()) {
      this.globalData.isLoggedIn = true
      this.globalData.studentName = storage.getStudentName()
      this.globalData.semester = storage.getSemester()
      // 启动不再无条件登录: 先静默校验后端会话, 只有会话失效时才自动重登一次。
      // 智慧理工侧短时间内频繁登录会被风控冻结, 后端也已加会话复用快路径。
      this._checkSession()
      // 后台预取各 Tab 页数据: 延迟启动不阻塞首屏, 滑动切换时零等待
      setTimeout(() => this._prefetchAll(), 800)
    }
  },

  /**
   * 后台预取各 Tab 页数据到本地缓存（课表/考试/评教/成绩/CET/校历状态）。
   * 仅读查询接口(不触发教务抓取), 后端有 30s 缓存兜底; 本地缓存新鲜则跳过;
   * 任何失败静默忽略, 不影响用户操作。
   */
  _prefetchAll() {
    const sid = storage.getStudentId()
    // 有学号但无 token(会话已失效/已退出)时不预取, 否则后端只会返回一串 401
    if (!sid || !storage.get('token', '')) return
    const sem = storage.getSemester()
    const ttl = config.CACHE_TTL
    const tasks = []

    // 空教室默认条件后台预热: 用户进入功能页后通常先看当天/本周,
    // 提前把查询结果写入本地缓存, 页面 onLoad 可直接渲染, 不再等网络。
    // 延后于课表等主数据, 避免抢占首屏请求。
    setTimeout(() => {
      const slotIndex = bigSectionIndex()
      const jc1 = BIG_SECTION_START_PERIODS[slotIndex]
      const jc2 = slotIndex >= BIG_SECTION_START_PERIODS.length - 1
        ? PERIOD_STARTS.length
        : BIG_SECTION_START_PERIODS[slotIndex + 1] - 1
      freeclassCache.warm({
        campus: '孝陵卫',
        jc1,
        jc2,
        semester: sem || ''
      }).catch(() => {})
    }, 900)

    // 课表（缓存键带学期）
    const coursesKey = 'cached_courses_' + (sem || 'default')
    if (storage.getCacheAge(coursesKey) > ttl.courses) {
      tasks.push(api.getCourses(sem).then((res) => {
        if (res && res.success && res.courses) {
          const cs = res.semester || sem || 'default'
          storage.setCached('cached_courses_' + cs, res.courses)
          storage.setSemester(cs)
          this.globalData.semester = cs
        }
      }))
    }

    // 考试（缓存键带学期）
    const examsKey = 'cached_exams_' + (sem || 'default')
    if (storage.getCacheAge(examsKey) > ttl.exams) {
      tasks.push(api.getExams(sem).then((res) => {
        if (res && res.success && res.exams) {
          storage.setCached('cached_exams_' + (res.semester || sem || 'default'), res.exams)
        }
      }))
    }

    // 评教
    if (storage.getCacheAge('cached_evaluations') > ttl.evaluations) {
      tasks.push(api.getEvalBatches().then((res) => {
        if (res && res.success && res.evaluations) storage.setCached('cached_evaluations', res)
      }))
    }

    // 成绩
    if (storage.getCacheAge('cached_grades') > ttl.grades) {
      tasks.push(api.getGrades('__all__').then((res) => {
        if (res && res.success) storage.setCached('cached_grades', res)
      }))
    }

    // 四六级
    if (storage.getCacheAge('cached_cet_scores') > ttl.cet) {
      tasks.push(api.getCetScores().then((res) => {
        if (res && res.success) storage.setCached('cached_cet_scores', res)
      }))
    }

    // 校历状态（第一周日期等, 课表页定位本周用; 后端按学期存储）
    const statusKey = 'cached_status_' + sid + '_' + (sem || 'default')
    if (storage.getCacheAge(statusKey) > ttl.status) {
      tasks.push(api.getStatus().then((res) => {
        if (res && res.first_week_date) {
          storage.setCached(statusKey, { t: Date.now(), first_week_date: res.first_week_date })
        }
      }))
    }

    if (tasks.length) {
      // 全部静默: 任一失败不影响其他
      Promise.all(tasks.map(p => p.catch(() => {})))
    }
  },

  /** 静默校验后端会话: 失效时先尝试自动重登(记住密码), 失败才提示 */
  _checkSession() {
    api.getStatus().then((res) => {
      // 请求失败(网络超时/5xx)返回 {success:false}, logged_in 为 undefined:
      // 绝不能当作"未登录"清空本地登录态, 静默跳过即可
      if (!res || res.success === false || typeof res.logged_in !== 'boolean') return
      // 能力协商: 记录后端 api_version / features, 供前端做兼容判断(旧后端没有这些字段时保持默认)
      try {
        if (typeof res.api_version === 'number') storage.set('api_version', String(res.api_version))
        if (Array.isArray(res.features)) storage.set('api_features', res.features.join(','))
      } catch (e) { /* 老后端: 忽略 */ }
      // 账号类型兜底同步(研究生: tabBar 隐藏评教、成绩/考试走研究生数据)
      if (res.account_type) {
        const changed = storage.get('account_type', '') !== res.account_type
        storage.set('account_type', res.account_type)
        if (changed) {
          // 类型变化时让 tabBar 立即重算(老会话首次启动时评教会闪一下)
          try {
            const pages = getCurrentPages()
            const cur = pages[pages.length - 1]
            const bar = cur && cur.selectComponent && cur.selectComponent('#tabbar')
            if (bar && typeof bar._refreshList === 'function') bar._refreshList()
          } catch (e) { /* 拿不到组件时忽略, 下次 show 会自然刷新 */ }
        }
      }
      if (res.logged_in) return
      api.autoRelogin().then((newToken) => {
        if (newToken) {
          // 自动恢复登录成功
          this.globalData.isLoggedIn = true
          this.globalData.studentName = storage.getStudentName()
          this.globalData.semester = storage.getSemester()
        } else {
          // 会话失效: 保留本地缓存数据 → 离线模式继续展示; 仅失效凭证
          storage.remove('token')
          // 注意: 会话过期时**保留** saved_password —— 这样登录页能自动回填账号,
          // 也能让 401 自动重登生效(之前这里删掉, 导致用户每次都要重新输一遍)
          storage.setOffline(true)
          this.globalData.isLoggedIn = false
          wx.showModal({
            title: '登录已过期',
            content: '已切换为离线模式，可继续查看本地缓存数据；需要更新数据请手动登录',
            showCancel: false,
            confirmText: '知道了'
          })
        }
      })
    }).catch(() => {
      // 网络失败不打扰用户, 由后续请求的 401 自动重登兜底
    })
  },

  /** 更新全局登录状态 */
  setLoginState(loggedIn, studentName, semester) {
    this.globalData.isLoggedIn = loggedIn
    this.globalData.studentName = studentName || ''
    this.globalData.semester = semester || ''
  },

  /** 退出登录（等待后端登出 + 本地清理完成） */
  async doLogout() {
    // 只保留上次学号用于登录页回填。密码按隐私承诺随退出删除，不回写。
    const lastSid = storage.getStudentId()
    await api.logout()
    try {
      // 注意: 不能用 setStudentId 写回 —— isLoggedIn() 判据就是"有没有学号",
      // 写回去会让 App 以为还处于登录态, 表现就是"退出登录点了没反应"。
      // 因此另存到 last_login_sid, 只供登录页回填。
      if (lastSid) storage.set('last_login_sid', lastSid)
    } catch (e) { /* 写回失败不影响登出 */ }
    this.globalData.isLoggedIn = false
    this.globalData.studentName = ''
    this.globalData.semester = ''
  }
})
