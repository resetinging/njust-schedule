# 课表助手

面向本校学生的教务一站式 Web 应用:登录强智教务系统,拉取并展示**课表、考试安排、教学评价、成绩绩点、四六级成绩**,支持**批量自动评教**与**保研口径 GPA** 计算。部署于微信云托管(Flask + MySQL),手机端可安装为 PWA。

> 本项目从桌面版迁移而来,基于微信云托管 Flask 模板框架二次开发,原模板的计数器示例代码已不再使用。
>
> 配套微信小程序与本后端的分工、模块划分与接口契约,详见 [docs/architecture.md](docs/architecture.md)。
>
> **架构(方案 A)**:后端收敛为「教务网关 + 认证 + 提交中转」,业务计算(GPA 绩点、评教自动评分、批量评教循环)已移至前端(小程序 `utils/gpa.js`、`eval.js`,Web `evaluations.js`)。

## 功能

- **课表**:周视图 + 手机列表视图,自动计算当前教学周(根据学期第一周周一),高亮今日课程
- **考试**:考试安排列表(时间/考场/座位号)
- **教学评价**:
  - 拉取评价批次与课程列表,解析评价指标表单
  - 按目标分自动填选(默认 95 分,含防同列机制与微调优化)
  - 后台线程批量保存/提交全部课程,进度实时可见
  - 内置教务页面反向代理(`/proxy/jw/*`),可在本应用中直接打开教务评价页
- **成绩与绩点**:
  - 成绩记录按学期存储,计算学期绩点与全部学期加权平均绩点(4.0 量表)
  - 排除通识教育选修课、缓考/缺考/免修等非正式成绩
  - 保研模式:四六级成绩按官方公式折算百分制,替换英语模块(8 学分)重算 GPA
- **登录**:支持智慧理工 SSO 密码登录与微信扫码登录。密码默认由后端 AES-256-GCM 加密保存，用于 24 小时内的 Cookie 快速恢复和会话失效自动重登；退出登录不删除密码，管理员不能查看明文。会话失效时后台全量同步会立即中止，不继续请求后续教务数据域
- **蹭课查询**:按课程名称、任课教师、地点、星期和节次组合查询教务课程课表; 支持同维度多选、不同维度同时匹配; 只展示课程名、教师、星期、节次、周次和教室等实际可得字段

## 技术栈

- 后端:Python 3.10 / Flask 2.2 / SQLAlchemy 1.4 / MySQL / gunicorn(单 worker 多线程,会话在进程内存)
- 爬虫:requests + BeautifulSoup(lxml),HTML 解析带多策略降级(API → 查询页表单 → 列表页)
- OCR:ddddocr(验证码自动识别)
- 前端:原生 JS + PWA(Service Worker 离线缓存)
- 部署:微信云托管(Dockerfile + container.config.json)

## 目录结构

```
.
├── config.py                    集中配置(数据库、教务 URL、大节定义、HTTP 头)
├── run.py                       Flask 启动入口
├── requirements.txt             依赖清单
├── Dockerfile                    云托管容器构建
├── container.config.json         云托管服务设置与建表 SQL
├── wxcloudrun/                   app 目录
│   ├── __init__.py               Flask 应用与 SQLAlchemy 初始化
│   ├── views.py                  页面路由 + Blueprint 装配 + 字体接口
│   ├── api/                      各域接口(认证/课表/成绩/评教/空教室/学习/订阅)
│   ├── core/                     通用能力(会话/Cookie 加密/限流/微信订阅/考试提醒)
│   ├── jwc_client.py             教务客户端门面(组合 jwc/ 下各域 mixin)
│   ├── jwc/                      教务各域 mixin(课表/考试/成绩/评教/周历/培养方案/学籍)
│   ├── model.py                  ORM 模型(Course/Exam/Evaluation/Grade/CetScore/Setting)
│   ├── dao.py                    数据访问层
│   ├── templates/                Jinja2 页面模板(课表/考试/成绩/评教/校历/设置)
│   └── static/                   前端资源(JS/CSS/PWA/图标/校历图片)
├── docs/
│   └── architecture.md           小程序前后端职责说明与接口契约
```

## 快速开始

### 环境变量

