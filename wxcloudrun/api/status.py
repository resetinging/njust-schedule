# -*- coding: utf-8 -*-
"""状态/连通性探测路由(Phase 1b 从 views.py 拆出)。"""
from flask import Blueprint, jsonify, request

from wxcloudrun import app, dao
from wxcloudrun.core.auth import _require_login
from wxcloudrun.core.sessions import _get_session_client
from wxcloudrun.core.stats import _get_data_stats
from wxcloudrun.core.timeutil import _beijing_now, _beijing_date
from wxcloudrun.core.web import _rid
from wxcloudrun.jwc_client import JWCClient

status_bp = Blueprint("status_api", __name__)
jwc_client = JWCClient()


def _current_semester() -> str:
    from wxcloudrun.views import _current_semester as _impl
    return _impl()


def _check_network(force: bool = False):
    from wxcloudrun.views import _check_network as _impl
    return _impl(force=force)


@status_bp.route('/api/status')
def api_status():
    # 仅支持手动登录：登录态只取决于当前请求 token 对应的会话
    client = _get_session_client()
    logged_in = bool(client and client.logged_in)
    student_id = client.student_id if logged_in else ""
    student_name = client.student_name if logged_in else ""
    semester_keys = [f"{student_id}:semester", "semester"] if logged_in else ["semester"]
    semester_settings = dao.get_settings(semester_keys)
    semester = ((semester_settings.get(f"{student_id}:semester") if logged_in else "")
                or semester_settings.get("semester") or _current_semester())

    has_courses = False
    has_exams = False
    if logged_in and semester:
        if getattr(client, "account_type", "") == "graduate":
            # 研究生课表实时来自研究生系统(不走本地缓存统计)
            has_courses = True
        else:
            has_courses, has_exams = _get_data_stats(student_id, semester)

    # 教务连通性(桌面端导航栏/设置页依赖, 5 分钟缓存; 仅用户主动测试时强制刷新)
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
    first_week_keys = ["first_week_date"]
    if logged_in and student_id and semester:
        first_week_keys.insert(0, f"{student_id}:first_week_date:{semester}")
    first_week_settings = dao.get_settings(first_week_keys)
    first_week_date = first_week_settings.get("first_week_date", "")
    if logged_in and student_id and semester:
        first_week_date = first_week_settings.get(
            f"{student_id}:first_week_date:{semester}", "") or first_week_date

    return jsonify({
        "logged_in": logged_in,
        "student_id": student_id,
        "student_name": student_name,
        "semester": semester,
        "has_courses": has_courses,
        "has_exams": has_exams,
        "login_method": client.login_method if logged_in else "",
        "account_type": getattr(client, "account_type", "undergraduate"),
        "auto_login_attempted": False,
        "auto_login_error": "",
        "server_time": _beijing_now(),
        "first_week_date": first_week_date,
        "network": network,
        "data_refresh": (getattr(client, "_data_refresh_state", None)
                         if logged_in else {"state": "idle", "updated_at": 0}),
        # 能力协商: 前端可据此判断后端支持哪些能力(以后加接口/改字段时避免静默不兼容)
        "api_version": 3,
        "features": ["yjs", "freeclass", "font_subset", "refresh_dedupe",
                     "credential_relogin", "prefetch_status"],
    })


@status_bp.route('/api/prefetch-status')
def api_prefetch_status():
    """轻量登录后同步状态: 不查数据库、不探测教务、不拉统计数据。"""
    client = _get_session_client()
    if client is None or not getattr(client, "logged_in", False):
        return jsonify({"success": False, "message": "尚未登录，请先登录"}), 401
    state = getattr(client, "_data_refresh_state", None) or {
        "state": "idle", "updated_at": 0,
    }
    return jsonify({"success": True, "data_refresh": state})


@status_bp.route('/api/connect-test')
def api_connect_test():
    ok, msg = _check_network(force=True)
    return jsonify({"ok": ok, "message": msg})


# ============================================================
# API — 问题反馈(需登录; 10 秒限流防重复提交; 仅管理端可见)
# ============================================================
# 内容敏感词过滤(留言板已下线, 反馈内容沿用同一词表)
