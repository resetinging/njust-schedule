const RELEASES = [
  {
    version: 'v1.10.0',
    title: '图书馆公共馆藏查询',
    published_at: '2026-10-29',
    changes: [
      { type: 'new', text: '新增「图书馆库存」功能页第 8 个入口：书名/作者/ISBN/索书号检索，明确提交后从服务器分页获取，支持加载更多、出错重试、无结果；点书目后按需查看逐册馆藏，可按全部/南京/江阴筛选，统计与明细一致，仅把明确“可借”计入可借' },
      { type: 'improve', text: '后端新增图书馆公共馆藏只读网关与 /api/library/search、/api/library/item：匿名上游不携带教务 Cookie，固定 host/path、校验书目 ID/参数，HTTP 200 业务错误与空结果分离；共享缓存（检索 30 分钟、单本 5 分钟、失败回退 24h 内旧值并标记 stale）、同 key 合并、限流与上游并发上限' },
      { type: 'improve', text: '图书馆使用 Island 卡片/弹层与统一刷新入口：搜索与详情请求序号防竞态，切字段/切校区/关闭详情后旧响应不覆盖；打开详情隐藏浮动底栏；新增 book 图标真实资源并登记映射，DSL 功能页与生成结果同步为 8 个入口' }
    ]
  },
  {
    version: 'v1.9.0',
    title: '广告接入、通识目录、Island 界面统一与考试状态修复',
    published_at: '2026-10-28',
    changes: [
      { type: 'new', text: '新增通识选修课大纲 13 页完整目录抓取与目录查询' },
      { type: 'improve', text: '课程大纲按需缓存，管理员支持目录刷新、状态查看与每日同步' },
      { type: 'new', text: '功能主页和 7 个功能子页接入微信原生模板广告' },
      { type: 'improve', text: '完善信息中心维护公告、QQ 群信息和广告事件统计' },
      { type: 'fix', text: '修复江阴校区空教室被四大教学楼筛选规则过滤的问题' },
      { type: 'improve', text: '江阴校区按实际教学楼展示全部空闲教室分组' },
      { type: 'improve', text: '统一全小程序配色、字阶、间距、圆角与按压反馈，去除装饰圆、厚投影和大面积渐变' },
      { type: 'improve', text: '「我的」页把姓名、学号、学期、指标与周次校准合并为一个信息区，偏好与帮助入口统一为列表' },
      { type: 'improve', text: '课表与二级页入场收敛为单层短动画，并保留减少动态效果支持' },
      { type: 'fix', text: '设置页版本号改为跟随内置更新记录，不再硬编码' },
      { type: 'improve', text: '切页入场统一由主页面单层播放，移除课表与我的页组件内的整页/内容入场' },
      { type: 'fix', text: '图标颜色按 4 档资源归一，修复部分中性色与 sync/check 图标请求不存在资源的问题' },
      { type: 'fix', text: '字体偏好真正生效：像素点阵与系统字两档区分正文、标题与组件字体，并恢复切换时的轻微淡入淡出' },
      { type: 'fix', text: '修复课表与「我的」页内容被截断/不可见：主页面改为稳定 flex 高度链，公告显隐、窗口尺寸与底部安全区自适应，滚动可达 TabBar 上方' },
      { type: 'improve', text: '统一底部弹层：进入退出时长、遮罩色、圆角、最大高度与底部安全区一致，动画只由 t-popup 一层负责，打开弹层时隐藏浮动底栏' },
      { type: 'improve', text: '统一刷新入口：88rpx 热区、轻量按压反馈、请求期间禁用与单层旋转，完成后恢复，避免重复 spin 与页面闪烁' },
      { type: 'improve', text: '恢复主 Tab 与二级页面的轻微 Q 弹入场，统一时长、缓动和单层动画责任，减少重复弹出' },
      { type: 'improve', text: '页面视觉复用设计系统卡片令牌（白卡、细边框、统一圆角/间距与文本层级），减少重复硬编码' },
      { type: 'improve', text: '移除课表页中部原生模板广告与 160rpx 预留高度，课表内容直接衔接、不再留广告空白' },
      { type: 'improve', text: '功能主页入口统一为两列等宽卡片，第 7 个入口保持单列宽度，右侧自然留空' },
      { type: 'improve', text: '全小程序改为 Island 悬浮岛式界面：雾灰页面承托白色内容岛，短控件/分段/底栏聚合为胶囊，仅在岛外表面使用浅软阴影' },
      { type: 'improve', text: '底部导航改为悬浮胶囊（保留三个文字标签与选中态），内容岛统一 32rpx 外层圆角、24rpx 分组圆角与岛内留白' },
      { type: 'improve', text: '主功能页、课表、我的与七个功能子页按岛式层级重排表面与控件，保留原有路由、信息结构、按压/Q 弹与减少动态效果' },
      { type: 'fix', text: '修复主页面高度链回归：一级视图宿主只填满父级（flex/min-height），课表与我的仅由内部 scroll-view 滚动，功能页自身滚动并保留尾部留白' },
      { type: 'fix', text: '修复学期选择器打开时浮动底栏可误触/取证截图叠层：ui-picker 上报可见性并入 popupstate，打开时隐藏底栏、关闭后恢复' },
      { type: 'improve', text: 'TDesign 主按钮统一胶囊圆角（--td-button-border-radius），蹭课输入框/查询按钮、我的字体分段与成绩分段统一为胶囊形态' },
      { type: 'improve', text: '课表学期/日期与周次操作拆分为两块完整圆角操作岛，保留 12rpx 呼吸间距' },
      { type: 'fix', text: '修复考试安排显示：逐场按“日期 + 开始/结束时间”判定（开考瞬间进行中、结束瞬间已结束），同日混合不再整组误标已结束；缺/异常时间保守显示“时间待定/已开始（结束待定）”' },
      { type: 'fix', text: '修复考试视图残留与竞态：空数组/缓存缺失/切学期/退出统一清空，服务器空列表同步清折叠；旧账号/旧学期迟到的刷新或静默响应不覆盖视图、不写缓存、不弹提示；页面重新显示按当前时间本地重算' },
      { type: 'fix', text: '修复研究生考试入口：研究生只读 cached_yjs_exams，后台请求只走研究生接口，不再误调本科考试接口或写本科缓存' },
    ]
  },
  {
    version: 'v1.8.2',
    title: '空间层次与按压反馈',
    published_at: '2026-10-20',
    changes: [
      { type: 'new', text: '新增四级景深令牌与双层阴影体系' },
      { type: 'improve', text: '统一卡片、课表、TabBar 和信息中心的浮起层级' },
      { type: 'improve', text: '优化按钮与课程块的按压位移、阴影和高光反馈' }
    ]
  },
  {
    version: 'v1.8.1',
    title: '信息中心与更新记录完善',
    published_at: '2026-10-20',
    changes: [
      { type: 'new', text: '信息中心支持重点公告、分类更新和 QQ 群联系信息' },
      { type: 'improve', text: '更新记录改为代码内置，完整覆盖 v1.0.0 以来的版本' },
      { type: 'fix', text: '兼容尚未部署信息中心接口的旧后端' },
      { type: 'fix', text: '修复公告已读、离线缓存和过期公告状态同步问题' }
    ]
  },
  {
    version: 'v1.8.0',
    title: '界面重构与云端同步',
    published_at: '2026-10-19',
    changes: [
      { type: 'improve', text: '全面刷新小程序页面层级、导航、卡片和交互动效' },
      { type: 'improve', text: '优化课表、我的页面和二级页面的切换体验' },
      { type: 'improve', text: '适配 WebGo 后端并完善云端同步与兼容策略' }
    ]
  },
  {
    version: 'v1.7.0',
    title: '使用统计与广告位',
    published_at: '2026-10-05',
    changes: [
      { type: 'new', text: '新增使用统计、页面访问和功能使用事件采集' },
      { type: 'new', text: '新增广告槽位可见性、停留时长和库存统计' },
      { type: 'improve', text: '管理面板支持查看使用统计和广告槽位数据' }
    ]
  },
  {
    version: 'v1.6.0',
    title: '连接测试与成绩提醒',
    published_at: '2026-10-04',
    changes: [
      { type: 'new', text: '新增服务端到智慧理工和教务的连通性测试' },
      { type: 'new', text: '新增成绩提醒订阅界面和提醒额度状态' },
      { type: 'improve', text: '优化提醒授权、订阅错误提示和登录态联动' }
    ]
  },
  {
    version: 'v1.5.0',
    title: '蹭课查询与课表体验',
    published_at: '2026-10-02',
    changes: [
      { type: 'new', text: '新增蹭课课程查询、课程详情和课表视图' },
      { type: 'new', text: '新增蹭课收藏、课表冲突判断和收藏课程展示' },
      { type: 'improve', text: '优化多条件查询、候选下拉、课表网格和手势交互' }
    ]
  },
  {
    version: 'v1.4.0',
    title: '会话缓存与性能优化',
    published_at: '2026-10-02',
    changes: [
      { type: 'improve', text: '完善登录会话缓存、自动恢复和离线只读模式' },
      { type: 'improve', text: '优化缓存优先加载、后台预取和请求去重' },
      { type: 'fix', text: '修复空教室、状态检测和页面切换中的竞态问题' }
    ]
  },
  {
    version: 'v1.3.0',
    title: '界面刷新与学习数据',
    published_at: '2026-10-01',
    changes: [
      { type: 'new', text: '新增学分进度、学籍卡片、教学周历校准和考试提醒' },
      { type: 'new', text: '重构三栏导航、我的页面、功能页和全局主题变量' },
      { type: 'improve', text: '空教室、校历图鉴、课表和成绩页面统一交互风格' },
      { type: 'improve', text: '补齐隐私保护指引、接口测试和发布前自检工具' }
    ]
  },
  {
    version: 'v1.2.0',
    title: '校园工具与反馈体系',
    published_at: '2026-09-21',
    changes: [
      { type: 'new', text: '新增问题反馈、管理员回复和我的反馈' },
      { type: 'new', text: '新增空教室查询、教学楼分组和定时共享缓存' },
      { type: 'new', text: '新增常用链接、自定义课程和多色课表' },
      { type: 'improve', text: '统一页面视觉规范，完善缓存、隐私和自动化测试' }
    ]
  },
  {
    version: 'v1.1.0',
    title: '多用户与性能体系',
    published_at: '2026-08-29',
    changes: [
      { type: 'new', text: '新增多用户会话隔离、记住密码和验证码自动识别' },
      { type: 'new', text: '接入智慧理工 SSO 登录和教务会话恢复' },
      { type: 'improve', text: '新增缓存优先、后台预取、手动刷新和页面滑动切换' },
      { type: 'fix', text: '完善学期隔离、评价批次、成绩口径和登录异常处理' }
    ]
  },
  {
    version: 'v1.0.0',
    title: '小程序初版',
    published_at: '2026-06-29',
    changes: [
      { type: 'new', text: '上线课表、考试、成绩、评教和教务登录功能' },
      { type: 'new', text: '支持云托管后端、周课表网格和基础课程详情' },
      { type: 'fix', text: '修复课表字段兼容、登录状态和云托管冷启动问题' }
    ]
  }
]

module.exports = { RELEASES }
