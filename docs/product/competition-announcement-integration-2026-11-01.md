# 竞赛公告集成（2026-11-01）

> 状态：已实现，本地未提交/未发布。版本记录并入 v1.11.0，BUILD `2026.11.27.2`。
> 本文不含账号、Cookie、Token 或任何真实用户数据。

## 1. 官方源核验结论

目标页面：<https://xspace.njust.edu.cn/14263/list.htm>

已核验：
- 用户此前从工作区普通 HTTP 访问目标页、X·Space 首页和南理工官网首页，均返回 **202 HTML 防护页**；
- `robots.txt`、`sitemap.xml` 曾返回 200，但内容为通用 HTML 错误页，不是 robots/sitemap；
- 2026-11-01 本轮再次尝试官方公开源：本环境 `web_fetch` 对 `xspace.njust.edu.cn` 返回“解析到非公网地址”错误，目标页、`robots.txt`、`sitemap.xml`、`rss.xml` 均无法读取；
- 公开搜索只能看到零散官方文章页（如 `c14263a.../page.htm`、`c14298a.../page.htm`），未发现 RSS/API/JSON 列表接口或稳定的列表字段结构。

结论：**没有可重复访问的官方机器可读源**。因此不实现自动抓取、不运行/解析防护脚本、不绕过防护、不借用登录态；采用管理员维护方案，不编造公告数据。

## 2. 方案

扩展既有 `settings.content_board_v1` JSON，增加 `competitions` 数组；不新建表、不做数据库迁移。

```json
{
  "updated": "2026-11-01 12:00:00",
  "announcements": [],
  "competitions": [
    {
      "id": "comp-...",
      "title": "竞赛名称",
      "summary": "列表摘要（可空，摘要/正文至少一项）",
      "body": "详细说明（可空）",
      "published_at": "2026-10-20",
      "deadline": "2026-11-01",
      "source_url": "https://xspace.njust.edu.cn/14263/list.htm",
      "enabled": true
    }
  ],
  "community": {"name": "", "qq": "", "note": ""}
}
```

- `deadline` 可为空字符串；
- `enabled=false` 的条目只存在于后台，不进入公开接口；
- 旧版 JSON 没有 `competitions` 时按空数组兼容；旧 `/api/announcement` 继续只读取公告，语义不变；
- 公开 `/api/content-board` 返回启用竞赛，按 `published_at` 倒序；`deadline` 只展示，不作为自动过期条件。

## 3. 服务端校验

- 必填：`id`、`title`、`published_at`、`source_url`；`summary`/`body` 至少一项非空；
- 长度：标题 ≤100 字、摘要 ≤300 字、正文 ≤3000 字、URL ≤500 字；最多 50 条竞赛；整个 board ≤60000 字节；
- `id` 唯一，最长 100；
- `published_at`、`deadline` 必须是 `YYYY-MM-DD`；`deadline` 不得早于 `published_at`；
- `source_url` 必须是 `https`，禁止 userinfo 和自定义端口（443 可为空）；
- host 只允许：
  - `xspace.njust.edu.cn`
  - `njust.edu.cn`
  - `*.njust.edu.cn` 子域
- `enabled` 为布尔值；缺失按 false 处理，后台新增默认 true。

## 4. 后台管理

「信息中心」管理页新增“竞赛”编辑区：

- 新增 / 编辑 / 删除；
- 启停（显示）复选框；
- 字段：标题、发布日期、截止日期（可空）、原文链接、摘要、正文；
- 保存仍走 `POST /api/admin/content-board`，由服务端统一校验；不新建接口、不新建表。

## 5. 小程序

信息中心新增独立「竞赛」Tab：

- 只展示服务端返回的启用条目；无真实条目时显示“暂无竞赛信息”空态，不塞示例数据；
- 按发布日期倒序；
- 展示标题、发布日期、摘要/正文、截止日期；截止日期为空显示“截止日期待定”；
- 每项提供“复制原文链接”，复制后短暂显示“已复制链接”；沿用小程序“复制后到浏览器打开”的既有规则，不新增外链跳转能力；
- 旧版公告、更新记录、联系 Tab 与旧 `/api/announcement` 行为保持不变。

## 6. 测试

- Go：竞赛校验（必填、长度、日期、域名/协议/端口、仿冒域名）、公开过滤/倒序、旧 JSON 兼容、后台非法链接拒绝；全量 `go test` 与 `go vet`。
- 小程序：`test_content_board.js` 覆盖竞赛过滤/倒序/摘要回退/空数组兼容；`test_notice_board.js` 覆盖竞赛 Tab、复制链接、空态与 WXML 契约；WXML/miniapp/图标校验。
- 验收修正：刷新加载态判断纳入竞赛、更新记录和联系信息缓存，已有内容时刷新不再闪回整页骨架屏；后台 `admin.js` 查询串更新，避免浏览器复用旧脚本。

## 7. 已知限制

- 竞赛数据完全由管理员维护，不自动同步 X·Space；官方页面改版或新增公告时需要管理员手工录入/更新。
- 没有可重复访问的官方 RSS/API，因此不会做自动抓取；若后续出现稳定官方机器可读源，再另行设计后端刷新/缓存与去重。
- 原文链接只做域名白名单，不校验页面内容；管理员应确认标题、日期和链接确实对应官方通知。
- 截止日期仅展示，不会自动隐藏过期竞赛；需要隐藏时由管理员关闭 `enabled`。
- 当前没有真实竞赛条目，空态是诚实状态；不预置示例数据。
