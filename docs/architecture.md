# 小程序与后端架构

本文描述课表助手微信小程序与 Go/WebGo 后端的现行职责、数据流和兼容边界。

## 一、系统边界

    微信小程序
        |
        | wx.cloud.callContainer
        | JSON + X-Auth-Token
        v
    微信云托管 WebGo 服务
        |-- MySQL：用户数据、共享目录、凭据密文、订阅额度
        |-- Redis：可选的跨进程登录会话
        |-- 智慧理工 SSO：密码登录、二维码登录
        |-- 强智本科教务 / 研究生教务：抓取与提交
        '-- 微信接口：订阅消息

核心边界：

- 小程序负责展示、交互、本地缓存、GPA 和评教评分等界面侧计算。
- 后端负责认证、会话、教务访问、HTML 解析、数据隔离、共享缓存、提醒和管理。
- 小程序不直连教务，不自行构造教务表单。
- 后端解析目标页面的真实表单字段后再提交，不猜测字段名。

## 二、运行时分层

| 层 | 目录 | 职责 |
|---|---|---|
| 入口 | cmd/server | 配置、日志、信号处理和优雅停机 |
| 应用装配 | internal/app | MySQL、Schema 校验和 HTTP 服务组装 |
| HTTP | internal/httpapi | 路由、认证、响应契约、管理端和后台任务 |
| 教务网关 | internal/jwc | SSO、Cookie、页面表单解析、数据抓取与提交 |
| 认证 | internal/authn | 加密密码、24 小时信任、30 天持久 Cookie |
| 会话 | internal/session | X-Auth-Token、LRU、单学号单 token、Redis 恢复 |
| 数据访问 | internal/store | database/sql 查询、事务和快照替换 |
| 迁移 | internal/migrate | MySQL 命名锁、幂等 DDL、版本与 Schema 校验 |
| 安全 | internal/security | AES-256-GCM、AAD 学号绑定、签名令牌 |

internal/httpapi 不直接解析教务 HTML，internal/jwc 不直接写业务数据库。共享数据刷新由 HTTP 服务编排，store 只负责持久化。

## 三、登录与会话

### 1. 密码登录

1. 小程序向 POST /api/login-webvpn 提交学号和智慧理工密码。
2. 后端检查同学号保存的密码是否恒定时间相等，且真实验证时间未超过 CREDENTIAL_TRUST_TTL。
3. 满足信任条件时，先用持久 Cookie 恢复智慧理工和教务会话。
4. Cookie 无效或不满足信任条件时，解析智慧理工登录页表单并执行真实 SSO。
5. 智慧理工要求验证码时，使用本地 ONNX Runtime + ddddocr 模型识别并提交；识别失败才回退二维码登录。
6. 成功后保存 AES-GCM 密码密文、持久 Cookie，并签发新的 X-Auth-Token。
7. 新 token 会顶掉同学号旧 token，然后异步预抓必要数据。

密码密文使用学号作为 AAD，不能跨账号解密。管理员接口不返回明文密码。

### 2. 二维码登录

1. POST /api/sso-qr/start 创建临时扫码会话并返回二维码。
2. GET /api/sso-qr/status 轮询智慧理工状态。
3. 用户确认后，后端换取 SSO 票据并进入教务。
4. 后端从实际教务页面识别学号、姓名和账号类型，保存持久 Cookie 并签发 token。

二维码登录不会凭空得到密码，因此只更新 Cookie，不创建密码记录。

微信订阅使用的 `X-WX-OPENID` 只在请求经过微信云托管网关时可信。生产服务必须置于该网关之后，由网关覆盖该请求头，不得把容器端口绕过网关直接暴露给公网；后端还会拒绝超长或包含非法字符的 OpenID。

### 3. 三类状态

| 状态 | 默认有效期 | 用途 |
|---|---:|---|
| X-Auth-Token 会话 | 12 小时无活动 | 小程序访问本服务 API |
| 保存密码的信任 | 24 小时 | 相同密码输入时允许优先探测 Cookie |
| 持久教务 Cookie | 30 天上限 | 减少重复 SSO 和供后台共享任务使用 |

