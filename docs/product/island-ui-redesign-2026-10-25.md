# 小程序 Island 悬浮岛式界面方案（2026-10-25）

> 状态：已实施（本地未提交、未发布）；执行与验收记录见 §6。
> 前置方案：[frontend-style-refresh-2026-10-24.md](./frontend-style-refresh-2026-10-24.md)（已实施，本轮在其令牌与布局基础上演进，不推翻其布局/动效/广告/卡片等行为约束）。

## 1. 目标

把整个小程序前端统一为 **Island（悬浮岛式移动界面）** 视觉：雾灰页面背景承托一块块白色内容岛，导航/筛选/操作聚合成胶囊或短控件，用留白与轻微层次表达分组；保留既有信息架构、业务语义、字体偏好、动效责任层与所有回归约束。

本轮只改表现层（WXSS 令牌与页面容器样式为主，必要的 WXML 类名不变），不改接口、数据结构、路由、登录/会话、广告 ID 与统计事件。

## 2. 调研结论与来源

**“Island”不是已确认的统一官方标准，也不是新组件库。** Google/Bing 检索未获得可验证的 Island 专有规范，因此本轮不宣称官方 Island 标准、不引用虚构案例；明确采用「悬浮岛式移动界面」这一描述性设计方向：

- 背景承托独立功能区：页面雾灰，内容面为浮起的白色岛；
- 控件聚合为胶囊/短控件，轻层次与留白显示分组，不做卡片套卡片的厚重拟物；
- 只在岛外表面使用浅软阴影，内部行用留白与分隔线；
- 玻璃材质仅限导航/操作层，正文内容层避免玻璃；
- 保留底部导航的三个文字标签与状态；模态/弹层打开时可遮住导航。

已实际阅读的官方参考（Apple Human Interface Guidelines）：

- Layout — https://developer.apple.com/design/human-interface-guidelines/layout
  ：内容分组、对齐、渐进披露、不同宽度与安全区适配 → 本轮据此保留 2 列自适应、88rpx 热区、长文本不撑破。
- Materials — https://developer.apple.com/design/human-interface-guidelines/materials
  ：玻璃只用于导航/操作层，正文内容避免 → 底栏保留毛玻璃 + 实色回退；内容岛为不透明白。
- Tab bars — https://developer.apple.com/design/human-interface-guidelines/tab-bars
  ：保留导航文字与各 Tab 状态；模态打开时可遮住导航 → 维持三个文字标签；弹层打开时 `popupstate` 隐藏浮动底栏。
- Motion — https://developer.apple.com/design/human-interface-guidelines/motion
  ：短而准确的反馈、进入退出方向一致、支持减少动态效果 → 保留既有单层 Q 弹与 reduced-motion。

继续使用现有 TDesign 小程序组件与本地 PNG 图标，不换库、不引入新的网络字体/远程图片/图标依赖。

## 3. 设计令牌（与代码同名）

颜色（沿用现有品牌与语义，只调整中性面）：

| 令牌 | 值 | 用途 |
| --- | --- | --- |
| `--bg-page` | `#F2F4F7` | 页面雾灰背景 |
| `--bg-card` | `#FFFFFF` | 岛的白色表面 |
| `--text-primary` | `#20262D` | 正文 |
| `--text-secondary` | `#59636F` | 次级 |
| `--primary` | `#3157D5` | 强调（不变） |
| `--success/--warning/--danger` | 现有语义色 | 状态（不变） |

圆角：

| 令牌 | 值 | 用途 |
| --- | --- | --- |
| `--radius-island` / `--radius-card` | `32rpx` | 外层内容岛 |
| `--radius-panel` / `--radius-group` | `24rpx` | 分组/嵌入面 |
| `--radius-sheet` | `36rpx` | 底部弹层 |
| `--radius-pill` | `999rpx` | 短控件/分段/底栏/胶囊按钮 |
| `--co-radius` | `10rpx` | 密集课表课程格（保持小圆角，不挤文字） |

阴影与层次：

