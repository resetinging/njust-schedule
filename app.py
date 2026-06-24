"""
南理工课表管理系统 - Flask Web 应用
=====================================
提供：
  - Web 界面展示课表和考试安排
  - API 接口供前端调用
  - SQLite 数据库持久化存储
  - 多设备局域网访问支持
"""

import sqlite3
import json
import os
import socket
import threading
from datetime import datetime
from flask import (
    Flask, render_template, request, jsonify, g,
    redirect, url_for, Response,
)
import requests as req_lib
from bs4 import BeautifulSoup

from jwc_client import JWCClient
from config import HOST, PORT, DB_FILENAME

# ============================================================
# 配置
# ============================================================

BASE_DIR = os.environ.get("NJUST_DB_DIR", os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(BASE_DIR, DB_FILENAME)

app = Flask(__name__)
app.config["JSON_AS_ASCII"] = False  # 支持中文 JSON
app.config["TEMPLATES_AUTO_RELOAD"] = True

# 全局教务客户端（线程不安全，操作时需加锁）
jwc_client = JWCClient()
jwc_lock = threading.Lock()


# ============================================================
# 数据库管理
# ============================================================

def get_db() -> sqlite3.Connection:
    """获取数据库连接"""
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA journal_mode=WAL")
    return g.db


@app.teardown_appcontext
def close_db(exception):
    """请求结束后关闭数据库"""
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    """初始化数据库表结构"""
    db = sqlite3.connect(DB_PATH)
    db.executescript("""
        CREATE TABLE IF NOT EXISTS courses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            teacher TEXT DEFAULT '',
            classroom TEXT DEFAULT '',
            day_of_week INTEGER DEFAULT 0,
            start_period INTEGER DEFAULT 0,
            end_period INTEGER DEFAULT 0,
            weeks TEXT DEFAULT '',
            week_type INTEGER DEFAULT 0,
            semester TEXT DEFAULT '',
            credits TEXT DEFAULT '',
            course_type TEXT DEFAULT '',
            raw_data TEXT DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS exams (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            course_name TEXT NOT NULL,
            exam_date TEXT DEFAULT '',
            exam_time TEXT DEFAULT '',
            location TEXT DEFAULT '',
            seat TEXT DEFAULT '',
            exam_type TEXT DEFAULT '期末考试',
            semester TEXT DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS evaluations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            semester TEXT DEFAULT '',
            category TEXT DEFAULT '',
            batch TEXT DEFAULT '',
            start_date TEXT DEFAULT '',
            end_date TEXT DEFAULT '',
            is_done INTEGER DEFAULT 0,
            items_json TEXT DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT DEFAULT ''
        );

        -- 插入默认设置
        INSERT OR IGNORE INTO settings (key, value) VALUES
            ('student_id', ''),
            ('student_name', ''),
            ('semester', ''),
            ('auto_refresh', 'false'),
            ('refresh_interval', '3600');
    """)
    db.commit()
    db.close()


# ============================================================
# 设置辅助函数
# ============================================================

def get_setting(key: str, default: str = "") -> str:
    """读取设置"""
    db = get_db()
    row = db.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else default


def set_setting(key: str, value: str):
    """写入设置"""
    db = get_db()
    db.execute(
        "INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = ?",
        (key, value, value),
    )
    db.commit()


def save_courses_to_db(courses: list[dict], semester: str):
    """将课表数据保存到数据库"""
    db = get_db()
    # 先清除该学期的旧数据
    db.execute("DELETE FROM courses WHERE semester = ?", (semester,))
    for c in courses:
        db.execute(
            """INSERT INTO courses
               (name, teacher, classroom, day_of_week, start_period, end_period,
                weeks, week_type, semester, credits, course_type, raw_data)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                c.get("name", ""),
                c.get("teacher", ""),
                c.get("classroom", ""),
                c.get("day", 0),
                c.get("start", 0),
                c.get("end", 0),
                c.get("weeks", ""),
                c.get("week_type", 0),
                semester,
                str(c.get("credits", "")),
                c.get("course_type", ""),
                json.dumps(c.get("raw", {}), ensure_ascii=False),
            ),
        )
    db.commit()


def save_exams_to_db(exams: list[dict], semester: str):
    """将考试数据保存到数据库"""
    db = get_db()
    db.execute("DELETE FROM exams WHERE semester = ?", (semester,))
    for e in exams:
        db.execute(
            """INSERT INTO exams
               (course_name, exam_date, exam_time, location, seat, exam_type, semester)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                e.get("course_name", ""),
                e.get("date", ""),
                e.get("time", ""),
                e.get("location", ""),
                e.get("seat", ""),
                e.get("type", "期末考试"),
                semester,
            ),
        )
    db.commit()


