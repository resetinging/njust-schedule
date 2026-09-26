# 架构重构记录（2026-09）

> 目标：优化项目结构与代码架构，**不改变任何对外行为**（URL/参数/响应/页面样式不变）。
> 方式：分阶段机械拆分 + 每步跑 `tests/smoke_test.py`（关键步骤加跑 `tests/multi_user_test.py`、`node tools/test_freeclass.js`）。
> 状态：**未推送**（本地检查点）。

## 服务端

### 拆分结果

| 层 | 内容 |
|---|---|
| `wxcloudrun/core/` | `cache`（进程内 TTL 缓存）、`sessions`（会话池/验证码临时会话）、`session_store`（SSO 会话持久化 + 认证节流）、`pool`（教务访问池/信号量）、`web`（请求日志/rid）、`auth`（登录守卫/重登封装）、`stats`（数据统计缓存）、`timeutil`（北京时间）、`media`（图片类型嗅探） |
| `wxcloudrun/api/` | `auth` / `schedule` / `exams(并入 schedule)` / `grades` / `eval` / `freeclass` / `feedback` / `settings` / `status` / `proxy` / `gallery` 蓝图层 |
| `wxcloudrun/jwc/` | `common`（常量/工具/CookieJar/SSO 加密）+ `base/login/core/schedule/exams/utils/eval/grades/cet/freeclass` 分域 mixin |
| `wxcloudrun/jwc_client.py` | 门面：组合各 mixin，re-export 旧符号，调用方零改动 |
| `wxcloudrun/views.py` | 仅保留 6 个页面路由 + 蓝图装配（1832 → 139 行） |

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

## 后续可选

- 测试目录若需 `unit/integration/probes` 分类，可加壳入口后再搬迁。