退出登录和管理员删除会话只删除第一类状态，不删除密码和持久 Cookie。

未配置 Redis 时 token 在单实例内存中；配置 Redis 后，会话密文写入 Redis，并使用学号到 token 的映射保证单学号单会话。Redis 写失败时不切换内存会话。

## 四、用户数据

每个用户的数据均以 student_id 隔离：

| 数据 | 表或存储 |
|---|---|
| 课表 | courses |
| 考试 | exams |
| 成绩 | grades |
| 四六级 | cet_scores |
| 评教 | evaluations |
| 用户设置、密文密码、持久 Cookie、校历、培养方案、学籍 | user_settings |
| 反馈 | feedback |
| 订阅额度与提醒任务 | user_settings、reminder_tasks |

刷新流程先完成教务请求和解析，再在数据库事务中替换对应快照。抓取失败不会先删除旧数据，数据库写入失败会回滚。

普通查询优先读取 MySQL。登录后的预抓和用户主动刷新都会更新版本号；小程序可通过 GET /api/sync/versions 只比较版本，再决定是否下载完整数据。

## 五、共享数据

### 1. Cookie 来源

空教室和蹭课目录按以下顺序选择本科会话：

1. 随机活跃本科会话
2. 随机持久化本科 Cookie
3. 本科服务账号

每个候选都先探测并恢复教务会话。服务账号的 Cookie 失效时，后端可使用管理端保存的加密密码重新登录。研究生会话不会进入该池。

### 2. 空教室

- GET /api/free-classrooms 只要求小程序从服务端取结果。
- 相同参数的并发请求会合并。
- 内存缓存持续到次日 00:02。
- 开启 FREE_CLASSROOM_PREWARM 时，启动和每日 00:02 预热当天两校区各大节。
- 缓存未命中时服务端可同步访问教务，小程序仍不直连教务。

### 3. 蹭课目录

- 后端按学期抓取全校课表并原子替换 audit_courses。
- 每日 00:05 检查目录版本；管理员也可主动触发。
- 候选目录支持版本校验和分片下载。
- 查询支持课程、教师、教室、星期和节次组合过滤。
- 收藏写入 audit_favorites，并保持 student_id 隔离。

课程单元格按“课程名列 + 上课时间列”解析。班级、教师、周次和教室允许多行、多值；显示层可聚合，查询索引使用拆分结果。

## 六、提醒

考试提醒和成绩提醒共用订阅基础设施，但分别记录额度和模板。

课程生命周期：

1. 从用户课表和培养方案识别课程结课时间与考核方式。
2. 考试课结课后等待考试安排，考试结束后进入成绩检测。
3. 考查课结课后直接进入成绩检测。
4. 只有拥有对应订阅额度的用户才进入提醒池。
5. 同课程名、同教师的用户可共享一次教务成绩探测，但发送前仍按用户实际成绩确认。
6. 同名课程教师冲突时标记歧义，不自动跨教师匹配。

成绩检测从开始日起最多 28 天：

- 第 1 至 7 天：10:00、14:00、18:00
- 第 8 至 21 天：06:00 至 23:00 每小时
- 第 22 至 28 天：10:00、14:00、18:00
- 超过 28 天仍无成绩则停止

微信个人主体小程序使用一次性订阅，每次发送消耗一个额度。

## 七、接口契约

所有受保护接口使用请求头 X-Auth-Token。JSON 响应保持 success、message 和既有业务字段，错误使用 400、401、403、404、409、429 或 500/502。

### 主要接口

