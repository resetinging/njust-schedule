# 小程序使用统计与广告效果规划

> 状态：仅规划，尚未实现埋点、统计后端或广告 SDK。

## 目标

统计每个用户的小程序使用情况，用于评估广告位价值、广告效果和留存影响。
不把成绩、课表原文、教务凭据等敏感教育数据用于广告分析。

## 核心指标

### 活跃与留存

- 首次打开、最后打开
- 日活、周活、月活
- 每日打开次数、会话数、使用时长
- D1、D7、D30 留存
- 连续活跃天数和回流用户数

### 页面与功能

- 课表、考试、成绩、评教、空教室、蹭课、照片墙、我的页访问次数
- 页面停留时长、进入次数、退出次数
- 功能刷新次数、失败次数
- 登录、提醒授权、收藏等关键动作次数

### 广告效果

- 广告位、广告类型、页面和位置
- 请求、加载成功、加载失败、填充失败
- 曝光、独立曝光用户、点击、关闭
- 激励视频完成次数和完成率
- eCPM、ARPDAU、人均曝光次数
- 广告曝光后的留存和下次使用时长变化

### 粗粒度分组

- 本科/研究生
- 年级
- 校区
- 活跃度：高/中/低
- 功能偏好：课表型/成绩型/考试型
- 是否开启考试或成绩提醒

不使用精确成绩、课程名称、教师名称、教室名称或精确位置做广告画像。

## 事件模型

建议新增：

```text
analytics_events
  id
  analytics_id
  session_id
  event_name
  page
  feature
  placement
  ad_unit_id
  ad_type
  properties_json
  app_version
  platform
  device_class
  created_at
```

```text
analytics_daily
  date
  analytics_id
  open_count
  session_count
  active_seconds
  page_views
  feature_counts_json
  ad_requests
  ad_impressions
  ad_clicks
  ad_revenue
  retention_day
```

建议事件：

```text
app_open
app_background
session_start
session_end
page_view
feature_open
feature_action
refresh_success
refresh_fail
login_success
reminder_grant
ad_request
ad_loaded
ad_failed
ad_impression
ad_click
ad_close
ad_reward_complete
```

## 隐私与合规

- 当前隐私指引明确写明不接入广告、统计 SDK，也不做用户画像；实施前必须更新。
- `analytics_id` 使用学号或 openid 的 HMAC 哈希，不直接保存原始身份。
- 增加“使用统计与广告效果分析”授权开关，支持退出。
- 原始事件建议保留 30 至 90 天，日聚合数据保留 1 年。
- 删除账号时同步删除用户级统计数据。
- 不采集密码、Cookie、token、精确成绩、课程原文、聊天、通讯录和精确位置。

## 推荐实施顺序

1. 活跃、会话、页面和功能统计
2. 广告曝光、点击、eCPM 和收益统计
3. 年级、校区、活跃度等粗粒度分组
4. 留存与广告频率联动分析
5. 在合规授权完成后，再评估个性化广告能力
