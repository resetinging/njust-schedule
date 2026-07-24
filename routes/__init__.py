"""
南理工课表管理系统 — 路由模块
============================
Flask 蓝图路由，按功能域拆分。
共享状态 → routes/shared.py
工具函数 → routes/helpers.py
"""
from routes.shared import (
    jwc_client, jwc_lock,
    _batch_progress, _batch_progress_lock,
    _auto_login_attempted, _last_auto_login_time,
    check_network, get_lan_ip,
)
from routes.helpers import (
    _encode_pwd, _decode_pwd,
    _auto_login, _require_login, _on_login_success,
    _course_row_to_dict, _exam_row_to_dict, _grade_row_to_dict,
)

__all__ = [
    "jwc_client", "jwc_lock",
    "_batch_progress", "_batch_progress_lock",
    "_auto_login_attempted", "_last_auto_login_time",
    "_encode_pwd", "_decode_pwd",
    "_auto_login", "_require_login", "_on_login_success",
    "_course_row_to_dict", "_exam_row_to_dict", "_grade_row_to_dict",
    "check_network",
    "get_lan_ip",
]
