"""
NJUST 课表 — Flask 路由
=======================
包含：页面路由 + 全量 API（多用户）+ 评教网关
"""
import base64
import os
import re
import secrets
import threading
import time
import uuid
from collections import defaultdict
from contextlib import contextmanager
from typing import Optional, Tuple
from flask import render_template, request, jsonify, Response, g
from bs4 import BeautifulSoup

from wxcloudrun import app
from wxcloudrun.jwc_client import JWCClient, CLASSROOM_SLOTS
from wxcloudrun import dao
import config

# ============================================================
# 基础设施已拆分到 wxcloudrun/core/ (Phase 1 重构)
# 此处显式 re-export, 保持 views.<name> 旧引用(测试/其它模块)可用
# ============================================================
from wxcloudrun.core.cache import (  # noqa: E402
    QUERY_CACHE_TTL, _cache_get, _cache_set, invalidate_user_cache)
from wxcloudrun.core.sessions import (  # noqa: E402
    TOKEN_HEADER, JW_MAX_CONCURRENT, SESSION_TTL, MAX_SESSIONS, CAPTCHA_TTL,
    _sessions, _captcha_clients, _sessions_lock, _prune_captcha_locked,
    _prune_sessions_locked, _new_captcha_client, _pop_captcha_client,
    _register_session, _get_session_client, _logout_session, _sid_by_token)
from wxcloudrun.core.pool import (  # noqa: E402
    _jw_semaphore, _jwc_request, _jwc_request_priority)
from wxcloudrun.core.web import (  # noqa: E402
    SLOW_MS, _rid, register_request_logging)

# 全局教务客户端：仅用于学期计算等无状态工具方法（不参与业务会话）
jwc_client = JWCClient()

# 请求级日志(before_request/after_request)
register_request_logging(app)

# 图鉴路由蓝图(Phase 1b 拆分)
from wxcloudrun.api.gallery import gallery_bp  # noqa: E402
from wxcloudrun.core.media import _sniff_image_mime  # noqa: E402

app.register_blueprint(gallery_bp)


# 教务连通性探测缓存（导航栏/设置页高频调用，30 秒内复用结果）
_network_cache = {"ts": 0.0, "ok": False}
NETWORK_CACHE_TTL = 30


def _check_network() -> Tuple[bool, str]:
    now = time.time()
    if now - _network_cache["ts"] < NETWORK_CACHE_TTL:
        return _network_cache["ok"], ""
    probe = JWCClient()
    try:
        # 短超时探测: 教务无响应时快速判离线, 不让 /api/status 被拖慢
        ok, msg = probe.test_connection(timeout=5)
    except Exception:
        ok, msg = False, ""
    _network_cache["ts"] = now
    _network_cache["ok"] = ok
    return ok, msg


def _current_semester() -> str:
    return jwc_client._current_semester()


# 北京时间工具已下沉到 core/timeutil.py(Phase 1b)
from wxcloudrun.core.timeutil import _beijing_now, _beijing_date  # noqa: E402


EVAL_HEADERS = {
    "Referer": "http://202.119.81.112:9080/njlgdx/xspj/xspj_find.do",
    "Host": "202.119.81.112:9080",
    "Origin": "http://202.119.81.112:9080",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9",
    "Cache-Control": "max-age=0",
}


def _warm_eval_session(client: JWCClient):
    """评教请求前的教务页面预热（应对教务的 Referer 校验）。

    同一用户 60 秒内只预热一次：批量评教逐门提交时，
    每个请求此前都会多打一次预热请求，缓存后教务请求量减半。
    """
    now = time.time()
    if now - getattr(client, "_eval_warm_ts", 0.0) < 60:
        return
    client._eval_warm_ts = now
    client.session.get(
        "http://202.119.81.112:9080/njlgdx/xspj/xspj_find.do",
        headers={"Referer": "http://202.119.81.112:9080/njlgdx/framework/main.jsp"},
        timeout=10)


# ============================================================
# 页面路由
# ============================================================
@app.route('/')
def index():
    # 公开网页端已下线: 根路径进入管理控制面板(管理员登录后使用)
    return render_template('admin.html')


@app.route('/exams')
def exams_page():
    # 公开页面已下线: 统一进入管理控制面板
    return render_template('admin.html')


@app.route('/evaluations')
def evaluations_page():
    return render_template('admin.html')


@app.route('/grades')
def grades_page():
    return render_template('admin.html')


@app.route('/settings')
def settings_page():
    return render_template('admin.html')


