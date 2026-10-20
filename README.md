# 课表助手后端

南京理工大学课表助手的微信小程序后端。服务部署在微信云托管，负责智慧理工 SSO、教务数据抓取与解析、用户数据缓存、共享课程目录、空教室、订阅提醒和管理端接口。

Go/WebGo 是生产运行时。旧 Flask 代码仅保留用于兼容性测试，不进入生产镜像；验证码识别由 Go 进程内的 ONNX Runtime 完成，Go 生产镜像不包含 Python、Flask 或 SQLAlchemy。

## 核心能力

- 本科和研究生课表、考试、成绩、四六级、评教、培养方案、校历和学籍信息
- 智慧理工密码登录与二维码登录
- 密码 AES-256-GCM 加密保存，24 小时本地信任，教务 Cookie 最长保留 30 天
- 空教室和蹭课目录使用活跃本科会话、持久 Cookie、服务账号三级来源
- 蹭课条件查询、候选分片、课程收藏和课表冲突数据
- 通识选修课目录分页刷新、关键词查询和课程大纲按需缓存
- 考试提醒、成绩提醒和微信一次性订阅额度
- 使用统计、反馈、公告、图库、字体和管理控制台
- 请求合并、教务并发限制、缓存、限流、优雅停机和就绪探针
- 兼容旧小程序的 API 路径、JSON 字段、HTTP 状态码和 X-Auth-Token

智慧理工要求验证码时，后端会本地识别并自动提交换图重试一次；模型或运行库不可用、连续识别失败时回退二维码登录。已有 token、持久 Cookie 和 24 小时信任凭据不走 OCR。

## 技术栈

- Go 1.26.9
- WebGo v7.1.1
- database/sql + go-sql-driver/mysql
- goquery
- MySQL
- Redis（可选，用于跨进程会话）
- Docker 多阶段构建 + Debian 最终镜像 + ONNX Runtime 1.23.2

## 目录结构

    cmd/
      server/                 WebGo 服务入口
      migrate/                MySQL 迁移入口
    internal/
      app/                    应用装配
      authn/                  密码与持久 Cookie
      config/                 环境变量和启动校验
      database/               MySQL 连接池
      httpapi/                API、后台任务和管理端
      jwc/                    智慧理工与教务客户端、页面解析
      migrate/                幂等迁移和 Schema 校验
      security/               AES-GCM、令牌签名
      session/                内存/Redis 会话
      store/                  SQL 数据访问
    wxcloudrun/static/        小程序需要的图库和字体资源
    wxcloudrun/templates/     管理端页面
    Dockerfile               生产镜像
    Dockerfile.development   Air 热重载镜像
    container.config.json    微信云托管服务配置

## 认证与会话

密码登录先检查服务端保存密码是否与本次输入一致，且上次真实 SSO 验证未超过 24 小时。满足条件时先探测持久 Cookie；Cookie 失效后才重新访问智慧理工。真实 SSO 成功会更新加密密码和持久 Cookie。

二维码登录不保存密码，但会保存成功换取的教务 Cookie。退出登录只删除 X-Auth-Token 对应的服务端会话，不删除保存的密码或持久 Cookie；管理员删除会话也遵循相同规则。

默认同一学号只保留一个登录 token。配置 Redis 后，会话可在进程重启或多实例间恢复；Redis 写入失败时不会产生半成功的内存会话。

## 环境变量

### 必需

| 变量 | 说明 |
|---|---|
| MYSQL_ADDRESS | MySQL 地址，格式 host:port |
| MYSQL_USERNAME | MySQL 用户名 |
| MYSQL_PASSWORD | MySQL 密码 |
| SESSION_KEY | 可解码为 32 字节的 base64 密钥 |
| ADMIN_PASSWORD | 管理控制台口令 |

### 常用

| 变量 | 默认值 | 说明 |
|---|---:|---|
| ADDRESS | :80 | HTTP 监听地址 |
| MYSQL_DATABASE | flask_demo | 数据库名，为兼容现网保留旧名称 |
| REDIS_URL | 空 | Redis URL；空值使用单实例内存会话 |
| SESSION_TTL | 43200 | 登录 token 无活动有效期，秒 |
| MAX_SESSIONS | 200 | 内存会话上限 |
| DATA_CACHE_TTL | 2592000 | 用户数据缓存时间，秒 |
| CREDENTIAL_TRUST_TTL | 86400 | 保存密码的本地信任期，秒 |
| SSO_SESSION_MAX_AGE | 2592000 | 持久教务 Cookie 最长复用时间，秒 |
| JW_MAX_CONCURRENT | 4 | 同时访问教务的请求上限 |
| JW_REQUEST_TIMEOUT | 30 | 单次教务 HTTP 请求超时，秒 |
| TRUSTED_PROXY_HOPS | 1 | 从 X-Forwarded-For 末端计算的可信代理跳数 |
| FREE_CLASSROOM_SID | 924101960123 | 本科服务账号学号 |
| CAPTCHA_OCR_MODEL_PATH | common.onnx | ddddocr 通用模型路径；文件缺失时自动回退二维码登录 |
| ONNXRUNTIME_SHARED_LIBRARY_PATH | 空 | ONNX Runtime 动态库路径；空值按可执行文件目录和当前目录探测 |
| STATIC_DIR | wxcloudrun/static | 静态资源目录 |
| LOG_LEVEL | INFO | DEBUG、INFO、WARN 或 ERROR |

