# -*- coding: utf-8 -*-
"""小程序使用统计上报接口。"""
import hashlib

from flask import Blueprint, jsonify, request

from wxcloudrun.core.rate_limit import client_ip, rate_limited
from wxcloudrun.core.sessions import TOKEN_HEADER
from wxcloudrun.core.usage import UsageValidationError, record_events


analytics_bp = Blueprint("analytics_api", __name__)


@analytics_bp.route('/api/analytics/events', methods=['POST'])
def api_analytics_events():
    payload = request.get_json(silent=True) or {}
    token = request.headers.get(TOKEN_HEADER, '') or ''
    rate_material = token or str(payload.get('visitor_id') or '')
    if not rate_material:
        rate_material = client_ip()
    rate_key = 'usage:' + hashlib.sha256(
        rate_material.encode('utf-8', 'ignore')).hexdigest()[:32]
    if rate_limited(rate_key, 300, 60):
        return jsonify({"success": False, "message": "上报过于频繁"}), 429
    try:
        accepted, duplicates, rejected = record_events(payload, token=token)
    except UsageValidationError as exc:
        return jsonify({
            "success": False,
            "message": str(exc),
        }), 400
    return jsonify({
        "success": True,
        "accepted": accepted,
        "duplicates": duplicates,
        "rejected": rejected,
    })
