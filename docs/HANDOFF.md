# Agent 交接说明

> 状态：现行
>
> 最后核对：2026-11-27
>
> 本文不记录密码、Token、Cookie、管理员口令或真实教务凭证。

## 1. 当前代码状态

### Server

- 当前分支：`server`
- 当前 HEAD：`132fa4d feat: 增加合作商验收演示数据`（已推送 `origin/server`）
- 当前已跟踪工作区无未提交改动；本机仅有 `.tmp/`、`.video-tools/`、`poster/`、`video/`、`audit-no-classroom.csv` 等未跟踪本地产物，不入库
- 2026-11-24 新增校园服务前后端（`internal/campus`、服务/线索表和接口、管理后台页签、`1002_campus_services` 安全迁移，以及小程序入口/服务簿/详情/咨询表单）
- 2026-10-29 新增图书馆公共馆藏只读网关与两个 API（已随 v1.10.0 提交）：`internal/library` + `internal/httpapi/library.go`，无数据库迁移；匿名访问 OPAC，登录用户共享有界内存缓存
- 生产运行时：Go/WebGo

### Miniapp

- 工作区：`C:\Users\a\Documents\local\njust-schedule\.miniapp`
- 当前分支：`miniapp`
- 基线提交：`118635a`
- 当前 HEAD：`aa93804 feat: 更新合作商验收与回归测试`（已推送 `origin/miniapp`）
- 当前本地构建标识：`2026.11.27.3`
- 当前版本：`v1.11.0`（校园服务、合作商验收账号、刷新入口恢复、用户数据同步、合作商演示数据与图书馆修复）；代码已提交并推送，是否发布小程序版本仍以微信平台上传记录为准
- 当前已跟踪工作区无未提交改动；本机仅有 `.tmp/` 未跟踪目录
- `C:\Users\a\Documents\local\miniprogram` 是微信开发者工具使用的独立克隆
- 修改 Miniapp 后必须按 `AGENTS.md` 同步并核对哈希：默认可按同步脚本排除 `.git`/`node_modules`/`.tmp`，但**最终复验要使用完整口径**（只排除这三个目录）并报告源/目标文件数与 missing/diff/extra；`project.config.json`、`project.private.config.json` 参与比对（本地配置一致时 diff=0，差异需显式说明）；目标独有 `minitest/test.config.json` 保留不删，作为 extra 单列，不得通过额外排除项声称“全量一致”。

不要使用 `git reset --hard`、`git checkout --` 或批量覆盖 Miniapp 未提交改动。

## 2. 先读什么

1. 仓库根目录 `AGENTS.md`
2. [文档索引](README.md)
3. 本文
4. [当前架构](architecture/current.md)
5. 按任务读取操作、产品或专题文档

`docs/plans/completed/` 中的文件是历史计划，不是当前待办。

## 3. 系统概览

- 小程序通过 `wx.cloud.callContainer` 调用微信云托管 WebGo 服务
- MySQL 保存用户数据、共享课程目录、凭据密文、订阅额度和运行配置
- Redis 可选；未配置时登录会话只存在单实例内存中
- 智慧理工 SSO 负责统一认证，后端解析真实页面后访问本科或研究生教务
- 小程序不直连教务，也不自行猜测教务表单字段

详细边界见 [architecture/current.md](architecture/current.md)。

## 4. 数据库与部署

- 迁移实现：`internal/migrate`
- 当前迁移版本：`1002_campus_services`
- 安全白名单只允许已登记的增量迁移
- 高风险 DDL、大表修改、删除和数据清洗必须手动执行
- 标准手动命令：

```bash
set -eu
cd /app
./migrate
exec ./server
```

- 镜像内也提供 `/app/manual-start`
- 不得恢复 `MIGRATIONS_AUTO` 类环境变量
- 部署细节见 [operations/live-coding.md](operations/live-coding.md) 和根目录 `README.md`

## 5. 近期完成内容

