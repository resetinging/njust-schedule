# -*- coding: utf-8 -*-
"""登录守卫与带重登的数据获取封装(蓝图/views 共用)。"""
from typing import Optional, Tuple

from flask import jsonify, request

from wxcloudrun.core.sessions import _get_session_client
from wxcloudrun.core.web import _rid
from wxcloudrun.jwc_client import JWCClient


def _try_credential_relogin(client: JWCClient) -> bool:
    """当前会话失效时，使用用户明确授权保存的密码重登一次。"""
    sid = getattr(client, "student_id", "") or ""
    if not sid:
        return False
    try:
        from wxcloudrun.core import credential_store
        password = credential_store.resolve(sid)
    except Exception:
        return False
    if not password:
        return False

    from wxcloudrun import app
    from wxcloudrun.core.pool import _jwc_request_priority

    ok = False
    try:
        with _jwc_request_priority(client):
            # 同一会话可能被多个并发预取请求同时判定为失效。
            # 拿到实例锁后先二次检查，避免并发重复提交 SSO 密码。
            if client.is_session_valid():
                ok = True
            elif getattr(client, "account_type", "") == "graduate":
                ok = bool(client.login(sid, password))
            elif hasattr(client, "login_webvpn"):
                ok = bool(client.login_webvpn(sid, password))
    except Exception as exc:  # noqa: BLE001 自动重登失败按未登录处理
        app.logger.warning("[auth] rid=%s 凭据自动重登异常 sid=%s: %s",
                           _rid(), sid, type(exc).__name__)
        ok = False

    try:
        if ok:
            credential_store.mark_used(sid)
            try:
                from wxcloudrun.core import session_store
                session_store.save_session(sid, client.session.cookies)
            except Exception:
                pass
            app.logger.info("[auth] rid=%s 凭据自动重登成功 sid=%s", _rid(), sid)
            return True
        err = (client.last_error or "").lower()
        transient = any(k in err for k in (
            "无法连接", "连接超时", "超时", "timeout", "network",
            "unreachable", "max retries", "connection",
        ))
        if not transient:
            credential_store.mark_failure(sid)
    except Exception:
        pass
    return False


def _require_login() -> Tuple[Optional[JWCClient], Optional[Tuple]]:
    """登录守卫：返回 (client, None) 或 (None, error_response)。

    未登录/会话过期一律 401；本服务仅支持手动登录，不自动重登录。
    """
    from wxcloudrun import app   # 延迟导入, 避免包初始化循环

    client = _get_session_client()
    if client is None or not client.logged_in:
        app.logger.info("[auth] rid=%s 401 未登录: %s %s", _rid(), request.method, request.path)
        return None, (jsonify({
            "success": False,
            "message": "尚未登录，请先登录",
        }), 401)
    if not client.is_session_valid():
        if _try_credential_relogin(client):
            return client, None
        client.logged_in = False
        app.logger.info("[auth] rid=%s 401 会话过期: sid=%s path=%s", _rid(),
                        client.student_id, request.path)
        return None, (jsonify({
            "success": False,
            "message": "会话已过期，请重新登录",
        }), 401)
    return client, None


def _retry_with_relogin(client: JWCClient, fetch_func, error_msg: str):
    """执行数据获取。三种结果:
      - 有数据 → 正常返回
      - 空结果且无错误信息 → 成功但无数据(如"本学期暂无考试"), 不报错
      - 有错误信息 → 区分会话过期(401 踢下线)与其他故障(500 提示重试)
    返回 (data, error_tuple)，成功时 error_tuple 为 None，
    失败时 data 为 []，error_tuple 为 (flask_response, status_code)。"""
    result = fetch_func()
    if result:
        return result, None
    last_err = client.last_error or ""
    if not last_err:
        # 成功获取但无数据（空表等正常场景）
        return [], None
    if "登录" in last_err or "logon" in last_err.lower():
        client.logged_in = False
        return [], (jsonify({
            "success": False,
            "message": "会话已过期，请重新登录",
        }), 401)
    return [], (jsonify({
        "success": False,
        "message": f"{error_msg}: {last_err}",
    }), 500)
