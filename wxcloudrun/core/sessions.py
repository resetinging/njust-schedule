# -*- coding: utf-8 -*-
"""多用户会话池 + 验证码临时会话。

- 会话池: 每个登录用户持有独立 JWCClient(独立教务会话/Cookie),
  登录签发随机 token, 请求经 X-Auth-Token 头识别; 带 TTL 与上限,
  防止长运行后内存堆积。
- 验证码临时会话: 登录尝试的客户端, 10 分钟未使用自动回收。
"""
import os
import secrets
import threading
import time
from typing import Optional, Tuple

from flask import request

from wxcloudrun.jwc_client import JWCClient

_sessions = {}          # token -> [JWCClient, last_active_ts]
_captcha_clients = {}   # captcha_id -> [JWCClient, created_ts]
_sessions_lock = threading.Lock()
TOKEN_HEADER = "X-Auth-Token"

JW_MAX_CONCURRENT = int(os.environ.get("JW_MAX_CONCURRENT", "4"))
SESSION_TTL = int(os.environ.get("SESSION_TTL", str(12 * 3600)))  # 默认 12h
MAX_SESSIONS = int(os.environ.get("MAX_SESSIONS", "200"))
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


def _register_session(client: JWCClient) -> str:
    """登录成功后注册用户会话，返回 token。

    同一学号只保留一个会话: 新登录顶掉旧会话(旧 token 立即失效)。
    小程序每次进入自动重登会新建会话, 不清理会导致在线会话列表
    出现多个相同用户。
    """
    from wxcloudrun import app, dao   # 延迟导入, 避免包初始化循环
    from wxcloudrun.core.web import _rid

    token = secrets.token_urlsafe(32)
    with _sessions_lock:
        # 顶掉同学生已有会话(单设备场景; 多设备交替使用会互相顶掉,
        # 旧端 401 后自动重登即可恢复)
        same_sid = [t for t, (c, _ts) in _sessions.items()
                    if c.student_id and c.student_id == client.student_id]
        for t in same_sid:
            _sessions.pop(t, None)
        _sessions[token] = [client, time.time()]
        _prune_sessions_locked()
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
            session_store.save_session(client.student_id, client.session.cookies)
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
        if item is None:
            return None
        if time.time() - item[1] > SESSION_TTL:
            _sessions.pop(token, None)
            return None
        item[1] = time.time()  # 更新活动时间
        return item[0]


def _logout_session(token: str):
    with _sessions_lock:
        item = _sessions.pop(token or "", None)
    if item is not None:
        try:
            item[0].logout()
        except Exception:
            pass
