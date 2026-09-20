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


# 登录/验证码/WebVPN 路由已拆到 wxcloudrun/api/auth.py (Phase 1b)
from wxcloudrun.api.auth import auth_bp  # noqa: E402

app.register_blueprint(auth_bp)


# 登录守卫/重登封装已下沉 core/auth.py(Phase 1b)
from wxcloudrun.core.auth import _require_login, _retry_with_relogin  # noqa: E402


from wxcloudrun.api.schedule import schedule_bp  # noqa: E402

app.register_blueprint(schedule_bp)

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


from wxcloudrun.api.eval import (  # noqa: E402
    eval_bp, _build_ordered_eval_post_data, _parse_eval_courses_page,
    _parse_eval_form_page)

app.register_blueprint(eval_bp)


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
from wxcloudrun.api.grades import grades_bp  # noqa: E402

app.register_blueprint(grades_bp)


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
