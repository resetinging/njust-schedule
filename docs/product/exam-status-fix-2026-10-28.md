# 考试安排状态修复（2026-10-28）

> 状态：已实施（本地未提交、未发布）；当前已并入 BUILD `2026.11.27.1`。
> 范围：仅小程序前端 `components/exams-view`、`utils/date.js` 的考试领域函数与 `utils/api/exams.js` 调用方式；不改后端、路由、缓存 TTL，不访问生产/教务。

## 1. 问题（已复现）

1. `timeUntil` 只取时间段第一个 `HH:mm`，开考后立即返回 done：2026-10-28 15:50~17:50 在 16:00 被显示“已结束”。
2. `_processExams` 日期组状态只由排序后第一场决定：同日 09:00~11:00（已结束）+ 19:00~21:00（未开始）在 16:00 会把整组与晚上卡片都标结束。
3. `loadCachedData` 只在缓存非空时 `setData`：非空→空数组/缺失/切空学期时旧 `exams/countdowns/dayGroups/collapsedDates` 残留。
4. 研究生入口可能误走本科 `GET /api/exams`；异步保护只覆盖成功分支；页面从后台回前台不重算状态。

## 2. 逐场状态规则（Asia/Shanghai，UTC+8，无夏令时）

| 条件 | 状态 |
| --- | --- |
| 现在 < 开考 | `upcoming`（倒计时以开考时间为目标） |
| 开考 ≤ 现在 < 结束 | `ongoing`（显示“进行中”） |
| 现在 ≥ 结束 | `done`（显示“已结束”） |
| 缺/非法日期、缺/非法时段 | `unknown`（“时间待定”，不误标 done） |
| 只有开始没有结束（`19:00`、`19:00-`、`19:00~`） | 考前 `upcoming`；开考后 `ongoing`（结束待定）；当天 23:59:59.999 前仍进行中，次日 00:00 起 `unknown` |
| 开始 == 结束 | 保守按“结束待定”处理：考前 upcoming、当天内 ongoing、次日 unknown；**不臆造 24 小时跨午夜** |
| 结束 < 开始 | 跨午夜，结束落次日（如 22:00~01:00 在 00:30 仍进行中） |

分隔符支持 `-`、`~`、`～`、`—`、`–`、`至`（时间 `:` 或 `：`）；无法解析一律保守 unknown，不产生 NaN/负耗时。

## 3. 分组、倒计时与卡片

- 日期组：任一场 ongoing → 组 `ongoing`（优先，不折叠）；全部 done → `done`（保留折叠/展开）；否则取最近 upcoming 文案；其余含 unknown → `unknown`（不折叠）。
- 卡片状态徽章/左边线取自身状态，不继承同日第一场。
- 倒计时最多 3 场：ongoing 优先，其次按开考时间升序的 upcoming；不含 done/unknown；<1 小时显示“X 分钟”，不会出现负小时/0h。
- `.exam-head` 中课程名 `flex:1 1 auto; min-width:0`，状态徽章 `max-width:52%` 且允许换行，窄屏不横向溢出。

## 4. 缓存、异步与页面生命周期

- `loadCachedData` 总是应用当前学期缓存：空数组/缺失 → 清空 exams/countdowns/dayGroups/collapsedDates；切学期清折叠状态并读新学期。
- 服务器刷新返回空数组也清空折叠；成功响应同步 `data.semester`。
- 统一清空入口 `_clearExamView`：未登录/退出清空考试视图与研究生 rows，并复位 `loading/refreshing/errorMsg/subExam`，同时递增请求序号使在途请求失效。
- 所有请求（本科加载/刷新、研究生刷新/静默加载）用 `_beginRequest` 绑定「身份 + 学期 + 序号」，success/catch/finally 均以 `_isCurrentRequest` 校验；同身份新刷新会使旧静默加载失效；迟到响应不写缓存、不 toast、不改新操作忙态；响应学期与请求学期不一致时丢弃。
- `attach` 按账号类型分流：研究生只读 `cached_yjs_exams`，后台请求仅 `getYjsExams`，绝不写本科缓存；本科生请求 `getExams(semester)`。
- `pageLifetimes.show`：回到前台按当前时间本地重算，不发请求；研究生保持分流。
- 无定时器、无网络轮询。

## 5. 测试与限制

- `tools/test_exams.js`：43 项 Node 桩件行为断言（固定时钟 Date.now），覆盖状态边界、时区、同日混合、缺/异常日期时间、只有开始/开始==结束、跨午夜、倒计时排序、缓存清空/切学期/退出、服务器空列表、旧账号/旧学期迟到响应与错误、同身份刷新使旧静默失效、响应学期不符、忙态不被旧请求清除、研究生分流与 rows、页面重显示、折叠交互。
- 同时运行 `test_navigation.js`、`test_api_smoke.js`、`test_page_animations.js`、`test_ad_slot.js`、`python -X utf8 tools/verify_wxml.py`、`verify_miniapp.py`，并通过 `git diff --check`（无真实空白错误）。
- 未访问生产/教务、未写真实凭据；320/430 与真机未验证（不作为已验收）。
