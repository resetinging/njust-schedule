# 文档索引

> 状态：现行文档索引

> 最后整理：2026-11-24
>
> Agent 接手时按以下顺序阅读：仓库 `AGENTS.md` → 本文 → `HANDOFF.md` → 当前架构 → 对应领域文档。

## 状态说明

| 状态 | 含义 |
|---|---|
| 现行 | 当前实现和操作方式，可作为执行依据 |
| 参考 | 特定流程、算法或背景资料，使用前核对代码 |
| 已完成归档 | 已实施或已过期的计划，仅用于追溯决策 |
| 研究记录 | 调研和选型过程，不代表当前实现 |
| 发布材料 | 宣传、视频和运营文案 |

## Agent 入口

- [交接说明](HANDOFF.md)
- [协作规则](../AGENTS.md)
- [Claude/Codex 入口](../CLAUDE.md)
- [项目总览](../README.md)

## 架构

| 文档 | 状态 | 用途 |
|---|---|---|
| [current.md](architecture/current.md) | 现行 | 当前系统边界、登录、数据、接口、迁移和可靠性 |
| [refactor-2026-09.md](architecture/refactor-2026-09.md) | 已完成归档 | 2026-09 架构拆分记录 |

## 操作与发布

| 文档 | 状态 | 用途 |
|---|---|---|
| [live-coding.md](operations/live-coding.md) | 现行 | 本地运行、Docker Compose、Air 和云托管联调 |
| [miniprogram-launch.md](operations/miniprogram-launch.md) | 现行 | 微信小程序上线与提审流程 |
| [sso-login.md](operations/sso-login.md) | 参考 | 智慧理工密码登录链路和错误处理 |
| [CHANGELOG.md](releases/CHANGELOG.md) | 现行 | 面向版本的功能变更记录 |

## 产品与专题

| 文档 | 状态 | 用途 |
|---|---|---|
| [island-ui-redesign-2026-10-25.md](product/island-ui-redesign-2026-10-25.md) | 现行 | 小程序 Island 悬浮岛式界面规范与执行记录 |
| [exam-status-fix-2026-10-28.md](product/exam-status-fix-2026-10-28.md) | 现行 | 考试逐场状态、分组、缓存与异步竞态修复说明 |
| [library-inventory-2026-10-29.md](product/library-inventory-2026-10-29.md) | 现行 | 图书馆公共馆藏检索/逐册库存、OPAC 接口、缓存与测试 |
| [user-data-daily-sync-2026-11-01.md](product/user-data-daily-sync-2026-11-01.md) | 现行 | 用户数据每日批量预热、登录兜底与主动刷新回源 |
| [competition-announcement-integration-2026-11-01.md](product/competition-announcement-integration-2026-11-01.md) | 现行 | 竞赛公告官方源核验、管理员维护、后台校验与信息中心竞赛 Tab |
| [campus-services-backend-2026-11-24.md](product/campus-services-backend-2026-11-24.md) | 现行 | 校园服务后端、咨询线索加密、管理后台与迁移 |
| [campus-services-frontend-2026-11-24.md](product/campus-services-frontend-2026-11-24.md) | 现行 | 校园服务入口、服务簿、详情与咨询表单 |
| [partner-preview-account-2026-11-24.md](product/partner-preview-account-2026-11-24.md) | 现行 | 合作商共享登录、固定验收账号和空数据边界 |
| [data-refresh-policy.md](product/data-refresh-policy.md) | 现行 | 个人数据主动刷新回源、共享数据只读服务端与凌晨预热边界 |
| [frontend-style-refresh-2026-10-24.md](product/frontend-style-refresh-2026-10-24.md) | 历史基线 | 小程序视觉规范（唯一现行来源）：token、页面规则、验收与执行记录 |
| [design-style.md](product/design-style.md) | 历史参考 | 旧的紫调渐变风格稿，已被上一条取代，不得据此恢复 |
| [analytics-ad-plan.md](product/analytics-ad-plan.md) | 现行 | 使用统计、广告槽位和数据口径 |
| [standalone-grade-query.md](product/standalone-grade-query.md) | 参考 | 独立成绩抓取流程 |
| [gpa-audit.md](product/gpa-audit.md) | 研究记录 | GPA 口径和真实数据审计 |

## 已完成计划

以下文档保留历史决策，不再作为待办清单：

- [execution-plan-2026-10-02.md](plans/completed/execution-plan-2026-10-02.md)
- [freeclass-fix-plan.md](plans/completed/freeclass-fix-plan.md)
- [calendar-credit-plan.md](plans/completed/calendar-credit-plan.md)
- [nav-refactor-plan.md](plans/completed/nav-refactor-plan.md)
- [credential-storage-plan.md](plans/completed/credential-storage-plan.md)
- [password-storage-impl-plan.md](plans/completed/password-storage-impl-plan.md)
- [session-persistence-plan.md](plans/completed/session-persistence-plan.md)
- [roadmap-v1.1.md](plans/completed/roadmap-v1.1.md)
- [roadmap-v1.2.md](plans/completed/roadmap-v1.2.md)

## 研究与推广

- [swipe-nav-research.md](research/swipe-nav-research.md)：滑动导航调研，研究记录
- [promo-video-script.md](promotion/promo-video-script.md)：推广视频分镜
- [video-production-guide.md](promotion/video-production-guide.md)：视频制作流程
- [图文宣传文案](../poster/promo/文案.md)：海报和社交平台文案

## 独立服务与本地素材

- [demo-server/README.md](../demo-server/README.md)：录制演示数据和素材服务器
- `poster/updates/正文.md`：本地更新文案草稿，保留在素材目录

## 小程序仓库

小程序使用独立的 `miniapp` 分支和工作区。现行入口：

- `.miniapp/README.md`
- `.miniapp/docs/privacy-guideline.md`

修改小程序后必须同步到 `C:\Users\a\Documents\local\miniprogram`，不能只保存在 `.miniapp` worktree。
