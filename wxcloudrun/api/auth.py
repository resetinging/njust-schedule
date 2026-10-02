# -*- coding: utf-8 -*-
"""登录/WebVPN 路由(Phase 1b 从 views.py 拆出)。

教务改版后只保留智慧理工 SSO 一步登录; 教务直连与「第二步教务登录」已下线
(路由保留并返回明确提示, 便于未升级的旧版客户端展示原因)。
"""
import time

from flask import Blueprint, Response, jsonify, request

import config
from wxcloudrun import app, dao
from wxcloudrun.core.auth import _require_login
from wxcloudrun.core.cache import invalidate_user_cache
from wxcloudrun.core.pool import _jwc_request_priority
from wxcloudrun.core.rate_limit import (
    client_ip, login_fail_key, login_fail_sid_key, rate_over)
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


def _can_resume_credential(student_id: str, password: str) -> bool:
    """旧前端传入的 remember 字段会被忽略; 新规则默认保存密码。"""
    try:
        from wxcloudrun.core import credential_store
        return credential_store.can_resume(student_id, password)
    except Exception:
        return False


def _save_login_credential(student_id: str, password: str) -> bool:
    try:
        from wxcloudrun.core import credential_store
        return credential_store.save(student_id, password)
    except Exception:
        return False


def _mark_resumed_credential(student_id: str) -> bool:
    try:
        from wxcloudrun.core import credential_store
        return bool(credential_store.mark_used(student_id))
    except Exception:
        return False


def _delete_token_for(student_id: str) -> str:
    try:
        from wxcloudrun.core import credential_store
        return credential_store.issue_delete_token(student_id)
    except Exception:
        return ""


