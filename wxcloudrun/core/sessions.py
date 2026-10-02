# -*- coding: utf-8 -*-
"""多用户会话池 + 验证码临时会话。

- 会话池: 每个登录用户持有独立 JWCClient(独立教务会话/Cookie),
  登录签发随机 token, 请求经 X-Auth-Token 头识别; 带 TTL 与上限,
  防止长运行后内存堆积。
- 验证码临时会话: 登录尝试的客户端, 10 分钟未使用自动回收。
"""
import hashlib
import secrets
import threading
import time
from typing import Optional, Tuple

from flask import request

from config import JW_MAX_CONCURRENT, MAX_SESSIONS, SESSION_TTL
from wxcloudrun.jwc_client import JWCClient

_sessions = {}          # token -> [JWCClient, last_active_ts]
_session_ua = {}        # token -> ua_hash(首次绑定的客户端指纹; 只告警不拦截)
_captcha_clients = {}   # captcha_id -> [JWCClient, created_ts]
_sessions_lock = threading.Lock()
TOKEN_HEADER = "X-Auth-Token"
_REMOTE_SESSION_PREFIX = "wx:session:token:"
_REMOTE_SID_PREFIX = "wx:session:sid:"


def _remote_token_key(token: str) -> str:
    return _REMOTE_SESSION_PREFIX + str(token or "")


def _remote_sid_key(sid: str) -> str:
    return _REMOTE_SID_PREFIX + str(sid or "")


def _cookie_rows(cookies) -> list:
    out = []
    for item in cookies or []:
        name = getattr(item, "name", "")
        if not name:
            continue
        out.append({
            "name": name,
            "value": getattr(item, "value", ""),
            "domain": getattr(item, "domain", ""),
            "path": getattr(item, "path", "") or "/",
        })
    return out


def _attach_cookie_rows(client, rows) -> None:
    for item in rows or []:
        try:
            client.session.cookies.set(
                item.get("name", ""), item.get("value", ""),
                domain=item.get("domain"), path=item.get("path") or "/")
        except Exception:  # noqa: BLE001
            continue


def _persist_remote_session(token: str, client) -> bool:
    from wxcloudrun.core import cookie_crypto, state
    if not (state.enabled() and cookie_crypto.enabled() and token and client):
        return False
    try:
        payload = {
            "student_id": getattr(client, "student_id", "") or "",
            "student_name": getattr(client, "student_name", "") or "",
            "account_type": getattr(client, "account_type", "undergraduate"),
            "login_method": getattr(client, "login_method", "") or "",
            "cookies": _cookie_rows(client.session.cookies),
        }
        blob = cookie_crypto.encrypt(token, payload)
        if not state.set_text(_remote_token_key(token), blob, SESSION_TTL):
            return False
        sid = payload["student_id"]
        if sid:
            state.set_text(_remote_sid_key(sid), token, SESSION_TTL)
        return True
    except Exception:  # noqa: BLE001
        return False


def _delete_remote_session(token: str, sid: str = "") -> None:
    from wxcloudrun.core import state
    if state.enabled():
        state.delete(_remote_token_key(token))
        if sid:
            state.delete(_remote_sid_key(sid))


def _delete_remote_sid(sid: str) -> None:
    from wxcloudrun.core import state
    if state.enabled() and sid:
        state.delete(_remote_sid_key(sid))


def _load_remote_session(token: str):
    from wxcloudrun.core import cookie_crypto, state
    if not (state.enabled() and cookie_crypto.enabled() and token):
        return None
    try:
        blob = state.get_text(_remote_token_key(token))
        if not blob:
            return None
        payload = cookie_crypto.decrypt(token, blob)
        if not isinstance(payload, dict):
            return None
        account_type = str(payload.get("account_type") or "undergraduate")
        if account_type == "graduate":
            from wxcloudrun.yjs_client import YJSClient
            client = YJSClient()
        else:
            client = JWCClient()
        _attach_cookie_rows(client, payload.get("cookies") or [])
        client.student_id = str(payload.get("student_id") or "")
        client.student_name = str(payload.get("student_name") or "")
        client.login_method = str(payload.get("login_method") or "")
        if account_type == "undergraduate":
            login_method = client.login_method
            if login_method in ("sso", "sso-cached"):
                from config import JW_SSO_BASE
                client.webvpn.enable_sso_direct(JW_SSO_BASE)
            elif "webvpn" in login_method:
                client.webvpn.activate()
        client.logged_in = True
        return client
    except Exception:  # noqa: BLE001
        return None


def _ua_hash() -> str:
    """当前请求的客户端指纹(UA 摘要, 不含个人信息)"""
    try:
        ua = request.headers.get("User-Agent", "") or ""
        return hashlib.sha256(ua.encode("utf-8", "ignore")).hexdigest()[:12]
    except Exception:
        return "-"


def _bind_ua_locked(token: str) -> None:
    _session_ua[token] = _ua_hash()
    if len(_session_ua) > 5000:          # 兜底: 防止字典无限增长
        _session_ua.clear()


