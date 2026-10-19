# WebGo 实时开发

本项目的实时开发镜像使用 Go 1.26.9、CGO 工具链和 Air。它只用于本地或微信云托管插件的 Live Coding，不参与生产构建。

## 文件职责

| 文件 | 作用 |
|---|---|
| Dockerfile | 生产多阶段构建，最终镜像不包含编译器 |
| Dockerfile.development | 开发镜像，安装 Go、Git 和 Air |
| docker-compose.yml | 源码挂载、端口、依赖缓存和环境变量 |
| .air.toml | 文件监听、迁移和重启规则 |

Air 监听 Go、HTML、CSS、JS 和 JSON。每次构建前先运行 cmd/migrate，迁移失败时不会启动开发服务。

## 前置条件

- Docker Desktop
- 可访问的 MySQL
- 有效的 MYSQL_ADDRESS、MYSQL_USERNAME、MYSQL_PASSWORD
- 有效的 SESSION_KEY 和 ADMIN_PASSWORD
- 本地网络可以访问智慧理工和教务，或已连接学校 VPN

Go 版只支持 MySQL，不支持 SQLite。

## Docker Compose

PowerShell 中先设置环境变量：

    $env:MYSQL_ADDRESS = "host:3306"
    $env:MYSQL_USERNAME = "root"
    $env:MYSQL_PASSWORD = "..."
    $env:MYSQL_DATABASE = "flask_demo"
    $env:SESSION_KEY = "..."
    $env:ADMIN_PASSWORD = "..."

启动：

    docker compose up --build

访问：

- 服务：http://127.0.0.1:27081
- 健康检查：http://127.0.0.1:27081/healthz
- 就绪检查：http://127.0.0.1:27081/readyz
- 管理端：http://127.0.0.1:27081/admin

停止：

    docker compose down

go-mod-cache 和 go-build-cache 是命名卷，避免每次重建重新下载依赖。

## 微信云托管插件

使用 CloudBase/微信云托管插件进入 Live Coding 时：

1. 插件读取 docker-compose.yml。
2. 当前仓库挂载到 /app。
3. Dockerfile.development 安装 Air。
4. Air 首次执行数据库迁移并构建 cmd/server。
5. 保存受监听文件后，Air 终止旧进程并重新构建。

compose 中保留 wxPort、hostPort、wxcloud 和服务名标签，供插件识别。容器名虽然保留历史服务标识 flask-5da7，但运行时已经是 WebGo。

## 直接运行

不使用 Docker 时：

    go mod download
    go run ./cmd/migrate
    go run ./cmd/server

也可以在本机安装 Air：

    go install github.com/air-verse/air@v1.63.0
    air -c .air.toml

## 开发开关

本地开发通常关闭会访问教务的后台任务：

    $env:FREE_CLASSROOM_PREWARM = "0"
    $env:AUDIT_CATALOG_SYNC = "0"
    $env:EXAM_REMINDER = "0"

REMINDER_LIFECYCLE 只在 EXAM_REMINDER 已启用且 MP_APPID、MP_SECRET 可用时生效。

## 常见问题

### 配置无效并退出

服务会在启动时强制检查 MySQL、SESSION_KEY 和 ADMIN_PASSWORD。查看容器日志中的“配置无效”字段，补齐对应环境变量。

### 迁移失败

Air 的 pre_cmd 会先运行迁移。检查：

- MySQL 地址是否是 host:port
- 数据库账号是否有 CREATE、ALTER、INDEX 权限
- 是否存在长事务持有 metadata lock
- audit_courses.class_info 和 audit_favorites.class_info 是否已为 TEXT

迁移使用 MySQL 命名锁。不要同时手工运行相同 ALTER TABLE。

### 热重载没有触发

- 确认源码目录确实挂载到 /app
- 查看 Air 日志是否发现文件变更
- 确认文件扩展名在 .air.toml 的 include_ext 中
- Windows 文件共享异常时重启 Docker Desktop 后重建容器

### 就绪检查失败

/readyz 会检查 MySQL；配置 REDIS_URL 后也会检查 Redis。健康检查通过但就绪检查失败，表示进程仍在运行，但不应接收业务流量。

### 教务请求失败

先访问 /api/connect-test。智慧理工要求验证码时，生产环境会使用本地 OCR；本地开发需同时配置 `CAPTCHA_OCR_MODEL_PATH` 和 `ONNXRUNTIME_SHARED_LIBRARY_PATH`，不可用时回退二维码登录。

## 与生产的差异

| 开发 | 生产 |
|---|---|
| 包含 Go、CGO 工具链和 Air | 两个 CGO Go 二进制、ONNX 模型与运行库 |
| 源码挂载 | 只复制构建产物与运行资源 |
| 保存后自动迁移、重建 | 默认只校验 Schema；维护时显式设置 `MIGRATIONS_AUTO=1` 执行迁移 |
| 可关闭后台任务 | 按云环境变量运行后台任务 |

两种环境使用同一个 cmd/server、cmd/migrate 和 MySQL Schema，不维护独立的开发实现。
