# -*- coding: utf-8 -*-
"""多数据域版本检查：只返回版本，不返回业务数据。"""
from datetime import datetime

from flask import Blueprint, jsonify, request
from sqlalchemy import func

from wxcloudrun import dao, db
from wxcloudrun.core.auth import _require_login
from wxcloudrun.model import CetScore, Course, Evaluation, Exam, Grade

sync_bp = Blueprint("sync_api", __name__)


def _version(model, sid: str, semester: str = "") -> str:
    query = db.session.query(
        func.count(model.id), func.max(model.id), func.max(model.created_at)
    ).filter(model.student_id == sid)
    if semester and hasattr(model, "semester"):
        query = query.filter(model.semester == semester)
    count, latest_id, latest = query.one()
    if not count:
        return "0"
    if isinstance(latest, datetime):
        latest = int(latest.timestamp())
    return f"{int(count)}:{int(latest_id or 0)}:{int(latest or 0)}"


@sync_bp.route('/api/sync/versions')
def api_sync_versions():
    client, err = _require_login()
    if err:
        return err
    sid = client.student_id or ""
    semester = ((request.args.get("semester") or "").strip()
                or dao.get_user_setting(sid, "semester") or "")
    return jsonify({
        "success": True,
        "semester": semester,
        "versions": {
            "courses": _version(Course, sid, semester),
            "exams": _version(Exam, sid, semester),
            "evaluations": _version(Evaluation, sid),
            "grades": _version(Grade, sid),
            "cet_scores": _version(CetScore, sid),
        },
    })
