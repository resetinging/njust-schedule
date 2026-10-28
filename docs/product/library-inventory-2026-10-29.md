# 图书馆库存查询（2026-10-29）

> 状态：已实现，本地未提交、未发布。版本：**v1.10.0**（BUILD `2026.10.29.1`）。范围：微信小程序 + Go/WebGo 后端。
> 本文不含任何密码、Cookie、Token 或真实用户/馆藏账号信息。

## 1. 目标与边界

- 在小程序「功能」页新增第 8 个入口「图书馆库存」，查询**公共 OPAC 纸本馆藏**。
- 支持按书名、作者、ISBN、索书号检索；明确提交后由本服务端分页返回，支持加载更多、错误重试、无结果。
- 搜索结果只展示书目元数据；用户点选某本书后，才请求该书的逐册馆藏，支持全部/南京/江阴筛选，统计与明细一致。
- 不接入借还、预约、个人借阅、通知、支付；不做全馆预抓取、不在登录时拉取、不在搜索列表中逐条抓库存。
- 访问本服务仍要求现有登录态（本科/研究生均可）；上游公共馆藏匿名访问，不取用任何用户教务 Cookie、服务账号或 SSO 凭据，不修改现有登录行为。
- 不新增 DB 迁移、不新增定时任务、不引入 Redis 缓存。

## 2. 入口与界面

- 生产主页：`pages/main/main` 功能页「校园工具」第二行新增「图书馆库存」（`data-page="library"`）。
- 页面内二级视图：`components/library-view`（Island 白卡/32rpx 岛圆角/像素字体继承/TDesign `t-popup` 底部弹层）。
- 交互：
  - 四个字段胶囊（书名/作者/ISBN/索书号）+ 输入框 + 圆形查询按钮（统一 `.refresh-action`，请求中 `is-busy` 单层旋转）；
  - 结果概览「共 N 条 + 旧缓存/更新时间 + 刷新」；书目卡片展示题名、作者/出版社/年份、索书号/ISBN、文献类型；
  - 加载更多、出错重试、无结果空态；
  - 点书目打开 `t-popup`（`--td-popup-distance-top: 12vh`），展示题名/元数据、全部/南京/江阴胶囊（含校区册数）、总册/可借册、逐册索书号/条码/馆藏地/状态；打开时通过 `popupstate` 隐藏浮动底栏；
  - “可借”只认状态明确等于「可借」的册；借出/在馆/不可借/未知保留原状态且不计入可借。
- DSL：`ui/pages/feature.ui.js` 增加 `library-entry`，用 `ui/compiler/cli.js` 重新生成 `components/generated/feature-page`（预览页，不替代生产主页）。
- 图标：新增真实资源 `static/icons/book-indigo.png`（96×96 RGBA），并在 `components/icon/index.wxml` 的 `file()` 映射登记；`tools/test_icon_assets.js` 通过。

## 3. 后端 API

两个接口都走现有 `X-Auth-Token` 登录校验；未登录 401。响应均为 JSON。

### 3.1 检索

`GET /api/library/search?field=title|author|isbn|callno&q=<关键词>&page=1&page_size=20`

- `q`：必填，1–80 字符，拒绝控制字符；`field` 缺省 `title`；`page` 1–50；`page_size` 1–50（缺省 20）。
- 显式非法分页参数返回 400（不静默回退）。

成功响应示例：

```json
{
  "success": true,
  "field": "title",
  "query": "高等数学",
  "page": 1,
  "page_size": 20,
  "total": 2582,
  "has_more": true,
  "records": [
    {
      "marc_no": "65743033384e4d567677433044795a4f5939463358413d3d",
      "title": "高等数学:理工类.上册.第3版",
      "author": "主编杨海涛",
      "publisher": "同济大学出版社",
      "pub_year": "2013",
      "isbn": "978-7-5608-5255-3",
      "call_no": "O13/797/V.1",
      "doc_type": "中文图书",
      "num": 1
    }
  ],
  "stale": false,
  "updated_at": 1793208600
}
```

- `total` 是本次关键词命中的结果总数（不是全馆藏书量），来自上游真实 `total`；不得伪造。
- `has_more = page * page_size < total`。
- 上游失败无旧缓存时返回 502 `{success:false,message:"图书馆检索服务暂时不可用，请稍后再试"}`，绝不把失败返回成空列表。

### 3.2 单本馆藏

`GET /api/library/item?marc_no=<不透明ID>&campus=all|nanjing|jiangyin`

- `marc_no`：8–128 个 `A-Za-z0-9+/=_-` 字符，拒绝 `../`、空格、query 注入等；只由固定上游 host/path 构造请求，不接受用户传上游 URL。
- `campus` 缺省 `all`；`nanjing`/`jiangyin` 只保留对应校区明细。

成功响应示例：

