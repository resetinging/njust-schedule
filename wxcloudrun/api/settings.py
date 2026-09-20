# -*- coding: utf-8 -*-
"""设置/学期/清理数据路由(Phase 1b 从 views.py 拆出)。"""
from flask import Blueprint, jsonify, request

from wxcloudrun import app, dao
from wxcloudrun.core.auth import _require_login
from wxcloudrun.core.cache import invalidate_user_cache
from wxcloudrun.core.sessions import _get_session_client
from wxcloudrun.jwc_client import JWCClient

settings_bp = Blueprint("settings_api", __name__)
jwc_client = JWCClient()


def _current_semester() -> str:
    """当前学期(views 实现, 延迟导入避免循环)"""
    from wxcloudrun.views import _current_semester as _impl
    return _impl()


@settings_bp.route('/api/settings', methods=['GET', 'POST'])
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


@settings_bp.route('/api/semesters')
def api_get_semesters():
    """获取可用学期列表"""
    try:
        semesters = jwc_client.get_semester_list()
        current = _current_semester()
        return jsonify({"success": True, "semesters": semesters, "current": current})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


@settings_bp.route('/api/semester', methods=['POST'])
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


@settings_bp.route('/api/clear-data', methods=['POST'])
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
