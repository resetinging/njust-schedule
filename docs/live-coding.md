# 云托管实时开发（Live Coding）配置说明

> 用途：改代码不用重新构建镜像/发布，保存即生效，适合调试教务抓取、接口联调。
> 官方文档：微信云托管 → 操作指南 → 本地调试 → 实时开发

## 一、准备

1. **Docker Desktop**（Windows 必须装，且建议开启 WSL2 后端）。本项目当前机器未安装。
2. VSCode 安装插件 **Weixin Cloudbase**（微信云托管官方插件）。
3. 仓库里已有两个配置文件（**不要删**，删了插件会按 `Dockerfile` 重新生成、丢掉本项目定制）：
   - `Dockerfile.development`：开发镜像，用 nodemon 监听改动并重启服务
   - `docker-compose.yml`：把当前目录挂进容器，映射端口 27081 → 容器 80

## 二、使用

1. VSCode 打开本项目，确认左侧出现云托管容器（`flask-5da7`）。
2. 右键容器 → **Live Coding**；插件会用 `Dockerfile.development` 启动容器。
3. 启动完成后按提示打开访问地址（`http://127.0.0.1:27081`）。
4. 修改任意 `.py/.html/.js/.json/.css`，nodemon 会自动重启，刷新即可看到效果。
5. 结束：右键运行中的容器 → **Stop**。

### 让小程序连到实时开发容器

两种方式，任选其一：

- **微信开发者工具「本地调试」**（推荐）：工具里开启云托管本地调试并选择该容器，小程序走
  `wx.cloud.callContainer` 的代码无需改动。
- **直连端口**：把 `.miniapp/utils/config.js` 改成 `USE_LOCAL = true` 且
  `LOCAL_BASE = 'http://127.0.0.1:27081'`，并在开发者工具勾选「不校验合法域名」。
  测完记得改回 `USE_LOCAL = false` 并同步到 `miniprogram` 目录。

## 三、数据库

默认走**云端 MySQL**：compose 里预留了 `MYSQL_USERNAME / MYSQL_PASSWORD / MYSQL_ADDRESS` 三个
变量，由插件的「本地调试」注入（云端内网地址需要 VPC 打通）。

想用本地 sqlite 调试，取消 `docker-compose.yml` 里这一行注释即可：

```yaml
- SQLALCHEMY_DATABASE_URI=sqlite:////app/local_dev.db
```

## 四、注意事项

- **Windows 文件事件**：Docker Desktop 非 Edge 版收不到宿主文件变化，所以 CMD 里已加
  `--legacy-watch`（CPU 占用略高，但热重载可靠）。
- **空教室预热**：compose 里默认设了 `FREE_CLASSROOM_PREWARM=0`，避免本地每次重启都去抓教务；
  要调预热逻辑再临时打开。
- **单进程约束**：会话保存在进程内存，gunicorn 必须 `--workers 1`，实时开发与生产都保持单 worker。
- 生产镜像仍走 `Dockerfile`（`gunicorn run:app`），两个文件互不影响。
