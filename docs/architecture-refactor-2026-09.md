# 架构重构记录（2026-09）

> 目标：优化项目结构与代码架构，**不改变任何对外行为**（URL/参数/响应/页面样式不变）。
> 方式：分阶段机械拆分 + 每步跑 `tests/smoke_test.py`（关键步骤加跑 `tests/multi_user_test.py`、`node tools/test_freeclass.js`）。
> 状态：**本地完成，待最终 review**。未提交、未推送。

## 服务端

### 拆分结果

| 层 | 内容 |
|---|---|
| `wxcloudrun/core/` | `cache`（进程内 TTL 缓存）、`sessions`（会话池/验证码临时会话）、`session_store`（SSO 会话持久化 + 认证节流）、`pool`（教务访问池/信号量）、`web`（请求日志/rid）、`auth`（登录守卫/重登封装）、`stats`（数据统计缓存）、`timeutil`（北京时间）、`media`（图片类型嗅探） |
| `wxcloudrun/api/` | `auth` / `schedule` / `exams(并入 schedule)` / `grades` / `eval` / `freeclass` / `feedback` / `settings` / `status` / `proxy` / `gallery` 蓝图层 |
| `wxcloudrun/jwc/` | `common`（常量/工具/CookieJar/SSO 加密）+ `base/login/core/schedule/exams/utils/eval/grades/cet/freeclass` 分域 mixin |
| `wxcloudrun/jwc_client.py` | 门面：组合各 mixin，re-export 旧符号，调用方零改动 |
| `wxcloudrun/views.py` | 仅保留 6 个页面路由 + 蓝图装配（1832 → 139 行） |
| `wxcloudrun/services/` | 统一教务刷新编排、错误映射、缓存失效与提醒同步；共享蹭课目录同步与用户数据刷新分离 |
| `wxcloudrun/repositories/` | 以用户学习数据和全校蹭课目录为边界，集中查询与原子快照替换 |
| `wxcloudrun/core/transactions.py` | 统一 SQLAlchemy 提交/回滚，刷新失败时保留上一份可用快照 |
| `wxcloudrun/jobs/` | 后台任务统一启动器与三个任务适配器，避免重复启动线程 |

### 数据库迁移启动策略

- 生产默认 `MIGRATIONS_AUTO=0`，应用启动仅执行只读 Schema 检查，不调用 `db.create_all()`。
- 发布阶段显式运行 `python tools/migrate.py`；迁移入口使用 MySQL 命名锁，避免多实例同时执行 DDL。
- 本地测试通过 `_run_migrations(force=True)` 建立临时数据库；迁移脚本通过 `SCHEMA_CHECK_ON_STARTUP=0` 导入应用后显式执行迁移。
- Schema 的表、关键列或迁移版本不完整时应用启动失败并提示迁移，不以运行时隐式建表掩盖发布遗漏；DDL 失败也不会登记迁移版本。

### 兼容策略

- 所有从 `views.py` 拆出的符号在其顶部显式 re-export（`views._sessions`、`views._register_session`、`views._freeclass_resp`、`views._build_ordered_eval_post_data` 等），既有测试/探针脚本无需修改。
- `jwc_client.py` 保持原导入路径：`from wxcloudrun.jwc_client import JWCClient, CLASSROOM_SLOTS, ClassroomBorrowError, _dedupe_schedule_courses` 全部可用。
- 跨层引用统一走 core（如 `core.auth._require_login`），个别仍需 views 的助手用惰性导入（`_current_semester`、`_warm_eval_session`、`_check_network`）避免循环依赖。

## 小程序

| 层 | 内容 |
|---|---|
| `utils/api.js` | 聚合入口（facade）：`Object.assign({}, require('./api/*'))`，对外 40 个 API 函数签名不变 |
| `utils/api/` | `core`（request/401 自动重登）+ `auth/schedule/exams/grades/eval/feedback/settings/freeclass/gallery/refresh` 分域模块 |

## 测试策略

- 现有测试文件保持原路径与运行方式（`python tests/smoke_test.py` 等），不做目录搬迁，避免破坏文档/习惯命令。
- 回归覆盖：`smoke_test`（40 项）、`multi_user_test`（29 项）、`node tools/test_freeclass.js`（26 项）、真实样本离线回归。
- 架构回归：`tests_pytest/test_services_architecture.py` 覆盖服务层入口、Repository 原子替换和任务启动注册；`pytest -q` 与既有脚本测试均需通过。

## 后续可选

- 测试目录若需 `unit/integration/probes` 分类，可加壳入口后再搬迁。
