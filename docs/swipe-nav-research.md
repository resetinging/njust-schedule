# 小程序滑动切换（Swipe Navigation）实现方案调研

> 调研日期: 2025 立项阶段；适用于微信小程序（原生，非 uni-app/taro）。
> 目标: Tab 页面（课表/考试/评教/成绩/我的）之间左右滑动切换 + 切换动画。

---

## 一、主流方案对比

### 方案 A：单页 swiper 容器承载所有 Tab（"合页"方案）

**做法**：新建一个主页面，内部 `<swiper>` 放 N 个 `swiper-item`，每个 item 放一个 Tab 的内容（
直接用 `<template>`/自定义组件承载原页面），`swiper` 自带的滑动切换 + 回弹动画即切换动画；
tabBar 改为自定义（`app.json` `"tabBar": {"custom": true}`）。

**优点**
- 手势识别由系统完成，**跟手、回弹、惯性最自然**，无需自己判方向/阈值
- 切换动画是 swiper 原生滑动，无"闪现/跳变"问题
- 可天然实现"边滑边看下一个页面"

**缺点 / 代价**
- 所有 Tab 内容常驻内存，**数据量大时明显卡顿**（社区大量反馈"swiper 数据多时过卡"，有专门优化插件）
- swiper 高度固定，内容超高必须内嵌 `scroll-view` 滚动，**页面级下拉刷新失效**，需改 `refresher-threshold` 自定义
- 5 个页面要改造成组件/模板，**页面生命周期（onShow/onHide）要手动模拟**（swiper change 事件），改动大、回归风险高
- 页面间状态隔离、弹窗层级（swiper 内 fixed 定位受限）都要处理

**结论**：体验上限最高，但**重构工作量最大、风险最高**，适合从零开发或内容轻量的场景；
对我们这种"数据重、已有 5 个成熟页面"的项目不划算。

---

### 方案 B：每页手势识别 + `wx.switchTab`（"分页手势"方案，本项目现行）

**做法**：每个 Tab 页根容器绑定 `touchstart/touchmove/touchend`，识别横向滑动；
超过阈值后 `wx.switchTab` 切到相邻 Tab；动画用"跟手 translateX + 新页 CSS 滑入"补足。

**优点**
- 改动最小：保留原生 tabBar、独立页面、页面生命周期，**不破坏现有功能**
- 数据隔离、弹窗、下拉刷新全部照旧
- 切页是真实页面切换，内存只有当前页

**缺点 / 坑（均已有对策）**
| 坑 | 对策 |
|---|---|
| 与纵向滚动冲突 | 横向位移 > 纵向 × 1.2 才激活手势 |
| 与下拉刷新冲突 | 横滑激活后 600ms 内忽略下拉（等效增大下拉阈值） |
| 高频 setData 卡顿 | touchmove 节流 16ms + 位移 ≥2px 才更新 |
| touchend 内同步 `switchTab` 偶发被吞 | `setTimeout(0)` 延迟到下一事件循环执行 |
| 切换瞬间无动画衔接 | 跟手平移 + 新页 0.24s 滑入动画 |
| transform 残留导致页面偏出屏幕 | 进入页面强制复位 + touchcancel 复位 + 动画播完清类 |
| 位移判定不准（节流丢帧） | 用 `changedTouches` 触摸终点计算最终位移 |

**结论**：**适合本项目**。社区大量同类实现（touchmove 左右滑动切换 tab）均采用此模式，
关键是处理好上述边界。

---

### 方案 C：自定义 tabBar + 手势（方案 B 的增强）

**做法**：`tabBar.custom: true` 写自定义 tabBar 组件（渲染 tab 按钮、角标、动效），
页面切换仍是 `wx.switchTab`，手势逻辑与方案 B 相同。

**优点**：tab 栏 UI 可完全自定义（角标、动画、长按），手势无关。
**代价**：自定义 tabBar 组件要在每个页面注册、注意 `getTabBar()` 状态同步，工作量中等。

**结论**：UI 需求不强时不必上；后续若要加"角标/红点"再考虑。

---

## 二、手势识别的关键细节（避坑指南）

来自社区踩坑贴的共性经验：

