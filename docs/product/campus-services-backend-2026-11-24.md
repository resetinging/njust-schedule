# 校园服务后端（2026-11-24）

> 状态：后端与首期小程序服务入口、详情及咨询表单均已实现，本地未提交/未发布。
> 本文不记录真实商家、学生联系方式、Cookie、Token 或管理员口令。

## 1. 范围

校园服务是独立于公告、图书馆和教务数据的校园服务模块，首期支持：

- `operator`：运营商校园套餐
- `materials`：复习资料
- `graduate`：保研咨询
- `exam`：考研培训

首期只提供服务展示与用户主动咨询，不提供小程序内支付、电话卡实名办理、课程播放或资料下载。

## 2. 数据库

迁移版本：`1002_campus_services`。

新增两张表：

- `campus_services`：管理员维护的服务分类、商家、标题、摘要、详情、人群、价格说明、校区、资质说明、合作标记、审核状态、上下架状态、排序和有效期。
- `campus_service_leads`：用户主动提交的咨询线索，包含服务 ID、联系方式密文、脱敏值、去重键、授权版本、状态、管理员备注和过期时间。

迁移只包含新表和索引，已登记为 `1001_general_education_syllabi` 到 `1002_campus_services` 的安全白名单增量迁移；未知基线或结构异常仍要求手动运行目标镜像内的 `/app/migrate`。

## 3. 公开接口

### GET `/api/campus-services`

公开读取已审核、已启用、已进入开始日期且未过期的服务。参数：

- `category`：可选，四类之一。
- `campus`：可选，`all|nanjing|jiangyin`。
- `page`：默认 1。
- `page_size`：默认 20，最大 50。

返回 `services/page/page_size/total/has_more`。公开 DTO 不包含 `verified`、`enabled` 和内部排序字段。

### GET `/api/campus-services/:id`

返回单个公开服务；不存在、未审核、已下架或已过期统一返回 404。

### POST `/api/campus-services/:id/leads`

要求 `X-Auth-Token`。请求体：

```json
{
  "contact_type": "phone",
  "contact": "13800138000",
  "note": "希望了解课程安排",
  "consent": true
}
```

- 手机号必须为 11 位中国大陆手机号；微信号必须为 3-40 位字母、数字、下划线或短横线。
- 必须显式提交 `consent=true`；服务端写入固定授权版本 `campus-service-2026-11-24`。
- 同一用户、服务、联系方式类型和规范化联系方式重复提交时返回成功但不重复入库。
- 联系方式使用 AES-256-GCM 加密，AAD 绑定服务 ID；数据库另存脱敏值与哈希去重键。
- 用户 3 次/小时、客户端 IP 10 次/小时的提交限流。
- 线索默认保留 30 天，每日 03:30 清理过期记录（服务启动时补跑一次）。

## 4. 管理员接口

- `GET /api/admin/campus-services`：读取全部服务，包含审核、上下架、排序和有效期。
- `POST /api/admin/campus-services`：事务保存完整服务列表；未出现在列表中的服务被删除。
- `GET /api/admin/campus-service-leads`：读取咨询线索，联系方式只返回脱敏值。
- `POST /api/admin/campus-service-leads/:id/reveal`：解密查看完整联系方式，只记录线索 ID 和 request ID，不记录联系方式。
- `POST /api/admin/campus-service-leads/:id/status`：更新 `new|contacted|converted|invalid` 和最多 300 字管理员备注。

服务上架前必须完成审核。服务文案拒绝“保过”“保上岸”“内部名额”“代考”“卖答案”等明确不允许的承诺，并拒绝 HTML 控制字符。

## 5. 管理后台

控制面板新增“校园服务”页签：

- 服务新增、编辑、删除、分类、校区、价格、有效期和排序。
- 合作推广、审核完成和上架三个独立开关。
- 咨询线索按状态读取，脱敏查看和按需解密查看联系方式。
- 更新线索跟进状态和内部备注。

## 6. 数据与合规边界

- 服务公开数据不包含商家联系电话；用户必须主动授权后才能提交联系方式。
- 不读取成绩、课表或考试数据来推断服务推荐，不做学业画像定向。
- 不向商家开放小程序管理后台，首期由管理员统一运营和跟进。
- 管理员查看完整联系方式不写入永久审计表，只写运行日志中的线索 ID 与 request ID；后续需要团队多管理员时再增加持久审计。
- 真实商家资质文件不进入本表；首期只保存审核状态和可公开的资质说明。

## 7. 测试

- `internal/campus`：服务字段、日期、HTML、违规承诺、手机号和微信号规范化。
- `internal/store`：公开筛选与分页、重复线索、过期清理。
- `internal/httpapi`：公开 DTO 不泄漏管理字段、未知分类拒绝、后台保存前校验、咨询授权校验。
- `internal/migrate`：`1000→1001→1002` 连续安全迁移、`1001` 基线校验和完整 Schema。
- 全量 `go test ./...`、`go vet ./...`、`node --check wxcloudrun/static/js/admin.js`。

## 8. 当前限制

- 小程序首期入口、服务簿、详情和咨询表单已接入，详见 [campus-services-frontend-2026-11-24.md](campus-services-frontend-2026-11-24.md)。
- 未接入微信支付、订单、退款、电话卡实名、资料下载和课程播放。
- 未实现商家自助账号、持久化管理员审计和多实例后台任务选主。
- 无正式商家数据时管理页为空，不预置示例服务。