- `--shadow-island: 0 6rpx 20rpx rgba(20,28,36,.035)`：只给岛外表面；
- 内部行：白底 + 1rpx 分隔线，不套描边、不套投影；
- 弹层沿用 `--shadow-sheet` 顶部阴影、`--shadow-pop` 居中弹窗；
- 不引入厚高光、凹凸拟物、装饰渐变、漂浮圆、彩虹背景与多重玻璃。

间距：页面 24rpx，岛间 16–24rpx，岛内 24rpx；触控热区保持 ≥88rpx（可见胶囊可小于热区）；320 宽可容纳，长姓名/学期/课程名不撑破布局。

基座同源：`styles/design-system.wxss`、`ui/theme/tokens.js` 与 `createCssVariables()` 必须一致；`ui/` 编译产物从源重新生成，生产页仍为 `pages/main`。

## 4. 动效（沿用上一轮结论，不新增责任层）

- 主 Tab：约 200ms，Q 弹轻微超调（`--motion-base` + `--ease-bounce`）；
- 二级页/底部弹层：约 280ms（`--motion-layer`/`--motion-sheet`），进入退出方向一致；
- 按压：约 120ms；
- 只在一个责任层进场（主 Tab 由 `main.wxss`，二级页由 `tool-layer`，弹层由 t-popup）；
- 刷新按钮单层 `ico-spin`，不抖动、不隐藏已有内容；
- 保留 `prefers-reduced-motion`；禁止 `transition: all`、全屏 blur 与布局/阴影循环动画。

## 5. 逐页范围

1. **主功能页**：只保留标题与通知入口；课业 4 + 校园工具 3 共 7 个入口为两列等宽等高独立岛卡，末项不跨行；统一图标底托、标题基线与按压；广告保留在文档流内。
2. **课表**：学期/日期与周次操作聚合为操作岛；今日课程为内容岛；网格为独立白色岛（保留小格圆角与周末/跨节几何）；列表/网格/收藏/周切换/自定义课/冲突判定语义不变；课表无广告。
3. **我的**：身份信息一个主岛；偏好、提醒服务、帮助为行式分组岛；清缓存居中、危险操作区分；登录表单与密码可见按钮可用；不删考试/成绩订阅入口与信息。
4. **成绩/学分/考试/评教**：筛选或概要为控制岛，结果为结果岛；长标题、分数列、进度/状态对齐；不新增文案、不改 GPA 口径。
5. **空教室**：筛选控制岛、楼宇结果岛、教室网格维持滚动与 4 列折叠契约；江阴楼宇完整显示、研究生学期格式不改。
6. **蹭课**：查询页/下拉/筛选/收藏/结果详情与岛风格一致；保持索引目录、三级联动、星期时间方向限制、精确筛选、虚拟/长列表滚动、同一输入框再次点击收起；不重现闪现/重复入场。
7. **图鉴、公告/更新记录/QQ 群**：统一岛面；分段控件为胶囊；详情/复制/预览动作保持。
8. **全局**：底栏为悬浮胶囊（保留三个文字标签）；弹层/确认/登录/反馈/字体/学期/时间等控件统一；保持 main flex 高度链、主滚动底部 `calc(140rpx + env(safe-area-inset-bottom))`、弹层顶部距离与内部滚动、`popupstate` 隐藏底栏、单 page-container、首次我的 activate 握手与超时兜底；不通过 JS 写死高度。

## 6. 执行与验收记录