@app.route('/gallery')
def gallery_page():
    return render_template('admin.html')


@app.route('/proxy/jw/<path:target_path>', methods=['GET', 'POST'])
def proxy_jw(target_path):
    client = _get_session_client()
    if client is None or not client.logged_in:
        return "请先登录教务系统", 401
    target_url = f"http://202.119.81.112:9080/njlgdx/{target_path}"
    qs = request.query_string.decode()
    if qs:
        target_url += "?" + qs
    try:
        if request.method == 'POST':
            resp = client.session.post(target_url, data=request.form,
                                       headers=EVAL_HEADERS, timeout=15)
        else:
            _warm_eval_session(client)
            resp = client.session.get(target_url, headers=EVAL_HEADERS, timeout=15)
    except Exception as e:
        return f"代理请求失败: {e}", 502
    if "text/html" in (resp.headers.get("content-type") or ""):
        content = resp.text
        if "非法访问" in content or "非法操作" in content:
            return Response(f"""
                <html><body style="padding:40px;text-align:center;font-family:sans-serif;">
                <h2>⚠️ 教务系统拒绝了请求</h2><p>{target_path}</p>
                <p><a href="/evaluations">返回评价列表</a></p>
                <p><a href="/settings">重新登录教务系统</a></p>
                </body></html>
            """, status=403)
        for old, new in [
            ('src="/njlgdx/', 'src="/proxy/jw/'),
            ('href="/njlgdx/', 'href="/proxy/jw/'),
            ("src='/njlgdx/", "src='/proxy/jw/"),
            ("href='/njlgdx/", "href='/proxy/jw/"),
            ('action="/njlgdx/', 'action="/proxy/jw/'),
            ("action='/njlgdx/", "action='/proxy/jw/"),
            ('"/njlgdx/js/', '"/proxy/jw/js/'),
            ("'/njlgdx/js/", "'/proxy/jw/js/"),
        ]:
            content = content.replace(old, new)
        return Response(content, status=resp.status_code,
                        content_type="text/html; charset=utf-8")
    return Response(resp.content, status=resp.status_code,
                    content_type=resp.headers.get("content-type", "text/html"))


# ============================================================
# API — 状态 / 连接测试
# ============================================================
from wxcloudrun.core.stats import (  # noqa: E402
    _stats_cache, _stats_cache_lock, STATS_CACHE_TTL, _get_data_stats)


@app.route('/api/status')
def api_status():
    # 仅支持手动登录：登录态只取决于当前请求 token 对应的会话
    client = _get_session_client()
    logged_in = bool(client and client.logged_in)
    student_id = client.student_id if logged_in else ""
    student_name = client.student_name if logged_in else ""
    semester = (dao.get_user_setting(student_id, "semester")
                if logged_in else "") or dao.get_setting("semester") or _current_semester()

    has_courses = False
    has_exams = False
    if logged_in and semester:
        has_courses, has_exams = _get_data_stats(student_id, semester)

    # 教务连通性(桌面端导航栏/设置页依赖, 30 秒缓存)
    try:
        ok, _msg = _check_network()
        network = {
            "reachable": ok,
            "method": "direct" if ok else "offline",
            "latency_ms": 0,
            "label": "教务在线" if ok else "离线",
            "hint": "" if ok else "请检查教务系统连接",
        }
    except Exception:
        network = {"reachable": False, "method": "offline", "latency_ms": 0,
                   "label": "离线", "hint": "请检查教务系统连接"}

    # 学期第一周周一: 按学期分别存储({sid}:first_week_date:{semester}),
    # 无学期值时回退全局设置(兼容旧数据)
    first_week_date = dao.get_setting("first_week_date", "")
    if logged_in and student_id and semester:
        first_week_date = dao.get_setting(
            f"{student_id}:first_week_date:{semester}", "") or first_week_date

    return jsonify({
        "logged_in": logged_in,
        "student_id": student_id,
        "student_name": student_name,
        "semester": semester,
        "has_courses": has_courses,
        "has_exams": has_exams,
        "login_method": client.login_method if logged_in else "",
        "auto_login_attempted": False,
        "auto_login_error": "",
        "server_time": _beijing_now(),
        "first_week_date": first_week_date,
        "network": network,
    })


@app.route('/api/connect-test')
def api_connect_test():
    ok, msg = _check_network()
    return jsonify({"ok": ok, "message": msg})


