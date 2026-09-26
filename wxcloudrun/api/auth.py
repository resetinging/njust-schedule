# -*- coding: utf-8 -*-
"""登录/WebVPN 路由(Phase 1b 从 views.py 拆出)。

教务改版后只保留智慧理工 SSO 一步登录; 教务直连与「第二步教务登录」已下线
(路由保留并返回明确提示, 便于未升级的旧版客户端展示原因)。
"""
import time

from flask import Blueprint, jsonify, request

import config
from wxcloudrun import app, dao
from wxcloudrun.core.auth import _require_login
from wxcloudrun.core.cache import invalidate_user_cache
from wxcloudrun.core.pool import _jwc_request_priority
from wxcloudrun.core.sessions import (
    _register_session, _logout_session, _get_session_client,
    _new_qr_client, _get_qr_client, _pop_qr_client,
    TOKEN_HEADER, _sessions, _sessions_lock)
from wxcloudrun.core.stats import _invalidate_stats
from wxcloudrun.core.timeutil import _beijing_now, _beijing_date
from wxcloudrun.core.web import _rid
from wxcloudrun.jwc_client import JWCClient

auth_bp = Blueprint("auth_api", __name__)
jwc_client = JWCClient()   # 无状态工具用(与 views 全局实例等价)


def _resolve_password(student_id: str, provided: str) -> str:
    """解析登录密码：必须显式提供，不回退任何已保存凭证。"""
    return provided or ""


from wxcloudrun.core.stats import _invalidate_stats  # noqa: E402


def _on_login_success(client: JWCClient, token: str):
    """登录成功后的公共处理：签发 token 并返回会话信息。

    不保存密码；登录默认重置为**当前学期**(课表默认显示本学期),
    用户手动切换其他学期后重新登录会回到本学期。
    """
    sid = client.student_id
    semester = client._current_semester()   # 登录即默认本学期
    dao.set_user_setting(sid, "semester", semester)
    return jsonify({
        "success": True,
        "message": f"登录成功！欢迎 {client.student_name or sid}",
        "student_id": sid,
        "student_name": client.student_name or sid,
        "semester": semester,
        "login_method": client.login_method,
        "token": token,
    })


@auth_bp.route('/api/get-captcha')
def api_get_captcha():
    """教务直连已下线（保留路由以兼容旧版小程序, 便于其展示明确提示）。"""
    return jsonify({"success": False, "message": "教务直连已下线"}), 400


@auth_bp.route('/api/login', methods=['POST'])
def api_login():
    """教务直连已下线（保留路由以兼容旧版小程序, 便于其展示明确提示）。"""
    app.logger.info("[login] rid=%s 教务直连已下线, 拒绝请求", _rid())
    return jsonify({"success": False, "message": "教务直连已下线"}), 400


@auth_bp.route('/api/login-manual', methods=['POST'])
def api_login_manual():
    """教务直连已下线（保留路由以兼容旧版小程序, 便于其展示明确提示）。"""
    return jsonify({"success": False, "message": "教务直连已下线"}), 400


# ============================================================
# API — 智慧理工 SSO 登录（校外/备用方式，多用户）
# ============================================================
@auth_bp.route('/api/get-webvpn-captcha', methods=['POST'])
def api_get_webvpn_captcha():
    """智慧理工一步登录（旧名保留兼容）。

    教务已支持 SSO 直连换取教务会话, 不再需要「第二步: 教务密码 + 验证码」。
    本路由现与 `/api/login-webvpn` 同一实现, 额外回传 already_logged_in 字段,
    以便仍未升级的旧版小程序按原分支直接采用 token。
    """
    data = request.get_json()
    student_id = (data.get("student_id") or "").strip()
    password = _resolve_password(student_id, data.get("password") or "")
    jwc_password = (data.get("jwc_password") or "").strip()
    if not student_id or not password:
        return jsonify({"success": False, "message": "学号和密码不能为空"}), 400

    client = JWCClient()
    with _jwc_request_priority(client):
        success = client.login_webvpn(student_id, password, jwc_password)
    if success:
        token = _register_session(client)
        _on_login_success(client, token)   # 副作用: 调用时初始化学期设置
        return jsonify({
            "success": True,
            "already_logged_in": True,
            "token": token,
            "student_id": client.student_id,
            "student_name": client.student_name or client.student_id,
            "semester": client._current_semester(),
            "login_method": client.login_method,
            "message": f"登录成功！欢迎 {client.student_name or client.student_id}",
        })
    app.logger.info("[login] rid=%s 智慧理工登录失败 sid=%s reason=%s",
                    _rid(), student_id, client.last_error)
    return jsonify({
        "success": False,
        "message": client.last_error or "智慧理工登录失败",
        "debug_log": client.debug_log[-20:],
    }), 400


