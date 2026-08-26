"""
NJUST 课表 — Flask 路由
=======================
包含：页面路由 + 全量 API + 批量评教后台
"""
import base64
import os
import re
import secrets
import threading
import time
from datetime import datetime
from flask import render_template, request, jsonify, Response
from bs4 import BeautifulSoup
from itsdangerous import BadSignature, URLSafeTimedSerializer

from wxcloudrun import app, db
from wxcloudrun.jwc_client import JWCClient
from wxcloudrun import dao

# ============================================================
# 全局教务客户端
# ============================================================
jwc_client = JWCClient()
jwc_lock = threading.Lock()

_auto_login_attempted = False
_last_auto_login_time = 0.0

# 自动登录开关：默认关闭（无账号模式）。
#   关闭时：任何人打开页面都是未登录状态，后端不会用数据库里保存的
#   凭证自动登录教务；用户必须在设置页手动输入学号/密码/验证码登录。
#   设环境变量 AUTO_LOGIN_ENABLED=True 可恢复旧行为。
AUTO_LOGIN_ENABLED = os.environ.get("AUTO_LOGIN_ENABLED", "False") == "True"

EVAL_HEADERS = {
    "Referer": "http://202.119.81.112:9080/njlgdx/xspj/xspj_find.do",
    "Host": "202.119.81.112:9080",
    "Origin": "http://202.119.81.112:9080",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9",
    "Cache-Control": "max-age=0",
}


def _warm_eval_session():
    jwc_client.session.get(
        "http://202.119.81.112:9080/njlgdx/xspj/xspj_find.do",
        headers={"Referer": "http://202.119.81.112:9080/njlgdx/framework/main.jsp"},
        timeout=10)


# ============================================================
# 页面路由
# ============================================================
@app.route('/')
def index():
    first_week_date = dao.get_setting("first_week_date", "")
    return render_template('index.html', first_week_date=first_week_date)


@app.route('/exams')
def exams_page():
    return render_template('exams.html')


@app.route('/evaluations')
def evaluations_page():
    return render_template('evaluations.html')


@app.route('/grades')
def grades_page():
    return render_template('grades.html')


@app.route('/settings')
def settings_page():
    return render_template('settings.html')


@app.route('/gallery')
def gallery_page():
    return render_template('gallery.html')


@app.route('/proxy/jw/<path:target_path>', methods=['GET', 'POST'])
def proxy_jw(target_path):
    if not jwc_client.logged_in:
        return "请先登录教务系统", 401
    target_url = f"http://202.119.81.112:9080/njlgdx/{target_path}"
    qs = request.query_string.decode()
    if qs:
        target_url += "?" + qs
    try:
        if request.method == 'POST':
            resp = jwc_client.session.post(target_url, data=request.form,
                                           headers=EVAL_HEADERS, timeout=15)
        else:
            _warm_eval_session()
            resp = jwc_client.session.get(target_url, headers=EVAL_HEADERS, timeout=15)
    except Exception as e:
        return f"代理请求失败: {e}", 502
    if "text/html" in (resp.headers.get("content-type") or ""):
        content = resp.text
        if "非法访问" in content or "非法操作" in content:
            return Response(f"""
                <html><body style="padding:40px;text-align:center;font-family:sans-serif;">
                <h2>⚠️ 教务系统拒绝了请求</h2><p>{target_path}</p>
                <p><a href="/evaluations">返回评价列表</a></p>
                <p><a href="/settings">重新登录教务系统</a></p>
                </body></html>
            """, status=403)
        for old, new in [
            ('src="/njlgdx/', 'src="/proxy/jw/'),
            ('href="/njlgdx/', 'href="/proxy/jw/'),
            ("src='/njlgdx/", "src='/proxy/jw/"),
            ("href='/njlgdx/", "href='/proxy/jw/"),
            ('action="/njlgdx/', 'action="/proxy/jw/'),
            ("action='/njlgdx/", "action='/proxy/jw/"),
            ('"/njlgdx/js/', '"/proxy/jw/js/'),
            ("'/njlgdx/js/", "'/proxy/jw/js/"),
        ]:
            content = content.replace(old, new)
        return Response(content, status=resp.status_code,
                        content_type="text/html; charset=utf-8")
    return Response(resp.content, status=resp.status_code,
                    content_type=resp.headers.get("content-type", "text/html"))