# ============================================================
# 页面路由
# ============================================================

def save_evaluations_to_db(evaluations: list[dict], semester: str):
    """将评价数据保存到数据库"""
    db = get_db()
    db.execute("DELETE FROM evaluations WHERE semester = ?", (semester,))
    for e in evaluations:
        db.execute(
            """INSERT INTO evaluations
               (semester, category, batch, start_date, end_date, is_done, items_json)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                e.get("semester", ""),
                e.get("category", ""),
                e.get("batch", ""),
                e.get("start_date", ""),
                e.get("end_date", ""),
                1 if e.get("is_done") else 0,
                json.dumps(e.get("items", []), ensure_ascii=False),
            ),
        )
    db.commit()


@app.route("/")
def index():
    """课表主页"""
    return render_template("index.html")


@app.route("/exams")
def exams_page():
    """考试安排页面"""
    return render_template("exams.html")


@app.route("/evaluations")
def evaluations_page():
    """教学评价页面"""
    return render_template("evaluations.html")


@app.route("/proxy/jw/<path:target_path>", methods=["GET", "POST"])
def proxy_jw(target_path):
    """代理教务系统页面"""
    if not jwc_client.logged_in:
        return "请先登录教务系统", 401

    target_url = f"http://202.119.81.112:9080/njlgdx/{target_path}"
    qs = request.query_string.decode()
    if qs:
        target_url += "?" + qs

    # 模拟浏览器请求头
    proxy_headers = {
        "Referer": "http://202.119.81.112:9080/njlgdx/xspj/xspj_find.do",
        "Host": "202.119.81.112:9080",
        "Origin": "http://202.119.81.112:9080",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9",
        "Cache-Control": "max-age=0",
    }

    try:
        if request.method == "POST":
            resp = jwc_client.session.post(target_url, data=request.form,
                                           headers=proxy_headers, timeout=15)
        else:
            # 先访问评价列表页建立会话状态
            jwc_client.session.get(
                "http://202.119.81.112:9080/njlgdx/xspj/xspj_find.do",
                headers={"Referer": "http://202.119.81.112:9080/njlgdx/framework/main.jsp"},
                timeout=10)
            resp = jwc_client.session.get(target_url, headers=proxy_headers, timeout=15)
    except Exception as e:
        return f"代理请求失败: {e}", 502

    if "text/html" in (resp.headers.get("content-type") or ""):
        content = resp.text
        # 检查是否被教务系统拦截
        if "非法访问" in content or "非法操作" in content:
            return Response(f"""
                <html><body style="padding:40px;text-align:center;font-family:sans-serif;">
                <h2>⚠️ 教务系统拒绝了请求</h2>
                <p>{target_path}</p>
                <p>请尝试：</p>
                <p><a href="/evaluations">返回评价列表</a></p>
                <p><a href="/settings">重新登录教务系统</a></p>
                </body></html>
            """, status=403)
        # 路径替换
        for old, new in [('src="/njlgdx/', 'src="/proxy/jw/'),
                         ('href="/njlgdx/', 'href="/proxy/jw/'),
                         ("src='/njlgdx/", "src='/proxy/jw/"),
                         ("href='/njlgdx/", "href='/proxy/jw/"),
                         ('action="/njlgdx/', 'action="/proxy/jw/'),
                         ("action='/njlgdx/", "action='/proxy/jw/"),
                         ('"/njlgdx/js/', '"/proxy/jw/js/'),
                         ("'/njlgdx/js/", "'/proxy/jw/js/")]:
            content = content.replace(old, new)
        return Response(content, status=resp.status_code,
                        content_type="text/html; charset=utf-8")
    return Response(resp.content, status=resp.status_code,
                    content_type=resp.headers.get("content-type", "text/html"))


@app.route("/settings")
def settings_page():
    """设置页面"""
    return render_template("settings.html")


# ============================================================
# API 路由
# ============================================================

@app.route("/api/status")
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
    import time as _time
    auto_login_error = ""
    if not jwc_client.logged_in and student_id:
        if not _auto_login_attempted or (_time.time() - _last_auto_login_time) > 30:
            if _auto_login():
                auto_login_error = ""  # 成功
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


@app.route("/api/connect-test")
def api_connect_test():
    """测试教务系统连接"""
    ok, msg = jwc_client.test_connection()
    return jsonify({"ok": ok, "message": msg})


@app.route("/api/get-captcha")
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


@app.route("/api/login", methods=["POST"])
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


@app.route("/api/login-manual", methods=["POST"])
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


def _encode_pwd(pwd: str) -> str:
    """简单编码密码（本地存储，非安全加密）"""
    import base64 as b64
    return b64.b64encode(pwd.encode()).decode()


def _decode_pwd(encoded: str) -> str:
    """解码密码"""
    import base64 as b64
    try:
        return b64.b64decode(encoded.encode()).decode()
    except Exception:
        return ""


_auto_login_attempted = False  # 全局标记：是否已尝试过自动登录（给前端展示用）
_last_auto_login_time = 0.0   # 上次自动登录尝试时间戳（避免频繁重试）

def _auto_login() -> bool:
    """尝试用存储的凭据自动登录"""
    global _auto_login_attempted, _last_auto_login_time
    import time as _time
    _auto_login_attempted = True
    _last_auto_login_time = _time.time()
    if jwc_client.logged_in:
        return True
    sid = get_setting("student_id")
    pwd = _decode_pwd(get_setting("password_enc", ""))
    if not sid or not pwd:
        return False
    jwc_client.login(sid, pwd)
    return jwc_client.logged_in


def _on_login_success(student_id: str, password: str = ""):
    """登录成功后的公共处理"""
    set_setting("student_id", student_id)
    if password:
        set_setting("password_enc", _encode_pwd(password))
    if jwc_client.student_name:
        set_setting("student_name", jwc_client.student_name)

    semester = get_setting("semester")
    if not semester:
        semester = jwc_client._current_semester()
        set_setting("semester", semester)

    return jsonify({
        "success": True,
        "message": f"登录成功！欢迎 {jwc_client.student_name or student_id}",
        "student_name": jwc_client.student_name or student_id,
        "login_method": jwc_client.login_method,
    })


# ============================================================
# 辅助函数
# ============================================================

def _require_login():
    """检查登录状态，未登录时尝试自动重登，仍失败则返回错误"""
    if not jwc_client.logged_in:
        auto_ok = _auto_login()
        student_id = get_setting("student_id")
        if not student_id:
            return jsonify({
                "success": False,
                "message": "尚未登录，请先在设置页面登录教务系统",
            }), 401
        if not auto_ok:
            err = jwc_client.last_error or "教务系统不可达"
            return jsonify({
                "success": False,
                "message": f"自动登录失败: {err}，请前往设置手动登录",
            }), 401
    return None


def _course_row_to_dict(row) -> dict:
    """数据库行 → 课表 JSON"""
    return {
        "id": row["id"],
        "name": row["name"],
        "teacher": row["teacher"],
        "classroom": row["classroom"],
        "day": row["day_of_week"],
        "start": row["start_period"],
        "end": row["end_period"],
        "weeks": row["weeks"],
        "week_type": row["week_type"],
        "credits": row["credits"],
        "course_type": row["course_type"],
    }


def _exam_row_to_dict(row) -> dict:
    """数据库行 → 考试 JSON"""
    return {
        "id": row["id"],
        "course_name": row["course_name"],
        "date": row["exam_date"],
        "time": row["exam_time"],
        "location": row["location"],
        "seat": row["seat"],
        "type": row["exam_type"],
    }


@app.route("/api/refresh-schedule", methods=["POST"])
def api_refresh_schedule():
    """刷新课表数据"""
    semester = get_setting("semester", jwc_client._current_semester())

    err = _require_login()
    if err:
        return err

    with jwc_lock:
        courses = jwc_client.get_schedule(semester)

    if not courses:
        return jsonify({
            "success": False,
            "message": jwc_client.last_error or "获取课表失败，请检查网络连接和登录状态",
        }), 500

    save_courses_to_db(courses, semester)
    set_setting("semester", semester)

    return jsonify({
        "success": True,
        "message": f"成功获取 {len(courses)} 门课程",
        "count": len(courses),
        "semester": semester,
    })


@app.route("/api/refresh-exams", methods=["POST"])
def api_refresh_exams():
    """刷新考试安排"""
    semester = get_setting("semester", jwc_client._current_semester())

    err = _require_login()
    if err:
        return err

    with jwc_lock:
        exams = jwc_client.get_exams(semester)

    if not exams and jwc_client.last_error:
        return jsonify({
            "success": False,
            "message": jwc_client.last_error or "获取考试安排失败，请检查网络连接和登录状态",
        }), 500

    save_exams_to_db(exams, semester)

    return jsonify({
        "success": True,
        "message": f"成功获取 {len(exams)} 场考试" + ("（本学期暂无考试）" if len(exams) == 0 else ""),
        "count": len(exams),
    })


@app.route("/api/refresh-all", methods=["POST"])
def api_refresh_all():
    """一键刷新课表和考试安排"""
    semester = get_setting("semester", jwc_client._current_semester())

    err = _require_login()
    if err:
        return err

    results = {"schedule": None, "exams": None}

    with jwc_lock:
        courses = jwc_client.get_schedule(semester)
        if courses:
            save_courses_to_db(courses, semester)
            results["schedule"] = {"count": len(courses), "ok": True}
        else:
            results["schedule"] = {"count": 0, "ok": False, "error": jwc_client.last_error}

        exams = jwc_client.get_exams(semester)
        if exams:
            save_exams_to_db(exams, semester)
            results["exams"] = {"count": len(exams), "ok": True}
        else:
            results["exams"] = {"count": 0, "ok": False, "error": jwc_client.last_error}

    set_setting("semester", semester)

    return jsonify({
        "success": True,
        "semester": semester,
        "schedule": results["schedule"],
        "exams": results["exams"],
        "message": (
            f"课表: {results['schedule']['count']}门, "
            f"考试: {results['exams']['count']}场"
        ),
    })


@app.route("/api/courses")
def api_get_courses():
    """获取已存储的课表数据"""
    semester = request.args.get(
        "semester", get_setting("semester", jwc_client._current_semester())
    )
    db = get_db()
    rows = db.execute(
        "SELECT * FROM courses WHERE semester = ? ORDER BY day_of_week, start_period",
        (semester,),
    ).fetchall()

    courses = [_course_row_to_dict(r) for r in rows]

    return jsonify({
        "semester": semester,
        "count": len(courses),
        "courses": courses,
    })


@app.route("/api/exams")
def api_get_exams():
    """获取已存储的考试安排"""
    semester = request.args.get(
        "semester", get_setting("semester", jwc_client._current_semester())
    )
    db = get_db()
    rows = db.execute(
        "SELECT * FROM exams WHERE semester = ? ORDER BY exam_date",
        (semester,),
    ).fetchall()

    exams = [_exam_row_to_dict(r) for r in rows]

    return jsonify({
        "semester": semester,
        "count": len(exams),
        "exams": exams,
    })


@app.route("/api/settings", methods=["GET", "POST"])
def api_settings():
    """读取或更新设置"""
    if request.method == "GET":
        db = get_db()
        rows = db.execute("SELECT key, value FROM settings").fetchall()
        settings = {r["key"]: r["value"] for r in rows}
        # 补充 semester 列表
        settings["semester_list"] = jwc_client.get_semester_list()
        settings["current_semester"] = jwc_client._current_semester()
        return jsonify(settings)

    else:
        data = request.get_json()
        for key, value in data.items():
            if key in ("student_id", "student_name", "semester",
                        "auto_refresh", "refresh_interval"):
                set_setting(key, str(value))
        return jsonify({"success": True, "message": "设置已保存"})


@app.route("/api/semester", methods=["POST"])
def api_set_semester():
    """切换学期"""
    data = request.get_json()
    semester = (data.get("semester") or "").strip()
    if not semester:
        return jsonify({"success": False, "message": "学期不能为空"}), 400

    set_setting("semester", semester)
    return jsonify({"success": True, "message": f"已切换到学期: {semester}"})


@app.route("/api/evaluations")
def api_get_evaluations():
    """获取已存储的教学评价"""
    semester = request.args.get(
        "semester", get_setting("semester", jwc_client._current_semester())
    )
    db = get_db()
    rows = db.execute(
        "SELECT * FROM evaluations WHERE semester = ? ORDER BY end_date",
        (semester,),
    ).fetchall()

    evals = []
    for r in rows:
        evals.append({
            "id": r["id"],
            "semester": r["semester"],
            "category": r["category"],
            "batch": r["batch"],
            "start_date": r["start_date"],
            "end_date": r["end_date"],
            "is_done": bool(r["is_done"]),
            "items": json.loads(r["items_json"]) if r["items_json"] else [],
        })

    return jsonify({
        "semester": semester,
        "count": len(evals),
        "evaluations": evals,
    })


@app.route("/api/refresh-evaluations", methods=["POST"])
def api_refresh_evaluations():
    """刷新教学评价数据"""
    semester = get_setting("semester", jwc_client._current_semester())

    err = _require_login()
    if err:
        return err

    with jwc_lock:
        evals = jwc_client.get_evaluations(semester)

    if not evals and jwc_client.last_error:
        return jsonify({
            "success": False,
            "message": jwc_client.last_error or "获取评价数据失败",
        }), 500

    save_evaluations_to_db(evals, semester)

    undone = sum(1 for e in evals if not e.get("is_done"))
    return jsonify({
        "success": True,
        "message": f"成功获取 {len(evals)} 条评价" + (
            f"，{undone} 条待完成" if undone > 0 else "，全部已完成"
        ),
        "count": len(evals),
        "undone": undone,
    })


@app.route("/api/eval-courses")
def api_eval_courses():
    """解析评教课程列表页（批次点击后的第二级页面）"""
    url = request.args.get("url", "")
    if not url:
        return jsonify({"success": False, "message": "缺少 URL"}), 400
    if not jwc_client.logged_in:
        return jsonify({"success": False, "message": "请先登录"}), 401

    target = f"http://202.119.81.112:9080{url}" if url.startswith("/") else url

    eval_headers = {
        "Referer": "http://202.119.81.112:9080/njlgdx/xspj/xspj_find.do",
        "Host": "202.119.81.112:9080",
        "Origin": "http://202.119.81.112:9080",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9",
        "Cache-Control": "max-age=0",
    }

    try:
        jwc_client.session.get(
            "http://202.119.81.112:9080/njlgdx/xspj/xspj_find.do",
            headers={"Referer": "http://202.119.81.112:9080/njlgdx/framework/main.jsp"},
            timeout=10)
        resp = jwc_client.session.get(target, headers=eval_headers, timeout=15)
        if "非法访问" in resp.text or "非法操作" in resp.text:
            return jsonify({"success": False, "message": "教务系统拒绝了请求"}), 403
        soup = BeautifulSoup(resp.text, "lxml")
    except Exception as e:
        return jsonify({"success": False, "message": f"请求失败: {e}"}), 500

    # 提取批次标题
    title_el = soup.select_one(".Nsb_r_title")
    batch_title = title_el.get_text(strip=True) if title_el else "评教课程"

    # 提取 Form1 中的隐藏字段（后续提交需要）
    form = soup.find("form", id="Form1")
    hidden_fields = {}
    if form:
        for inp in form.find_all("input", type="hidden"):
            name = inp.get("name", "")
            value = inp.get("value", "")
            if name:
                hidden_fields[name] = value

    # 解析课程列表 (#dataList)
    courses = []
    data_table = soup.find("table", id="dataList")
    if data_table:
        for row in data_table.find_all("tr")[1:]:  # 跳过表头
            cells = row.find_all("td")
            if len(cells) < 8:
                continue
            # 提取评价链接（javascript:openWindow('...',1000,700)）
            eval_url = ""
            eval_link = cells[7].find("a")
            if eval_link:
                href = eval_link.get("href", "")
                m = __import__("re").search(r"openWindow\('([^']+)'", href)
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

    if not courses:
        return jsonify({"success": False, "message": "未找到课程列表"}), 500

    return jsonify({
        "success": True,
        "batch_title": batch_title,
        "courses": courses,
        "hidden_fields": hidden_fields,
    })


@app.route("/api/eval-form")
def api_eval_form():
    """解析评教表单为结构化 JSON（xspj_edit.do 页面）"""
    url = request.args.get("url", "")
    if not url:
        return jsonify({"success": False, "message": "缺少评教 URL"}), 400
    if not jwc_client.logged_in:
        return jsonify({"success": False, "message": "请先登录"}), 401

    target = f"http://202.119.81.112:9080{url}" if url.startswith("/") else url

    # 模拟浏览器请求头（与 proxy_jw 保持一致，避免教务拒绝）
    eval_headers = {
        "Referer": "http://202.119.81.112:9080/njlgdx/xspj/xspj_find.do",
        "Host": "202.119.81.112:9080",
        "Origin": "http://202.119.81.112:9080",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9",
        "Cache-Control": "max-age=0",
    }

    try:
        # 先访问评价列表页建立会话状态
        jwc_client.session.get(
            "http://202.119.81.112:9080/njlgdx/xspj/xspj_find.do",
            headers={"Referer": "http://202.119.81.112:9080/njlgdx/framework/main.jsp"},
            timeout=10)
        resp = jwc_client.session.get(target, headers=eval_headers, timeout=15)
        # 检查教务是否拒绝请求
        if "非法访问" in resp.text or "非法操作" in resp.text:
            return jsonify({"success": False, "message": "教务系统拒绝了请求，请重新登录后重试"}), 403
        soup = BeautifulSoup(resp.text, "lxml")
    except Exception as e:
        return jsonify({"success": False, "message": f"请求失败: {e}"}), 500

    # 提取课程信息（教务用 &nbsp; 分隔字段）
    th = soup.find("th", class_="Nsb_r_list_thb")
    course_info = th.get_text() if th else ""
    course_name = ""
    # 用正则从 "课程名称：XXX  评教大类：XXX  总评分: XX" 中提取
    m = __import__("re").search(r'课程名称[：:]\s*(.+?)(?:\s{2,}|\xa0|$)', course_info)
    if m:
        course_name = m.group(1).strip()

    # 提取隐藏字段
    form = soup.find("form", id="Form1")
    hidden_fields = {}
    if form:
        for inp in form.find_all("input", type="hidden"):
            name = inp.get("name", "")
            value = inp.get("value", "")
            if name:
                hidden_fields[name] = value

    # 提取评价指标
    indicators = []
    for row in soup.select("#table1 tr"):
        tds = row.find_all("td")
        if len(tds) < 2:
            continue
        # 第一个 td: 指标标签 + <input type="hidden" name="pj06xh">
        label = tds[0].get_text(strip=True)
        if not label or "评价指标" in label:
            continue
        seq_input = tds[0].find("input", attrs={"name": "pj06xh"})
        seq = seq_input.get("value", "") if seq_input else ""

        # 第二个 td: radio 选项 + 隐藏分值字段交替排列
        # 结构: <input type="radio" ...> 标签文字 <input type="hidden" name="pj0601fz_SEQ_UUID" value="分数"> ...
        # 先构建分值映射: {radio_uuid: score}
        fz_map = {}
        for inp in tds[1].find_all("input", type="hidden"):
            fz_name = inp.get("name", "")
            fz_value = inp.get("value", "")
            if fz_name.startswith("pj0601fz_"):
                # pj0601fz_10_UUID → 最后一段是 UUID
                parts = fz_name.rsplit("_", 1)
                if len(parts) == 2:
                    fz_map[parts[1]] = fz_value

        options = []
        for radio in tds[1].find_all("input", type="radio"):
            opt_name = radio.get("name", "")
            opt_value = radio.get("value", "")
            opt_score = fz_map.get(opt_value, "")
            # 直接取 radio 后面的 NavigableString 文本节点
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
            })
        indicators.append({"seq": seq, "label": label, "options": options})

    if not course_name and not indicators:
        return jsonify({"success": False, "message": "未找到评价表单内容，请返回课程列表重试"}), 500

    # 提取表单 action URL
    form_action = form.get("action", "") if form else ""

    return jsonify({
        "success": True,
        "course_name": course_name,
        "hidden_fields": hidden_fields,
        "indicators": indicators,
        "action": form_action,
    })


@app.route("/api/submit-eval", methods=["POST"])
def api_submit_eval():
    """提交评教数据到教务系统"""
    if not jwc_client.logged_in:
        return jsonify({"success": False, "message": "请先登录"}), 401
    data = request.get_json()
    form_data = data.get("form_data", {})
    submit_type = data.get("submit_type", "0")
    action_path = data.get("action", "/njlgdx/xspj/xspj_save.do")

    form_data["issubmit"] = submit_type
    target_url = f"http://202.119.81.112:9080{action_path}"

    # 完整的浏览器模拟头部
    submit_headers = {
        "Referer": "http://202.119.81.112:9080/njlgdx/xspj/xspj_find.do",
        "Host": "202.119.81.112:9080",
        "Origin": "http://202.119.81.112:9080",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9",
        "Cache-Control": "max-age=0",
    }

    try:
        # 先访问评价列表页建立会话状态
        jwc_client.session.get(
            "http://202.119.81.112:9080/njlgdx/xspj/xspj_find.do",
            headers={"Referer": "http://202.119.81.112:9080/njlgdx/framework/main.jsp"},
            timeout=10)
        resp = jwc_client.session.post(target_url, data=form_data, headers=submit_headers, timeout=15)
        if "评价成功" in resp.text or "提交成功" in resp.text or "保存成功" in resp.text:
            return jsonify({"success": True, "message": "评教提交成功！"})
        return jsonify({"success": True, "message": "已提交（请返回教务确认）"})
    except Exception as e:
        return jsonify({"success": False, "message": f"提交失败: {e}"}), 500


@app.route("/api/clear-data", methods=["POST"])
def api_clear_data():
    """清除当前学期的数据"""
    semester = get_setting("semester", jwc_client._current_semester())
    db = get_db()
    db.execute("DELETE FROM courses WHERE semester = ?", (semester,))
    db.execute("DELETE FROM exams WHERE semester = ?", (semester,))
    db.commit()
    return jsonify({"success": True, "message": "数据已清除"})



# ============================================================
# 服务器信息
# ============================================================

def get_lan_ip() -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.254.254.254", 1))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


@app.context_processor
def inject_global():
    return {"lan_ip": get_lan_ip(), "port": PORT}


# ============================================================
# 错误处理
# ============================================================

@app.errorhandler(404)
def not_found(e):
    return jsonify({"error": "页面不存在"}), 404


@app.errorhandler(500)
def server_error(e):
    return jsonify({"error": "服务器内部错误"}), 500


# ============================================================
# 启动入口（直接 python app.py 时使用，桌面模式下由 main.py 启动）
# ============================================================

if __name__ == "__main__":
    init_db()
    print(f"南理工课表管理系统 - http://127.0.0.1:{PORT}")
    app.run(host="127.0.0.1", port=PORT, debug=False, threaded=True)