| 变量 | 说明 | 默认 |
|---|---|---|
| `SQLALCHEMY_DATABASE_URI` | 数据库连接串；本地可用 `sqlite:///xxx.db` | 空(则必须配置下列 MySQL 变量) |
| `MYSQL_USERNAME` / `MYSQL_PASSWORD` / `MYSQL_ADDRESS` | 云托管 MySQL 连接信息；生产环境必须完整配置 | 空 |
| `DEBUG` | Flask 调试模式(生产环境保持关闭) | `False` |
| `JW_MAX_CONCURRENT` | 教务访问池并发上限(同时进行的教务 HTTP 请求数,防打爆教务服务器) | `4` |
| `SESSION_TTL` | 用户会话无活动回收时间(秒) | `43200`(12h) |
| `MAX_SESSIONS` | 用户池上限,超限自动淘汰最久未活动会话 | `200` |
| `DATA_CACHE_TTL` | 课表/成绩/评教/周历/培养方案/学籍等业务数据缓存时间(秒) | `2592000`(30天) |
| `SSO_SESSION_MAX_AGE` | 教务持久 Cookie 最长复用时间(秒) | `2592000`(30天) |
| `CREDENTIAL_TRUST_TTL` | 服务端保存密码的本地信任期；只有真实 SSO 成功才续期(秒) | `86400`(24小时) |
| `NETWORK_CACHE_TTL` | `/api/status` 教务连通性结果缓存时间(秒) | `300`(5分钟) |
| `FREE_CLASSROOM_PREWARM_DAYS` | 空教室后台预热天数(1=仅今天, 2=今天+明天) | `1` |
| `FREE_CLASSROOM_COOKIE_SOURCE` | 空教室 Cookie 来源: `auto`/`active-only`/`persistent-only`/`service-only` | `auto` |
| `FREE_CLASSROOM_CANDIDATE_RETRIES` | 每类 Cookie 候选重试上限 | `5` |
| `FREE_CLASSROOM_PERSISTED_LIMIT` | 单次读取的持久化 Cookie 候选上限 | `50` |
| `TRUSTED_PROXY_HOPS` | 可信反向代理跳数, 用于安全解析客户端 IP | `1` |
| `JW_TRY_DEFAULT_PWD` | 是否允许尝试教务初始密码兜底(高风险, 默认关闭) | `false` |
| `ADMIN_REQUEST_TTL` | 管理端请求监控缓冲留存时间(秒) | `900` |
| `ADMIN_PASSWORD` | 管理控制面板(/admin)登录口令; 未配置则本次运行随机生成(重启即变) | 随机 |
| `SESSION_KEY` | 32 字节 base64 密钥: 教务会话/密码加密落库, 并派生 admin token 签名 | 空(相关能力禁用) |
| `REDIS_URL` | 可选 Redis 地址；启用后会话、限流、缓存和调度锁可跨 worker 共享 | 空(单实例内存模式) |
| `MIGRATIONS_AUTO` | 是否启动时自动执行幂等迁移；生产建议 `0` 并在发布阶段运行 `python tools/migrate.py` | `1` |
| `REQUIRE_SECURE_CONFIG` | 是否强制生产密钥配置，缺少 `SESSION_KEY`/`ADMIN_PASSWORD` 时拒绝启动 | `0` |
| `MP_SECRET` | 小程序 AppSecret: 订阅消息(考试提醒)发送用; 不配置则只记录授权、不发送 | 空(发送禁用) |
| `SUBSCRIBE_TPL_EXAM` | 考试提醒的订阅消息模板 ID | 已内置 |
| `EXAM_REMINDER` / `EXAM_REMINDER_HOUR` | 考试提醒开关 / 考前一天开始提醒的小时(北京时间) | `1` / `18` |

### 本地运行

```bash
pip install -r requirements.txt
python run.py 127.0.0.1 5000
```

浏览器访问 http://127.0.0.1:5000,在「设置」页登录教务系统后即可刷新数据。
注意:教务系统仅限校园网或 VPN 环境访问。

### 安全扫描

```bash
pip install -r requirements-dev.txt
python tools/security_scan.py
```

脚本会依次执行 Python 编译检查、凭据/会话/管理端/冒烟测试、pytest、
`pip-audit` 依赖漏洞扫描和 Bandit 静态安全扫描。仓库内的
`.github/workflows/security.yml` 会在 push/PR 时执行同一入口。

### 云托管部署