- 令牌与共享类：`styles/design-system.wxss` 更新中性面、圆角、阴影与共享表面/列表/按钮/头部/弹层规则；`ui/theme/tokens.js` 同步（含 `motion.base` 200ms 漂移修复），`components/generated/feature-page` 由 `ui/compiler/cli.js` 从源重新生成。
- 页面改造：`pages/main/main.wxss`（功能页、公告条、二级页外壳、窄屏）、`custom-tab-bar/index.wxss`（悬浮胶囊底栏）以及课表/我的/成绩/学分/考试/评教/空教室/蹭课/图鉴/公告/蹭课扩展/选择器/空态/广告槽各组件 WXSS 的岛面与胶囊化。
- 验证：Node 测试与 Python 校验全量跑通（20 个 `test_*.js` + 4 个 `verify_*.py` = 24/24）；微信开发者工具（390×753 模拟器）截图 3 主页 + 7 子页 + 信息中心 + 长下拉（学期选择器）+ 底部弹层；重复开关二级页 10 次 10/10 回到正常态、控制台错误 0；计算样式确认页面背景 rgb(242,244,247)、岛面白底 + 32rpx 圆角（16px）+ 浅软阴影 rgba(20,28,36,.035)、弹层 36rpx（18px）；截图目录 `.tmp/shots-island/`，改前对照见 `.tmp/shots-ads/`、`.tmp/shots-layout/`。320/430 未实测（自动化接口不支持切换机型），不作为已验收。

### 6.1 Codex review 第一轮修复记录（2026-10-25 晚）

1. **高度链回归（必须修复）**：上一版把 `.tab-wrap > schedule-view/settings-view/.feat-page` 组合规则误改成
   `height:100%; overflow-y:auto; padding:24rpx … 140rpx`，导致组件宿主二次滚动 + 可视区缩小，课表/我的正文在约半屏处被截断、
   下方大片空白。已恢复宿主 `flex:1; min-height:0`（不滚动/不加内边距/不写 height），功能页自己滚动并保留尾部留白；
   课表/我的只由内部 `.view-scroll` 滚动，留白在可滚内容尾部。新增 `tools/test_main_height_chain.js` 锁定该契约。
   实测（390×753）：课表宿主 390×753 == scroll-view 390×753，滚到底最后网格底部 637 < 浮动底栏 top 695（尾部留白 58px）；
   我的宿主/滚动 753/753，滚到底 version-tip 底 647 < 695（尾部留白 48px）。
2. **取证错误**：旧截图“常用链接”下叠着未关闭的学期 picker（脚本用假字段/错误组件选择器）。现改为实际 tap `.tb-sem` 打开，
   点 `.t-picker__cancel` 关闭；打开时 `popupOpen=true`、picker 可见、浮动底栏宽度 0（隐藏）、遮罩 1；取消后
   picker 0 个、遮罩 0、`popupOpen=false`、底栏恢复可见。截图见 `.tmp/shots-island2/review-03/04`。
3. **风格遗漏**：TDesign 主按钮通过页面级 `--td-button-border-radius: var(--radius-pill)` 统一胶囊（评教 t-button computed 519px）；
   蹭课 3 个输入框 t-class 因与 TDesign 同优先级未覆盖，改为 `border-radius: var(--radius-pill) !important`（computed 519px）；
   “查询课程”主按钮改胶囊；我的字体分段轨道/选中态均胶囊化（computed 519px）；成绩 `.seg` 同步胶囊化。
4. **课表操作岛**：`.weekbar` 改为完整 32rpx 圆角岛并加 `margin: 12rpx 20rpx 12rpx`，与 `.topbar` 之间形成 12rpx 呼吸间距（实测间距 6px），
   两块不再共用断续边缘。
5. **取证与限制**：本轮截图均为内存 setData mock（示例同学/示例教师/示例课程），不使用真实缓存姓名学号；新增蹭课“课程名长候选”
   可滚动截图（mock 20 条长课程名，候选面板 291px 高、滚到底截图 `review-09/09b`）。
6. **哈希口径**：改用完整 SHA-256 口径（仅排除 `.git`/`node_modules`/`.tmp`），报告源/目标文件数与 missing/diff/extra；
   目标独有 `minitest/test.config.json` 保留并单列，不通过额外排除项声称全量一致。

验证：全量测试 20 个 Node + 4 个 Python = 24/24 通过；开发者工具几何/交互断言 14/14 通过（`review-log.txt`）；
320/430 与真机仍未实测。
- 交付：本地 BUILD `2026.10.25.1`，未提交未推送；同步到开发者工具目录并逐文件 SHA-256 核对。
