# -*- coding: utf-8 -*-
"""服务器端保存教务密码(可逆加密), 用于"会话与 Cookie 都失效时静默重登"。

与 session_store 同一套路, 复用 settings 表(键 `{student_id}:credential`),
因此**不需要新建表/迁移**; 密文走 cookie_crypto(AES-256-GCM, AAD 绑学号)。

安全底线:
- 未配置 SESSION_KEY(加密不可用) → save() 直接返回 False, **绝不落明文**;
- resolve() 解密失败/格式不对 → 返回 None, 并把失败计数 +1;
- 连续失败达上限(max_fail=3) → 自动删除凭据(防止用错误密码无限重试);
- 任何日志都不打印密码/密文(本模块只记学号是否命中)。
"""
import json
import time
from typing import Optional

from config import SSO_SESSION_SETTING_KEY  # noqa: F401  (同域常量, 便于对齐)

CRED_KEY = "credential"          # settings 键后缀: {student_id}:credential
MAX_FAIL = 3                     # 连续失败上限


def _dao():
    from wxcloudrun import dao          # 延迟导入, 避免包初始化循环
    return dao


def _crypto():
    from wxcloudrun.core import cookie_crypto
    return cookie_crypto


def enabled() -> bool:
    """加密可用(即已配置 SESSION_KEY)才允许保存"""
    try:
        return _crypto().enabled()
    except Exception:
        return False


def save(student_id: str, password: str) -> bool:
    """加密保存密码; 加密不可用或参数为空时返回 False(不落任何明文)"""
    if not student_id or not password or not enabled():
        return False
    payload = {"pwd": password, "ts": int(time.time()), "used_at": 0, "fail": 0}
    try:
        blob = _crypto().encrypt(student_id, payload)
    except Exception:
        return False
    try:
        _dao().set_user_setting(student_id, CRED_KEY, blob)
        return True
    except Exception:
        return False


def _load(student_id: str) -> Optional[dict]:
    if not student_id:
        return None
    try:
        raw = _dao().get_user_setting(student_id, CRED_KEY, "")
    except Exception:
        return None
    if not raw:
        return None
    data = _crypto().decrypt(student_id, raw)
    if isinstance(data, dict) and data.get("pwd"):
        return data
    return None


def resolve(student_id: str) -> Optional[str]:
    """取出明文密码用于自动重登; 解密失败或格式异常一律返回 None(不抛错)"""
    data = _load(student_id)
    if not data:
        return None
    return str(data.get("pwd") or "") or None


def mark_used(student_id: str) -> None:
    """自动重登成功后调用: 刷新 used_at 并清零失败计数"""
    data = _load(student_id)
    if not data:
        return
    data["used_at"] = int(time.time())
    data["fail"] = 0
    _write(student_id, data)


def mark_fail(student_id: str, limit: int = MAX_FAIL) -> None:
    """自动重登失败后调用: 计数 +1, 达上限直接删除凭据"""
    data = _load(student_id)
    if not data:
        return
    data["fail"] = int(data.get("fail") or 0) + 1
    if data["fail"] >= limit:
        drop(student_id)
        return
    _write(student_id, data)


def drop(student_id: str) -> None:
    """删除凭据(用户关闭/退出登录/连续失败时调用)"""
    if not student_id:
        return
    try:
        _dao().set_user_setting(student_id, CRED_KEY, "")
    except Exception:
        pass


def _write(student_id: str, data: dict) -> None:
    try:
        blob = _crypto().encrypt(student_id, data)
        _dao().set_user_setting(student_id, CRED_KEY, blob)
    except Exception:
        pass
