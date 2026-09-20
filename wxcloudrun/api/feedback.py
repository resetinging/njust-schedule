# -*- coding: utf-8 -*-
"""问题反馈与公告路由(Phase 1b 从 views.py 拆出)。"""
import time
import threading

from flask import Blueprint, jsonify, request

from wxcloudrun import app, dao
from wxcloudrun.core.auth import _require_login
from wxcloudrun.core.web import _rid

feedback_bp = Blueprint("feedback_api", __name__)


_CONTENT_BLOCK_WORDS = ["代考", "代做", "代写", "出售答案", "买答案", "刷课", "代刷",
                        "代课", "替考", "枪手", "作弊", "卖答案", "发答案", "有偿代", "包过"]
FEEDBACK_RATE_SEC = 10            # 每用户提交间隔(秒)
FEEDBACK_MAX_LEN = 500            # 单条反馈最大字数
_feedback_last_post = {}          # sid -> 上次提交时间戳(内存限流)
_feedback_rate_lock = threading.Lock()
_FEEDBACK_TYPES = ("suggest", "bug", "other")


@feedback_bp.route('/api/feedback', methods=['POST'])
def api_post_feedback():
    """提交问题反馈(需登录; 10 秒限流; 敏感词过滤; 不再收集联系方式)"""
    client, err = _require_login()
    if err:
        return err
    sid = client.student_id or ""
    data = request.get_json(silent=True) or {}
    fb_type = str(data.get("type", "other"))
    if fb_type not in _FEEDBACK_TYPES:
        fb_type = "other"
    content = str(data.get("content", "")).strip()
    if not content:
        return jsonify({"success": False, "message": "反馈内容不能为空"}), 400
    if len(content) > FEEDBACK_MAX_LEN:
        return jsonify({"success": False, "message": f"内容不能超过 {FEEDBACK_MAX_LEN} 字"}), 400
    for w in _CONTENT_BLOCK_WORDS:
        if w in content:
            return jsonify({"success": False, "message": "内容包含敏感词，请修改"}), 400
    # 限流: 每用户 10 秒 1 条, 避免重复提交
    with _feedback_rate_lock:
        last = _feedback_last_post.get(sid, 0)
        if time.time() - last < FEEDBACK_RATE_SEC:
            remain = max(1, int(FEEDBACK_RATE_SEC - (time.time() - last)))
            return jsonify({"success": False, "message": f"提交太频繁，请 {remain} 秒后再试"}), 429
        _feedback_last_post[sid] = time.time()
    name = client.student_name or dao.get_user_setting(sid, "name", "")
    fb = dao.save_feedback(sid, name, fb_type, content)
    app.logger.info("[feedback] rid=%s 反馈 sid=%s type=%s len=%d", _rid(), sid, fb_type, len(content))
    return jsonify({"success": True, "message": "反馈已提交，可在「我的反馈」查看回复", "fb": fb})


@feedback_bp.route('/api/my-feedback')
def api_my_feedback():
    """我的反馈列表(倒序, 含管理员回复) + 未读回复数(小程序小红点)"""
    client, err = _require_login()
    if err:
        return err
    sid = client.student_id or ""
    items = dao.list_feedback_by_user(sid, limit=50)
    return jsonify({
        "success": True,
        "feedback": items,
        "unread": dao.count_unread_replies(sid),
    })


@feedback_bp.route('/api/my-feedback/read', methods=['POST'])
def api_my_feedback_read():
    """标记回复已读(用户打开「我的反馈」时调用, 清除小红点)"""
    client, err = _require_login()
    if err:
        return err
    marked = dao.mark_replies_read(client.student_id or "")
    return jsonify({"success": True, "marked": marked})


# ============================================================
# API — 公告（公开, 无需登录; 控制面板设置）
# ============================================================
@feedback_bp.route('/api/announcement')
def api_announcement():
    """小程序公告: 返回文本/开关/更新时间(公开接口, 未登录可读)。

    updated 为管理端保存时间字符串, 小程序端以"updated != 本地已读标记"
    判断是否有新公告 → 主页面顶部横幅仅在更新后展示, 查看后隐藏。
    """
    text = dao.get_setting("announcement_text", "")
    enabled = dao.get_setting("announcement_enabled", "1") == "1"
    updated = dao.get_setting("announcement_updated", "")
    return jsonify({
        "success": True,
        "enabled": enabled and bool(text.strip()),
        "text": text.strip(),
        "updated": updated,
    })


# ============================================================
# API — 登录（多用户：登录成功后签发 token）
# ============================================================
# 本服务仅支持手动登录：登录密码只用于本次登录流程，
# 不加密保存到数据库（无任何自动登录机制，保存密码无意义）。