```json
{
  "success": true,
  "marc_no": "65743033384e4d567677433044795a4f5939463358413d3d",
  "scope": "jiangyin",
  "total": 2,
  "available": 2,
  "campus_counts": { "nanjing": 2, "jiangyin": 2, "unknown": 1 },
  "copies": [
    { "call_no": "O13/797/V.1", "barcode": "B0000001", "volume": "2013", "campus": "江阴", "location": "江阴综合书库305室", "status": "可借", "available": true }
  ],
  "stale": false,
  "updated_at": 1793208600
}
```

- `total`/`available` 是**当前校区筛选后**的统计（与明细一致）；`campus_counts` 是**全量**校区分布，供弹层显示三个胶囊的册数。
- 馆藏地以“南京/江阴”开头识别校区；无前缀归为“未知”，不强行映射。
- 空馆藏是合法结果（`copies: []`, `total: 0`），与上游错误严格区分。

## 4. 上游接口与失败判据（江苏汇文 OPAC，匿名）

- 高级检索页：`http://libopac.njust.edu.cn/uopac/opac/search_adv.php`（页面 JS 的真实请求格式见下）。
- `GET /uopac/opac/ajax_adv_info.php`：返回 searchFieldsList（`any`/`02`/`03`/`04`/`05`/`07`/`08`/`09`/`10`）、deptList（00 南京/06 江阴）、deptLocationList、locationList、docTypeList。仅作核对资料，不写入代码密钥。
- `POST /uopac/opac/ajax_search_adv.php`，`Content-Type: application/json`、`X-Requested-With: XMLHttpRequest`、Referer 高级检索页；真实请求体：

```json
{"searchWords":[{"fieldList":[{"fieldCode":"02","fieldValue":"高等数学"}]}],"filters":[],"limiter":[],"sortField":"relevance","sortType":"desc","pageSize":20,"pageCount":1,"locale":"zh_CN","first":true}
```

  响应 `{"total":2582,"content":[{author,callNo,docTypeName,isbn,marcRecNo,num,pubYear,publisher,title}],"facetsList":[...]}`；分页用 `pageCount`（1 起），`pageSize` 控制每页。
- `GET /uopac/opac/ajax_item.php?marc_no=<marcRecNo>`：HTML 表格 `table#item`，表头为索书号/条码号/年卷期/校区—馆藏地/书刊状态；按行解析，首行表头跳过。
- 失败判据：
  - HTTP 非 200 → 上游失败（不重试无限次；由调用方决定旧缓存回退）；
  - 正文含「出错啦」→ 业务错误（HTTP 可能仍是 200），不能当空库存；
  - 检索 JSON 无法解析/含 `err:true` → 业务或上游错误；
  - 明细 HTML 缺少 `table#item` → 业务错误；`table#item` 存在但无数据行 → 合法空馆藏；
  - 响应体上限 2 MiB、HTTP 超时 12s，超限/超时按上游失败处理。
- `ajax_adv_lend_avl.php` 正文为“出错啦”，不得使用其结果作为库存。
- 已知限制：本次实现会话中，上游在少量只读请求后触发限流（503）；真实正向检索需在正常网络下复验。`internal/library/testdata/` 中 `search_empty.json`、`item_empty.html`、`adv_info.json` 为真实抓取；`search_handoff.json`、`item_handoff.html`、`item_unknown_status.html` 为按交接已核验结构与真实表头构造的样例，不含真实用户数据。

## 5. 缓存、并发与限流

- 缓存为 `Server` 进程内共享有界缓存（现有实现，上限 4096，过期淘汰）；只存公开书目/馆藏，不含用户搜索词或凭据。
- 检索：新鲜 TTL 30 分钟；单本馆藏：5 分钟；上游失败时可回退到过期 24 小时内的旧值并令响应 `stale: true`、`updated_at` 为写入时间；无缓存则明确 502。
- 同 key 并发通过现有 `doOnceValue` 合并（同一时刻只打一次上游，等待者共享结果）。
- 上游并发上限：`LIBRARY_MAX_CONCURRENT`（缺省 3），超出排队/受请求 context 取消。
- 限流：按客户端 IP，检索 40 次/分钟、明细 80 次/分钟，超出 429。
- 旧缓存过期后仍会先尝试上游刷新；刷新失败才回退 stale。
- 前端刷新按钮只请求本服务，不携带任何绕过缓存的 force 参数；服务端不接受用户强制刷新参数。

## 6. 前端竞态与生命周期

- 搜索与详情各自维护请求序号：
  - 新搜索（页码=1）可覆盖在途加载更多/旧搜索；旧响应因序号不匹配被丢弃；
  - 加载更多在请求中不重复触发；
  - 详情切校区用序号守卫，旧校区响应不覆盖新校区；
  - 关闭详情后递增详情序号，晚到响应不得重开/回写；组件 `detached` 也递增序号；
  - 详情 loading/error 状态不覆盖已关闭弹层。
