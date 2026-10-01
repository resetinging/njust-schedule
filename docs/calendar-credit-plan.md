# 教学周历自动校准 + 学分进度 · 实施计划

> 状态：已与用户确认（2026-10-01），次日开工。
> 决策：① 周次口径**以教务为准**；② 学分进度入口放**功能页**；③ 培养方案**登录后自动抓取一次**，另提供手动刷新。

## 0. 背景与来源

探查用账号 924101960123（2026-2027-1）确认过两个数据源：

- `GET /njlgdx/jxzl/jxzl_query?Ves632DSdyV=NEW_XSD_WDZM`（教学周历查看）
  - 页面用 `<select name="xnxq01id" onchange="Form1.submit()">` 切换学期；
  - 表格列为 星期一…星期日 + 备注，行首为教学周次；
  - 实测 2026-2027-1 第 1 周 = 8/24(周一)–8/30(周日)。
- `GET /njlgdx/pyfa/zxjh_query_find?Ves632DSdyV=NEW_XSD_PYGL`（专业培养方案）
  - 查询条件：学年学期；课程体系（专业方向课/专业选修课/专业基础课/专业教育课/通识教育课/通识选修课/进阶课程/交叉融合课/学科教育课）；课程属性（进阶/必修/限选/任选/公选/其它/计划外）；另有 `kctxs` 输入框；
  - 结果表列（已实测）：序号 | 开课学期 | 课程编号 | 课程名称 | 开课单位 | 学分 | 总学时 | 考核方式 | 课程属性 | 是否考试 | 操作列；
    分页信息为"共 N 页 M 条"（实测 6 页 101 条），查询 POST 到 `/njlgdx/pyfa/pyfa_query`（字段 `kctxs`/`xnxq`/`kcsx`/`pageIndex`）。

## 1. 功能 A：教学周历自动校准

**后端**

- 新增 `wxcloudrun/jwc/calendar.py`（沿用 jwc mixin 结构）：`fetch_calendar(semester)` →
  `{semester, first_monday, weeks:[{week, monday, sunday, note}], fetched_at}`。
- 缓存：`settings` 全局键 `calendar:{semester}`（全校统一，一份即可）；TTL 7 天，`refresh=1` 强制失效。
- 接口：`GET /api/calendar?semester=…`（登录后可用）、`POST /api/refresh-calendar`（走现有 dedupe/节流）。

**前端（miniapp）**

- 课表页加载时：该学期"第一周周一"未设置或与后端不一致 → 自动采用教务值；「我的」页保留手动设置，并标注来源（教务/手动）。
- 抓取失败保留本地旧值，不阻塞页面。
- 上线时按教务口径核对并修正现有偏差（现为 9/7，教务为 8/24，差 2 周）。

**测试**：周历页面保存为 fixture 做离线解析测试 + 接口冒烟 + 校准逻辑用例。

## 2. 功能 B：培养方案 → 学分进度

**后端**

- 新增 `wxcloudrun/jwc/programme.py`：`fetch_programme()`（`xnxq` 留空=整份方案，自动翻页）→
  `{courses:[{semester,code,name,dept,credit,hours,exam_type,attribute,is_exam}], pages, count}`。
- 存储：`settings` 键 `{sid}:programme`（整份方案，不分学期），只存结构化 JSON，不存 HTML。
- 接口：`GET /api/programme`、`POST /api/refresh-programme`。
- 抓取时机：登录成功后自动抓一次（失败静默，不阻塞登录）+ 手动刷新。

**前端（miniapp）**

- 入口放**功能页**；新增「学分进度」页/卡片：总进度 + 分类别进度条 + 未修列表。
- 计算沿用项目现状（后端只存原始数据）：新增 `utils/credit.js`，按课程体系/属性汇总"应修 vs 已修"。
- 已修用现有成绩按**课程代码**匹配，名称兜底；培养方案里的弹性学分（如"至少 N 学分"）按下限展示。
- 研究生账号（学号 1 开头）隐藏该功能。

**测试**：解析 fixture 单测 + 聚合纯函数单测 + 接口冒烟。

## 3. 执行顺序与验收

1. 重新登录一次会话，抓取两份 fixture（周历 + 培养方案结果页）。
2. 功能 A（周历）→ 后端解析/接口 → 前端接入 → 测试 → review。
3. 功能 B（学分进度）→ 后端解析/存储/接口 → 前端页面 → 测试 → review。
4. 各自独立提交；测试通过、用户确认后再推送。

**验收标准**

- 课表页周次与教务周历一致，日期随学期自动切换，无手动设置也能正确定位本周。
- 功能页可在登录后直接看到学分进度，分类别进度与教务培养方案口径一致；刷新按钮可手动更新。

## 4. 实施现状（已实现，待小程序验收）

**后端（server 分支）**

- `wxcloudrun/jwc/calendar.py`（`CalendarMixin` + 纯函数 `parse_calendar`）、
  `wxcloudrun/jwc/programme.py`（`ProgrammeMixin` + `parse_programme_page`）。
- `wxcloudrun/api/study.py`：`GET /api/calendar`、`POST /api/refresh-calendar`、
  `GET /api/programme`、`POST /api/refresh-programme`；周历为全局缓存（7 天），
  培养方案为用户缓存；研究生账号返回 `supported:false`。
- 登录预抓 `schedule_study_prefetch`：先周历（命中全局缓存则不产生教务请求）→ 回写
  `{sid}:first_week_date:{semester}`（课表页据此校准，教务为准）→ 再抓培养方案。
- 测试：`tests/calendar_programme_test.py`（离线 fixture 解析 15 项）、冒烟新增接口用例（含
  缓存命中、刷新、`first_week_date` 回写、研究生降级）。

**前端（miniapp）**

- 功能页新增「学分进度」入口；`components/credit-view/*`（总分/分类别进度、未通过/本学期/后续
  未开课三块折叠列表、计划外与同组选项提示、刷新按钮）。
- `utils/credit.js` 纯计算（node 单测 `tests/credit_calc_test.js`，14 项）。

**review 中发现并修正**

1. 周历抓取后未回写 `first_week_date` → 已补（缓存命中/新抓取/降级三条路径 + 登录预抓）。
2. 等级制成绩（优-、良+、良、中+…）`grade_point=0` 被误判为未通过 → 判定改为
   "否定词 → 绩点 → 百分制 → 等级制"（免修算通过；缓考/缺考/旷考等不算）。
3. 未通过列表混入"本学期在读/后续未开课"课程 → 拆成三块展示。
4. 同名选修池（如"专用英语-XXX"11 门）未选课程被列为未通过 → 同组已选时其余单列
   "同组其他选项"，应修学分按已选课程折算（未选取池内最小单课学分）。

**交叉验证（22 个账号 / 1171 条成绩）**

- 等级制取值 236 条（优-/良/良+/中+/及格…）在新判定下全部算通过；旧逻辑会全部误判为未通过。
- 同专业账号按同一培养方案匹配：典型命中 46/54 门，计划内已修 82.2~96.7 学分，无异常值。
