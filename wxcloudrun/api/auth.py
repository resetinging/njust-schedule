# -*- coding: utf-8 -*-
"""登录/验证码/WebVPN 路由(Phase 1b 从 views.py 拆出)。"""
import base64
import time

from flask import Blueprint, jsonify, request

import config
from wxcloudrun import app, dao
from wxcloudrun.core.auth import _require_login
from wxcloudrun.core.cache import invalidate_user_cache
from wxcloudrun.core.media import _sniff_image_mime
from wxcloudrun.core.pool import _jwc_request_priority
from wxcloudrun.core.sessions import (
    _new_captcha_client, _pop_captcha_client, _register_session,
    _logout_session, _get_session_client, TOKEN_HEADER, _sessions, _sessions_lock)
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
    cid, client = _new_captcha_client()
    with _jwc_request_priority(client):
        b64, error = client.get_captcha_base64()
    if error or not b64:
        _pop_captcha_client(cid)
        return jsonify({
            "success": False,
            "message": error or "获取验证码失败",
        }), 500
    return jsonify({
        "success": True,
        "captcha_id": cid,
        "captcha_b64": b64,
        "captcha_mime": _sniff_image_mime(base64.b64decode(b64)),
        "message": "验证码获取成功",
    })


@auth_bp.route('/api/login', methods=['POST'])
def api_login():
    """教务直连自动 OCR 登录（无需验证码输入）"""
    data = request.get_json()
    student_id = (data.get("student_id") or "").strip()
    password = _resolve_password(student_id, data.get("password") or "")
    if not student_id or not password:
        return jsonify({"success": False, "message": "学号和密码不能为空"}), 400
    client = JWCClient()
    with _jwc_request_priority(client):
        success = client.login(student_id, password)
    if success:
        token = _register_session(client)
        return _on_login_success(client, token)
    app.logger.info("[login] rid=%s 自动登录失败 sid=%s reason=%s", _rid(),
                    student_id, client.last_error or "未知")
    return jsonify({
        "success": False,
        "message": client.last_error or "登录失败",
        "need_captcha": "验证码" in (client.last_error or ""),
    }), 401


@auth_bp.route('/api/login-manual', methods=['POST'])
def api_login_manual():
    """教务直连手动验证码登录（验证码与临时会话绑定）"""
    data = request.get_json()
    student_id = (data.get("student_id") or "").strip()
    password = _resolve_password(student_id, data.get("password") or "")
    captcha_text = (data.get("captcha") or "").strip()
    captcha_id = data.get("captcha_id") or ""
    if not student_id or not password:
        return jsonify({"success": False, "message": "学号和密码不能为空"}), 400
    if not captcha_text:
        return jsonify({"success": False, "message": "请先输入验证码"}), 400
    client = _pop_captcha_client(captcha_id)
    if client is None:
        return jsonify({"success": False, "message": "验证码会话已过期，请重新获取"}), 400
    with _jwc_request_priority(client):
        success = client.login_with_manual_captcha(student_id, password, captcha_text)
    if success:
        token = _register_session(client)
        return _on_login_success(client, token)
    return jsonify({
        "success": False,
        "message": client.last_error or "登录失败",
    }), 401


