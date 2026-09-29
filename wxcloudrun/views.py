"""
课表助手 — Flask 路由
=======================
包含：页面路由 + 全量 API（多用户）+ 评教网关
"""
import base64
import hashlib
import os
import re
import secrets
import threading
import time
import uuid
from collections import defaultdict
from contextlib import contextmanager
from io import BytesIO
from typing import Optional, Tuple
from flask import render_template, request, jsonify, Response, g, send_file
from bs4 import BeautifulSoup

from wxcloudrun import app
from wxcloudrun.jwc_client import JWCClient, CLASSROOM_SLOTS
from wxcloudrun import dao
import config

# ============================================================
# 基础设施已拆分到 wxcloudrun/core/ (Phase 1 重构)
# 此处显式 re-export, 保持 views.<name> 旧引用(测试/其它模块)可用
# ============================================================
from wxcloudrun.core.cache import (  # noqa: E402
    QUERY_CACHE_TTL, _cache_get, _cache_set, invalidate_user_cache)
from wxcloudrun.core.sessions import (  # noqa: E402
    TOKEN_HEADER, JW_MAX_CONCURRENT, SESSION_TTL, MAX_SESSIONS, CAPTCHA_TTL,
    _sessions, _captcha_clients, _sessions_lock, _prune_captcha_locked,
    _prune_sessions_locked, _new_captcha_client, _pop_captcha_client,
    QR_TTL, _qr_clients, _new_qr_client, _get_qr_client, _pop_qr_client,
    _register_session, _get_session_client, _logout_session, _sid_by_token)
from wxcloudrun.core.pool import (  # noqa: E402
    _jw_semaphore, _jwc_request, _jwc_request_priority)
from wxcloudrun.core.web import (  # noqa: E402
    SLOW_MS, _rid, register_request_logging)

# 全局教务客户端：仅用于学期计算等无状态工具方法（不参与业务会话）
jwc_client = JWCClient()

# 请求级日志(before_request/after_request)
register_request_logging(app)

# 图鉴路由蓝图(Phase 1b 拆分)
from wxcloudrun.api.gallery import gallery_bp  # noqa: E402
from wxcloudrun.core.media import _sniff_image_mime  # noqa: E402

app.register_blueprint(gallery_bp)


# 教务连通性探测缓存（导航栏/设置页高频调用，30 秒内复用结果）
_network_cache = {"ts": 0.0, "ok": False}
NETWORK_CACHE_TTL = 30


def _check_network() -> Tuple[bool, str]:
    now = time.time()
    if now - _network_cache["ts"] < NETWORK_CACHE_TTL:
        return _network_cache["ok"], ""
    probe = JWCClient()
    try:
        # 短超时探测: 教务无响应时快速判离线, 不让 /api/status 被拖慢
        ok, msg = probe.test_connection(timeout=5)
    except Exception:
        ok, msg = False, ""
    _network_cache["ts"] = now
    _network_cache["ok"] = ok
    return ok, msg


def _current_semester() -> str:
    return jwc_client._current_semester()


# 北京时间工具已下沉到 core/timeutil.py(Phase 1b)
from wxcloudrun.core.timeutil import _beijing_now, _beijing_date  # noqa: E402


EVAL_HEADERS = {
    "Referer": "http://202.119.81.112:9080/njlgdx/xspj/xspj_find.do",
    "Host": "202.119.81.112:9080",
    "Origin": "http://202.119.81.112:9080",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9",
    "Cache-Control": "max-age=0",
}


def _warm_eval_session(client: JWCClient):
    """评教请求前的教务页面预热（应对教务的 Referer 校验）。

    同一用户 60 秒内只预热一次：批量评教逐门提交时，
    每个请求此前都会多打一次预热请求，缓存后教务请求量减半。
    """
    now = time.time()
    if now - getattr(client, "_eval_warm_ts", 0.0) < 60:
        return
    client._eval_warm_ts = now
    client.session.get(
        "http://202.119.81.112:9080/njlgdx/xspj/xspj_find.do",
        headers={"Referer": "http://202.119.81.112:9080/njlgdx/framework/main.jsp"},
        timeout=10)


# ============================================================
# 页面路由
# ============================================================
@app.route('/')
def index():
    return render_template('index.html')


# ============================================================
# 像素字体: 前端按需拉取(冷僻字兜底), 微信会按 Cache-Control 缓存
# ============================================================
FONT_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static', 'fonts', 'pixel.woff2')

# base64 结果进程内缓存: 字体是静态文件, 没必要每次请求都读盘+编码(966KB→1.29MB)
_FONT_B64_CACHE = None


def _font_b64() -> str:
    global _FONT_B64_CACHE
    if _FONT_B64_CACHE is None:
        with open(FONT_FILE, 'rb') as f:
            _FONT_B64_CACHE = base64.b64encode(f.read()).decode('ascii')
    return _FONT_B64_CACHE


@app.route('/api/font/pixel')
def font_pixel():
    if not os.path.exists(FONT_FILE):
        return jsonify({'error': 'font not found'}), 404
    resp = send_file(FONT_FILE, mimetype='font/woff2', conditional=True)
    resp.headers['Cache-Control'] = 'public, max-age=604800'
    # 渲染层(WebView)拉字体是跨域请求, 必须显式放行, 否则报 CORS
    resp.headers['Access-Control-Allow-Origin'] = '*'
    return resp


