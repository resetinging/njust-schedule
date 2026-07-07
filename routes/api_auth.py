"""
南理工课表管理系统 — 认证 API 路由
==================================
登录、验证码、系统状态。
"""
import time
from datetime import datetime
from flask import Blueprint, request, jsonify

from routes import (
    jwc_client, jwc_lock,
    _auto_login_attempted, _last_auto_login_time,
    _auto_login, _on_login_success,
)
from database import get_db, get_setting

auth_bp = Blueprint("api_auth", __name__)


@auth_bp.route("/api/status")
def api_status():
    """获取系统状态"""
    student_id = get_setting("student_id")
    student_name = get_setting("student_name")
    semester = get_setting("semester")

    has_courses = False
    has_exams = False
    if student_id and semester:
        db = get_db()
        course_count = db.execute(
            "SELECT COUNT(*) FROM courses WHERE semester = ?", (semester,)
        ).fetchone()[0]
        exam_count = db.execute(
            "SELECT COUNT(*) FROM exams WHERE semester = ?", (semester,)
        ).fetchone()[0]
        has_courses = course_count > 0
        has_exams = exam_count > 0

    # 如果未登录且已保存凭据，尝试自动登录（30秒冷却）
    auto_login_error = ""
    if not jwc_client.logged_in and student_id:
        if not _auto_login_attempted or (time.time() - _last_auto_login_time) > 30:
            with jwc_lock:
                ok = _auto_login()
            if ok:
                auto_login_error = ""
            else:
                auto_login_error = jwc_client.last_error or "登录失败，请检查验证码或网络"

    return jsonify({
        "logged_in": jwc_client.logged_in,
        "student_id": student_id,
        "student_name": student_name or jwc_client.student_name or "",
        "semester": semester or jwc_client._current_semester(),
        "has_courses": has_courses,
        "has_exams": has_exams,
        "login_method": jwc_client.login_method or "",
        "auto_login_attempted": _auto_login_attempted,
        "auto_login_error": auto_login_error,
        "server_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    })


@auth_bp.route("/api/connect-test")
def api_connect_test():
    """测试教务系统连接"""
    ok, msg = jwc_client.test_connection()
    return jsonify({"ok": ok, "message": msg})


@auth_bp.route("/api/get-captcha")
def api_get_captcha():
    """获取验证码图片（Base64），供手动输入"""
    with jwc_lock:
        b64, error = jwc_client.get_captcha_base64()

    if error or not b64:
        return jsonify({
            "success": False,
            "message": error or "获取验证码失败，请确认已连接校园网/VPN",
        }), 500

    return jsonify({
        "success": True,
        "captcha_b64": b64,
        "message": "验证码获取成功，请在下方输入（不区分大小写）",
    })


@auth_bp.route("/api/login", methods=["POST"])
def api_login():
    """登录教务系统（自动OCR识别验证码）"""
    data = request.get_json()
    student_id = (data.get("student_id") or "").strip()
    password = data.get("password") or ""

    if not student_id or not password:
        return jsonify({"success": False, "message": "学号和密码不能为空"}), 400

    with jwc_lock:
        success = jwc_client.login(student_id, password)

    if success:
        return _on_login_success(student_id, password)
    else:
        return jsonify({
            "success": False,
            "message": jwc_client.last_error or "登录失败，请检查学号和密码",
            "need_captcha": "验证码" in (jwc_client.last_error or ""),
        }), 401


@auth_bp.route("/api/login-manual", methods=["POST"])
def api_login_manual():
    """使用手动输入的验证码登录"""
    data = request.get_json()
    student_id = (data.get("student_id") or "").strip()
    password = data.get("password") or ""
    captcha_text = (data.get("captcha") or "").strip()

    if not student_id or not password:
        return jsonify({"success": False, "message": "学号和密码不能为空"}), 400
    if not captcha_text:
        return jsonify({"success": False, "message": "请先获取验证码并输入"}), 400

    with jwc_lock:
        success = jwc_client.login_with_manual_captcha(
            student_id, password, captcha_text
        )

    if success:
        return _on_login_success(student_id, password)
    else:
        return jsonify({
            "success": False,
            "message": jwc_client.last_error or "登录失败，请检查验证码是否正确",
        }), 401
