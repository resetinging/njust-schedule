# -*- coding: utf-8 -*-
"""订阅消息接口: 授权额度上报 / 状态查询 / 样例发送。

- GET  /api/subscribe/status    : 各提醒类型的模板可用性 + 剩余额度
- POST /api/subscribe/grant     : 小程序授权成功后上报(记 openid + 额度 +1)
- POST /api/subscribe/test-send : 发送一条样例考试提醒(消耗 1 次额度, 用于验证配置)
"""
from flask import Blueprint, jsonify, request

from wxcloudrun import app
from wxcloudrun.core import mp, subscribe_store
from wxcloudrun.core.auth import _require_login
from wxcloudrun.core.reminder import build_exam_data
from wxcloudrun.core.web import _rid
from wxcloudrun.model import Exam

subscribe_bp = Blueprint("subscribe_api", __name__)


@subscribe_bp.route('/api/subscribe/status')
def api_subscribe_status():
    client, err = _require_login()
    if err:
        return err
    sid = client.student_id or ""
    openid = subscribe_store.caller_openid()
    if openid:
        subscribe_store.save_openid(sid, openid)
    kinds = {}
    for kind in subscribe_store.KINDS:
        tpl = mp.template_id(kind)
        kinds[kind] = {"template_id": tpl, "enabled": bool(tpl),
                       "quota": subscribe_store.quota(sid, kind)}
    return jsonify({
        "success": True,
        "kinds": kinds,
        "openid_bound": bool(subscribe_store.get_openid(sid)),
        "send_enabled": mp.enabled(),
    })


@subscribe_bp.route('/api/subscribe/grant', methods=['POST'])
def api_subscribe_grant():
    client, err = _require_login()
    if err:
        return err
    data = request.get_json(silent=True) or {}
    kind = str(data.get("kind") or "").strip()
    if kind not in subscribe_store.KINDS:
        return jsonify({"success": False, "message": "未知的提醒类型"}), 400
    openid = subscribe_store.caller_openid()
    # 微信一次性订阅一次授权只产生 1 条额度; 客户端 count 不可信。
    item = subscribe_store.grant(client.student_id or "", kind, 1, openid)
    app.logger.info("[subscribe] rid=%s 授权 kind=%s quota=%s sid=%s openid=%s",
                    _rid(), kind, item.get("count"), client.student_id,
                    "有" if openid else "无")
    return jsonify({"success": True, "kind": kind, "quota": item.get("count") or 0})


@subscribe_bp.route('/api/subscribe/test-send', methods=['POST'])
def api_subscribe_test_send():
    """发送一条样例考试提醒(优先用该用户最近一场考试, 否则用样例数据)。"""
    client, err = _require_login()
    if err:
        return err
    sid = client.student_id or ""
    tpl = mp.template_id("exam")
    if not (tpl and mp.enabled()):
        return jsonify({"success": False,
                        "message": "订阅消息未配置(缺模板 ID 或 MP_SECRET)"}), 400
    openid = subscribe_store.caller_openid() or subscribe_store.get_openid(sid)
    if not openid:
        return jsonify({"success": False,
                        "message": "未获取到 openid(需在小程序内触发)"}), 400
    if subscribe_store.quota(sid, "exam") <= 0:
        return jsonify({"success": False, "message": "没有可用订阅额度, 请先授权"}), 400

    class _Sample:
        course_name = "样例课程"
        exam_date = "2026-10-08"
        exam_time = "09:00-11:00"
        location = "I-301"
        exam_type = "期末考试"

    exam = Exam.query.filter(Exam.student_id == sid).order_by(Exam.exam_date).first() or _Sample()
    res = mp.send_subscribe(openid, tpl, build_exam_data(exam, None))
    if res.get("ok"):
        subscribe_store.consume(sid, "exam")
    app.logger.info("[subscribe] rid=%s 样例发送 sid=%s ok=%s errcode=%s",
                    _rid(), sid, res.get("ok"), res.get("errcode"))
    return jsonify({"success": bool(res.get("ok")), "result": res})
