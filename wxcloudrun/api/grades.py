# -*- coding: utf-8 -*-
"""成绩与四六级路由(Phase 1b 从 views.py 拆出)。"""
from flask import Blueprint, jsonify, request

import config
from wxcloudrun import app, dao
from wxcloudrun.core.auth import _require_login, _retry_with_relogin
from wxcloudrun.core.cache import _cache_get, _cache_set, invalidate_user_cache
from wxcloudrun.core.pool import _jwc_request
from wxcloudrun.core.stats import _invalidate_stats
from wxcloudrun.core.web import _rid
from wxcloudrun.jwc_client import JWCClient

grades_bp = Blueprint("grades_api", __name__)
jwc_client = JWCClient()


def _current_semester() -> str:
    """当前学期(views 实现, 延迟导入避免循环)"""
    from wxcloudrun.views import _current_semester as _impl
    return _impl()


@grades_bp.route('/api/grades')
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


@grades_bp.route('/api/refresh-grades', methods=['POST'])
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
@grades_bp.route('/api/refresh-cet', methods=['POST'])
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


@grades_bp.route('/api/cet-scores')
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
