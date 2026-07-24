"""
南理工课表管理系统 — 数据 API 路由
==================================
课表、考试、成绩、四六级的获取与刷新。
"""
from collections import defaultdict
from flask import Blueprint, request, jsonify

from routes import (
    jwc_client, jwc_lock,
    _require_login,
    _course_row_to_dict, _exam_row_to_dict, _grade_row_to_dict,
)
from database import (
    get_db, get_setting, set_setting,
    save_courses_to_db, save_exams_to_db, save_grades_to_db,
    save_cet_scores, get_cet_scores as db_get_cet_scores,
)
from gpa import (
    score_to_gp, calc_gpa, calc_semester_gpas, is_gpa_course,
    calc_gpa_baoyan,
)

data_bp = Blueprint("api_data", __name__)


# ============================================================
# 课表
# ============================================================

@data_bp.route("/api/refresh-schedule", methods=["POST"])
def api_refresh_schedule():
    """刷新课表数据"""
    semester = get_setting("semester", jwc_client._current_semester())

    err = _require_login()
    if err:
        return err

    with jwc_lock:
        courses = jwc_client.get_schedule(semester)

    if not courses:
        return jsonify({
            "success": False,
            "message": jwc_client.last_error or "获取课表失败，请检查网络连接和登录状态",
        }), 500

    save_courses_to_db(courses, semester)
    set_setting("semester", semester)

    return jsonify({
        "success": True,
        "message": f"成功获取 {len(courses)} 门课程",
        "count": len(courses),
        "semester": semester,
    })


@data_bp.route("/api/courses")
def api_get_courses():
    """获取已存储的课表数据"""
    semester = request.args.get(
        "semester", get_setting("semester", jwc_client._current_semester())
    )
    db = get_db()
    rows = db.execute(
        "SELECT * FROM courses WHERE semester = ? ORDER BY day_of_week, start_period",
        (semester,),
    ).fetchall()

    courses = [_course_row_to_dict(r) for r in rows]

    return jsonify({
        "semester": semester,
        "count": len(courses),
        "courses": courses,
    })


# ============================================================
# 考试
# ============================================================

@data_bp.route("/api/refresh-exams", methods=["POST"])
def api_refresh_exams():
    """刷新考试安排"""
    semester = get_setting("semester", jwc_client._current_semester())

    err = _require_login()
    if err:
        return err

    with jwc_lock:
        exams = jwc_client.get_exams(semester)

    if not exams and jwc_client.last_error:
        return jsonify({
            "success": False,
            "message": jwc_client.last_error or "获取考试安排失败，请检查网络连接和登录状态",
        }), 500

    save_exams_to_db(exams, semester)

    return jsonify({
        "success": True,
        "message": f"成功获取 {len(exams)} 场考试" + ("（本学期暂无考试）" if len(exams) == 0 else ""),
        "count": len(exams),
    })


@data_bp.route("/api/exams")
def api_get_exams():
    """获取已存储的考试安排"""
    semester = request.args.get(
        "semester", get_setting("semester", jwc_client._current_semester())
    )
    db = get_db()
    rows = db.execute(
        "SELECT * FROM exams WHERE semester = ? ORDER BY exam_date",
        (semester,),
    ).fetchall()

    exams = [_exam_row_to_dict(r) for r in rows]

    return jsonify({
        "semester": semester,
        "count": len(exams),
        "exams": exams,
    })


@data_bp.route("/api/refresh-all", methods=["POST"])
def api_refresh_all():
    """一键刷新课表和考试安排"""
    semester = get_setting("semester", jwc_client._current_semester())

    err = _require_login()
    if err:
        return err

    results = {"schedule": None, "exams": None}

    with jwc_lock:
        courses = jwc_client.get_schedule(semester)
        if courses:
            save_courses_to_db(courses, semester)
            results["schedule"] = {"count": len(courses), "ok": True}
        else:
            results["schedule"] = {"count": 0, "ok": False, "error": jwc_client.last_error}

        exams = jwc_client.get_exams(semester)
        if exams:
            save_exams_to_db(exams, semester)
            results["exams"] = {"count": len(exams), "ok": True}
        else:
            results["exams"] = {"count": 0, "ok": False, "error": jwc_client.last_error}

    set_setting("semester", semester)

    return jsonify({
        "success": True,
        "semester": semester,
        "schedule": results["schedule"],
        "exams": results["exams"],
        "message": (
            f"课表: {results['schedule']['count']}门, "
            f"考试: {results['exams']['count']}场"
        ),
    })


# ============================================================
# 成绩查询
# ============================================================