| 分组 | 路径 |
|---|---|
| 登录 | /api/login-webvpn、/api/get-webvpn-captcha、/api/sso-qr/*、/api/logout |
| 状态 | /api/status、/api/prefetch-status、/api/connect-test |
| 课表考试 | /api/courses、/api/exams、/api/refresh-schedule、/api/refresh-exams、/api/refresh-all |
| 成绩 | /api/grades、/api/cet-scores、/api/refresh-grades、/api/refresh-cet |
| 评教 | /api/evaluations、/api/eval-courses、/api/eval-form、/api/submit-eval、/api/jw-proxy |
| 学业 | /api/calendar、/api/programme、/api/profile 及对应 refresh 路由 |
| 空教室 | /api/free-classrooms |
| 蹭课 | /api/audit-courses、/api/audit-options、/api/audit-favorites |
| 同步 | /api/sync/versions |
| 订阅 | /api/subscribe/status、/api/subscribe/grant、/api/subscribe/test-send |
| 内容 | /api/feedback、/api/my-feedback、/api/announcement、/api/gallery-*、/api/font/* |
| 统计 | /api/analytics/events |
| 管理 | /admin、/api/admin/* |

### 旧前端兼容

- GET /api/get-captcha、POST /api/login、POST /api/login-manual 仍存在，但返回“教务直连已下线”。
- POST /api/login-webvpn-manual 仍存在，但返回“无需第二步教务登录”。
- POST /api/get-webvpn-captcha 与新登录流程共用实现，并保留 already_logged_in 字段。
- /api/status 的 features 保留 yjs 等旧前端分支判断字段。
- 研究生登录后 has_courses 与旧实现一致。
- 本科课表必须合并 kbtable 的周次、教室与 dataList 的精确节次；不能只解析 dataList。
- 考试和成绩查询页没有直接数据时，继续回退到 xsksap_list、cjcx_list 列表页。
- 成绩列表没有“绩点”列时 grade_point 写 0，由小程序按成绩计算，不能使用行号兜底。
- 蹭课目录使用“一行一门课、列=星期×大节”的 43 列课程目录结构，并按旧版规则拆分多教师、多班级、多教室和多周次。
- 空列表统一返回 [] 而不是 null，包括收藏、管理端用户详情和考试安排。
- 小程序启动预取通过 /api/sync/versions 比较数据版本，不能只依赖本地 30 天 TTL。

## 八、并发与可靠性

- JW_MAX_CONCURRENT 控制所有教务 HTTP 并发。
- 相同刷新任务使用请求合并，避免同一用户重复访问教务。
- Session 内互斥锁防止同一 Cookie 会话被并发改写。
- HTTP 请求体上限 2MB，并拒绝尾随 JSON。
- 学期、学号、蹭课查询和收藏字段均执行格式与数据库列长度校验。
- 登录、管理端和字体接口有限流。
- TRUSTED_PROXY_HOPS 控制客户端 IP 解析，避免直接使用可伪造的 X-Forwarded-For 首项。
- 管理员令牌带随机 nonce；退出管理端会在当前实例立即撤销该令牌。
- 公开 /metrics 只输出非敏感累计请求数，不暴露实时在线会话数量。
- 后台任务受根 context 管理，停机时等待退出。
- /readyz 同时检查 MySQL 与已配置的 Redis。

当前 container.config.json 固定 maxNum 为 1。若未来横向扩容，需要先把共享缓存、后台任务选主、限流和管理端实时统计迁移到 Redis 或数据库。

## 九、数据库迁移

cmd/migrate 是唯一 Schema 写入入口：

1. 获取 MySQL 命名锁。
2. 创建缺失表。
3. 增加缺失列和索引。
4. 执行受控数据修复。
5. 校验必需表、列、关键列类型和迁移版本。
6. 全部成功后登记 schema_migrations。

服务进程先绑定健康端口，再在后台执行带 MySQL 命名锁的迁移。迁移完成前 `/readyz` 和业务接口返回 503，后台任务不会启动；迁移失败时进程退出，云托管保留旧版本。

container.config.json 只创建数据库，不重复声明业务表。

## 十、生产镜像

Dockerfile 使用 Go 1.26.9 Debian 多阶段构建。最终镜像以非 root 用户运行，并通过文件能力仅授予 server 绑定 80 端口的权限；镜像包含两个 CGO Go 二进制、ddddocr 通用模型、ONNX Runtime 1.23.2 动态库、静态资源、管理端模板、CA 证书和时区数据。

旧 wxcloudrun 下的 Flask 源码、requirements 文件和 Python 测试不会进入最终镜像。OCR 由 Go 进程内的 ONNX Runtime 完成，不依赖 Python。旧代码只用于迁移比对，新增业务应进入 internal 下的 Go 分层。