# ============================================================
# API — 问题反馈(需登录; 10 秒限流防重复提交; 仅管理端可见)
# ============================================================
# 内容敏感词过滤(留言板已下线, 反馈内容沿用同一词表)
from wxcloudrun.api.feedback import feedback_bp  # noqa: E402

app.register_blueprint(feedback_bp)


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


@app.route('/api/get-captcha')
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


@app.route('/api/login', methods=['POST'])
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


@app.route('/api/login-manual', methods=['POST'])
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
@app.route('/api/get-webvpn-captcha', methods=['POST'])
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
        return jsonify({
            "success": False,
            "message": error,
            "debug_log": client.debug_log[-20:],
        }), 500

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


@app.route('/api/login-webvpn-manual', methods=['POST'])
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


@app.route('/api/login-webvpn', methods=['POST'])
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


@app.route('/api/logout', methods=['POST'])
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
# 登录守卫/重登封装已下沉 core/auth.py(Phase 1b)
from wxcloudrun.core.auth import _require_login, _retry_with_relogin  # noqa: E402


@app.route('/api/refresh-schedule', methods=['POST'])
def api_refresh_schedule():
    client, err = _require_login()
    if err:
        return err
    sid = client.student_id or ""
    semester = dao.get_user_setting(sid, "semester") or _current_semester()
    with _jwc_request(client):
        courses, retry_err = _retry_with_relogin(
            client, lambda: client.get_schedule(semester), "获取课表失败")
    if retry_err:
        return retry_err
    dao.save_courses(courses, semester, sid)
    invalidate_user_cache(sid, "courses")

    dao.set_user_setting(sid, "semester", semester)

    _invalidate_stats(sid, semester)

    app.logger.info("[refresh] rid=%s 课表 sid=%s semester=%s count=%d", _rid(), sid, semester, len(courses))
    return jsonify({
        "success": True,
        "message": f"成功获取 {len(courses)} 门课程",
        "count": len(courses),
        "semester": semester,
    })


@app.route('/api/refresh-exams', methods=['POST'])
def api_refresh_exams():
    client, err = _require_login()
    if err:
        return err
    sid = client.student_id or ""
    semester = dao.get_user_setting(sid, "semester") or _current_semester()
    with _jwc_request(client):
        exams, retry_err = _retry_with_relogin(
            client, lambda: client.get_exams(semester), "获取考试失败")
    if retry_err:
        return retry_err
    dao.save_exams(exams, semester, sid)
    invalidate_user_cache(sid, "exams")

    _invalidate_stats(sid, semester)

    app.logger.info("[refresh] rid=%s 考试 sid=%s semester=%s count=%d", _rid(), sid, semester, len(exams))
    if exams:
        msg = f"成功获取 {len(exams)} 场考试"
    else:
        msg = "成功获取 0 场考试（本学期暂无考试安排）"
    return jsonify({
        "success": True,
        "message": msg,
        "count": len(exams),
    })


@app.route('/api/refresh-all', methods=['POST'])
def api_refresh_all():
    client, err = _require_login()
    if err:
        return err
    sid = client.student_id or ""
    semester = dao.get_user_setting(sid, "semester") or _current_semester()
    results = {"schedule": None, "exams": None}
    with _jwc_request(client):
        courses, sched_err = _retry_with_relogin(
            client, lambda: client.get_schedule(semester), "获取课表失败")
        if not sched_err:
            dao.save_courses(courses, semester, sid)
            results["schedule"] = {"count": len(courses), "ok": True}
        else:
            results["schedule"] = {"count": 0, "ok": False, "error": client.last_error}

        exams, exam_err = _retry_with_relogin(
            client, lambda: client.get_exams(semester), "获取考试失败")
        if not exam_err:
            dao.save_exams(exams, semester, sid)
            results["exams"] = {"count": len(exams), "ok": True}
        else:
            results["exams"] = {"count": 0, "ok": False, "error": client.last_error}
    # 刷新成功部分即时失效查询缓存(失败部分保持旧缓存)
    if results["schedule"] and results["schedule"]["ok"]:
        invalidate_user_cache(sid, "courses")
    if results["exams"] and results["exams"]["ok"]:
        invalidate_user_cache(sid, "exams")

    dao.set_user_setting(sid, "semester", semester)
    _invalidate_stats(sid, semester)
    return jsonify({
        "success": True,
        "semester": semester,
        "schedule": results["schedule"],
        "exams": results["exams"],
        "message": f"课表: {results['schedule']['count']}门, 考试: {results['exams']['count']}场",
    })