1. **方向判定**：`dx`/`dy` 同时存在时，只有 `|dx| > |dy| * 1.2~1.5` 才视为横向手势，
   否则交给页面滚动（[touchmove 滑动切换实战](https://developer.aliyun.com/article/1271171)、
   [手势滑动切换页面](https://blog.csdn.net/grpc6streamer/article/details/153813053)）。
2. **防重复触发**：滑动过程中多次满足阈值，要一次性消费手势（切换后 `_swipe=null`），
   避免一次滑动切两页（[避坑指南](https://blog.csdn.net/weixin_30790841/article/details/95628182)）。
3. **touchcancel 必须处理**：系统中断（来电/下拉/滚动接管）时复位，否则 transform 残留。
4. **节流**：touchmove 是高频事件，setData 必须节流（16ms 或位移阈值），否则卡顿
   （[touchmove 重复触发](https://blog.csdn.net/weixin_33734785/article/details/159867966)）。
5. **快速滑动（flick）判定**：位移小但速度快也应触发（`时间 < 400ms && 位移 > 20px`）。
6. **最终位移用 `changedTouches`**：touchend 事件里取触摸终点算位移，比 touchmove 累计值可靠。

---

## 三、动画实现方式

| 方式 | 说明 | 适用 |
|---|---|---|
| **CSS keyframes / transition** | 声明式，视图层执行，性能最好 | ✅ 推荐：跟手 translateX + 滑入动画 |
| `wx.createAnimation` | JS 驱动，可控性强，但经 setData 通信，复杂动画易卡 | 简单缩放/旋转/按钮动效 |
| swiper 原生动画 | 系统手势驱动 | 方案 A 专用 |

注意点：
- 进入动画延迟 30ms 等页面首帧稳定再播，避免与数据渲染竞态"闪现"
- 动画播完必须清除动画类（否则残留类影响后续手势样式）
- 动画时长 0.2~0.3s 手感最佳

---

## 四、数据预加载（切换流畅的另一半）

切换流畅 = 手势/动画流畅 + **目标页数据就绪**。社区共识：

- 原生小程序没有 `preloadPage`（uni-app 才有），替代做法：
  1. **启动后台预取**各 Tab 数据写入本地缓存（只读查询接口，不触发抓取）——本项目已实现
  2. **页面本地优先（stale-while-revalidate）**：有缓存立即渲染，过期后台静默刷新——已实现
  3. 首次进入无缓存时**静默后台加载**，不阻塞显示——已实现
- 效果：滑动切换时目标页直接渲染缓存，零等待、无 loading。

---

## 五、本项目结论与建议

**保持方案 B**（手势 + switchTab + 跟手/滑入动画），理由：
- 5 个成熟页面零重构，符合"不破坏现有功能"原则
- 全部已知坑已按上表处理
- 后续可选增强（按需）：
  - 自定义 tabBar（角标/红点）→ 方案 C
  - 若未来重写 UI 且内容变轻 → 再评估方案 A
  - 若需自定义下拉距离 → 改 scroll-view + `refresher-threshold`（较大改造，先不启）

**主要参考来源**：
- [微信小程序使用 touchmove 实现左右滑动切换页面](https://developer.aliyun.com/article/1271171)
- [微信小程序手势滑动切换页面实战（touchmove 详解）](https://blog.csdn.net/grpc6streamer/article/details/153813053)
- [小程序 Swiper 实现 Tab 切换与下拉刷新上拉加载实战](https://blog.csdn.net/weixin_36012152/article/details/153754875)
- [小程序自定义 tabbar 的两种方式](https://developer.cloud.tencent.cn/article/2166062)
- [微信小程序左右滑动切换 tab 栏避坑指南（防重复触发）](https://blog.csdn.net/weixin_30790841/article/details/95628182)
- [微信小程序左右滑动避坑指南（touchmove 重复触发）](https://blog.csdn.net/weixin_33734785/article/details/159867966)
- [微信小程序开发中的动画效果与过渡效果](https://blog.csdn.net/wx_linying1029/article/details/141125200)
- [微信小程序 tabbar 性能提升秘籍](https://wenku.csdn.net/column/439i3q8yh1)
- [微信小程序过渡动画实现（cool-coding）](https://github.com/echo-cool-coding/cool-coding/blob/main/docs/framework/wechatminiprogram/9-applet-user-experience/4-transition-animation-implementation.mdx)