使用微信云托管控制台选择本仓库部署(参考[云托管快速开始](https://developers.weixin.qq.com/miniprogram/dev/wxcloudrun/src/basic/guide.html)),数据表由 `container.config.json` 的建表 SQL 与应用启动时的 `db.create_all()` 双保险创建。

**单实例部署**(`minNum`/`maxNum` 已设为 1):教务会话保存在容器内存中,多实例弹性扩容会导致用户登录态被负载均衡随机丢失;单实例 1 核 2G 对几十人规模足够(并发由访问池限流保护),且 `minNum=1` 常驻避免冷启动。

## 主要 API

| 端点 | 说明 |
|---|---|
| `GET /api/status` | 登录状态、学期、数据统计 |
| `POST /api/login` / `POST /api/login-manual` / `GET /api/get-captcha` | **已下线**(教务直连),返回「教务直连已下线」 |
| `POST /api/refresh-schedule` / `refresh-exams` / `refresh-all` | 从教务刷新课表/考试/全部 |
| `POST /api/refresh-grades` / `refresh-cet` / `refresh-evaluations` | 刷新成绩/四六级/评价列表 |
| `GET /api/courses` / `exams` / `grades` / `cet-scores` / `evaluations` | 查询已存储数据(**原始数据**,GPA/折算等计算在前端完成) |
| `GET /api/eval-courses` / `eval-form` | 解析评教课程列表 / 评价表单 |
| `POST /api/submit-eval` | 单门评教提交中转(批量循环由前端执行) |
| `POST /api/jw-proxy` | 通用教务网关:转发任意 9080 GET/POST 并返回原始内容 |
| `POST /api/login-webvpn` | 智慧理工 SSO 一步登录(免教务密码/验证码);`get-webvpn-captcha` 为其旧名别名 |
| `DELETE /api/credentials` | 删除当前用户明确授权保存的服务端密码 |
| `POST /api/sso-qr/start` / `GET /api/sso-qr/status` / `POST /api/sso-qr/cancel` | 微信扫码登录(免密码): 长按二维码→识别图中二维码→确认 |
| `GET/POST /api/settings`, `POST /api/semester` | 设置与学期切换 |
| `POST /api/clear-data` | 清除当前学期数据 |
| `GET /api/connect-test` | 教务连通性测试 |
| `GET/POST /proxy/jw/*` | 教务页面反向代理(评教用) |
| `GET /api/calendar` / `POST /api/refresh-calendar` | 教学周历(第 N 周→日期); 登录后自动回写 `first_week_date`(以教务为准) |
| `GET /api/programme` / `POST /api/refresh-programme` | 专业培养方案(整份, 自动翻页); 学分进度数据源 |
| `GET /api/profile` / `POST /api/refresh-profile` | 学籍卡片(院系/专业/班级等; 30 天缓存, 不含头像) |
| `GET /api/subscribe/status` / `POST /api/subscribe/grant` | 订阅消息额度查询 / 授权上报(当前仅考试提醒) |
| `POST /api/subscribe/test-send` | 发送一条样例考试提醒(验证模板与密钥, 消耗 1 次额度) |

## 使用注意

- 教务系统需要校园网或 VPN 才能访问;**登录必须显式提供密码**(不接受空密码/仅凭历史会话登录),Session 过期后需重新输入学号与密码。
- 服务端在配置 `SESSION_KEY` 后**默认加密保存登录密码**(AES-256-GCM, 学号绑定)。密码匹配且距最近一次真实 SSO 认证不超过 24 小时时可优先复用教务 Cookie；退出登录保留密码，管理员控制台不提供明文查询。
- 空教室刷新优先随机使用活跃本科教务 Cookie，其次使用持久化本科 Cookie，最后回退服务账号；同一轮刷新复用同一教务会话。
- **多用户**:每位用户独立登录、持有独立的教务会话(以登录签发的 token 标识),课表/考试/成绩/评教/四六级数据按学号隔离、互不可见。未配置 Redis 时会话保存在容器内存;配置 `REDIS_URL` 后会话 Cookie 加密写入 Redis，可由多个 worker 恢复。
- 生产探针：`GET /healthz`、`GET /readyz`；指标：`GET /metrics`。
- 批量评教为自动化辅助工具,请仅用于自己的账号,并自行承担使用责任。

## License

[MIT](./LICENSE)