# ============================================================
# API — 数据查询（按用户隔离）
# ============================================================
def _dedupe_courses(courses: list) -> list:
    """去掉跨大节课程在 kbtable 每个大节格产生的重复条目。

    例: 第1-13节的课程设计在 kbtable 五个大节格各解析出一条完全相同
    的记录,前端网格会把它们全部堆进同一个单元格导致溢出。
    """
    seen = set()
    result = []
    for c in courses:
        key = (str(c.get("name", "")), c.get("day"), c.get("start"), c.get("end"),
               str(c.get("weeks", "")), str(c.get("teacher", "")),
               str(c.get("classroom", "")))
        if key in seen:
            continue
        seen.add(key)
        result.append(c)
    return result


@app.route('/api/courses')
def api_get_courses():
    client, err = _require_login()
    if err:
        return err
    sid = client.student_id or ""
    semester = (request.args.get("semester") or "").strip() or \
        dao.get_user_setting(sid, "semester") or _current_semester()
    cache_key = f"{sid}:courses:{semester}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return jsonify(cached)
    courses = _dedupe_courses(dao.get_courses(semester, sid))
    resp = {
        "success": True,
        "semester": semester,
        "count": len(courses),
        "courses": courses,
    }
    _cache_set(cache_key, resp)
    return jsonify(resp)


@app.route('/api/exams')
def api_get_exams():
    client, err = _require_login()
    if err:
        return err
    sid = client.student_id or ""
    semester = (request.args.get("semester") or "").strip() or \
        dao.get_user_setting(sid, "semester") or _current_semester()
    cache_key = f"{sid}:exams:{semester}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return jsonify(cached)
    exams = dao.get_exams(semester, sid)
    resp = {
        "success": True,
        "semester": semester,
        "count": len(exams),
        "exams": exams,
    }
    _cache_set(cache_key, resp)
    return jsonify(resp)


# ============================================================
# 空教室路由已拆到 wxcloudrun/api/freeclass.py (Phase 1b)
# 显式 re-export, 保持 views.<name> 旧引用(测试/探针)可用
# ============================================================
from wxcloudrun.api.freeclass import (  # noqa: E402
    freeclass_bp, FREE_CLASSROOM_CAMPUSES, _current_teaching_week,
    _service_free_classrooms, _freeclass_cache_key, _freeclass_resp,
    freeclass_refresh_plan, _next_freeclass_refresh, _freeclass_ttl,
    _prewarm_targets, _prewarm_free_classrooms, _start_freeclass_prewarm)

app.register_blueprint(freeclass_bp)


@app.route('/api/settings', methods=['GET', 'POST'])
def api_settings():
    client = _get_session_client()
    logged_in = bool(client and client.logged_in)
    sid = client.student_id if logged_in else ""
    if request.method == 'GET':
        # first_week_date: 当前学期的值优先, 回退全局(兼容旧数据)
        fwd = dao.get_setting("first_week_date", "")
        cur_sem = (dao.get_user_setting(sid, "semester") if logged_in else "") \
            or dao.get_setting("semester")
        if logged_in and sid and cur_sem:
            fwd = dao.get_setting(f"{sid}:first_week_date:{cur_sem}", "") or fwd
        settings = {
            "student_id": sid,
            "student_name": client.student_name if logged_in else "",
            "semester": cur_sem,
            "auto_refresh": dao.get_setting("auto_refresh", "false"),
            "refresh_interval": dao.get_setting("refresh_interval", "3600"),
            "first_week_date": fwd,
            "semester_list": jwc_client.get_semester_list(),
            "current_semester": _current_semester(),
        }
        return jsonify(settings)
    else:
        data = request.get_json() or {}
        for key, value in data.items():
            if key in ("auto_refresh", "refresh_interval"):
                dao.set_setting(key, str(value))
            elif key == "first_week_date":
                # 按当前学期存储(登录时), 同时写全局兼容回退
                dao.set_setting("first_week_date", str(value))
                if logged_in and sid:
                    cur_sem = dao.get_user_setting(sid, "semester")
                    if cur_sem:
                        dao.set_setting(f"{sid}:first_week_date:{cur_sem}", str(value))
            elif key == "semester" and logged_in and sid:
                dao.set_user_setting(sid, "semester", str(value))
        return jsonify({"success": True, "message": "设置已保存"})


