# -*- coding: utf-8 -*-
"""登录守卫与带重登的数据获取封装(蓝图/views 共用)。"""
from typing import Optional, Tuple

from flask import jsonify, request

from wxcloudrun.core.sessions import _get_session_client
from wxcloudrun.core.web import _rid
from wxcloudrun.jwc_client import JWCClient


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
