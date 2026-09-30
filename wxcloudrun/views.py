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
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from collections import defaultdict
from contextlib import contextmanager
from io import BytesIO
from typing import Optional, Tuple
from flask import render_template, request, jsonify, Response, g, send_file, redirect
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


# 教务连通性探测的后台刷新状态(必须在 _check_network 之前定义:
# 否则万一在模块导入期就被调用, 会 NameError)
_network_refreshing = {"on": False}
_network_lock = threading.Lock()


def _check_network() -> Tuple[bool, str]:
    """教务连通性: 只读缓存, 过期交给后台线程刷新 —— 绝不在请求路径里阻塞。

    之前是同步探测(timeout=5, TTL=30s), 探测失败时每个请求都要等 5~10s,
    表现为 /api/status 偶发 10s; 现在请求永远毫秒返回上次结果。
    """
    now = time.time()
    age = now - _network_cache["ts"]
    if age >= NETWORK_CACHE_TTL and not _network_refreshing["on"]:
        with _network_lock:
            if not _network_refreshing["on"]:
                _network_refreshing["on"] = True
                threading.Thread(target=_refresh_network_cache, daemon=True).start()
    if _network_cache["ts"] <= 0:
        # 首次启动还没探测过: 返回"暂不可知", 由前端容错(不阻塞)
        return False, ""
    return _network_cache["ok"], ""


def _refresh_network_cache():
    """后台探测教务连通性(短超时), 结果写入缓存供请求直接读取"""
    try:
        try:
            probe = JWCClient()
            ok, _msg = probe.test_connection(timeout=3)
        except Exception:
            ok = False
        _network_cache["ok"] = ok
        _network_cache["ts"] = time.time()
    finally:
        # 必须放 finally: 中途抛异常也要把标记放掉, 否则后台刷新会被永久禁用
        _network_refreshing["on"] = False


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
    # 公开网页端已下线: 根路径直接进管理控制面板(管理员登录后使用)
    return redirect('/admin')


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
    if _rate_limited('fontjson:' + _client_ip(), 5, 60):
        return jsonify({'error': 'too many requests'}), 429
    resp = jsonify({'format': 'woff2', 'encoding': 'base64', 'data': _font_b64()})
    return resp


# 按需子集: 字体里大部分字用不到, 只把"该用户课程文本"涉及的字发给前端,
# 体积从 966KB 降到几十 KB, 也不用配 downloadFile 白名单(callContainer 能直接收 JSON)。
_RATE_BUCKETS = {}
_RATE_LOCK = threading.Lock()


def _rate_limited(key: str, limit: int, window: float = 60.0) -> bool:
    """简易滑动窗口限流(进程内): 返回 True 表示超限。

    单实例部署下够用; 以后要多实例, 换成 Redis 计数即可。
    """
    now = time.time()
    with _RATE_LOCK:
        hits = [t for t in _RATE_BUCKETS.get(key, []) if now - t < window]
        if len(hits) >= limit:
            _RATE_BUCKETS[key] = hits
            return True
        hits.append(now)
        _RATE_BUCKETS[key] = hits
        if len(_RATE_BUCKETS) > 5000:            # 防止字典无限增长
            _RATE_BUCKETS.clear()
    return False


def _rate_over(key: str, limit: int, window: float = 60.0) -> bool:
    """只检查是否超限, 不计数(计数交给 _rate_hit)"""
    now = time.time()
    with _RATE_LOCK:
        hits = [t for t in _RATE_BUCKETS.get(key, []) if now - t < window]
        _RATE_BUCKETS[key] = hits
        return len(hits) >= limit


def _rate_hit(key: str) -> None:
    with _RATE_LOCK:
        _RATE_BUCKETS.setdefault(key, []).append(time.time())


def _rate_clear(key: str) -> None:
    with _RATE_LOCK:
        _RATE_BUCKETS.pop(key, None)


def _client_ip() -> str:
    return (request.headers.get('X-Forwarded-For') or request.remote_addr or '-').split(',')[0].strip()


def _LOGIN_FAIL_KEY(student_id: str, ip: str) -> str:
    return 'loginfail:%s:%s' % (student_id or '-', ip)


@app.after_request
def _count_login_failure(resp):
    """登录接口: 成功清零计数, 失败累加 —— 实现"只统计失败次数"的节流。"""
    try:
        if request.path == '/api/login-webvpn' and request.method == 'POST':
            body = request.get_json(silent=True) or {}
            sid = (body.get('student_id') or '').strip()
            key = _LOGIN_FAIL_KEY(sid, _client_ip())
            if resp.status_code == 200:
                _rate_clear(key)
            else:
                _rate_hit(key)
    except Exception:
        pass
    return resp


_SUBSET_CACHE = {}        # key -> (chars_set, base64)
_SUBSET_BUILDING = set()  # 正在后台生成的 key
_SUBSET_LOCK = threading.Lock()
_SUBSET_CACHE_MAX = 6


def _build_subset_now(chars: str) -> str:
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
    return base64.b64encode(buf.getvalue()).decode('ascii')


_SUBSET_MAX_BUILDING = 2      # 同时最多两个生成任务, 避免请求量大时堆一堆子进程
_SUBSET_TOOL = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'font_subset_tool.py')