@app.route('/api/semesters')
def api_get_semesters():
    """获取可用学期列表"""
    try:
        semesters = jwc_client.get_semester_list()
        current = _current_semester()
        return jsonify({"success": True, "semesters": semesters, "current": current})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


@app.route('/api/semester', methods=['POST'])
def api_set_semester():
    data = request.get_json()
    semester = (data.get("semester") or "").strip()
    if not semester:
        return jsonify({"success": False, "message": "学期不能为空"}), 400
    client = _get_session_client()
    if client is not None and client.logged_in and client.student_id:
        dao.set_user_setting(client.student_id, "semester", semester)
    else:
        dao.set_setting("semester", semester)
    return jsonify({"success": True, "message": f"已切换到学期: {semester}"})


@app.route('/api/evaluations')
def api_get_evaluations():
    client, err = _require_login()
    if err:
        return err
    sid = client.student_id or ""
    cache_key = f"{sid}:evaluations"
    cached = _cache_get(cache_key)
    if cached is not None:
        return jsonify(cached)
    # 评教是待办事项: 返回该账号全部批次(不过滤学期), 批次自带 semester 字段
    evals = dao.get_evaluations("", sid)
    resp = {
        "success": True,
        "count": len(evals),
        "evaluations": evals,
    }
    _cache_set(cache_key, resp)
    return jsonify(resp)


@app.route('/api/refresh-evaluations', methods=['POST'])
def api_refresh_evaluations():
    client, err = _require_login()
    if err:
        return err
    sid = client.student_id or ""
    with _jwc_request(client):
        evals, retry_err = _retry_with_relogin(
            client, lambda: client.get_evaluations(""), "获取评价数据失败")
    if retry_err:
        return retry_err
    dao.save_evaluations(evals, "", sid)
    invalidate_user_cache(sid, "evaluations")
    undone = sum(1 for e in evals if not e.get("is_done"))
    return jsonify({
        "success": True,
        "message": f"成功获取 {len(evals)} 条评价" + (f"，{undone} 条待完成" if undone > 0 else ""),
        "count": len(evals),
        "undone": undone,
    })


# ============================================================
# 评教 — 页面解析（网关层，评分由前端完成）
# ============================================================
def _parse_eval_courses_page(html: str) -> dict:
    soup = BeautifulSoup(html, "lxml")
    title_el = soup.select_one(".Nsb_r_title")
    batch_title = title_el.get_text(strip=True) if title_el else "评教课程"
    form = soup.find("form", id="Form1")
    hidden_fields = {}
    if form:
        for inp in form.find_all("input", type="hidden"):
            name = inp.get("name", "")
            value = inp.get("value", "")
            if name:
                hidden_fields[name] = value
    courses = []
    data_table = soup.find("table", id="dataList")
    if data_table:
        for row in data_table.find_all("tr")[1:]:
            cells = row.find_all("td")
            if len(cells) < 8:
                continue
            eval_url = ""
            eval_link = cells[7].find("a")
            if eval_link:
                href = eval_link.get("href", "")
                m = re.search(r"openWindow\('([^']+)'", href)
                if m:
                    eval_url = m.group(1)
            courses.append({
                "seq": cells[0].get_text(strip=True),
                "code": cells[1].get_text(strip=True),
                "name": cells[2].get_text(strip=True),
                "teacher": cells[3].get_text(strip=True),
                "score": cells[4].get_text(strip=True),
                "evaluated": cells[5].get_text(strip=True) == "是",
                "submitted": cells[6].get_text(strip=True) == "是",
                "eval_url": eval_url,
            })
    return {"batch_title": batch_title, "courses": courses, "hidden_fields": hidden_fields}