- WebGo 后端替代生产 Flask 运行时，同时保留旧 API 契约
- 通识选修课目录分页刷新、查询和大纲按需缓存
- 安全迁移白名单与手动高风险迁移流程
- 研究生 `秋学期/春学期` 学期格式统一为 `YYYY-YYYY-N`
- 小程序信息中心、公告、QQ 群和使用统计
- 微信原生模板广告组件及功能页底部广告位
- 在线会话删除、反馈、提醒、空教室和蹭课查询
- 江阴校区空教室按实际教学楼完整展示，孝陵卫继续使用四大教学楼视图
- 全小程序界面样式统一：单一 token 基座（`styles/design-system.wxss` + `ui/theme/tokens.js`）、中性白灰主体、品牌蓝少量强调、去装饰圆/厚投影/大面积渐变、单层入场动画
- 主 Tab 与二级页面恢复轻微 Q 弹入场：分别使用 200ms / 280ms 统一缓动，保持单层动画责任和减少动态效果支持
- 课表页不再放置广告：原 `slot-schedule-mid` 原生模板广告（含 160rpx 预留高度）已撤除，仅保留底部 `slot-schedule-bottom` 历史库存统计标记（纯标记、不占高度）；其他页面广告与公共 `ad-slot` 组件不受影响
- 「我的」页身份信息区（姓名/学号/学期/指标/周次校准）合并，「偏好 / 服务 / 帮助与反馈」统一为列表
- 竞赛公告集成（2026-11-01，合并入 v1.11.0 未提交记录）：官方 X·Space 无可重复访问的机器可读 RSS/API，改为管理员维护；扩展 `settings.content_board_v1` 的 `competitions`，后台新增/编辑/删除/启停，服务端校验日期与官方 HTTPS 域名，信息中心新增竞赛 Tab 与复制原文链接；详见 `docs/product/competition-announcement-integration-2026-11-01.md`
- 校园服务前后端（2026-11-24，未提交）：新增 `campus_services`/`campus_service_leads`、公开服务与咨询接口、管理员服务/线索接口和后台页签；联系方式 AES-256-GCM 加密、30 天保留与每日清理，服务上架前必须审核；小程序新增入口、服务簿、分类、详情与咨询表单，入口已并入校园工具两列网格并与其他功能卡统一，详见 `docs/product/campus-services-backend-2026-11-24.md`、`docs/product/campus-services-frontend-2026-11-24.md`
- 图书馆六项 review 修复及第二轮边界修正（2026-11-01，合并入 v1.11.0 未提交记录）：草稿/提交分离、失败页精确重试、严格拒绝 HTTP200 异常结构、MaxPage=200 + truncated/max_page、stale 24h 与 cleanup/容量淘汰分离、共享缓存真正有界；详见 `docs/product/library-inventory-2026-10-29.md`
- v1.11.0 用户数据每日自动同步（2026-11-01，未提交）：用户课表/考试/成绩/评教/四六级/培养方案/学籍改为服务端每日 00:20 批量预热（启动补跑），登录仅在缓存未命中时兜底预抓；课表/成绩/评教/培养方案刷新入口已恢复，但除考试外的 `/api/refresh-*` 默认只返回服务器数据提示并重载快照（`ALLOW_LIVE_REFRESH=1` 可临时回退）；失败保留旧快照，批量任务限制并发且失败不回写成功标记；说明见 `docs/product/user-data-daily-sync-2026-11-01.md`
- 考试刷新修复（2026-11-24，未提交）：前端 `refreshExams` 强制绕过离线短路并在有记忆密码时自动重登；后端 `/api/refresh-exams` 独立于 `ALLOW_LIVE_REFRESH` 实时访问教务，按用户 3 次/分钟限流；服务器返回未实时刷新时显示真实提示，不再误报“已刷新 0 场”
- 用户反馈修复（2026-11-27，未提交）：启动状态校验强制绕过离线短路，自动重登后重新预取并激活当前页面；研究生课表优先当前学期；考试合并 JSON 与 HTML 并按 30 分钟窗口静默刷新；成绩页缓存为空时自动补拉并重算 GPA/学分；反馈未读状态随会话恢复
- 合作商验收账号（2026-11-24，未提交）：与学生共用登录页，后端通过 `PARTNER_PREVIEW_USER/PASSWORD` 识别固定账号并签发 `role=partner` 会话；完整功能导航可用，课程/考试/成绩/四六级/学业进度返回只读虚构演示数据并标记 `demo_mode:true`，不读取真实学生数据、不写数据库且不触发教务；评教和学籍仍为空；详见 `docs/product/partner-preview-account-2026-11-24.md`
- v1.10.0 图书馆库存（2026-10-29，已随 `45a2f77` 本地提交、未 push）：功能页第 8 个入口，支持书名/作者/ISBN/索书号检索与服务器分页；书目列表不 N+1，点开书目后才请求逐册馆藏并按南京/江阴/全部筛选，统计只认明确“可借”；后端匿名 OPAC 客户端固定上游 host/path、校验书目 ID、限制响应体/超时/页码/关键词，HTTP 200 业务错误与空结果区分；共享缓存（检索 30 分钟、单本 5 分钟、失败可回退新鲜期结束后 24h 内旧缓存并标记 stale）、同 key 并发合并、限流与上游并发上限；说明见 `docs/product/library-inventory-2026-10-29.md`