# ============================================================
# API — 智慧理工 SSO 登录（校外/备用方式，多用户）
# ============================================================
@auth_bp.route('/api/get-webvpn-captcha', methods=['POST'])
def api_get_webvpn_captcha():
    """Step 1: 智慧理工 SSO 登录 → 自动识别教务验证码登录（失败回退返回验证码图）"""
    data = request.get_json()
    student_id = (data.get("student_id") or "").strip()
    password = _resolve_password(student_id, data.get("password") or "")
    # 教务密码可与智慧理工密码不同(自动识别要用它登教务); 未填回退智慧理工密码
    jwc_password = (data.get("jwc_password") or "").strip()
    auto_password = jwc_password or password

    if not student_id or not password:
        return jsonify({"success": False, "message": "学号和密码不能为空"}), 400


    cid, client = _new_captcha_client()
    with _jwc_request_priority(client):
        b64, error = client.get_webvpn_captcha_base64(student_id, password)

    if b64 == "__ALREADY_LOGGED_IN__":
        # SSO 后已有教务会话，无需再输验证码 → 直接注册用户会话
        _pop_captcha_client(cid)
        client.logged_in = True
        client.login_method = "webvpn"
        token = _register_session(client)
        _on_login_success(client, token)  # 初始化用户学期设置（不重复返回 JSON）
        return jsonify({
            "success": True,
            "already_logged_in": True,
            "token": token,
            "student_id": client.student_id,
            "student_name": client.student_name or client.student_id,
            "semester": client._current_semester(),
            "message": "已有教务会话，无需重复登录",
        })

    if error:
        _pop_captcha_client(cid)
        # SSO/账号层面的失败(如"SSO 验证码不正确"/"账号或密码错误")属于
        # 用户可修正的问题, 返回 400 让前端展示具体原因而不是"服务器错误 500";
        # 真正未知异常仍由全局 500 处理。
        app.logger.info("[login] rid=%s 智慧理工登录失败(可重试) sid=%s: %s",
                        _rid(), student_id, error)
        return jsonify({
            "success": False,
            "message": error,
            "debug_log": client.debug_log[-20:],
        }), 400

    # Step 1.5: 服务端自动识别教务验证码(与直连模式同款能力) → 直接完成登录。
    # 识别失败则回退原流程: 返回验证码图, 由用户在第二步手动输入。
    try:
        with _jwc_request_priority(client):
            auto_ok = client.auto_complete_webvpn_login(student_id, auto_password)
    except Exception as e:
        auto_ok = False
        app.logger.warning("[login] rid=%s 自动识别教务验证码异常: %s", _rid(), e)

    if auto_ok:
        _pop_captcha_client(cid)
        token = _register_session(client)
        _on_login_success(client, token)  # 初始化用户学期设置（不重复返回 JSON）
        app.logger.info("[login] rid=%s 智慧理工自动识别教务验证码成功 sid=%s",
                        _rid(), student_id)
        return jsonify({
            "success": True,
            "already_logged_in": True,
            "token": token,
            "student_id": client.student_id,
            "student_name": client.student_name or client.student_id,
            "semester": client._current_semester(),
            "message": "验证码已自动识别，登录成功",
        })

    app.logger.info("[login] rid=%s 教务验证码自动识别未成功 sid=%s reason=%s, 回退手动输入",
                    _rid(), student_id, client.last_error)
    # 回退: 重新取一张验证码(自动识别的重试已把原图换掉)
    try:
        img = client._fetch_captcha()
        if img:
            b64 = base64.b64encode(img).decode()
    except Exception as e:
        app.logger.warning("[login] rid=%s 回退取验证码异常: %s", _rid(), e)

    # 验证码获取成功说明 SSO 登录成功（不保存密码），返回 captcha_id 供第二步使用
    return jsonify({
        "success": True,
        "captcha_id": cid,
        "captcha_b64": b64,
        "captcha_mime": _sniff_image_mime(base64.b64decode(b64)),
        "message": "验证码自动识别未成功，请手动输入验证码",
    })


@auth_bp.route('/api/login-webvpn-manual', methods=['POST'])
def api_login_webvpn_manual():
    """Step 2: 使用手动输入的验证码完成教务登录（智慧理工模式）"""
    data = request.get_json()
    student_id = (data.get("student_id") or "").strip()
    # 教务密码: 优先用 jwc_password(界面上与智慧理工密码分开填写),
    # 未填时回退智慧理工密码(两者相同是最常见情况)
    sso_password = _resolve_password(student_id, data.get("password") or "")
    password = (data.get("jwc_password") or "").strip() or sso_password
    captcha_text = (data.get("captcha") or "").strip()
    captcha_id = data.get("captcha_id") or ""

    if not student_id or not password:
        return jsonify({"success": False, "message": "学号和密码不能为空"}), 400
    if not captcha_text:
        return jsonify({"success": False, "message": "请先获取验证码并输入"}), 400
    client = _pop_captcha_client(captcha_id)
    if client is None:
        return jsonify({"success": False, "message": "验证码会话已过期，请重新获取"}), 400

    with _jwc_request_priority(client):
        success = client.complete_webvpn_login(student_id, password, captcha_text)

    if success:
        client.login_method = "webvpn"
        token = _register_session(client)
        return _on_login_success(client, token)
    app.logger.info("[login] rid=%s 智慧理工手动登录失败 sid=%s reason=%s",
                    _rid(), student_id, client.last_error)
    return jsonify({
        "success": False,
        "message": client.last_error or "登录失败，请检查验证码",
        "debug_log": client.debug_log[-20:],
    }), 401


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
