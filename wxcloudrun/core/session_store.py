# -*- coding: utf-8 -*-
"""SSO 会话持久化与认证节流（core 层）。

背景：教务改版后只能用智慧理工 SSO 登录，而短时间内反复向智慧理工提交账号
密码会触发风控冻结。因此这一层负责两件事：

1. **会话持久化复用**：登录成功后把会话 cookie 存入 `settings` 表
   （`{student_id}:jwc_session`），下次登录先用它探测教务入口，有效则直接建立
   会话，不再提交密码。存的是会话凭据而非密码；超过 `SSO_SESSION_MAX_AGE`
   一律作废，探测失败也会被调用方丢弃。
2. **认证节流**：同一学号认证失败后进入 `SSO_LOGIN_COOLDOWN` 冷却期，期间
   不再向智慧理工发起认证请求。

分层说明：cookie 的读写属于「状态/持久化」，按架构归 core；`jwc` 层只负责
导出/载入 cookie 与探测教务会话，不直接接触 dao。
"""
import json
import threading
import time
from typing import List, Optional

from config import (SSO_LOGIN_COOLDOWN, SSO_SESSION_MAX_AGE,
                    SSO_SESSION_SETTING_KEY)

_fail_ts = {}          # student_id -> 上次认证失败时间
_fail_lock = threading.Lock()


# ============================================================
# 会话 cookie 持久化
# ============================================================
def serialize_cookies(cookies) -> List[dict]:
    """把 requests 的 cookie 容器转成可入库的结构。"""
    out = []
    for c in cookies:
        name = getattr(c, "name", "")
        if not name:
            continue
        out.append({"name": name, "value": getattr(c, "value", ""),
                    "domain": getattr(c, "domain", ""),
                    "path": getattr(c, "path", "") or "/"})
    return out


def save_session(student_id: str, cookies) -> int:
    """持久化会话 cookie，返回写入条数（0 表示未写入）。"""
    if not student_id:
        return 0
    rows = serialize_cookies(cookies)
    if not rows:
        return 0
    from wxcloudrun import dao          # 延迟导入，避免包初始化循环
    dao.set_user_setting(student_id, SSO_SESSION_SETTING_KEY,
                         json.dumps({"ts": int(time.time()), "cookies": rows}))
    return len(rows)


def load_session(student_id: str) -> Optional[List[dict]]:
    """读取未过期的会话 cookie；无记录/超期返回 None。"""
    if not student_id:
        return None
    from wxcloudrun import dao          # 延迟导入，避免包初始化循环
    raw = dao.get_user_setting(student_id, SSO_SESSION_SETTING_KEY, "")
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        return None
    if time.time() - int(data.get("ts") or 0) > SSO_SESSION_MAX_AGE:
        return None
    return data.get("cookies") or None


def clear_session(student_id: str) -> None:
    """删除持久化会话（退出登录时调用, 避免票据副本继续可用）。"""
    if not student_id:
        return
    try:
        from wxcloudrun import dao      # 延迟导入, 避免包初始化循环
        dao.set_user_setting(student_id, SSO_SESSION_SETTING_KEY, "")
    except Exception:                   # noqa: BLE001 清理失败不影响登出流程
        pass


# ============================================================
# 认证节流（防智慧理工风控冻结）
# ============================================================
def cooldown_left(student_id: str) -> int:
    """距离上次认证失败还差多少秒才允许再试（0 表示可以尝试）。"""
    if not student_id or SSO_LOGIN_COOLDOWN <= 0:
        return 0
    with _fail_lock:
        ts = _fail_ts.get(student_id, 0.0)
    left = SSO_LOGIN_COOLDOWN - (time.time() - ts)
    return int(left) + 1 if left > 0 else 0


def mark_failure(student_id: str) -> None:
    """记录一次认证失败，冷却期内不再重复请求智慧理工。"""
    if student_id and SSO_LOGIN_COOLDOWN > 0:
        with _fail_lock:
            _fail_ts[student_id] = time.time()


def clear_failure(student_id: str) -> None:
    """认证成功后清除失败标记（正常登录不会被冷却拦截）。"""
    with _fail_lock:
        _fail_ts.pop(student_id or "", None)