@data_bp.route("/api/grades")
def api_get_grades():
    """获取已存储的成绩数据

    参数:
        semester: 学期代码（如 "2024-2025-1"），传 "__all__" 查看全部学期
    """
    semester = request.args.get(
        "semester", get_setting("semester", jwc_client._current_semester())
    )

    db = get_db()

    # 获取已有成绩的学期列表 + 各学期绩点汇总
    semester_gpas = calc_semester_gpas(db)
    available = db.execute(
        "SELECT DISTINCT academic_year, semester FROM grades ORDER BY academic_year DESC, semester DESC"
    ).fetchall()
    available_semesters = [f"{r['academic_year']}-{r['semester']}" for r in available]

    # 计算全部学期的累计绩点
    all_rows = db.execute(
        "SELECT * FROM grades ORDER BY academic_year DESC, semester DESC, course_type, course_name"
    ).fetchall()
    all_grades_list = [_grade_row_to_dict(r) for r in all_rows]
    for g in all_grades_list:
        if float(g.get("grade_point", 0) or 0) == 0:
            g["grade_point"] = score_to_gp(g.get("score", ""))
    all_gpa = calc_gpa(all_grades_list, gpa_only=False) if all_grades_list else 0
    all_gpa_counted = calc_gpa(all_grades_list, gpa_only=True) if all_grades_list else 0
    all_credits = round(sum(
        float(g.get("credit", 0) or 0) for g in all_grades_list
        if is_gpa_course(g.get("course_nature", ""))
    ), 1)

    # 是否查看全部学期
    view_all = (semester == "__all__" or not semester)

    if view_all:
        grades = all_grades_list
        display_semester = "__all__"
    else:
        parts = semester.split("-") if semester else []
        academic_year = f"{parts[0]}-{parts[1]}" if len(parts) >= 2 else ""
        sem = parts[2] if len(parts) >= 3 else ""
        if academic_year and sem:
            rows = db.execute(
                """SELECT * FROM grades
                   WHERE academic_year = ? AND semester = ?
                   ORDER BY course_type, course_name""",
                (academic_year, sem),
            ).fetchall()
        else:
            rows = []
        grades = [_grade_row_to_dict(r) for r in rows]
        for g in grades:
            if float(g.get("grade_point", 0) or 0) == 0:
                g["grade_point"] = score_to_gp(g.get("score", ""))
        display_semester = semester

    # 保研/推免模式：CET 折算替换英语模块
    gpa_mode = request.args.get("gpa_mode", "")
    cet_scores = db_get_cet_scores() if gpa_mode == "baoyan" else None

    gpa_baoyan = 0.0
    all_gpa_baoyan = 0.0
    if gpa_mode == "baoyan" and grades:
        gpa_baoyan = calc_gpa_baoyan(grades, cet_scores, gpa_only=True)
    if gpa_mode == "baoyan" and all_grades_list:
        all_gpa_baoyan = calc_gpa_baoyan(all_grades_list, cet_scores, gpa_only=True)

    return jsonify({
        "semester": display_semester,
        "count": len(grades),
        "grades": grades,
        "available_semesters": available_semesters,
        "total_credits": round(sum(
            float(g.get("credit", 0) or 0) for g in grades
            if is_gpa_course(g.get("course_nature", ""))
        ), 1),
        "gpa": calc_gpa(grades, gpa_only=True) if grades else 0,
        "gpa_all": calc_gpa(grades, gpa_only=False) if grades else 0,
        # 保研模式 GPA（CET 折算）
        "gpa_baoyan": gpa_baoyan,
        "all_gpa_baoyan": all_gpa_baoyan,
        "gpa_mode": gpa_mode,
        # 全部学期汇总
        "all_gpa": all_gpa_counted,
        "all_gpa_all": all_gpa,
        "all_credits": all_credits,
        "all_count": sum(1 for g in all_grades_list if is_gpa_course(g.get("course_nature", ""))),
        "all_count_total": len(all_grades_list),
        "semester_gpas": semester_gpas,
    })


@data_bp.route("/api/refresh-grades", methods=["POST"])
def api_refresh_grades():
    """刷新成绩数据（从教务系统拉取）"""
    err = _require_login()
    if err:
        return err

    with jwc_lock:
        grades = jwc_client.get_grades("")

    if not grades and jwc_client.last_error:
        return jsonify({
            "success": False,
            "message": jwc_client.last_error or "获取成绩失败，请检查网络连接和登录状态",
        }), 500

    # 成绩可能跨多个学期，按学期分组保存
    grouped = defaultdict(list)
    for g in grades:
        key = (g.get("academic_year", ""), g.get("semester", ""))
        grouped[key].append(g)

    total_count = 0
    for (ay, s), group in grouped.items():
        save_grades_to_db(group, ay, s)
        total_count += len(group)

    return jsonify({
        "success": True,
        "message": f"成功获取 {total_count} 条成绩记录（{len(grouped)} 个学期）",
        "count": total_count,
    })


# ============================================================
# 四六级
# ============================================================

@data_bp.route("/api/refresh-cet", methods=["POST"])
def api_refresh_cet():
    """刷新四六级成绩（从教务系统拉取）"""
    err = _require_login()
    if err:
        return err

    with jwc_lock:
        scores = jwc_client.get_cet_scores()

    if not scores:
        return jsonify({
            "success": False,
            "message": "未获取到四六级成绩，请确认已参加考试",
        }), 404

    save_cet_scores(scores)
    return jsonify({
        "success": True,
        "message": f"成功获取 {len(scores)} 条四六级成绩",
        "scores": scores,
    })


@data_bp.route("/api/cet-scores")
def api_cet_scores():
    """获取已存储的四六级成绩及折算信息"""
    from gpa import cet_to_percentage
    scores = db_get_cet_scores()

    # 计算折算百分制
    cet_info = []
    for s in scores:
        pct = cet_to_percentage(s["score"], s["type"])
        cet_info.append({
            **s,
            "percentage": pct,
            "usable": pct > 0,
        })

    # 选择最佳可用 CET 分数
    best_pct = 0.0
    best_type = ""
    for ci in cet_info:
        if ci["usable"] and ci["percentage"] > best_pct:
            best_pct = ci["percentage"]
            best_type = ci["type"]

    return jsonify({
        "scores": cet_info,
        "best_type": best_type,
        "best_percentage": best_pct,
        "has_usable": best_pct > 0,
    })
