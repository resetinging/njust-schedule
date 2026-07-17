"""Routes helper functions (auth, login, row converters)."""
import base64
import time

from flask import jsonify

from database import get_setting, set_setting
import routes.shared as shared


def _encode_pwd(pwd: str) -> str:
    return base64.b64encode(pwd.encode()).decode()


def _decode_pwd(encoded: str) -> str:
    try:
        return base64.b64decode(encoded.encode()).decode()
    except Exception:
        return ""


def _auto_login() -> bool:
    """尝试用存储的凭据自动登录"""
    shared._auto_login_attempted = True
    shared._last_auto_login_time = time.time()

    if shared.jwc_client.logged_in:
        return True

    if shared.jwc_client._webvpn_manual_ready:
        return False

    sid = get_setting("student_id")
    jwc_pwd = _decode_pwd(get_setting("jwc_password_enc", ""))
    sso_pwd = _decode_pwd(get_setting("password_enc", ""))
    pwd = jwc_pwd or sso_pwd
    if not sid or not pwd:
        return False

    shared.jwc_client.login(sid, pwd)
    return shared.jwc_client.logged_in


def _require_login():
    """检查登录状态，未登录时尝试自动重登"""
    if not shared.jwc_client.logged_in:
        auto_ok = _auto_login()
        student_id = get_setting("student_id")
        if not student_id:
            return jsonify({
                "success": False,
                "message": "尚未登录，请先在设置页面登录教务系统",
            }), 401
        if not auto_ok:
            err = shared.jwc_client.last_error or "教务系统不可达"
            return jsonify({
                "success": False,
                "message": f"自动登录失败: {err}，请前往设置手动登录",
            }), 401
    return None


def _on_login_success(student_id: str, password: str = ""):
    """登录成功后的公共处理"""
    set_setting("student_id", student_id)
    if password:
        set_setting("password_enc", _encode_pwd(password))
    if shared.jwc_client.student_name:
        set_setting("student_name", shared.jwc_client.student_name)
    else:
        set_setting("student_name", "")

    semester = get_setting("semester")
    if not semester:
        semester = shared.jwc_client._current_semester()
        set_setting("semester", semester)

    return jsonify({
        "success": True,
        "message": f"登录成功！欢迎 {shared.jwc_client.student_name or student_id}",
        "student_name": shared.jwc_client.student_name or student_id,
        "login_method": shared.jwc_client.login_method,
    })


def _course_row_to_dict(row) -> dict:
    return {
        "id": row["id"],
        "name": row["name"],
        "teacher": row["teacher"],
        "classroom": row["classroom"],
        "day": row["day_of_week"],
        "start": row["start_period"],
        "end": row["end_period"],
        "weeks": row["weeks"],
        "week_type": row["week_type"],
        "credits": row["credits"],
        "course_type": row["course_type"],
    }


def _exam_row_to_dict(row) -> dict:
    return {
        "id": row["id"],
        "course_name": row["course_name"],
        "date": row["exam_date"],
        "time": row["exam_time"],
        "location": row["location"],
        "seat": row["seat"],
        "type": row["exam_type"],
    }


def _grade_row_to_dict(row) -> dict:
    return {
        "id": row["id"],
        "academic_year": row["academic_year"],
        "semester": row["semester"],
        "course_code": row["course_code"],
        "course_name": row["course_name"],
        "score": row["score"],
        "credit": row["credit"],
        "grade_point": row["grade_point"],
        "course_type": row["course_type"],
        "course_nature": row["course_nature"] if "course_nature" in row.keys() else "",
        "exam_type": row["exam_type"],
    }