def _start_subset_build(key: str, chars: str, font_key: str = 'pixel'):
    """后台生成子集。

    生成器放在**独立子进程**里跑: 子集生成是纯 CPU 活, 放在 Flask 进程里会持有 GIL,
    把 /api/status 这类轻接口一起拖慢(这正是之前 10s 的来源之一)。
    """
    with _SUBSET_LOCK:
        if key in _SUBSET_BUILDING or key in _SUBSET_CACHE:
            return
        if len(_SUBSET_BUILDING) >= _SUBSET_MAX_BUILDING:
            return                                    # 闸门: 超出就等下次请求再排
        _SUBSET_BUILDING.add(key)

    def _work():
        tmp_dir = tempfile.mkdtemp(prefix='fontsubset-')
        chars_file = os.path.join(tmp_dir, 'chars.txt')
        out_file = os.path.join(tmp_dir, 'subset.woff')
        try:
            with open(chars_file, 'w', encoding='utf-8') as f:
                f.write(chars)
            proc = subprocess.run(
                # 直接当脚本执行: 用 -m 会先导入 wxcloudrun 包, 触发数据库初始化
                [sys.executable, _SUBSET_TOOL, chars_file, out_file, font_key],
                capture_output=True, timeout=120)
            if proc.returncode != 0:
                raise RuntimeError((proc.stderr or b'').decode('utf-8', 'replace')[:200])
            with open(out_file + '.b64', encoding='ascii') as f:
                data = f.read()
            with _SUBSET_LOCK:
                if len(_SUBSET_CACHE) >= _SUBSET_CACHE_MAX:
                    _SUBSET_CACHE.clear()
                _SUBSET_CACHE[key] = (set(chars), data)
        except Exception as exc:                      # 字体/依赖/超时都不该影响接口可用性
            app.logger.warning("[font] 子集生成失败: %s", exc)
        finally:
            with _SUBSET_LOCK:
                _SUBSET_BUILDING.discard(key)
            shutil.rmtree(tmp_dir, ignore_errors=True)

    threading.Thread(target=_work, daemon=True).start()


def _pick_subset(need: set):
    """返回 (base64, 是否只是近似结果)"""
    with _SUBSET_LOCK:
        items = list(_SUBSET_CACHE.items())
    best = None
    for _key, (chars_set, data) in items:
        if need <= chars_set:
            return data, False
        score = len(need & chars_set)
        if best is None or score > best[0]:
            best = (score, data)
    return (best[1], True) if best else (None, True)


@app.route('/api/font/subset', methods=['POST'])
def font_subset():
    """body: {text: "该用户课程名/教师/教室拼接", font?: "pixel|wenkai|smiley"} → 子集字体(base64)"""
    if not os.path.exists(FONT_FILE):
        return jsonify({'error': 'font not found'}), 404
    # 生成子集是 CPU 活, 必须限流, 否则可被反复调用吃满 CPU
    if _rate_limited('fontsubset:' + _client_ip(), 10, 60):
        return jsonify({'error': 'too many requests'}), 429
    payload = request.get_json(silent=True) or {}
    text = payload.get('text') or ''
    font_key = str(payload.get('font') or 'pixel')
    if not re.fullmatch(r'[a-z0-9_-]{1,16}', font_key):
        return jsonify({'error': 'bad font'}), 400
    if not isinstance(text, str) or not text.strip():
        return jsonify({'error': 'no text'}), 400
    chars = ''.join(sorted(set(text)))[:3000]
    key = hashlib.md5((font_key + '|' + chars).encode('utf-8')).hexdigest()
    data, partial = _pick_subset(set(chars))
    if not partial:
        body = {'format': 'woff', 'encoding': 'base64', 'chars': len(chars), 'data': data}
    else:
        # 还没有覆盖这份文本的子集: 后台去生成, 本次先给上一份可用的(前端会自行重试)
        _start_subset_build(key, chars, font_key)
        if data is None:
            return jsonify({'pending': True, 'message': 'subset building'}), 202
        body = {'format': 'woff', 'encoding': 'base64', 'chars': len(chars),
                'partial': True, 'data': data}
    resp = jsonify(body)
    return resp


@app.route('/api/font/list')
def font_list():
    """可用字体档位(pixel 内联在客户端, 这里列出需要下载的)"""
    fonts = [{'key': 'pixel', 'name': '像素点阵', 'builtin': True}]
    for key, name in (('wenkai', '霞鹜文楷'), ('smiley', '得意黑')):
        for ext in ('.woff2', '.ttf', '.otf'):
            if os.path.exists(os.path.join(os.path.dirname(FONT_FILE), key + ext)):
                fonts.append({'key': key, 'name': name, 'builtin': False})
                break
    resp = jsonify({'success': True, 'fonts': fonts})
    return resp


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
    return jsonify({"error": "页面不存在", "rid": _rid()}), 404


@app.errorhandler(500)
def server_error(e):
    # 记录完整堆栈, 便于线上排障(云托管采集 stdout 日志)
    app.logger.error("[500] rid=%s %s %s: %s", _rid(), request.method, request.path, e, exc_info=True)
    # 回给前端的只有通用文案 + rid: 用户报障时能直接对上日志, 又不泄露内部细节
    return jsonify({"error": "服务器内部错误", "rid": _rid()}), 500


# 空教室定时预热: 由服务入口 run.py 启动(默认开启, FREE_CLASSROOM_PREWARM=0 关闭)。
# 不在这里启动: 导入应用即起线程会让测试/工具进程也拉起预热并占住数据库连接。