# ============================================================
# API — 状态 / 连接测试
# ============================================================
@app.route('/api/status')
def api_status():
    # 无账号模式：登录态只取决于当前进程内的教务会话（jwc_client），
    # 不读取数据库里保存的账号，也绝不在这里触发自动登录。
    logged_in = bool(jwc_client.logged_in)
    student_id = jwc_client.student_id if logged_in else ""
    student_name = jwc_client.student_name if logged_in else ""
    semester = dao.get_setting("semester", jwc_client._current_semester())

    has_courses = False
    has_exams = False
    if logged_in and semester:
        has_courses = dao.count_courses(semester) > 0
        has_exams = dao.count_exams(semester) > 0

    # 教务连通性(桌面端导航栏/设置页依赖)
    try:
        ok, _msg = jwc_client.test_connection()
        network = {
            "reachable": ok,
            "method": "direct" if ok else "offline",
            "latency_ms": 0,
            "label": "教务在线" if ok else "离线",
            "hint": "" if ok else "请检查教务系统连接",
        }
    except Exception:
        network = {"reachable": False, "method": "offline", "latency_ms": 0,
                   "label": "离线", "hint": "请检查教务系统连接"}

    return jsonify({
        "logged_in": logged_in,
        "student_id": student_id,
        "student_name": student_name,
        "semester": semester or jwc_client._current_semester(),
        "has_courses": has_courses,
        "has_exams": has_exams,
        "login_method": jwc_client.login_method if logged_in else "",
        "auto_login_attempted": False,
        "auto_login_error": "",
        "server_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "first_week_date": dao.get_setting("first_week_date", ""),
        "network": network,
    })


@app.route('/api/connect-test')
def api_connect_test():
    ok, msg = jwc_client.test_connection()
    return jsonify({"ok": ok, "message": msg})


# ============================================================
# API — 登录
# ============================================================
# 教务密码加密存储（不再使用可逆 Base64 明文）:
#   - 优先使用环境变量 PASSWORD_SECRET 作为密钥（生产环境推荐配置）
#   - 未配置时，首次使用自动生成随机密钥并存入 settings 表（key: secret_key）
#   - 解密失败时回退尝试旧版 Base64 编码，兼容历史数据
_PWD_SALT = "jwc-pwd-v1"


def _get_pwd_secret() -> str:
    key = (os.environ.get("PASSWORD_SECRET") or "").strip()
    if key:
        return key
    key = dao.get_setting("secret_key", "")
    if not key:
        key = secrets.token_hex(32)
        dao.set_setting("secret_key", key)
    return key


def _encode_pwd(pwd: str) -> str:
    return URLSafeTimedSerializer(_get_pwd_secret(), salt=_PWD_SALT).dumps(pwd)


def _decode_pwd(encoded: str) -> str:
    if not encoded:
        return ""
    try:
        return URLSafeTimedSerializer(_get_pwd_secret(), salt=_PWD_SALT).loads(encoded)
    except BadSignature:
        pass
    # 兼容旧版 Base64 存储
    try:
        return base64.b64decode(encoded.encode()).decode()
    except Exception:
        return ""


def _resolve_password(student_id: str, provided: str) -> str:
    """解析登录密码。

    无账号模式：登录必须显式提供密码，不再回退到数据库里保存的凭证
    （避免"空密码登录"隐式使用他人保存的账号密码）。
    """
    return provided or ""


def _auto_login() -> bool:
    """用数据库保存的凭证自动登录教务。

    仅当 AUTO_LOGIN_ENABLED=True 时生效（默认无账号模式，直接失败）。
    """
    if not AUTO_LOGIN_ENABLED:
        jwc_client.last_error = "自动登录已关闭，请手动登录"
        return False
    global _auto_login_attempted, _last_auto_login_time
    _auto_login_attempted = True
    _last_auto_login_time = time.time()
    # 检查 Session 是否真实有效（而非仅信任 logged_in 标志位）
    if jwc_client.logged_in and jwc_client.is_session_valid():
        return True
    # Session 已过期或未登录 → 强制重新登录
    jwc_client.logged_in = False
    sid = dao.get_setting("student_id")
    pwd = _decode_pwd(dao.get_setting("jwc_password_enc", "")) or \
        _decode_pwd(dao.get_setting("password_enc", ""))
    if not sid or not pwd:
        return False
    jwc_client.login(sid, pwd)
    return jwc_client.logged_in


def _on_login_success(student_id: str, password: str = ""):
    dao.set_setting("student_id", student_id)
    if password:
        dao.set_setting("password_enc", _encode_pwd(password))
    if jwc_client.student_name:
        dao.set_setting("student_name", jwc_client.student_name)
    semester = dao.get_setting("semester")
    if not semester:
        semester = jwc_client._current_semester()
        dao.set_setting("semester", semester)
    return jsonify({
        "success": True,
        "message": f"登录成功！欢迎 {jwc_client.student_name or student_id}",
        "student_name": jwc_client.student_name or student_id,
        "semester": semester,
        "login_method": jwc_client.login_method,
    })


