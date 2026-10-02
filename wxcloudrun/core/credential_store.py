# -*- coding: utf-8 -*-
"""服务器端保存教务密码(可逆加密), 用于会话失效时自动重登。

与 session_store 同一套路, 复用 settings 表(键 `{student_id}:credential`),
因此**不需要新建表/迁移**; 密文走 cookie_crypto(AES-256-GCM, AAD 绑学号)。

安全底线:
- 未配置 SESSION_KEY(加密不可用) → save() 直接返回 False, **绝不落明文**;
- resolve() 解密失败/格式不对 → 返回 None(不抛错);
- 删除时机: 用户主动删除凭据;
- 任何日志都不打印密码/密文(本模块只记学号是否命中)。
"""
import base64
import hashlib
import hmac
import json
import time
from typing import Optional

from config import CREDENTIAL_TRUST_TTL, SSO_SESSION_SETTING_KEY  # noqa: F401

CRED_KEY = "credential"          # settings 键后缀: {student_id}:credential
DELETE_TOKEN_TTL = 30 * 24 * 3600


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
    now = int(time.time())
    payload = {
        "pwd": password,
        "ts": now,
        "verified_at": now,
        "used_at": 0,
        "fail": 0,
    }
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


def _password_matches(data: Optional[dict], password: str) -> bool:
    if not data or not password:
        return False
    saved = str(data.get("pwd") or "")
    if not saved:
        return False
    return hmac.compare_digest(saved.encode("utf-8"), str(password).encode("utf-8"))


def _verified_recently(data: Optional[dict]) -> bool:
    if not data:
        return False
    verified_at = int(data.get("verified_at")
                      or data.get("ts")
                      or 0)
    if verified_at <= 0:
        return False
    age = time.time() - verified_at
    return 0 <= age < max(60, int(CREDENTIAL_TRUST_TTL))


def verify(student_id: str, password: str) -> bool:
    """常量时间比较提交密码与服务端保存密码。"""
    return _password_matches(_load(student_id), password)


def trusted(student_id: str) -> bool:
    """最近一次真实 SSO 认证是否仍在本地信任期内。"""
    return _verified_recently(_load(student_id))


def can_resume(student_id: str, password: str) -> bool:
    """密码匹配且仍处于 24 小时本地信任期时，允许尝试复用教务 Cookie。"""
    data = _load(student_id)
    return _password_matches(data, password) and _verified_recently(data)


def _save_payload(student_id: str, data: dict) -> bool:
    if not student_id or not data or not enabled():
        return False
    try:
        blob = _crypto().encrypt(student_id, data)
        _dao().set_user_setting(student_id, CRED_KEY, blob)
        return True
    except Exception:
        return False


def mark_used(student_id: str) -> bool:
    """记录一次成功使用, 不延长真实认证信任期。"""
    data = _load(student_id)
    if not data:
        return False
    data["used_at"] = int(time.time())
    data["fail"] = 0
    return _save_payload(student_id, data)


def mark_verified(student_id: str) -> bool:
    """真实通过智慧理工认证后刷新 24 小时信任期。"""
    data = _load(student_id)
    if not data:
        return False
    data["verified_at"] = int(time.time())
    data["fail"] = 0
    return _save_payload(student_id, data)


def mark_failure(student_id: str, limit: int = 3) -> bool:
    """记录一次自动重登失败；连续失败达到上限后删除凭据。"""
    data = _load(student_id)
    if not data:
        return False
    fail = int(data.get("fail") or 0) + 1
    if fail >= max(1, int(limit)):
        drop(student_id)
        return False
    data["fail"] = fail
    return _save_payload(student_id, data)


def drop(student_id: str) -> bool:
    """删除凭据；返回是否成功执行删除。"""
    if not student_id:
        return False
    try:
        _dao().set_user_setting(student_id, CRED_KEY, "")
        return True
    except Exception:
        return False


def _delete_token_key() -> bytes:
    """删除凭据专用签名密钥，和会话/密文加密域分离。"""
    try:
        raw = _crypto().key()
    except Exception:
        return b""
    if not raw:
        return b""
    return hashlib.sha256(b"credential-delete-v1|" + raw).digest()


def issue_delete_token(student_id: str, ttl: int = DELETE_TOKEN_TTL) -> str:
    """签发“仅删除凭据”token；不授予任何数据访问权限。"""
    if not student_id:
        return ""
    key = _delete_token_key()
    if not key:
        return ""
    exp = int(time.time()) + max(60, int(ttl))
    payload = f"{student_id}|{exp}".encode("utf-8")
    body = base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")
    sig = hmac.new(key, payload, hashlib.sha256).hexdigest()
    return body + "." + sig


def verify_delete_token(token: str) -> str:
    """校验删除 token，返回 student_id；无效/过期返回空串。"""
    if not token or "." not in token:
        return ""
    key = _delete_token_key()
    if not key:
        return ""
    try:
        body, sig = token.split(".", 1)
        raw = base64.urlsafe_b64decode(body + "=" * (-len(body) % 4))
        payload_text = raw.decode("utf-8")
        student_id, exp_text = payload_text.rsplit("|", 1)
        if int(exp_text) < time.time():
            return ""
        expect = hmac.new(key, raw, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, expect):
            return ""
        return student_id
    except Exception:
        return ""