- 打开详情时 `popupstate {open:true}`，关闭时 false；主页面据此隐藏/恢复浮动底栏。
- 不自动联网：进入页面只显示说明与搜索框，用户提交后才请求。

## 7. 测试

后端：

```bash
go test -count=1 ./internal/library/ ./internal/httpapi/
go test -count=1 ./...
go vet ./...
```

- `internal/library`：真实 JSON/HTML 结构解析、真实空响应、业务错误（JSON err / “出错啦”）、HTTP 503、非法关键词/字段/页码、ID 校验与 URL 固定、未知状态不计可借、空馆藏合法、HTTP 200 错误、响应体上限、context 取消、校区过滤统计一致（12 项 `Test*`）。
- `internal/httpapi`：未登录 401、本科/研究生共享、参数校验（缺失/非法/超长）、成功响应与共享缓存（二次不打上游）、stale 回退与无缓存 502、单飞合并、限流 429、上游并发上限、详情校区过滤与 campus_counts、未知状态、非法 marc/校区（11 项 `Test*`）。
- 全量 `go test -count=1 ./...` 全绿（串行 `-p 1`；有测试的 11 个包），`go vet ./...` 通过。本机环境在并行构建时曾因分页文件不足出现 `runtime: cannot allocate memory`，串行重跑通过（环境资源限制，不是测试失败）。

前端：

```bash
node tools/test_library.js        # 11 项行为测试
node tools/test_api_smoke.js      # 接口集合（63 个）
node tools/test_navigation.js
node tools/test_icon_assets.js
node tools/test_main_height_chain.js
node tools/test_font_preference.js
node tools/test_page_animations.js
node tools/test_ui_compiler.js
node tools/test_ui_dsl.js
node tools/test_ui_preview.js
node tools/test_freeclass.js && node tools/test_audit.js && node tools/test_exams.js && node tools/test_ad_slot.js
PYTHONIOENCODING=utf-8 python tools/verify_miniapp.py .
PYTHONIOENCODING=utf-8 python tools/verify_privacy.py .
```

- `tools/test_library.js` 覆盖：无关键词不发请求、搜索参数/结果映射、加载更多去重、切换字段使在途搜索失效、搜索竞态、详情按需请求、校区切换与统计一致、详情切校区竞态、关闭后晚到响应、错误保留列表/重试、详情错误重试（11 项）。
- 所有前端行为测试使用 wx/api 桩件，不访问真实后端。

## 8. 开发者工具验证记录（2026-10-29）

- 项目：`C:\Users\a\Documents\local\miniprogram`（390 宽模拟器，iPhone 12/13 Pro 口径）。
- 运行期把 `/api/library/search`、`/api/library/item` mock 为内存数据，其他网络原语全部阻断；不访问真实后端。
- 已实际执行通过（automator 断言 + 截图）：
  1. 功能页 8 个入口存在，**真实点击**「图书馆库存」卡片进入（`toolPage=library`，组件已挂载）；
  2. 输入关键词后**真实点击**搜索按钮 → `total=2582`、`records=20`、`has_more=true`，上游 mock 调用 1 次；
  3. **真实点击**第一张书目卡 → 详情弹层打开、`popupOpen=true`、5 册/可借 3 册、校区计数 5/2/2；
  4. 切「江阴」→ `scope=jiangyin`、总 2 册/可借 2 册、明细 2 条；
  5. **真实点击**关闭 → `showDetail=false`、`popupOpen=false`，列表 20 条保留；
  6. 返回功能页 → `toolPage=''`、工具层已释放。
- 截图证据：`.tmp/library-verify/01-library-empty.png` 至 `06-feature-after-back.png`（mock 数据，非真机/真实馆藏）。
- 说明：功能页底部仍保留既有第三方广告位（与本次功能无关）；本功能页自身无广告位。
- 诚信说明：上述完整验证执行于最后两处小改动（字段切换使在途搜索失效、analytics 改用既有 `feature_action`）之前；之后两次 DevTools automator 连接超时，未重录。这两处改动由 `tools/test_library.js` 的 11 项行为测试覆盖（含“切换检索字段”用例），页面结构/样式未变。

## 9. 已知限制

- 未做真机、320/430 宽度验收；只在 390 宽开发者工具模拟器验证。
- 本次会话上游限流导致正向真实检索未拿到数据；已用真实表头/空响应 fixture + 交接核验结构做解析测试，上线前需在正常网络复验一次。
- 多实例部署时缓存不共享（未引入 Redis/DB）；需要跨实例一致时应再加 Redis 缓存层。
- 搜索为全馆范围，暂不支持在搜索层按校区筛选（上游 `filters` 的校区精确格式未验证）；校区筛选只作用于已选书目的库存明细，且统计与明细一致。
- 不展示热门榜（非核心，且含非图书条目需另行过滤）。