def _check_ua_locked(token: str) -> None:
    """token 指纹变化时告警(不拦截): 正常用户换设备/升级 UA 会命中, 只作风险线索"""
    bound = _session_ua.get(token)
    now = _ua_hash()
    if bound and now != bound and now != "-":
        # app / _rid 在本模块是延迟导入的, 这里同样延迟取, 并且绝不能让告警失败影响请求
        try:
            from wxcloudrun import app
            from wxcloudrun.core.web import _rid
            app.logger.warning(
                "[session] rid=%s token=%s… 客户端指纹变化(绑定=%s 当前=%s), 可能是换设备或凭据外泄",
                _rid(), token[:6], bound, now)
        except Exception:
            pass

CAPTCHA_TTL = 10 * 60  # 验证码临时会话 10 分钟


def _sid_by_token(token: str) -> str:
    """token → 用户学号(会话池反查; 未登录/失效返回 '-')"""
    if not token:
        return "-"
    with _sessions_lock:
        sess = _sessions.get(token)
    return sess[0].student_id if sess else "-"


def _prune_captcha_locked():
    now = time.time()
    expired = [cid for cid, (_c, ts) in _captcha_clients.items()
               if now - ts > CAPTCHA_TTL]
    for cid in expired:
        _captcha_clients.pop(cid, None)


def _prune_sessions_locked():
    now = time.time()
    expired = [t for t, (_c, ts) in _sessions.items() if now - ts > SESSION_TTL]
    for t in expired:
        _sessions.pop(t, None)
    # 上限保护: 淘汰最久未活动的会话
    while len(_sessions) > MAX_SESSIONS:
        oldest = min(_sessions, key=lambda t: _sessions[t][1])
        _sessions.pop(oldest, None)


def _new_captcha_client() -> Tuple[str, JWCClient]:
    """创建一次登录尝试的临时教务会话，返回 (captcha_id, client)"""
    cid = secrets.token_urlsafe(16)
    client = JWCClient()
    with _sessions_lock:
        _prune_captcha_locked()
        _captcha_clients[cid] = [client, time.time()]
    return cid, client


def _pop_captcha_client(captcha_id: str) -> Optional[JWCClient]:
    """取出并删除登录尝试会话（验证码与教务 Cookie 绑定同一实例）"""
    with _sessions_lock:
        item = _captcha_clients.pop(captcha_id or "", None)
    return item[0] if item else None


# ============================================================
# 微信扫码登录临时会话（qr_id → 生成二维码的那个 JWCClient）
# 二维码有效期约 3 分钟, 过期后前端重新申请即可
# ============================================================
_qr_clients = {}        # qr_id -> [JWCClient, created_ts]
QR_TTL = 300            # 5 分钟(留出扫描+确认的时间余量)


def _prune_qr_locked():
    now = time.time()
    for qid in [k for k, (_c, ts) in _qr_clients.items() if now - ts > QR_TTL]:
        _qr_clients.pop(qid, None)


def _new_qr_client() -> Tuple[str, JWCClient]:
    """创建扫码登录临时会话，返回 (qr_id, client)。"""
    qid = secrets.token_urlsafe(16)
    client = JWCClient()
    with _sessions_lock:
        _prune_qr_locked()
        _qr_clients[qid] = [client, time.time()]
    return qid, client


def _get_qr_client(qr_id: str) -> Optional[JWCClient]:
    """按 qr_id 取回扫码会话(轮询期间保持不变, 确认后才清理)。"""
    with _sessions_lock:
        _prune_qr_locked()
        item = _qr_clients.get(qr_id or "")
    return item[0] if item else None


def _pop_qr_client(qr_id: str) -> Optional[JWCClient]:
    """取出并删除扫码会话(登录完成/取消/失效时调用)。"""
    with _sessions_lock:
        item = _qr_clients.pop(qr_id or "", None)
    return item[0] if item else None


def _register_session(client: JWCClient) -> str:
    """登录成功后注册用户会话，返回 token。

    同一学号只保留一个会话: 新登录顶掉旧会话(旧 token 立即失效)。
    小程序每次进入自动重登会新建会话, 不清理会导致在线会话列表
    出现多个相同用户。
    """
    from wxcloudrun import app, dao   # 延迟导入, 避免包初始化循环
    from wxcloudrun.core.web import _rid

    token = secrets.token_urlsafe(32)
    previous_remote = ""
    with _sessions_lock:
        # 顶掉同学生已有会话(单设备场景; 多设备交替使用会互相顶掉,
        # 旧端 401 后自动重登即可恢复)
        same_sid = [t for t, (c, _ts) in _sessions.items()
                    if c.student_id and c.student_id == client.student_id]
        for t in same_sid:
            _sessions.pop(t, None)
            _session_ua.pop(t, None)
        _sessions[token] = [client, time.time()]
        _bind_ua_locked(token)
        _prune_sessions_locked()
    try:
        from wxcloudrun.core import state
        if state.enabled() and client.student_id:
            previous_remote = state.get_text(
                _remote_sid_key(client.student_id)) or ""
    except Exception:  # noqa: BLE001
        previous_remote = ""
    if previous_remote and previous_remote != token:
        _delete_remote_session(previous_remote, client.student_id)
    _persist_remote_session(token, client)
    app.logger.info("[session] rid=%s 登录成功 sid=%s name=%s token=%s… 顶掉旧会话=%d 在线=%d",
                    _rid(), client.student_id, client.student_name, token[:6],
                    len(same_sid), len(_sessions))
    # 持久化姓名: 控制面板用户列表离线也能显示真实姓名(而非 "-")
    if client.student_id and client.student_name:
        try:
            dao.set_user_setting(client.student_id, "name", client.student_name)
        except Exception:
            pass
    # 持久化会话 cookie: 下次登录优先复用, 避免反复向智慧理工提交密码
    try:
        from wxcloudrun.core import session_store
        if client.student_id:
            session_store.save_session(
                client.student_id, client.session.cookies,
                account_type=getattr(client, "account_type", "undergraduate"))
    except Exception:
        pass
    return token


