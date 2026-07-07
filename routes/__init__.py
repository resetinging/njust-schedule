"""
南理工课表管理系统 — 路由模块
============================
Flask 蓝图路由，按功能域拆分。
共享状态和工具函数集中在本模块。
"""
import base64
import time
import threading
import socket

from jwc_client import JWCClient
from database import get_setting, set_setting

# ============================================================
# 全局共享状态
# ============================================================

# 全局教务客户端（线程不安全，操作时需加锁）
jwc_client = JWCClient()
jwc_lock = threading.Lock()

# 批量评教进度追踪
_batch_progress = {}       # {batch_id: {current, total, course, status, message, done, results}}
_batch_progress_lock = threading.Lock()

# 自动登录冷却
_auto_login_attempted = False
_last_auto_login_time = 0.0


# ============================================================
# 密码编码（本地存储，非安全加密）
# ============================================================

def _encode_pwd(pwd: str) -> str:
    return base64.b64encode(pwd.encode()).decode()


def _decode_pwd(encoded: str) -> str:
    try:
        return base64.b64decode(encoded.encode()).decode()
    except Exception:
        return ""


# ============================================================
# 自动登录
# ============================================================

def _auto_login() -> bool:
    """尝试用存储的凭据自动登录"""
    global _auto_login_attempted, _last_auto_login_time
    _auto_login_attempted = True
    _last_auto_login_time = time.time()

    if jwc_client.logged_in:
        return True

    sid = get_setting("student_id")
    pwd = _decode_pwd(get_setting("password_enc", ""))
    if not sid or not pwd:
        return False

    jwc_client.login(sid, pwd)
    return jwc_client.logged_in


def _require_login():
    """检查登录状态，未登录时尝试自动重登，仍失败则返回错误响应"""
    from flask import jsonify
    if not jwc_client.logged_in:
        auto_ok = _auto_login()
        student_id = get_setting("student_id")
        if not student_id:
            return jsonify({
                "success": False,
                "message": "尚未登录，请先在设置页面登录教务系统",
            }), 401
        if not auto_ok:
            err = jwc_client.last_error or "教务系统不可达"
            return jsonify({
                "success": False,
                "message": f"自动登录失败: {err}，请前往设置手动登录",
            }), 401
    return None


def _on_login_success(student_id: str, password: str = ""):
    """登录成功后的公共处理"""
    from flask import jsonify
    set_setting("student_id", student_id)
    if password:
        set_setting("password_enc", _encode_pwd(password))
    if jwc_client.student_name:
        set_setting("student_name", jwc_client.student_name)

    semester = get_setting("semester")
    if not semester:
        semester = jwc_client._current_semester()
        set_setting("semester", semester)

    return jsonify({
        "success": True,
        "message": f"登录成功！欢迎 {jwc_client.student_name or student_id}",
        "student_name": jwc_client.student_name or student_id,
        "login_method": jwc_client.login_method,
    })


# ============================================================
# 数据库行 → JSON 转换
# ============================================================

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


# ============================================================
# 网络工具
# ============================================================

def get_lan_ip() -> str:
    """获取局域网 IP"""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.254.254.254", 1))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


# ============================================================
# 暴露给其他模块的符号
# ============================================================

__all__ = [
    "jwc_client", "jwc_lock",
    "_batch_progress", "_batch_progress_lock",
    "_auto_login_attempted", "_last_auto_login_time",
    "_encode_pwd", "_decode_pwd",
    "_auto_login", "_require_login", "_on_login_success",
    "_course_row_to_dict", "_exam_row_to_dict", "_grade_row_to_dict",
    "get_lan_ip",
]