def _parse_eval_form_page(html: str) -> dict:
    soup = BeautifulSoup(html, "lxml")
    th = soup.find("th", class_="Nsb_r_list_thb")
    course_info = th.get_text() if th else ""
    course_name = ""
    m = re.search(r'课程名称[：:]\s*(.+?)(?:\s{2,}|\xa0|$)', course_info)
    if m:
        course_name = m.group(1).strip()
    form = soup.find("form", id="Form1")
    hidden_fields = {}
    if form:
        for inp in form.find_all("input", type="hidden"):
            name = inp.get("name", "")
            value = inp.get("value", "")
            if name:
                hidden_fields[name] = value
    indicators = []
    for row in soup.select("#table1 tr"):
        tds = row.find_all("td")
        if len(tds) < 2:
            continue
        label = tds[0].get_text(strip=True)
        if not label or "评价指标" in label:
            continue
        seq_input = tds[0].find("input", attrs={"name": "pj06xh"})
        seq = seq_input.get("value", "") if seq_input else ""
        fz_map = {}
        for inp in tds[1].find_all("input", type="hidden"):
            fz_name = inp.get("name", "")
            fz_value = inp.get("value", "")
            if fz_name.startswith("pj0601fz_"):
                hidden_fields[fz_name] = fz_value
                parts = fz_name.rsplit("_", 1)
                if len(parts) == 2:
                    fz_map[parts[1]] = fz_value
        options = []
        for radio in tds[1].find_all("input", type="radio"):
            opt_name = radio.get("name", "")
            opt_value = radio.get("value", "")
            opt_score = fz_map.get(opt_value, "")
            opt_checked = radio.has_attr("checked")
            opt_label = ""
            sib = radio.next_sibling
            if sib:
                try:
                    txt = str(sib).strip()
                    if txt:
                        opt_label = txt
                except Exception:
                    pass
            if not opt_label:
                opt_label = radio.parent.get_text().strip() if radio.parent else ""
            options.append({
                "name": opt_name,
                "value": opt_value,
                "label": opt_label.strip(),
                "score": opt_score,
                "checked": opt_checked,
            })
        indicators.append({"seq": seq, "label": label, "options": options})
    form_action = form.get("action", "") if form else ""
    return {
        "course_name": course_name,
        "hidden_fields": hidden_fields,
        "indicators": indicators,
        "action": form_action,
    }


def _build_ordered_eval_post_data(form_data: dict, batch_hidden_fields=None,
                                  auto_fill_selections=None, submit_type: str = "1") -> list:
    merged = dict(form_data)
    if batch_hidden_fields:
        for k, v in batch_hidden_fields.items():
            if k not in merged:
                merged[k] = v
    if auto_fill_selections:
        for seq, val in auto_fill_selections.items():
            if seq == "_total":
                continue
            name, value = val
            merged[name] = value
    indicator_groups = {}
    form_level_pairs = []
    for k, v in merged.items():
        if k.startswith("pj0601fz_"):
            parts = k.split("_", 2)
            if len(parts) >= 2:
                seq = parts[1]
                indicator_groups.setdefault(seq, []).append((k, v))
                continue
        elif k.startswith("pj0601id_"):
            seq = k.replace("pj0601id_", "")
            indicator_groups.setdefault(seq, []).append((k, v))
            continue
        elif k == "pj06xh":
            continue
        else:
            form_level_pairs.append((k, v))
    sorted_seqs = sorted(indicator_groups.keys(), key=int)
    post_data = []
    head_keys = {"issubmit"}
    for k, v in form_level_pairs:
        if k not in head_keys:
            post_data.append((k, v))
    for seq in sorted_seqs:
        post_data.append(("pj06xh", seq))
        for k, v in indicator_groups[seq]:
            post_data.append((k, v))
    for k, v in form_level_pairs:
        if k in head_keys:
            post_data.append((k, v))
    return post_data


# ============================================================
# API — 评教操作（多用户：使用请求 token 对应的会话）
# ============================================================
def _fetch_with_client(client: JWCClient, url: str):
    """用用户会话 GET 教务页面，检查非法访问"""
    target = f"http://202.119.81.112:9080{url}" if url.startswith("/") else url
    _warm_eval_session(client)
    resp = client.session.get(target, headers=EVAL_HEADERS, timeout=15)
    if "非法访问" in resp.text or "非法操作" in resp.text:
        return None, jsonify({"success": False, "message": "教务系统拒绝了请求"}), 403
    return resp, None, None


@app.route('/api/eval-courses')
def api_eval_courses():
    url = request.args.get("url", "")
    if not url:
        return jsonify({"success": False, "message": "缺少 URL"}), 400
    client, err = _require_login()
    if err:
        return err
    try:
        resp, err_resp, status = _fetch_with_client(client, url)
        if err_resp is not None:
            return err_resp, status
    except Exception as e:
        return jsonify({"success": False, "message": f"请求失败: {e}"}), 500
    parsed = _parse_eval_courses_page(resp.text)
    if not parsed or not parsed.get("courses"):
        return jsonify({"success": False, "message": "未找到课程列表"}), 500
    return jsonify({
        "success": True,
        "batch_title": parsed["batch_title"],
        "courses": parsed["courses"],
        "hidden_fields": parsed["hidden_fields"],
    })