def _get_session_client() -> Optional[JWCClient]:
    """从当前请求头取 token 并返回对应会话客户端（未登录返回 None）。

    惰性回收: 会话超过 TTL 未活动时当场删除并视为未登录(内存保护 +
    过期会话及时失效, 不依赖下次注册时统一清理)。
    """
    token = request.headers.get(TOKEN_HEADER) or ""
    with _sessions_lock:
        item = _sessions.get(token)
        if item is not None and time.time() - item[1] > SESSION_TTL:
            _sessions.pop(token, None)
            _session_ua.pop(token, None)
            item = None
        if item is not None:
            item[1] = time.time()  # 更新活动时间
            _check_ua_locked(token)
            client = item[0]
        else:
            client = None
    if client is not None:
        from wxcloudrun.core import state
        if state.enabled():
            state.expire(_remote_token_key(token), SESSION_TTL)
        return client

    client = _load_remote_session(token)
    if client is None:
        return None
    with _sessions_lock:
        current = _sessions.get(token)
        if current is not None:
            current[1] = time.time()
            return current[0]
        _sessions[token] = [client, time.time()]
        _bind_ua_locked(token)
        _prune_sessions_locked()
    return client


def _list_undergraduate_clients(limit: int = 50) -> list:
    """返回当前有效的活跃本科教务客户端快照。"""
    now = time.time()
    out = []
    with _sessions_lock:
        for client, last_active in _sessions.values():
            if now - last_active > SESSION_TTL:
                continue
            if getattr(client, "account_type", "undergraduate") != "undergraduate":
                continue
            if not getattr(client, "student_id", "") or not getattr(client, "logged_in", False):
                continue
            out.append(client)
    secrets.SystemRandom().shuffle(out)
    target = max(1, int(limit))
    out = out[:target]
    if len(out) >= target:
        return out
    try:
        from wxcloudrun.core import state
        if state.enabled():
            existing_sids = {
                getattr(c, "student_id", "") for c in out
                if getattr(c, "student_id", "")
            }
            for key in state.scan_keys(_REMOTE_SESSION_PREFIX, target * 2):
                token = key[len(_REMOTE_SESSION_PREFIX):]
                client = _load_remote_session(token)
                if not client:
                    continue
                if getattr(client, "account_type", "undergraduate") != "undergraduate":
                    continue
                if not getattr(client, "student_id", "") or not getattr(client, "logged_in", False):
                    continue
                if client.student_id in existing_sids:
                    continue
                client._remote_token = token
                existing_sids.add(client.student_id)
                out.append(client)
                if len(out) >= target:
                    break
    except Exception:  # noqa: BLE001
        pass
    return out


def _logout_session(token: str):
    with _sessions_lock:
        item = _sessions.pop(token or "", None)
        sid = str(getattr(item[0], "student_id", "") or "") if item else ""
    if item is not None:
        try:
            item[0].logout()
        except Exception:
            pass
    _delete_remote_session(token, sid)


def delete_user_session(student_id: str) -> int:
    """关闭某学号的应用会话，但保留持久化教务 Cookie 和业务数据。"""
    sid = str(student_id or "").strip()
    if not sid:
        return 0
    tokens = []
    with _sessions_lock:
        for token, (client, _ts) in list(_sessions.items()):
            if str(getattr(client, "student_id", "") or "") != sid:
                continue
            tokens.append(token)
            _sessions.pop(token, None)
            _session_ua.pop(token, None)
    try:
        from wxcloudrun.core import state
        if state.enabled():
            remote_token = state.get_text(_remote_sid_key(sid)) or ""
            if remote_token and remote_token not in tokens:
                tokens.append(remote_token)
    except Exception:  # noqa: BLE001
        pass
    for token in tokens:
        _delete_remote_session(token, sid)
    # 即使内存里没有活跃会话，也清掉学号到旧 token 的映射；
    # session_store 中的教务 Cookie 不在这里清理。
    _delete_remote_sid(sid)
    return len(tokens)