def _on_login_success(client: JWCClient, token: str, credential_saved=None,
                      prefetch_mode: str = "full"):
    """登录成功后的公共处理：签发 token 并返回会话信息。

    密码的保存(加密落库)由各调用方在成功分支里完成, 本函数不接触密码;
    登录默认重置为**当前学期**(课表默认显示本学期),
    用户手动切换其他学期后重新登录会回到本学期。
    """
    sid = client.student_id
    semester = client._current_semester()   # 登录即默认本学期
    dao.set_user_setting(sid, "semester", semester)
    delete_token = _delete_token_for(sid)
    # 新教务会话建立: 失效旧数据缓存, 后台全量同步一次; 之后仅用户主动刷新。
    try:
        from wxcloudrun.api.study import schedule_data_prefetch
        schedule_data_prefetch(client, sid, semester, mode=prefetch_mode)
    except Exception:
        pass
    return jsonify({
        "success": True,
        "message": f"登录成功！欢迎 {client.student_name or sid}",
        "student_id": sid,
        "student_name": client.student_name or sid,
        "semester": semester,
        "login_method": client.login_method,
        # 研究生/本科分流: 前端可据此切换课表展示(数据结构一致, 一般无需区分)
        "account_type": getattr(client, "account_type", "undergraduate"),
        "token": token,
        "credential_delete_token": delete_token,
        "credential_saved": credential_saved,
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
    data = request.get_json(silent=True) or {}
    student_id = (data.get("student_id") or "").strip()
    raw_password = str(data.get("password") or "").strip()
    password = _resolve_password(student_id, data.get("password") or "")
    jwc_password = (data.get("jwc_password") or "").strip()
    if not student_id or not password:
        return jsonify({"success": False, "message": "学号和密码不能为空"}), 400

    resume_ok = _can_resume_credential(student_id, password)
    client = JWCClient()
    with _jwc_request_priority(client):
        success = client.login_webvpn(student_id, password, jwc_password,
                                      allow_resume=resume_ok)
    if success:
        token = _register_session(client)
        if client.login_method == "sso-cached":
            credential_saved = _mark_resumed_credential(student_id)
        else:
            credential_saved = _save_login_credential(student_id, raw_password)
        _on_login_success(
            client, token, credential_saved,
            prefetch_mode=("if_stale" if client.login_method == "sso-cached" else "full"))
        return jsonify({
            "success": True,
            "already_logged_in": True,
            "token": token,
            "student_id": client.student_id,
            "student_name": client.student_name or client.student_id,
            "semester": client._current_semester(),
            "login_method": client.login_method,
            "credential_delete_token": _delete_token_for(client.student_id),
            "credential_saved": credential_saved,
            "message": f"登录成功！欢迎 {client.student_name or client.student_id}",
        })
    app.logger.info("[login] rid=%s 智慧理工登录失败 sid=%s reason=%s",
                    _rid(), student_id, client.last_error)
    payload = {
        "success": False,
        "message": client.last_error or "智慧理工登录失败",
    }
    if config.DEBUG:
        payload["debug_log"] = client.debug_log[-20:]
    return jsonify(payload), 400


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
    data = request.get_json(silent=True) or {}
    student_id = (data.get("student_id") or "").strip()
    # 登录限流: 防止爆破学号密码, 也避免频繁登录触发智慧理工风控
    # 只统计"失败次数": 连续失败 3 次才冷却 60 秒, 登录成功立刻清零。
    # 这样正常登录/自动重登永远不会被自己的成功请求挤掉额度。
    if (rate_over(login_fail_key(student_id, client_ip()), 3, 60)
            or rate_over(login_fail_sid_key(student_id), 6, 300)):
        return jsonify({"success": False, "message": "登录过于频繁，请稍后再试"}), 429
    password = _resolve_password(student_id, data.get("password") or "")
    # 教务密码可与智慧理工密码不同(见 api_login_webvpn_manual)
    jwc_password = (data.get("jwc_password") or "").strip()
    # 安全: 必须显式提供密码 —— 不接受"空密码+服务端已存凭据"的隐式登录
    # (_resolve_password 本身也不再回退已存凭据, 此处双保险并给出明确的 400)
    if not student_id or not str(data.get("password") or "").strip():
        return jsonify({"success": False, "message": "学号和密码不能为空"}), 400

    # 学号 1 开头 = 研究生账户: 走研究生综合管理信息系统(与教务是两套系统)
    # 与本科一致: 必须真实验证密码 —— 不再复用缓存会话(否则"有会话时错密码也能登录")
    if student_id.startswith("1"):
        from wxcloudrun.yjs_client import YJSClient
        g_client = YJSClient()
        if not g_client.login(student_id, password):
            return jsonify({
                "success": False,
                "message": g_client.last_error or "研究生系统登录失败",
            }), 401
        token = _register_session(g_client)
        # 登录成功: 默认加密保存密码, 旧前端的 remember 字段被忽略。
        credential_saved = _save_login_credential(
            student_id, str((data.get("password") or "")).strip())
        return _on_login_success(g_client, token, credential_saved)

    resume_ok = _can_resume_credential(student_id, password)
    client = JWCClient()
    with _jwc_request_priority(client):
        success = client.login_webvpn(student_id, password, jwc_password,
                                      allow_resume=resume_ok)

    if success:
        token = _register_session(client)
        if client.login_method == "sso-cached":
            credential_saved = _mark_resumed_credential(student_id)
        else:
            credential_saved = _save_login_credential(
                student_id, str((data.get("password") or "")).strip())
        return _on_login_success(
            client, token, credential_saved,
            prefetch_mode=("if_stale" if client.login_method == "sso-cached" else "full"))
    payload = {
        "success": False,
        "message": client.last_error or "智慧理工登录失败",
    }
    if config.DEBUG:
        payload["debug_log"] = client.debug_log[-20:]
    return jsonify(payload), 401


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


@auth_bp.route('/api/sso-qr/image')
def api_sso_qr_image():
    """二维码图片直链。

    小程序真机上 base64 图片不会触发长按识别菜单, 必须用 URL 引用,
    因此这里直接返回 PNG 字节(与 start 返回的 base64 内容一致)。
    """
    qid = (request.args.get("qr_id") or "").strip()
    client = _get_qr_client(qid)
    data = getattr(client, "_qr_image", b"") if client else b""
    if not data:
        return jsonify({"success": False, "message": "二维码不存在或已过期"}), 404
    return Response(data, mimetype="image/png",
                    headers={"Cache-Control": "no-store"})


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
                "credential_delete_token": _delete_token_for(client.student_id),
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
    """退出登录：销毁当前 token 对应的会话, 保留服务端保存的密码"""
    token = request.headers.get(TOKEN_HEADER) or ""
    app.logger.info("[session] rid=%s 退出登录 token=%s…", _rid(), token[:6] if token else "-")
    item = None
    with _sessions_lock:
        item = _sessions.pop(token, None)
    # 注意: _sessions 存的是 [client, ts] 列表, 取 item[0] 才是客户端
    client = item[0] if item is not None else None
    sid = (getattr(client, "student_id", "") or "") if client is not None else ""
    if client is not None:
        try:
            client.logout()
        except Exception:
            pass
    return jsonify({
        "success": True,
        "message": "已退出登录",
        # 兼容旧前端字段; 新语义固定为保留密码。
        "credential_deleted": False,
        "credential_retained": bool(sid),
    })


@auth_bp.route('/api/credentials', methods=['DELETE'])
def api_delete_credentials():
    """删除当前用户明确授权保存的服务端密码。"""
    from wxcloudrun.core import credential_store
    delete_token = request.headers.get("X-Credential-Delete-Token", "")
    sid = credential_store.verify_delete_token(delete_token)
    if not sid:
        client = _get_session_client()
        sid = (getattr(client, "student_id", "") or "") if client is not None else ""
    if not sid:
        return jsonify({"success": False, "message": "登录凭证已失效，请重新登录后再关闭"}), 401
    try:
        ok = bool(credential_store.drop(sid))
    except Exception as exc:
        app.logger.warning("[credential] rid=%s 删除服务端凭据异常 sid=%s: %s",
                           _rid(), sid, type(exc).__name__)
        ok = False
    if not ok:
        return jsonify({"success": False, "message": "服务端密码删除失败，请稍后重试"}), 503
    app.logger.info("[credential] rid=%s 已删除服务端凭据 sid=%s", _rid(), sid)
    return jsonify({"success": True, "message": "已删除服务端保存的密码"})


# ============================================================
# API — 数据刷新（多用户：使用请求 token 对应的会话）
# ============================================================