@app.route('/api/eval-form')
def api_eval_form():
    url = request.args.get("url", "")
    if not url:
        return jsonify({"success": False, "message": "缺少评教 URL"}), 400
    client, err = _require_login()
    if err:
        return err
    try:
        resp, err_resp, status = _fetch_with_client(client, url)
        if err_resp is not None:
            return err_resp, status
    except Exception as e:
        return jsonify({"success": False, "message": f"请求失败: {e}"}), 500
    parsed = _parse_eval_form_page(resp.text)
    if not parsed or (not parsed.get("course_name") and not parsed.get("indicators")):
        return jsonify({"success": False, "message": "未找到评价表单"}), 500
    return jsonify({
        "success": True,
        "course_name": parsed["course_name"],
        "hidden_fields": parsed["hidden_fields"],
        "indicators": parsed["indicators"],
        "action": parsed["action"],
    })


@app.route('/api/submit-eval', methods=['POST'])
def api_submit_eval():
    client, err = _require_login()
    if err:
        return err
    data = request.get_json()
    form_data = data.get("form_data", {})
    submit_type = data.get("submit_type", "0")
    action_path = data.get("action", "/njlgdx/xspj/xspj_save.do")
    form_data["issubmit"] = submit_type
    target_url = f"http://202.119.81.112:9080{action_path}"
    try:
        _warm_eval_session(client)
        post_data = _build_ordered_eval_post_data(form_data, submit_type=submit_type)
        resp = client.session.post(target_url, data=post_data, headers=EVAL_HEADERS, timeout=15)
        if "评价成功" in resp.text or "提交成功" in resp.text or "保存成功" in resp.text:
            return jsonify({"success": True, "message": "评教提交成功！"})
        return jsonify({"success": True, "message": "已提交（请返回教务确认）"})
    except Exception as e:
        return jsonify({"success": False, "message": f"提交失败: {e}"}), 500


@app.route('/api/jw-proxy', methods=['POST'])
def api_jw_proxy():
    """通用教务网关: 用当前用户会话转发任意 9080 请求,返回原始内容。

    方案 A(薄后端)核心接口: 前端负责业务逻辑,后端只做认证 + 转发。

    参数:
        method: "GET" | "POST"
        path: 教务路径,如 "/njlgdx/xskb/xskb_list.do?Ves632DSdyV=..."
              (query 可拼在 path 里,或单独传 query)
        data: POST 表单参数 {key: value}
    返回:
        success/status/content_type/text(文本) 或 data_b64(二进制)
    """
    client, err = _require_login()
    if err:
        return err
    data = request.get_json() or {}
    method = (data.get("method") or "GET").upper()
    path = (data.get("path") or "").strip()
    if not path:
        return jsonify({"success": False, "message": "缺少 path"}), 400
    if method not in ("GET", "POST"):
        return jsonify({"success": False, "message": "method 仅支持 GET/POST"}), 400
    if not path.startswith("/"):
        path = "/" + path

    target = f"http://202.119.81.112:9080{path}"
    qs = data.get("query")
    if qs and isinstance(qs, str):
        target += "?" + qs.lstrip("?")
    form_data = data.get("data") or {}
    if not isinstance(form_data, dict):
        form_data = {}

    try:
        with _jwc_request(client):
            _warm_eval_session(client)
            if method == "POST":
                resp = client.session.post(target, data=form_data,
                                           headers=EVAL_HEADERS, timeout=15)
            else:
                resp = client.session.get(target, headers=EVAL_HEADERS, timeout=15)
    except Exception as e:
        return jsonify({"success": False, "message": f"请求失败: {e}"}), 502

    content_type = resp.headers.get("content-type") or ""
    if content_type.startswith(("text/", "application/json", "application/javascript")):
        return jsonify({
            "success": True,
            "status": resp.status_code,
            "content_type": content_type,
            "text": resp.text,
        })
    # 二进制内容(图片等) → base64
    return jsonify({
        "success": True,
        "status": resp.status_code,
        "content_type": content_type,
        "data_b64": base64.b64encode(resp.content).decode(),
    })


# ============================================================
# API — 清除数据（按用户隔离）
# ============================================================
@app.route('/api/clear-data', methods=['POST'])
def api_clear_data():
    client, err = _require_login()
    if err:
        return err
    sid = client.student_id or ""
    semester = dao.get_user_setting(sid, "semester") or _current_semester()
    dao.clear_data(semester, sid)
    _invalidate_stats(sid, semester)
    return jsonify({"success": True, "message": "数据已清除"})