@auth_bp.route('/api/login-webvpn-manual', methods=['POST'])
def api_login_webvpn_manual():
    """第二步教务登录已废弃：智慧理工 SSO 直连即可建立教务会话, 无需教务密码/验证码。"""
    app.logger.info("[login] rid=%s 收到已废弃的第二步登录请求, 已拒绝", _rid())
    return jsonify({
        "success": False,
        "message": "智慧理工直连已无需第二步教务登录，请使用 /api/login-webvpn",
    }), 400


@auth_bp.route('/api/login-webvpn', methods=['POST'])
def api_login_webvpn():
    """通过智慧理工 SSO 自动登录（含自动 OCR 教务验证码）"""
    data = request.get_json()
    student_id = (data.get("student_id") or "").strip()
    password = _resolve_password(student_id, data.get("password") or "")
    # 教务密码可与智慧理工密码不同(见 api_login_webvpn_manual)
    jwc_password = (data.get("jwc_password") or "").strip()

    if not student_id or not password:
        return jsonify({"success": False, "message": "学号和密码不能为空"}), 400


    client = JWCClient()
    with _jwc_request_priority(client):
        success = client.login_webvpn(student_id, password, jwc_password)

    if success:
        token = _register_session(client)
        return _on_login_success(client, token)
    return jsonify({
        "success": False,
        "message": client.last_error or "智慧理工登录失败",
        "debug_log": client.debug_log[-20:],
    }), 401


# ============================================================
# API — 微信扫码登录（后端代跑扫码流程, 免密码 / 单设备可用）
# ============================================================
@auth_bp.route('/api/sso-qr/start', methods=['POST'])
def api_sso_qr_start():
    """申请一张智慧理工登录二维码（约 3 分钟有效, 前端可随时刷新）。"""
    qid, client = _new_qr_client()
    with _jwc_request_priority(client):
        b64, err = client.start_qr_login()
    if err or not b64:
        _pop_qr_client(qid)
        app.logger.info("[sso-qr] rid=%s 申请二维码失败: %s", _rid(), err)
        return jsonify({"success": False, "message": err or "申请二维码失败"}), 400
    app.logger.info("[sso-qr] rid=%s 已生成二维码 qr_id=%s…", _rid(), qid[:6])
    return jsonify({
        "success": True,
        "qr_id": qid,
        "qr_b64": b64,
        "expires_in": 180,
        "message": "长按二维码 → 识别图中二维码 → 确认登录",
    })


@auth_bp.route('/api/sso-qr/status')
def api_sso_qr_status():
    """轮询扫码状态; 确认后由后端换取票据并注册会话。"""
    qid = (request.args.get("qr_id") or "").strip()
    client = _get_qr_client(qid)
    if client is None:
        return jsonify({"success": False, "status": "expired",
                        "message": "二维码已过期，请刷新"}), 400
    with _jwc_request_priority(client):
        st = client.poll_qr_login()
        if st == "1":
            if not client.finish_qr_login():
                _pop_qr_client(qid)
                app.logger.info("[sso-qr] rid=%s 确认后登录失败: %s",
                                _rid(), client.last_error)
                return jsonify({"success": False, "status": "error",
                                "message": client.last_error or "扫码登录失败"}), 400
            _pop_qr_client(qid)
            token = _register_session(client)
            _on_login_success(client, token)   # 副作用: 初始化学期设置
            app.logger.info("[sso-qr] rid=%s 扫码登录成功 sid=%s",
                            _rid(), client.student_id)
            return jsonify({
                "success": True,
                "status": "ok",
                "token": token,
                "student_id": client.student_id,
                "student_name": client.student_name or client.student_id,
                "semester": client._current_semester(),
                "login_method": client.login_method,
                "message": f"登录成功！欢迎 {client.student_name or client.student_id}",
            })
    if st == "3":
        _pop_qr_client(qid)
        return jsonify({"success": False, "status": "expired",
                        "message": "二维码已失效，请刷新"}), 400
    return jsonify({"success": True,
                    "status": "scanned" if st == "2" else "pending"})


@auth_bp.route('/api/sso-qr/cancel', methods=['POST'])
def api_sso_qr_cancel():
    data = request.get_json(silent=True) or {}
    _pop_qr_client((data.get("qr_id") or "").strip())
    return jsonify({"success": True})


@auth_bp.route('/api/logout', methods=['POST'])
def api_logout():
    """退出登录：销毁当前 token 对应的教务会话"""
    token = request.headers.get(TOKEN_HEADER) or ""
    app.logger.info("[session] rid=%s 退出登录 token=%s…", _rid(), token[:6] if token else "-")
    client = None
    with _sessions_lock:
        client = _sessions.pop(token, None)
    if client is not None:
        try:
            client.logout()
        except Exception:
            pass
    return jsonify({"success": True, "message": "已退出登录"})


# ============================================================
# API — 数据刷新（多用户：使用请求 token 对应的会话）
# ============================================================
