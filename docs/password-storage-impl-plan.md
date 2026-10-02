# 密码入库 · 实施计划（可直接开工版）

> **实施现状（2026-10 更新）**：密码默认加密保存；登录入口必须显式提交密码，
> 只有密码匹配且距最近一次真实 SSO 成功不超过 24 小时时才允许复用 Cookie；
> 本地复用不续期，真实 SSO 成功才刷新信任期。退出登录保留密码；
> `DELETE /api/credentials` 仍可主动删除。管理员控制台不提供明文查询；
> 明确认证失败连续 3 次触发 `mark_failure` 并删除，网络/超时等临时故障不计入失败次数。
> 本文以下内容为当时的实施计划，保留存档。

> 前置：`docs/credential-storage-plan.md` 是选型与安全边界；本文是**落地步骤**。
> 现状：`SESSION_KEY` 已在云托管配置；`wxcloudrun/core/cookie_crypto.py` 已有
> AES-256-GCM 加密层（AAD 绑学号、密钥版本、无密钥即禁用），直接复用它加密密码。

## 0. 一句话范围

默认把**教务/智慧理工密码**加密保存；密码匹配且距最近一次真实 SSO 成功不超过 24 小时时，
可优先复用 Cookie。超过信任期、密码不匹配或 Cookie 失效时，后端用保存密码静默重登一次。
用户可通过 `DELETE /api/credentials` 主动删除。

## 1. 数据层（0.5 天）

```sql
CREATE TABLE user_credentials (
  student_id  VARCHAR(32) PRIMARY KEY,
  pwd_enc     TEXT     NOT NULL,   -- cookie_crypto.encrypt(sid, {"pwd": ...})
  updated_at  DATETIME NOT NULL,
  last_used_at DATETIME NULL,
  fail_count  INT      NOT NULL DEFAULT 0
);
```

- `wxcloudrun/model.py` 加模型；`wxcloudrun/__init__.py` 的迁移段加"表不存在则建"（沿用现有
  `_migrate_*` 写法，sqlite/MySQL 都要能跑）；
- `wxcloudrun/dao.py` 加 4 个方法：`save_credential / get_credential / touch_credential /
  bump_credential_fail / delete_credential`（删除仅此入口使用，应用不暴露通用删表能力）。

## 2. 服务层（0.5 天）

新增 `wxcloudrun/core/credential_store.py`（与 `session_store` 同级，职责单一）：

- `save(sid, password)`：`cookie_crypto.enabled()` 为假 → 直接返回 False（**不落明文**）；
- `resolve(sid) -> Optional[str]`：解密取密码；解密失败 → 记 fail 并返回 None；
- `drop(sid)`：删除记录（用户主动删除、连续认证失败达上限时调用；退出登录不删除）；
- `mark_used(sid)` / `mark_fail(sid, limit=3)`：更新 `last_used_at`，失败达上限自动 `drop`。

## 3. 接口层（0.3 天）

放在 `wxcloudrun/api/auth.py`（与登录同域，便于复用会话校验）：

| 方法 | 路径 | 行为 |
| --- | --- | --- |
| `POST` | `/api/credentials` | body `{password}`；**需登录态**；保存加密密文；返回 `{success, saved:true}` |
| `GET` | `/api/credentials` | 返回 `{saved: bool, updated_at}`；**永不回传密码** |
| `DELETE` | `/api/credentials` | 删除；顺便 `clear_session` 保证票据副本也失效 |

统一：`cookie_crypto.enabled()` 为假 → 返回 503 + "服务端未开启该能力"（不静默失败）。

## 4. 使用点（0.5 天）

只接一条路径 —— `wxcloudrun/jwc/login.py` 的登录流程，顺序调整为：

1. 内存会话命中 → 直接用（现状）；
2. 命中 `session_store.load_session`（Cookie 未过期）→ 探测成功即可用（现状）；
3. **新增**：前两步都失败 → `credential_store.resolve(sid)` 拿到密码 → 提交智慧理工登录
   → 成功则刷新 Cookie 与 `mark_used`；失败则 `mark_fail`（达 3 次自动 drop 并要求手动登录）；
4. 全程受现有节流约束（`cooldown_left` / `mark_failure`），避免触发智慧理工风控。

## 5. 前端与兼容

- 登录页不再提供“记住密码”开关，密码默认随登录请求到达后端；
- `/api/login-webvpn` 真实认证成功时加密保存密码；本地 Cookie 恢复成功后只更新使用时间，不延长信任期；
- 退出登录保留服务端与本机密码，只清理 token、登录态、教务 Cookie 和业务缓存；
- 旧前端仍可发送 `remember` 字段，接口不会报错；但旧端的 `remember=false` 不再覆盖当前的默认保存策略；
- 连续认证失败 3 次仍自动删除凭据。

## 6. 测试清单（0.5 天）

**单元（扩 `tests/session_store_test.py` 或新建）**

1. 保存 → `resolve` 能取回原始密码；
2. 密文不含明文密码（断言字符串里搜不到）；
3. 篡改密文 → `resolve` 返回 None 且 fail+1；
4. 换学号（AAD）→ 解不开；
5. 未配置 `SESSION_KEY` → `save` 返回 False，接口 503；
6. 连续失败 3 次 → 记录被自动删除。

**集成（关键）**

7. 保存密码 → 清空内存会话 + 清空 Cookie 记录（模拟重启/过期）→ 调用课表接口 → **自动重登成功**；
8. 同上但密码已失效 → 返回"需重新登录"，且凭据被清理。

## 7. 风险与既定边界

- 解密后明文只活在函数作用域，不写日志、不进异常信息、不缓存（**Python 无法保证内存零化**，需在评审记录里写明）；
- 密钥沿用 `SESSION_KEY`：泄露影响面 = 密码批量泄露；轮换流程见选型文档（密文带 key_version）；
- 自动恢复失败时会回退到手动登录；校园网/教务侧可能因异地登录触发风控，需在隐私指引中说明。

## 8. 顺序与验收

1. 表 + dao（跑 sqlite 迁移）→ 2. `credential_store` + 单测 → 3. 三个接口 → 
4. 接入登录流程（含节流）→ 5. 集成测试 7/8 → 6. 前端开关 + 隐私文案 → 7. 冒烟 42 项回归。

**每步都可独立提交**；1~4 步纯后端、不影响现有客户端行为，可先行上线（接口上线后前端再跟）。