# ============================================================
# API — 成绩查询（按用户隔离）
# ============================================================
@app.route('/api/grades')
def api_get_grades():
    """返回当前用户已存储的成绩原始数据(方案 A: GPA 等业务计算已移至前端)

    参数:
        semester: 学期代码(如 "2024-2025-1"),传 "__all__" 或不传查看全部学期
    """
    client, err = _require_login()
    if err:
        return err
    sid = client.student_id or ""
    semester = request.args.get("semester", "")
    view_all = (semester == "__all__" or not semester)

    cache_key = f"{sid}:grades:{semester or '__all__'}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return jsonify(cached)

    all_grades = dao.get_grades(student_id=sid)
    available_semesters = dao.get_grade_semesters(sid)

    if view_all:
        grades = all_grades
        display_semester = "__all__"
    else:
        parts = semester.split("-") if semester else []
        academic_year = f"{parts[0]}-{parts[1]}" if len(parts) >= 2 else ""
        sem = parts[2] if len(parts) >= 3 else ""
        grades = dao.get_grades(academic_year, sem, sid) if academic_year and sem else []
        display_semester = semester

    resp = {
        "success": True,
        "semester": display_semester,
        "count": len(grades),
        "grades": grades,
        "available_semesters": available_semesters,
    }
    _cache_set(cache_key, resp)
    return jsonify(resp)


@app.route('/api/refresh-grades', methods=['POST'])
def api_refresh_grades():
    """刷新当前用户成绩数据（从教务系统拉取）"""
    client, err = _require_login()
    if err:
        return err
    sid = client.student_id or ""

    with _jwc_request(client):
        grades = client.get_grades("")

    if not grades and client.last_error:
        return jsonify({
            "success": False,
            "message": client.last_error or "获取成绩失败",
        }), 500

    grouped = defaultdict(list)
    for g in grades:
        key = (g.get("academic_year", ""), g.get("semester", ""))
        grouped[key].append(g)

    total_count = 0

    for (ay, s), group in grouped.items():
        dao.save_grades(group, ay, s, sid)
        total_count += len(group)

    invalidate_user_cache(sid, "grades")
    app.logger.info("[refresh] rid=%s 成绩 sid=%s 学期数=%d 总数=%d", _rid(), sid, len(grouped), total_count)

    return jsonify({
        "success": True,
        "message": f"成功获取 {total_count} 条成绩记录（{len(grouped)} 个学期）",
        "count": total_count,
    })


# ============================================================
# API — 四六级（按用户隔离）
# ============================================================
@app.route('/api/refresh-cet', methods=['POST'])
def api_refresh_cet():
    """刷新当前用户四六级成绩（从教务系统拉取）"""
    client, err = _require_login()
    if err:
        return err
    sid = client.student_id or ""

    with _jwc_request(client):
        scores = client.get_cet_scores()

    if not scores:
        return jsonify({
            "success": False,
            "message": "未获取到四六级成绩",
        }), 404

    dao.save_cet_scores(scores, sid)
    invalidate_user_cache(sid, "cet")


    app.logger.info("[refresh] rid=%s 四六级 sid=%s count=%d", _rid(), sid, len(scores))
    return jsonify({
        "success": True,
        "message": f"成功获取 {len(scores)} 条四六级成绩",
        "scores": scores,
    })


@app.route('/api/cet-scores')
def api_cet_scores():
    """获取当前用户已存储的四六级原始成绩(折算计算已移至前端)"""
    client, err = _require_login()
    if err:
        return err
    sid = client.student_id or ""
    cache_key = f"{sid}:cet"
    cached = _cache_get(cache_key)
    if cached is not None:
        return jsonify(cached)
    scores = dao.get_cet_scores(sid)
    resp = {"success": True, "scores": scores}
    _cache_set(cache_key, resp)
    return jsonify(resp)


# ============================================================
# 错误处理
# ============================================================
@app.errorhandler(404)
def not_found(e):
    return jsonify({"error": "页面不存在"}), 404


@app.errorhandler(500)
def server_error(e):
    # 记录完整堆栈, 便于线上排障(云托管采集 stdout 日志)
    app.logger.error("[500] rid=%s %s %s: %s", _rid(), request.method, request.path, e, exc_info=True)
    return jsonify({"error": "服务器内部错误"}), 500


# 空教室定时预热(默认关闭, 云托管环境变量 FREE_CLASSROOM_PREWARM=1 开启)
_start_freeclass_prewarm()