def _sniff_image_mime(data: bytes) -> str:
    """根据文件头识别验证码图片类型,前端据此构造 data URL"""
    if data.startswith(b"\x89PNG"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith(b"GIF87a") or data.startswith(b"GIF89a"):
        return "image/gif"
    if data.startswith(b"BM"):
        return "image/bmp"
    return "image/png"


@app.route('/api/get-captcha')
def api_get_captcha():
    with jwc_lock:
        b64, error = jwc_client.get_captcha_base64()
    if error or not b64:
        return jsonify({
            "success": False,
            "message": error or "获取验证码失败",
        }), 500
    return jsonify({
        "success": True,
        "captcha_b64": b64,
        "captcha_mime": _sniff_image_mime(base64.b64decode(b64)),
        "message": "验证码获取成功",
    })


@app.route('/api/login', methods=['POST'])
def api_login():
    data = request.get_json()
    student_id = (data.get("student_id") or "").strip()
    password = _resolve_password(student_id, data.get("password") or "")
    if not student_id or not password:
        return jsonify({"success": False, "message": "学号和密码不能为空"}), 400
    with jwc_lock:
        success = jwc_client.login(student_id, password)
    if success:
        return _on_login_success(student_id, password)
    else:
        return jsonify({
            "success": False,
            "message": jwc_client.last_error or "登录失败",
            "need_captcha": "验证码" in (jwc_client.last_error or ""),
        }), 401


@app.route('/api/login-manual', methods=['POST'])
def api_login_manual():
    data = request.get_json()
    student_id = (data.get("student_id") or "").strip()
    password = _resolve_password(student_id, data.get("password") or "")
    captcha_text = (data.get("captcha") or "").strip()
    if not student_id or not password:
        return jsonify({"success": False, "message": "学号和密码不能为空"}), 400
    if not captcha_text:
        return jsonify({"success": False, "message": "请先输入验证码"}), 400
    with jwc_lock:
        success = jwc_client.login_with_manual_captcha(student_id, password, captcha_text)
    if success:
        return _on_login_success(student_id, password)
    else:
        return jsonify({
            "success": False,
            "message": jwc_client.last_error or "登录失败",
        }), 401


# ============================================================
# API — 智慧理工 SSO 登录（校外/备用方式）
# ============================================================
@app.route('/api/get-webvpn-captcha', methods=['POST'])
def api_get_webvpn_captcha():
    """Step 1: 智慧理工 SSO 登录 → 获取教务验证码（或发现已有教务会话）"""
    data = request.get_json()
    student_id = (data.get("student_id") or "").strip()
    password = _resolve_password(student_id, data.get("password") or "")

    if not student_id or not password:
        return jsonify({"success": False, "message": "学号和密码不能为空"}), 400

    with jwc_lock:
        b64, error = jwc_client.get_webvpn_captcha_base64(student_id, password)

    if b64 == "__ALREADY_LOGGED_IN__":
        # SSO 后已有教务会话，无需再输验证码
        dao.set_setting("password_enc", _encode_pwd(password))
        jwc_client.logged_in = True
        jwc_client.login_method = "webvpn"
        return jsonify({
            "success": True,
            "already_logged_in": True,
            "message": "已有教务会话，无需重复登录",
        })

    if error:
        return jsonify({
            "success": False,
            "message": error,
            "debug_log": jwc_client.debug_log[-20:],
        }), 500

    # 验证码获取成功说明 SSO 登录成功，保存智慧理工密码
    dao.set_setting("password_enc", _encode_pwd(password))
    return jsonify({
        "success": True,
        "captcha_b64": b64,
        "captcha_mime": _sniff_image_mime(base64.b64decode(b64)),
        "message": "智慧理工登录成功，请输入教务密码和验证码",
    })


@app.route('/api/login-webvpn-manual', methods=['POST'])
def api_login_webvpn_manual():
    """Step 2: 使用手动输入的验证码完成教务登录（智慧理工模式）"""
    data = request.get_json()
    student_id = (data.get("student_id") or "").strip()
    password = _resolve_password(student_id, data.get("password") or "")
    captcha_text = (data.get("captcha") or "").strip()

    if not student_id or not password:
        return jsonify({"success": False, "message": "学号和密码不能为空"}), 400
    if not captcha_text:
        return jsonify({"success": False, "message": "请先获取验证码并输入"}), 400

    with jwc_lock:
        success = jwc_client.complete_webvpn_login(student_id, password, captcha_text)

    if success:
        # 教务密码与智慧理工密码分开存储
        jwc_password = data.get("jwc_password") or password
        if jwc_password:
            dao.set_setting("jwc_password_enc", _encode_pwd(jwc_password))
        return _on_login_success(student_id, password)
    else:
        return jsonify({
            "success": False,
            "message": jwc_client.last_error or "登录失败，请检查验证码",
        }), 401


@app.route('/api/login-webvpn', methods=['POST'])
def api_login_webvpn():
    """通过智慧理工 SSO 自动登录（含自动 OCR 教务验证码）"""
    data = request.get_json()
    student_id = (data.get("student_id") or "").strip()
    password = _resolve_password(student_id, data.get("password") or "")

    if not student_id or not password:
        return jsonify({"success": False, "message": "学号和密码不能为空"}), 400

    with jwc_lock:
        success = jwc_client.login_webvpn(student_id, password)

    if success:
        # 教务密码与智慧理工密码分开存储
        jwc_password = data.get("jwc_password") or password
        if jwc_password:
            dao.set_setting("jwc_password_enc", _encode_pwd(jwc_password))
        return _on_login_success(student_id, password)
    else:
        return jsonify({
            "success": False,
            "message": jwc_client.last_error or "智慧理工登录失败",
            "debug_log": jwc_client.debug_log[-20:],
        }), 401


# ============================================================
# API — 数据刷新
# ============================================================
def _require_login():
    if not jwc_client.logged_in or not jwc_client.is_session_valid():
        jwc_client.logged_in = False
        if not AUTO_LOGIN_ENABLED:
            return jsonify({
                "success": False,
                "message": "尚未登录，请先在设置页面登录",
            }), 401
        auto_ok = _auto_login()
        student_id = dao.get_setting("student_id")
        if not student_id:
            return jsonify({
                "success": False,
                "message": "尚未登录，请先在设置页面登录",
            }), 401
        if not auto_ok:
            err = jwc_client.last_error or "教务系统不可达"
            return jsonify({
                "success": False,
                "message": f"自动登录失败: {err}",
            }), 401
    return None


def _retry_with_relogin(fetch_func, error_msg: str):
    """执行数据获取，失败时仅在自动登录开启的情况下重新登录后重试一次。
    返回 (data, error_tuple)，成功时 error_tuple 为 None，
    失败时 data 为 []，error_tuple 为 (flask_response, status_code)。"""
    result = fetch_func()
    if result:
        return result, None
    # 失败 → 会话过期；无账号模式下不自动重登录，直接要求手动登录
    jwc_client.logged_in = False
    if not AUTO_LOGIN_ENABLED or not _auto_login():
        return [], (jsonify({
            "success": False,
            "message": f"{error_msg}: 会话已过期，请重新登录",
        }), 401)
    # 重试
    result = fetch_func()
    if result:
        return result, None
    return [], (jsonify({
        "success": False,
        "message": jwc_client.last_error or error_msg,
    }), 500)


@app.route('/api/refresh-schedule', methods=['POST'])
def api_refresh_schedule():
    semester = dao.get_setting("semester", jwc_client._current_semester())
    err = _require_login()
    if err:
        return err
    with jwc_lock:
        courses, retry_err = _retry_with_relogin(
            lambda: jwc_client.get_schedule(semester),
            "获取课表失败",
        )
    if retry_err:
        return retry_err
    dao.save_courses(courses, semester)
    dao.set_setting("semester", semester)
    return jsonify({
        "success": True,
        "message": f"成功获取 {len(courses)} 门课程",
        "count": len(courses),
        "semester": semester,
    })


@app.route('/api/refresh-exams', methods=['POST'])
def api_refresh_exams():
    semester = dao.get_setting("semester", jwc_client._current_semester())
    err = _require_login()
    if err:
        return err
    with jwc_lock:
        exams, retry_err = _retry_with_relogin(
            lambda: jwc_client.get_exams(semester),
            "获取考试失败",
        )
    if retry_err:
        return retry_err
    dao.save_exams(exams, semester)
    return jsonify({
        "success": True,
        "message": f"成功获取 {len(exams)} 场考试",
        "count": len(exams),
    })


@app.route('/api/refresh-all', methods=['POST'])
def api_refresh_all():
    semester = dao.get_setting("semester", jwc_client._current_semester())
    err = _require_login()
    if err:
        return err
    results = {"schedule": None, "exams": None}
    with jwc_lock:
        courses, sched_err = _retry_with_relogin(
            lambda: jwc_client.get_schedule(semester),
            "获取课表失败",
        )
        if not sched_err:
            dao.save_courses(courses, semester)
            results["schedule"] = {"count": len(courses), "ok": True}
        else:
            results["schedule"] = {"count": 0, "ok": False, "error": jwc_client.last_error}

        exams, exam_err = _retry_with_relogin(
            lambda: jwc_client.get_exams(semester),
            "获取考试失败",
        )
        if not exam_err:
            dao.save_exams(exams, semester)
            results["exams"] = {"count": len(exams), "ok": True}
        else:
            results["exams"] = {"count": 0, "ok": False, "error": jwc_client.last_error}

    dao.set_setting("semester", semester)
    return jsonify({
        "success": True,
        "semester": semester,
        "schedule": results["schedule"],
        "exams": results["exams"],
        "message": f"课表: {results['schedule']['count']}门, 考试: {results['exams']['count']}场",
    })


# ============================================================
# API — 数据查询
# ============================================================
def _dedupe_courses(courses: list) -> list:
    """去掉跨大节课程在 kbtable 每个大节格产生的重复条目。

    例: 第1-13节的课程设计在 kbtable 五个大节格各解析出一条完全相同
    的记录,前端网格会把它们全部堆进同一个单元格导致溢出。
    """
    seen = set()
    result = []
    for c in courses:
        key = (str(c.get("name", "")), c.get("day"), c.get("start"), c.get("end"),
               str(c.get("weeks", "")), str(c.get("teacher", "")),
               str(c.get("classroom", "")))
        if key in seen:
            continue
        seen.add(key)
        result.append(c)
    return result


@app.route('/api/courses')
def api_get_courses():
    err = _require_login()
    if err:
        return err
    semester = (request.args.get("semester") or "").strip() or \
        dao.get_setting("semester", jwc_client._current_semester())
    courses = _dedupe_courses(dao.get_courses(semester))
    return jsonify({
        "success": True,
        "semester": semester,
        "count": len(courses),
        "courses": courses,
    })


@app.route('/api/exams')
def api_get_exams():
    err = _require_login()
    if err:
        return err
    semester = (request.args.get("semester") or "").strip() or \
        dao.get_setting("semester", jwc_client._current_semester())
    exams = dao.get_exams(semester)
    return jsonify({
        "success": True,
        "semester": semester,
        "count": len(exams),
        "exams": exams,
    })


@app.route('/api/settings', methods=['GET', 'POST'])
def api_settings():
    if request.method == 'GET':
        # 无账号模式：未登录时不返回数据库里保存的账号与密码状态
        logged_in = bool(jwc_client.logged_in)
        settings = {
            "student_id": (jwc_client.student_id if logged_in else ""),
            "student_name": (jwc_client.student_name if logged_in else ""),
            "semester": dao.get_setting("semester"),
            "auto_refresh": dao.get_setting("auto_refresh", "false"),
            "refresh_interval": dao.get_setting("refresh_interval", "3600"),
            "first_week_date": dao.get_setting("first_week_date", ""),
            "semester_list": jwc_client.get_semester_list(),
            "current_semester": jwc_client._current_semester(),
            "has_password": bool(dao.get_setting("password_enc", "")) if logged_in else False,
            "has_jwc_password": bool(dao.get_setting("jwc_password_enc", "")) if logged_in else False,
        }
        return jsonify(settings)
    else:
        data = request.get_json()
        for key, value in data.items():
            if key in ("student_id", "student_name", "semester",
                       "auto_refresh", "refresh_interval", "first_week_date"):
                dao.set_setting(key, str(value))
        return jsonify({"success": True, "message": "设置已保存"})


@app.route('/api/gallery-images')
def api_gallery_images():
    """返回 static/gallery/ 目录下的图片列表"""
    gallery_dir = os.path.join(app.static_folder, 'gallery')
    images = []
    if os.path.isdir(gallery_dir):
        for f in sorted(os.listdir(gallery_dir)):
            if f.lower().endswith(('.png', '.jpg', '.jpeg', '.gif', '.webp', '.bmp')):
                images.append(f)
    return jsonify({"success": True, "images": images})


@app.route('/api/gallery-image')
def api_gallery_image():
    """返回单张校历图片的 base64 数据（供小程序通过云托管内网获取）"""
    name = (request.args.get("name") or "").strip()
    if not name or "/" in name or "\\" in name or ".." in name:
        return jsonify({"success": False, "message": "无效的文件名"}), 400
    gallery_dir = os.path.join(app.static_folder, 'gallery')
    path = os.path.join(gallery_dir, name)
    if not os.path.isfile(path):
        return jsonify({"success": False, "message": "图片不存在"}), 404
    with open(path, "rb") as f:
        data = f.read()
    return jsonify({
        "success": True,
        "name": name,
        "mime": _sniff_image_mime(data),
        "data_b64": base64.b64encode(data).decode(),
    })


@app.route('/api/semesters')
def api_get_semesters():
    """获取可用学期列表"""
    try:
        semesters = jwc_client.get_semester_list()
        current = jwc_client._current_semester()
        return jsonify({"success": True, "semesters": semesters, "current": current})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


@app.route('/api/semester', methods=['POST'])
def api_set_semester():
    data = request.get_json()
    semester = (data.get("semester") or "").strip()
    if not semester:
        return jsonify({"success": False, "message": "学期不能为空"}), 400
    dao.set_setting("semester", semester)
    return jsonify({"success": True, "message": f"已切换到学期: {semester}"})


@app.route('/api/evaluations')
def api_get_evaluations():
    err = _require_login()
    if err:
        return err
    semester = (request.args.get("semester") or "").strip() or \
        dao.get_setting("semester", jwc_client._current_semester())
    evals = dao.get_evaluations(semester)
    return jsonify({
        "success": True,
        "semester": semester,
        "count": len(evals),
        "evaluations": evals,
    })


@app.route('/api/refresh-evaluations', methods=['POST'])
def api_refresh_evaluations():
    semester = dao.get_setting("semester", jwc_client._current_semester())
    err = _require_login()
    if err:
        return err
    with jwc_lock:
        evals, retry_err = _retry_with_relogin(
            lambda: jwc_client.get_evaluations(semester),
            "获取评价数据失败",
        )
    if retry_err:
        return retry_err
    dao.save_evaluations(evals, semester)
    undone = sum(1 for e in evals if not e.get("is_done"))
    return jsonify({
        "success": True,
        "message": f"成功获取 {len(evals)} 条评价" + (f"，{undone} 条待完成" if undone > 0 else ""),
        "count": len(evals),
        "undone": undone,
    })


# ============================================================
# 评教 — 页面解析
# ============================================================
def _parse_eval_courses_page(html: str) -> dict:
    soup = BeautifulSoup(html, "lxml")
    title_el = soup.select_one(".Nsb_r_title")
    batch_title = title_el.get_text(strip=True) if title_el else "评教课程"
    form = soup.find("form", id="Form1")
    hidden_fields = {}
    if form:
        for inp in form.find_all("input", type="hidden"):
            name = inp.get("name", "")
            value = inp.get("value", "")
            if name:
                hidden_fields[name] = value
    courses = []
    data_table = soup.find("table", id="dataList")
    if data_table:
        for row in data_table.find_all("tr")[1:]:
            cells = row.find_all("td")
            if len(cells) < 8:
                continue
            eval_url = ""
            eval_link = cells[7].find("a")
            if eval_link:
                href = eval_link.get("href", "")
                m = re.search(r"openWindow\('([^']+)'", href)
                if m:
                    eval_url = m.group(1)
            courses.append({
                "seq": cells[0].get_text(strip=True),
                "code": cells[1].get_text(strip=True),
                "name": cells[2].get_text(strip=True),
                "teacher": cells[3].get_text(strip=True),
                "score": cells[4].get_text(strip=True),
                "evaluated": cells[5].get_text(strip=True) == "是",
                "submitted": cells[6].get_text(strip=True) == "是",
                "eval_url": eval_url,
            })
    return {"batch_title": batch_title, "courses": courses, "hidden_fields": hidden_fields}


def _parse_eval_form_page(html: str) -> dict:
    soup = BeautifulSoup(html, "lxml")
    th = soup.find("th", class_="Nsb_r_list_thb")
    course_info = th.get_text() if th else ""
    course_name = ""
    m = re.search(r'课程名称[：:]\s*(.+?)(?:\s{2,}|\xa0|$)', course_info)
    if m:
        course_name = m.group(1).strip()
    form = soup.find("form", id="Form1")
    hidden_fields = {}
    if form:
        for inp in form.find_all("input", type="hidden"):
            name = inp.get("name", "")
            value = inp.get("value", "")
            if name:
                hidden_fields[name] = value
    indicators = []
    for row in soup.select("#table1 tr"):
        tds = row.find_all("td")
        if len(tds) < 2:
            continue
        label = tds[0].get_text(strip=True)
        if not label or "评价指标" in label:
            continue
        seq_input = tds[0].find("input", attrs={"name": "pj06xh"})
        seq = seq_input.get("value", "") if seq_input else ""
        fz_map = {}
        for inp in tds[1].find_all("input", type="hidden"):
            fz_name = inp.get("name", "")
            fz_value = inp.get("value", "")
            if fz_name.startswith("pj0601fz_"):
                hidden_fields[fz_name] = fz_value
                parts = fz_name.rsplit("_", 1)
                if len(parts) == 2:
                    fz_map[parts[1]] = fz_value
        options = []
        for radio in tds[1].find_all("input", type="radio"):
            opt_name = radio.get("name", "")
            opt_value = radio.get("value", "")
            opt_score = fz_map.get(opt_value, "")
            opt_checked = radio.has_attr("checked")
            opt_label = ""
            sib = radio.next_sibling
            if sib:
                try:
                    txt = str(sib).strip()
                    if txt:
                        opt_label = txt
                except Exception:
                    pass
            if not opt_label:
                opt_label = radio.parent.get_text().strip() if radio.parent else ""
            options.append({
                "name": opt_name,
                "value": opt_value,
                "label": opt_label.strip(),
                "score": opt_score,
                "checked": opt_checked,
            })
        indicators.append({"seq": seq, "label": label, "options": options})
    form_action = form.get("action", "") if form else ""
    return {
        "course_name": course_name,
        "hidden_fields": hidden_fields,
        "indicators": indicators,
        "action": form_action,
    }


def _build_ordered_eval_post_data(form_data: dict, batch_hidden_fields=None,
                                  auto_fill_selections=None, submit_type: str = "1") -> list:
    merged = dict(form_data)
    if batch_hidden_fields:
        for k, v in batch_hidden_fields.items():
            if k not in merged:
                merged[k] = v
    if auto_fill_selections:
        for seq, val in auto_fill_selections.items():
            if seq == "_total":
                continue
            name, value = val
            merged[name] = value
    indicator_groups = {}
    form_level_pairs = []
    for k, v in merged.items():
        if k.startswith("pj0601fz_"):
            parts = k.split("_", 2)
            if len(parts) >= 2:
                seq = parts[1]
                indicator_groups.setdefault(seq, []).append((k, v))
                continue
        elif k.startswith("pj0601id_"):
            seq = k.replace("pj0601id_", "")
            indicator_groups.setdefault(seq, []).append((k, v))
            continue
        elif k == "pj06xh":
            continue
        else:
            form_level_pairs.append((k, v))
    sorted_seqs = sorted(indicator_groups.keys(), key=int)
    post_data = []
    head_keys = {"issubmit"}
    for k, v in form_level_pairs:
        if k not in head_keys:
            post_data.append((k, v))
    for seq in sorted_seqs:
        post_data.append(("pj06xh", seq))
        for k, v in indicator_groups[seq]:
            post_data.append((k, v))
    for k, v in form_level_pairs:
        if k in head_keys:
            post_data.append((k, v))
    return post_data


# ============================================================
# API — 评教操作
# ============================================================
@app.route('/api/eval-courses')
def api_eval_courses():
    url = request.args.get("url", "")
    if not url:
        return jsonify({"success": False, "message": "缺少 URL"}), 400
    if not jwc_client.logged_in:
        return jsonify({"success": False, "message": "请先登录"}), 401
    target = f"http://202.119.81.112:9080{url}" if url.startswith("/") else url
    try:
        _warm_eval_session()
        resp = jwc_client.session.get(target, headers=EVAL_HEADERS, timeout=15)
        if "非法访问" in resp.text or "非法操作" in resp.text:
            return jsonify({"success": False, "message": "教务系统拒绝了请求"}), 403
    except Exception as e:
        return jsonify({"success": False, "message": f"请求失败: {e}"}), 500
    parsed = _parse_eval_courses_page(resp.text)
    if not parsed or not parsed.get("courses"):
        return jsonify({"success": False, "message": "未找到课程列表"}), 500
    return jsonify({
        "success": True,
        "batch_title": parsed["batch_title"],
        "courses": parsed["courses"],
        "hidden_fields": parsed["hidden_fields"],
    })


@app.route('/api/eval-form')
def api_eval_form():
    url = request.args.get("url", "")
    if not url:
        return jsonify({"success": False, "message": "缺少评教 URL"}), 400
    if not jwc_client.logged_in:
        return jsonify({"success": False, "message": "请先登录"}), 401
    target = f"http://202.119.81.112:9080{url}" if url.startswith("/") else url
    try:
        _warm_eval_session()
        resp = jwc_client.session.get(target, headers=EVAL_HEADERS, timeout=15)
        if "非法访问" in resp.text or "非法操作" in resp.text:
            return jsonify({"success": False, "message": "教务系统拒绝了请求"}), 403
    except Exception as e:
        return jsonify({"success": False, "message": f"请求失败: {e}"}), 500
    parsed = _parse_eval_form_page(resp.text)
    if not parsed or (not parsed.get("course_name") and not parsed.get("indicators")):
        return jsonify({"success": False, "message": "未找到评价表单"}), 500
    return jsonify({
        "success": True,
        "course_name": parsed["course_name"],
        "hidden_fields": parsed["hidden_fields"],
        "indicators": parsed["indicators"],
        "action": parsed["action"],
    })


@app.route('/api/submit-eval', methods=['POST'])
def api_submit_eval():
    if not jwc_client.logged_in:
        return jsonify({"success": False, "message": "请先登录"}), 401
    data = request.get_json()
    form_data = data.get("form_data", {})
    submit_type = data.get("submit_type", "0")
    action_path = data.get("action", "/njlgdx/xspj/xspj_save.do")
    form_data["issubmit"] = submit_type
    target_url = f"http://202.119.81.112:9080{action_path}"
    try:
        _warm_eval_session()
        post_data = _build_ordered_eval_post_data(form_data, submit_type=submit_type)
        resp = jwc_client.session.post(target_url, data=post_data, headers=EVAL_HEADERS, timeout=15)
        if "评价成功" in resp.text or "提交成功" in resp.text or "保存成功" in resp.text:
            return jsonify({"success": True, "message": "评教提交成功！"})
        return jsonify({"success": True, "message": "已提交（请返回教务确认）"})
    except Exception as e:
        return jsonify({"success": False, "message": f"提交失败: {e}"}), 500


@app.route('/api/jw-proxy', methods=['POST'])
def api_jw_proxy():
    """通用教务网关: 用已登录会话转发任意 9080 请求,返回原始内容。

    方案 A(薄后端)核心接口: 前端负责业务逻辑,后端只做认证 + 转发。

    参数:
        method: "GET" | "POST"
        path: 教务路径,如 "/njlgdx/xskb/xskb_list.do?Ves632DSdyV=..."
              (query 可拼在 path 里,或单独传 query)
        data: POST 表单参数 {key: value}
    返回:
        success/status/content_type/text(文本) 或 data_b64(二进制)
    """
    err = _require_login()
    if err:
        return err
    data = request.get_json() or {}
    method = (data.get("method") or "GET").upper()
    path = (data.get("path") or "").strip()
    if not path:
        return jsonify({"success": False, "message": "缺少 path"}), 400
    if method not in ("GET", "POST"):
        return jsonify({"success": False, "message": "method 仅支持 GET/POST"}), 400
    if not path.startswith("/"):
        path = "/" + path

    target = f"http://202.119.81.112:9080{path}"
    qs = data.get("query")
    if qs and isinstance(qs, str):
        target += "?" + qs.lstrip("?")
    form_data = data.get("data") or {}
    if not isinstance(form_data, dict):
        form_data = {}

    try:
        with jwc_lock:
            _warm_eval_session()
            if method == "POST":
                resp = jwc_client.session.post(target, data=form_data,
                                               headers=EVAL_HEADERS, timeout=15)
            else:
                resp = jwc_client.session.get(target, headers=EVAL_HEADERS, timeout=15)
    except Exception as e:
        return jsonify({"success": False, "message": f"请求失败: {e}"}), 502

    content_type = resp.headers.get("content-type") or ""
    if content_type.startswith(("text/", "application/json", "application/javascript")):
        return jsonify({
            "success": True,
            "status": resp.status_code,
            "content_type": content_type,
            "text": resp.text,
        })
    # 二进制内容(图片等) → base64
    return jsonify({
        "success": True,
        "status": resp.status_code,
        "content_type": content_type,
        "data_b64": base64.b64encode(resp.content).decode(),
    })
# ============================================================
# API — 清除数据
# ============================================================
@app.route('/api/clear-data', methods=['POST'])
def api_clear_data():
    semester = dao.get_setting("semester", jwc_client._current_semester())
    dao.clear_data(semester)
    return jsonify({"success": True, "message": "数据已清除"})


# ============================================================
# API — 成绩查询
# ============================================================

@app.route('/api/grades')
def api_get_grades():
    """返回已存储的成绩原始数据(方案 A: GPA 等业务计算已移至前端)

    参数:
        semester: 学期代码(如 "2024-2025-1"),传 "__all__" 或不传查看全部学期
    """
    err = _require_login()
    if err:
        return err
    semester = request.args.get("semester", "")
    view_all = (semester == "__all__" or not semester)

    all_grades = dao.get_grades()
    available_semesters = dao.get_grade_semesters()

    if view_all:
        grades = all_grades
        display_semester = "__all__"
    else:
        parts = semester.split("-") if semester else []
        academic_year = f"{parts[0]}-{parts[1]}" if len(parts) >= 2 else ""
        sem = parts[2] if len(parts) >= 3 else ""
        grades = dao.get_grades(academic_year, sem) if academic_year and sem else []
        display_semester = semester

    return jsonify({
        "success": True,
        "semester": display_semester,
        "count": len(grades),
        "grades": grades,
        "available_semesters": available_semesters,
    })


@app.route('/api/refresh-grades', methods=['POST'])
def api_refresh_grades():
    """刷新成绩数据（从教务系统拉取）"""
    err = _require_login()
    if err:
        return err

    with jwc_lock:
        grades = jwc_client.get_grades("")

    if not grades and jwc_client.last_error:
        return jsonify({
            "success": False,
            "message": jwc_client.last_error or "获取成绩失败",
        }), 500

    from collections import defaultdict
    grouped = defaultdict(list)
    for g in grades:
        key = (g.get("academic_year", ""), g.get("semester", ""))
        grouped[key].append(g)

    total_count = 0
    for (ay, s), group in grouped.items():
        dao.save_grades(group, ay, s)
        total_count += len(group)

    return jsonify({
        "success": True,
        "message": f"成功获取 {total_count} 条成绩记录（{len(grouped)} 个学期）",
        "count": total_count,
    })


# ============================================================
# API — 四六级
# ============================================================

@app.route('/api/refresh-cet', methods=['POST'])
def api_refresh_cet():
    """刷新四六级成绩（从教务系统拉取）"""
    err = _require_login()
    if err:
        return err

    with jwc_lock:
        scores = jwc_client.get_cet_scores()

    if not scores:
        return jsonify({
            "success": False,
            "message": "未获取到四六级成绩",
        }), 404

    dao.save_cet_scores(scores)
    return jsonify({
        "success": True,
        "message": f"成功获取 {len(scores)} 条四六级成绩",
        "scores": scores,
    })


@app.route('/api/cet-scores')
def api_cet_scores():
    """获取已存储的四六级原始成绩(折算计算已移至前端)"""
    err = _require_login()
    if err:
        return err
    scores = dao.get_cet_scores()
    return jsonify({"success": True, "scores": scores})


# ============================================================
# 错误处理
# ============================================================
@app.errorhandler(404)
def not_found(e):
    return jsonify({"error": "页面不存在"}), 404


@app.errorhandler(500)
def server_error(e):
    return jsonify({"error": "服务器内部错误"}), 500
