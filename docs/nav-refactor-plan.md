# 导航重构计划（功能 / 课表 / 我的）

> 本轮改动只动前端导航骨架，不碰取数、登录、缓存逻辑。

## 目标

底栏从 5 项（课表·考试·评教·成绩·我的）改为 3 项：**功能 | 课表 | 我的**，
打开小程序默认停在课表。考试、评教、成绩从底栏移到「功能」页，同页展示并带返回。

## 结构设计

主页面 `pages/main/`：

- `current`：底栏选中项（0=功能 1=课表 2=我的）
- `sub`：功能页里的二级视图（''=功能列表 | 'exams' | 'eval' | 'grades'）
- 组件挂载索引维持不变，减少改动面：
  0 schedule-view / 1 exams-view / 2 eval-view / 3 grades-view / 4 settings-view
- 各 `.tab-wrap` 的显示条件：
  - schedule：`current === 1`
  - 功能列表：`current === 0 && !sub`（纯 wxml，不引组件）
  - exams / eval / grades：`current === 0 && sub === '<key>'`
  - settings：`current === 2`
- `_activate`：切到功能页二级视图时，激活对应组件索引；切到课表/我的时激活 0 / 4。
- 二级视图顶部加返回条（返回 = `sub: ''`），返回时不销毁组件（保留滚动/数据）。

`custom-tab-bar/index.js`：

- `ALL_TABS` 改为 3 项：功能(grid) / 课表(calendar) / 我的(user)。
- 取消按 `account_type` 过滤 tab 的逻辑（三个 tab 恒定显示）；
  评教的可见性改由「功能」页的入口列表判断（研究生账号隐藏该入口）。

## 功能页入口

| 入口 | 类型 | 处理 |
| --- | --- | --- |
| 考试安排 | 组件 | `sub='exams'` |
| 教学评价 | 组件 | `sub='eval'`，研究生账号不渲染 |
| 成绩查询 | 组件 | `sub='grades'` |
| 空教室查询 | 页面 | `wx.navigateTo('/pages/freeclass/freeclass')` |
| 校历 & 照片墙 | 页面 | `wx.navigateTo('/pages/gallery/gallery')` |
| 常用链接 | 弹窗 | 从 settings 组件抽成独立模块后被功能页调用 |
| 问题反馈 | 弹窗 | 同上 |
| 我的反馈 | 弹窗 | 同上 |

## 「我的」页保留

账号信息、登录/退出、学期第一周设置、公告栏、清除缓存。

## 待办顺序

1. 抽独立模块：`components/feedback-dialogs/`（常用链接 / 问题反馈 / 我的反馈三块弹窗
   及其 js、wxss 从 settings-view 迁出，settings 只留引用）。
2. 改 `custom-tab-bar`（3 项 + 图标）。
3. 改 `pages/main`（data/`_activate`/`_syncTabBar`/`_onTabChange` + wxml 结构 + 功能页样式）。
4. 同步 `C:\Users\a\Documents\local\miniprogram` 并核对哈希；出三张图（功能页 / 课表 / 我的）。

## 字体（下一轮）

- 后端加 `GET /api/font/pixel` 返回字体（长缓存）。
- 前端 `utils/font.js`：本地缓存 → `wx.loadFontFace`（先用 callContainer 拉字节存本地文件，
  不行再走白名单远程 URL）→ 失败回退内联子集。
- 内联子集从 3200 字扩到 6000 字做兜底。
