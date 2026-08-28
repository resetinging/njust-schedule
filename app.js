/**
 * 课表助手 — 小程序入口
 */

const api = require('./utils/api')
const storage = require('./utils/storage')
const config = require('./utils/config')

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
      // 静默校验后端会话: 容器重启/会话过期后立即提示, 而不是等用户刷新数据才报错
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
    if (!sid) return
    const sem = storage.getSemester()
    const ttl = config.CACHE_TTL
    const tasks = []

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
      if (res && res.logged_in) return
      if (res && !res.logged_in) {
        api.autoRelogin().then((newToken) => {
          if (newToken) {
            // 自动恢复登录成功
            this.globalData.isLoggedIn = true
            this.globalData.studentName = storage.getStudentName()
            this.globalData.semester = storage.getSemester()
          } else {
            storage.clearAll()
            this.globalData.isLoggedIn = false
            this.globalData.studentName = ''
            this.globalData.semester = ''
            wx.showModal({
              title: '登录已过期',
              content: '后端会话已失效且自动重登失败，请手动登录',
              showCancel: false,
              confirmText: '去登录'
            })
          }
        })
      }
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
    await api.logout()
    this.globalData.isLoggedIn = false
    this.globalData.studentName = ''
    this.globalData.semester = ''
  }
})