## 6. 当前已知限制

- `ad-custom` 不支持前端点击事件，小程序无法直接上报 `ad_click`
- 竞赛公告（v1.11.0，未提交）：官方 X·Space 页面无可重复访问的机器可读 RSS/API，竞赛数据由管理员手工维护，不会自动同步；若官方后续提供稳定机器可读源，再另行设计后端刷新/缓存与去重。原文链接只做域名白名单，管理员需确认内容确属官方通知；截止日期仅展示，过期条目需手动关闭 enabled。
- 校园服务（2026-11-24，前后端首期已实现，未提交）：未接支付、订单、商户自助、资质文件上传和持久管理员审计；管理员查看完整联系方式目前只写运行日志中的线索 ID 与 request ID；详情/表单仅完成开发者工具逻辑与静态验收，仍需真机确认键盘、弹层与长文本滚动。
- 合作商验收账号：固定账号密码保存在云托管环境变量，修改密码需更新环境并重新部署；首期只有一个账号、无后台管理与密码重置页面；合作商能看到共享功能，学生数据页展示只读演示数据，刷新不会访问真实数据源。
- 用户数据每日同步（v1.11.0，未提交）：批量任务只在单实例进程内运行（当前容器 `maxNum=1`），横向扩容需要选主/分布式锁；启动补跑可能集中访问教务，需要观察上游负载；持久 Cookie 失效用户不会在批量中重登（避免 SSO 风控），会在下次登录时兜底
- 用户数据最多延迟到下一个凌晨；批量失败或用户无缓存时，登录兜底会实时访问一次教务，这是与空教室一致的“缓存未命中回源”行为，不是手动刷新
- 考试刷新是唯一实时访问教务的手动刷新入口：需要有效登录/可自动重登的记忆密码，单用户 3 次/分钟；其他页面刷新按钮只重新读取服务器快照。若持久 Cookie 与密码恢复均失败，仍会回到离线缓存模式
- Miniapp 当前仅有 v1.11.0 未提交改动；交接前必须保留现状，不要用 reset/checkout 覆盖
- 考试安排状态（2026-10-28 修复，已包含在 miniapp HEAD `9737245`，未 push）：逐场按「日期 + 开始/结束时间」按 Asia/Shanghai 判定，开考瞬间 ongoing、结束瞬间 done；日期组有进行中优先、全部结束才 done 且可折叠；缺/异常时间保守显示「时间待定/已开始（结束待定）」；开始==结束按结束待定处理（不臆造 24 小时），仅结束早于开始才跨午夜，单开始时日界为次日 00:00。空数组/缓存缺失/切学期/退出统一清空与复位；请求绑定「身份+学期+序号」，迟到旧请求不覆盖视图/缓存、不改新操作忙态；研究生只读 cached_yjs_exams 且只走研究生接口；页面重新显示本地重算不发请求。说明见 `docs/product/exam-status-fix-2026-10-28.md`，回归 `tools/test_exams.js`（43 项）。
- 界面样式统一（含 2026-10-25 Island 悬浮岛式改造）已包含在 miniapp HEAD `9737245`，未 push、未发布；现行方案为 `docs/product/island-ui-redesign-2026-10-25.md`，`docs/product/frontend-style-refresh-2026-10-24.md` 为交接前基线记录（其“跨满整行/180ms”等描述已被 Island 方案替代，不得据此恢复）
- 渲染验收只有 **390 宽开发者工具模拟器**：320/430 与真机均未实测，不能当作已验收（Island 轮同样只实测 390）
- 考试状态修复的行为验证是 **Node 固定时钟 + wx/API 桩件**（`tools/test_exams.js`，43 项），不访问生产/教务、不写真实凭据；模拟器截图/静态检查不代表真机验收
- 图书馆库存（2026-10-29；2026-11-01 修复）：真实匿名只读复验成功——高等数学 2582 条、首页首本「高等数学:理工类.上册.第3版」ISBN 978-7-5608-5255-3、5 册全部可借（南京 3、江阴 2）；2026-10-29 的 503 只是短时限流，不再作为“无法验证”限制。后端行为测试仍用 `httptest` + 去标识 fixture，不依赖外网；上线前建议在部署环境抽一次真实检索+明细
- 图书馆缓存是**进程内共享有界缓存（上限 4096，FIFO/最旧淘汰）**：多实例部署时各实例各自缓存，未引入 Redis/DB 迁移；缓存 key 包含检索字段/关键词/页码，只保存公开书目/馆藏，不在服务端持久化搜索历史，也不保存身份凭据、Cookie/Token；fresh-only 读取不删除 retained 项，stale 24 小时从新鲜期结束起算，cleanup 按 retention 清理，容量压力可淘汰最旧项，前端会显示“旧缓存”
- 图书馆 UI 仅在 390 宽开发者工具模拟器中用内存 mock（示例书目/馆藏）验证；320/430、真机、上游真实分页数据均未验收；未接入借还/预约/个人借阅/提醒/支付
- 图书馆入口接入 DSL：`ui/pages/feature.ui.js` 源与 `components/generated/feature-page` 生成结果同步；本次重新生成同时带入了设计令牌的最新编译输出（颜色/间距 token 化），该生成页仅用于预览，不影响生产主页