@app.route('/api/font/pixel.json')
def font_pixel_json():
    """备用通道: 云托管 callContainer 只能收 JSON, 这里给 base64。
    仅当前端直连字体 URL 失败(域名未加白名单等)时才走这条路。"""
    if not os.path.exists(FONT_FILE):
        return jsonify({'error': 'font not found'}), 404
    resp = jsonify({'format': 'woff2', 'encoding': 'base64', 'data': _font_b64()})
    resp.headers['Access-Control-Allow-Origin'] = '*'
    return resp


# 按需子集: 字体里大部分字用不到, 只把"该用户课程文本"涉及的字发给前端,
# 体积从 966KB 降到几十 KB, 也不用配 downloadFile 白名单(callContainer 能直接收 JSON)。
_SUBSET_CACHE = {}
_SUBSET_CACHE_MAX = 40


def _subset_font_b64(chars: str) -> str:
    key = hashlib.md5(chars.encode('utf-8')).hexdigest()
    cached = _SUBSET_CACHE.get(key)
    if cached:
        return cached
    from fontTools import subset as ft_subset
    from fontTools.ttLib import TTFont

    font = TTFont(FONT_FILE)          # woff2 读取依赖 brotli(见 requirements.txt)
    opts = ft_subset.Options()
    opts.flavor = 'woff'
    opts.layout_features = ['*']
    subsetter = ft_subset.Subsetter(options=opts)
    subsetter.populate(text=chars)
    subsetter.subset(font)
    buf = BytesIO()
    font.save(buf)
    b64 = base64.b64encode(buf.getvalue()).decode('ascii')
    if len(_SUBSET_CACHE) >= _SUBSET_CACHE_MAX:
        _SUBSET_CACHE.clear()
    _SUBSET_CACHE[key] = b64
    return b64


@app.route('/api/font/subset', methods=['POST'])
def font_subset():
    """body: {text: "该用户课程名/教师/教室拼接"} → 子集字体(base64)"""
    if not os.path.exists(FONT_FILE):
        return jsonify({'error': 'font not found'}), 404
    payload = request.get_json(silent=True) or {}
    text = payload.get('text') or ''
    if not isinstance(text, str) or not text.strip():
        return jsonify({'error': 'no text'}), 400
    chars = ''.join(sorted(set(text)))[:3000]
    try:
        data = _subset_font_b64(chars)
    except Exception as exc:                      # 字体缺失/依赖缺失都不能影响接口可用性
        return jsonify({'error': f'subset failed: {exc}'}), 500
    resp = jsonify({'format': 'woff', 'encoding': 'base64', 'chars': len(chars), 'data': data})
    resp.headers['Access-Control-Allow-Origin'] = '*'
    return resp
    # 公开网页端已下线: 根路径进入管理控制面板(管理员登录后使用)
    return render_template('admin.html')


@app.route('/exams')
def exams_page():
    # 公开页面已下线: 统一进入管理控制面板
    return render_template('admin.html')


@app.route('/evaluations')
def evaluations_page():
    return render_template('admin.html')


@app.route('/grades')
def grades_page():
    return render_template('admin.html')


@app.route('/settings')
def settings_page():
    return render_template('admin.html')


@app.route('/gallery')
def gallery_page():
    return render_template('admin.html')


from wxcloudrun.api.proxy import proxy_bp  # noqa: E402
from wxcloudrun.api.status import status_bp  # noqa: E402

app.register_blueprint(proxy_bp)
app.register_blueprint(status_bp)

from wxcloudrun.api.feedback import feedback_bp  # noqa: E402
from wxcloudrun.api.auth import auth_bp  # noqa: E402
from wxcloudrun.api.schedule import schedule_bp  # noqa: E402
from wxcloudrun.api.freeclass import (  # noqa: E402
    freeclass_bp, FREE_CLASSROOM_CAMPUSES, _current_teaching_week,
    _service_free_classrooms, _freeclass_cache_key, _freeclass_resp,
    freeclass_refresh_plan, _next_freeclass_refresh, _freeclass_ttl,
    _prewarm_targets, _prewarm_free_classrooms, _start_freeclass_prewarm)

app.register_blueprint(feedback_bp)
app.register_blueprint(auth_bp)
app.register_blueprint(schedule_bp)
app.register_blueprint(freeclass_bp)


from wxcloudrun.api.settings import settings_bp  # noqa: E402

app.register_blueprint(settings_bp)


from wxcloudrun.api.eval import (  # noqa: E402
    eval_bp, _build_ordered_eval_post_data, _parse_eval_courses_page,
    _parse_eval_form_page)

app.register_blueprint(eval_bp)


from wxcloudrun.api.grades import grades_bp  # noqa: E402

app.register_blueprint(grades_bp)


@app.errorhandler(404)
def not_found(e):
    return jsonify({"error": "页面不存在"}), 404


@app.errorhandler(500)
def server_error(e):
    # 记录完整堆栈, 便于线上排障(云托管采集 stdout 日志)
    app.logger.error("[500] rid=%s %s %s: %s", _rid(), request.method, request.path, e, exc_info=True)
    return jsonify({"error": "服务器内部错误"}), 500


# 空教室定时预热: 由服务入口 run.py 启动(默认开启, FREE_CLASSROOM_PREWARM=0 关闭)。
# 不在这里启动: 导入应用即起线程会让测试/工具进程也拉起预热并占住数据库连接。
