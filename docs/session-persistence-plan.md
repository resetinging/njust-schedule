# 会话持久化（教务 Cookie 加密落库）实施计划

> 解决的问题：会话对象在进程内存里，服务重启/重新部署后所有用户掉线，必须重新登录。
> 本方案是 [credential-storage-plan.md](credential-storage-plan.md) 里的**路线 B**：
> 不存密码，只把"教务侧的会话 Cookie"加密落库，重启后用它重建客户端。

## 一、为什么不是"签名 token"

内存里存的不只是 token→用户名，而是一个**活的教务会话对象**（HTTP 客户端 + Cookie）。
把 token 改成 HMAC 无状态签名，只能让"token 有效"，**教务会话依然不存在**，
用户还是要重登。所以必须持久化的是 **Cookie**。

## 二、数据模型

```sql
CREATE TABLE session_cache (
  student_id   VARCHAR(32) PRIMARY KEY,
  cookie_enc   TEXT        NOT NULL,   -- base64(key_version|iv|ciphertext|tag)
  expires_at   DATETIME    NULL,       -- 教务 Cookie 的过期时间(可空)
  probe_ok_at  DATETIME    NULL,       -- 最近一次探活成功时间
  updated_at   DATETIME    NOT NULL
);
```

## 三、依赖与密钥（前置决策）

1. 新增依赖 **`cryptography`**（AES-256-GCM），写进 `requirements.txt`；
2. 密钥来自环境变量 **`SESSION_KEY`**（32 字节 base64），走云托管环境变量/KMS；
   - 未配置时：**不启用持久化**（只告警），而不是降级成明文；
3. 密文结构带 `key_version`，为将来轮换留口子。

## 四、改造点（3 处）

1. **`wxcloudrun/jwc_client.py`**：新增 `export_cookies()` / `import_cookies(list)`，
   把 `requests` 的 cookie jar 序列化成 `[{name, value, domain, path, expires}]`（纯数据，不含密码）；
2. **`wxcloudrun/core/session_store.py`（新增）**：
   - `save(student_id, cookies, expires_at)`：AES-GCM 加密（AAD = student_id）后 upsert；
   - `load(student_id)`：解密并返回 cookies；解密失败/tag 校验失败 → 丢弃并计数；
   - `drop(student_id)`：删除（登出、探活失败时调用）。
3. **`wxcloudrun/core/sessions.py`**：
   - 登录成功后调用 `save(...)`；
   - `_get_session_client()` 拿不到内存会话时，尝试 `rebuild(sid)`：
     读库 → 解密 → `import_cookies` → 构造 JWCClient → **一次轻量探活**（拉课表首页或状态页）；
   - 探活成功：登记进内存会话池（`probe_ok_at` 更新）；失败：`drop()` 并返回 401（前端按现有逻辑提示重新登录）；
   - 登出 / 会话过期 / 自动重登失败时同步 `drop()`。

## 五、安全边界

- AES-256-GCM + 每行随机 IV + AAD 绑学号（换学号解密必失败）；
- 只落 Cookie，**不落密码**；Cookie 泄漏可被教务侧吊销，影响面远小于密码；
- 建议保留时长 ≤ 7 天（`expires_at` 到期即失效），并支持"用户主动清除会话缓存"（可挂在现有"清除缓存数据"上）；
- 日志只记学号掩码（脱敏 Filter 已覆盖）与 rid，不记 Cookie 内容。

## 六、验收标准与测试

**必须通过的用例**：

1. 单测：加解密往返一致；**篡改密文任何一个字节 → 解密必须失败**；AAD 换成别的学号 → 解密必须失败；
2. 集成：登录 → **重启后端进程** → 用同一个 token 请求 `/api/courses` **成功**（证明 Cookie 重建生效）；
3. 负向：Cookie 已过期 → 返回 401 且 `session_cache` 中该行被删除（不能留下"永远失败"的脏数据）；
4. 负向：`SESSION_KEY` 未配置 → 不写库、只告警，登录流程不受影响；
5. 回归：现有 `tests/smoke_test.py` 42 项保持全绿。

## 七、风险与对策

| 风险 | 说明 | 对策 |
| --- | --- | --- |
| 教务侧绑定 IP/UA | Cookie 换环境可能直接失效 | 探活失败即静默降级为"需重新登录"，不报错 |
| 密钥泄露 | 等价于 Cookie 批量泄露 | 密钥轮换（key_version）+ 全量 drop + 强制重登 |
| 多实例并发重建 | 同一学号被两实例同时重建 | 重建入口加"按学号"进程内锁（同实例），跨实例靠 DB 幂等 upsert |
| `cryptography` 依赖 | 增加镜像体积（约 +5MB） | 可接受；不接受则本方案不成立 |

## 八、工期与顺序

1. 依赖 + 密钥配置（0.5h，需你确认）；
2. `jwc_client` 导出/导入 Cookie（1h，单测覆盖）；
3. `session_store` 加解密 + dao 迁移（1h，单测覆盖篡改/AAD）；
4. 会话池接入重建 + 探活 + drop（1.5h，集成测试含"重启后仍在线"）；
5. review + 冒烟测试 + 出文档（0.5h）。