- Island 轮截图证据：姓名/学号/课程等均为**内存 setData mock**（示例同学 / 示例教师 / 示例课程），不使用真实缓存身份数据；picker、弹层、长候选下拉均走实际交互路径截图，见 `.tmp/shots-island2/`
- 课表网格的列底线与节次线使用 `background-image` 线性渐变绘制，属于绘制手段，不属于方案禁止的装饰渐变，调整几何时不要误删
- 图标组件 `components/icon` 是 PNG 4 档资源映射：`tone()` 只做色→档归一，`file()` 必须只返回 `static/icons` 里真实存在的文件；改动后必须跑 `node tools/test_icon_assets.js`（会执行运行时 wxs 并枚举全部 WXML 用法）
- WXS 与 JavaScript 的语法支持不同：Node VM 资源测试通过不代表 WXS 编译通过。本轮一次包含 `String()` 与映射表的改写在模拟器中失败，最终采用已验证的 `if/return` 写法；后续改映射还必须在开发者工具确认图标正常渲染，不能据此推断所有映射表或辅助函数都不受支持
- 主页面高度链契约（2026-10-25 review 更正）：一级视图**宿主只负责填满父级**（`.tab-wrap > schedule-view/settings-view/.feat-page { flex:1; min-height:0; }`），**不得**给宿主再加 `overflow`/`padding`/`height:100%`——那会让课表/我的的内部 scroll-view 二次滚动并压缩可视区，造成正文被截断到半屏、下方大片不可用空白。滚动与底部留白归属：功能页 `.feat-page` 作为滚动容器承担滚动与 `padding-bottom: calc(140rpx + env(safe-area-inset-bottom))`；课表/我的由各自内部 `.view-scroll` 滚动，同样只在该 scroll-view 内保留 140rpx + 安全区尾部留白（留白属于可滚内容，不缩小视口）。禁止用 JS `swiperHeight` 或内联 px 高度；布局契约由 `tools/test_main_height_chain.js` 锁定，改动高度链时必须同时用开发者工具量宿主/scroll-view/底栏矩形并滚到底验证。
- 底部弹层契约：`--td-popup-distance-top: 12vh` 控制最大高度（直接写 max-height 会被 TDesign 自身规则覆盖）、`--td-popup-transition` 走 `--motion-sheet`、遮罩色走 `--td-overlay-bg-color`；一级页打开弹层时由 `popupstate` 事件把浮动 TabBar 隐藏（`main.wxml` 的 `.tabbar-slot`），组件侧用 `observers` 监听弹层字段上报。
- 刷新入口契约：统一用 `.refresh-action`（88rpx 热区 + 按压反馈），请求中用 `is-busy`（降权 + 禁用 + 单层旋转）；页面不要再另加 `.spin` 到按钮上，避免重复旋转。
- 字体档位契约：默认档是**像素点阵**（基座 `--font-pixel`，内联 base64），根节点挂 `.font-system` 才走系统字；`app.wxss` 的 `.font-system` 必须同时重新赋值 `--font-plain/--font-ann/--td-font-family(-medium)`（这些在 page 上已把 `var(--font-body)` 替换成像素字面量再继承，不会回灌，漏改会让 TDesign 组件在系统字档下仍是像素字）；改动后跑 `node tools/test_font_preference.js`
- 设置页版本号改为读取 `utils/changelog.js` 的最新记录，新增版本时只需更新更新记录
- TDesign 的 `t-input` / `t-textarea` 默认白底优先级高于页面 `t-class`：需要非白底时必须显式覆盖（当前 4 处已覆盖），否则灰底行或表单里会出现白块
- 浮动底栏（`custom-tab-bar`，高 92rpx + 14rpx + 安全区）会覆盖内容：三个一级视图的滚动容器都必须留 `padding-bottom: calc(140rpx + env(safe-area-inset-bottom))`
- 静态动画测试（`tools/test_page_animations.js`、`test_feature_page.js`）断言的是「单层入场、无错峰、无装饰圆、保留按压反馈」的行为契约，改动画时改实现不要删断言
- 未配置 Redis 时，部署或重启会清空服务端 token 会话，客户端需要自动重登
- 管理面板没有独立的维护日志表；当前维护信息通过信息中心公告管理
- 部分历史规划文档记录的是旧 UI 或旧迁移策略，以 `docs/README.md` 的状态标注为准
- 生成海报、`.tmp`、临时 CSV 不属于产品代码，不要误提交

## 7. 常用验证

### Server

```bash
go test -count=1 ./...
go vet ./...
.venv/Scripts/python.exe -m pytest -q
```

### Miniapp

```bash
node tools/test_api_smoke.js
node tools/test_navigation.js
node tools/test_audit.js
node tools/test_freeclass.js
node tools/test_library.js
node tools/test_ad_slot.js
node tools/test_analytics_slots.js
PYTHONIOENCODING=utf-8 python tools/verify_miniapp.py .
PYTHONIOENCODING=utf-8 python tools/verify_privacy.py .
```

## 8. 修改原则

- 先读代码和真实页面，再修改
- 不猜测智慧理工或教务表单字段
- 不在 Markdown、日志、测试或提交中写入敏感凭证
- 服务端改动先测试，通过后再推送
- Miniapp 改动必须同步到开发者工具目录
- 完成改动后先 review，再等待用户确认提交、推送或同步以外的后续操作

## 9. 建议下一步

- 将 Miniapp 当前未提交功能按主题拆分成可审查提交
- 为广告点击数据补充微信广告后台的运营口径说明
- 如需要可新增真正的管理员维护日志表和管理界面
- 每次发布同步更新 [CHANGELOG.md](releases/CHANGELOG.md)