### 微信订阅

| 变量 | 说明 |
|---|---|
| MP_APPID | 小程序 AppID；仓库内有当前应用默认值 |
| MP_SECRET | 小程序 AppSecret；未配置时只记录额度，不发送消息 |
| SUBSCRIBE_TPL_EXAM | 考试提醒模板 ID |
| SUBSCRIBE_TPL_GRADE | 成绩提醒模板 ID；空值回退考试模板 |

### 后台任务

以下开关默认开启，设置为 0、false 或 off 可关闭：

- AUDIT_CATALOG_SYNC：每日 00:05 检查并刷新蹭课目录
- GENERAL_EDUCATION_SYNC：每日 00:10 检查并刷新通识选修课目录
- FREE_CLASSROOM_PREWARM：启动时及每日 00:02 预热当天空教室
- EXAM_REMINDER：每 10 分钟扫描提醒
- REMINDER_LIFECYCLE：启用课程结课、考试、成绩提醒生命周期

## 本地运行

需要 Go 1.26.9+ 和可访问的 MySQL。Go 版不支持 SQLite。

    go mod download
    go run ./cmd/migrate
    go run ./cmd/server

Windows PowerShell 示例：

    $env:MYSQL_ADDRESS = "127.0.0.1:3306"
    $env:MYSQL_USERNAME = "root"
    $env:MYSQL_PASSWORD = "..."
    $env:MYSQL_DATABASE = "flask_demo"
    $env:SESSION_KEY = "..."
    $env:ADMIN_PASSWORD = "..."
    go run ./cmd/migrate
    go run ./cmd/server

服务默认监听 80。开发热重载见 docs/live-coding.md。

## 测试

    go test ./...
    go vet ./...
    go test -race ./...

Linux 构建需要 CGO 和 C 编译器；ONNX Runtime 在运行时动态加载：

    CGO_ENABLED=1 GOOS=linux GOARCH=amd64 go build -o .tmp/server ./cmd/server
    CGO_ENABLED=1 GOOS=linux GOARCH=amd64 go build -o .tmp/migrate ./cmd/migrate

## 云托管部署

微信云托管只运行常驻服务，生产环境的迁移与启动流程如下：

先在目标版本容器的 WebShell 中显式执行完整启动命令：

    set -eu
    cd /app
    ./migrate
    exec ./server

也可以执行：

    /app/manual-start

服务进程只执行只读 Schema 校验，不运行 DDL。迁移失败时命令立即停止，不得继续启动服务；迁移成功并确认 `/readyz` 返回 200 后，才能切换生产流量。镜像默认 `/app/server` 仅用于 Schema 已迁移完成后的正常运行和重启。

如果 WebShell 所在实例已经由平台运行 `/app/server`，完整启动命令会因 80 端口占用而失败。此时先执行 `/app/migrate`，再通过平台重启实例，由 Docker CMD 启动新版本服务，不要强制终止平台管理的进程。

container.config.json 只负责确保数据库存在，所有表、列、索引和迁移版本统一由 cmd/migrate 管理，避免控制台 SQL 与代码迁移出现双重来源。

生产最终镜像只包含：

- server 和 migrate 两个 Go 二进制
- ddddocr 通用模型与 ONNX Runtime 1.23.2 动态库
- wxcloudrun/static
- wxcloudrun/templates/admin.html
- CA 证书、时区数据和仅授予 server 的低端口绑定能力

建议保持单实例运行。当前共享缓存、定时任务锁和部分限流状态位于进程内；需要水平扩容时，应先把这些状态迁移到 Redis 或数据库。

## 运维端点

| 端点 | 用途 |
|---|---|
| GET /healthz | 进程存活 |
| GET /readyz | MySQL 与已配置 Redis 的就绪状态 |
| GET /metrics | 非敏感累计请求指标（不公开在线用户数） |
| GET /admin | 管理控制台 |

## API 兼容

- 认证头保持 X-Auth-Token。
- 响应继续使用 success、message 和既有业务字段。
- /api/login-webvpn、/api/get-webvpn-captcha 和二维码登录路由保留。
- /api/get-captcha、/api/login、/api/login-manual 保留路径，但明确返回教务直连已下线。
- /api/login-webvpn-manual 保留路径，但返回无需第二步教务登录。

完整职责、数据流和接口分组见 docs/architecture.md。

## License

MIT
