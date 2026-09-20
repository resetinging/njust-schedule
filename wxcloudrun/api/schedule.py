# -*- coding: utf-8 -*-
"""课表/考试刷新与查询路由(Phase 1b 从 views.py 拆出)。"""
from flask import Blueprint, jsonify, request

import config
from wxcloudrun import app, dao
from wxcloudrun.core.auth import _require_login, _retry_with_relogin
from wxcloudrun.core.cache import _cache_get, _cache_set, invalidate_user_cache
from wxcloudrun.core.pool import _jwc_request
from wxcloudrun.core.stats import _invalidate_stats
from wxcloudrun.core.web import _rid
from wxcloudrun.jwc_client import JWCClient

schedule_bp = Blueprint("schedule_api", __name__)
jwc_client = JWCClient()


def _current_semester() -> str:
    """当前学期(views 实现, 延迟导入避免循环)"""
    from wxcloudrun.views import _current_semester as _impl
    return _impl()


@schedule_bp.route('/api/refresh-schedule', methods=['POST'])
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


@schedule_bp.route('/api/refresh-exams', methods=['POST'])
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


@schedule_bp.route('/api/refresh-all', methods=['POST'])
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


@schedule_bp.route('/api/courses')
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


@schedule_bp.route('/api/exams')
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



