"""
南理工课表管理系统 — 设置 API 路由
==================================
学期切换、设置读写、数据清除。
"""
from flask import Blueprint, request, jsonify

from routes import jwc_client
from database import get_db, get_setting, set_setting

settings_bp = Blueprint("api_settings", __name__)


@settings_bp.route("/api/settings", methods=["GET", "POST"])
def api_settings():
    """读取或更新设置"""
    if request.method == "GET":
        db = get_db()
        rows = db.execute("SELECT key, value FROM settings").fetchall()
        settings = {r["key"]: r["value"] for r in rows}
        # 补充 semester 列表
        settings["semester_list"] = jwc_client.get_semester_list()
        settings["current_semester"] = jwc_client._current_semester()
        # 标记密码是否已保存（不返回原始密码）
        settings["has_password"] = bool(settings.get("password_enc", ""))
        settings["has_jwc_password"] = bool(settings.get("jwc_password_enc", ""))
        settings.pop("password_enc", None)  # 不暴露编码密码到前端
        settings.pop("jwc_password_enc", None)
        return jsonify(settings)

    else:
        data = request.get_json()
        for key, value in data.items():
            if key in ("student_id", "student_name", "semester",
                        "auto_refresh", "refresh_interval", "first_week_date"):
                set_setting(key, str(value))
        return jsonify({"success": True, "message": "设置已保存"})


@settings_bp.route("/api/semester", methods=["POST"])
def api_set_semester():
    """切换学期"""
    data = request.get_json()
    semester = (data.get("semester") or "").strip()
    if not semester:
        return jsonify({"success": False, "message": "学期不能为空"}), 400

    set_setting("semester", semester)
    return jsonify({"success": True, "message": f"已切换到学期: {semester}"})


@settings_bp.route("/api/clear-data", methods=["POST"])
def api_clear_data():
    """清除当前学期的数据"""
    semester = get_setting("semester", jwc_client._current_semester())
    db = get_db()
    db.execute("DELETE FROM courses WHERE semester = ?", (semester,))
    db.execute("DELETE FROM exams WHERE semester = ?", (semester,))
    db.commit()
    return jsonify({"success": True, "message": "数据已清除"})
