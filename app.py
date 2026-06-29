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
import re
import time
import base64
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
from config import HOST, PORT, DB_FILENAME, DEBUG_EVAL

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

# 批量评教进度追踪
_batch_progress = {}       # {batch_id: {current, total, course, status, message, done, results}}
_batch_progress_lock = threading.Lock()

# 评教相关请求的公共头部（避免教务拦截）
EVAL_HEADERS = {
    "Referer": "http://202.119.81.112:9080/njlgdx/xspj/xspj_find.do",
    "Host": "202.119.81.112:9080",
    "Origin": "http://202.119.81.112:9080",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9",
    "Cache-Control": "max-age=0",
}


def _warm_eval_session():
    """访问评教列表页建立会话状态，避免后续请求被教务拒绝"""
    jwc_client.session.get(
        "http://202.119.81.112:9080/njlgdx/xspj/xspj_find.do",
        headers={"Referer": "http://202.119.81.112:9080/njlgdx/framework/main.jsp"},
        timeout=10)


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


# ============================================================
# 页面路由
# ============================================================

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

    try:
        if request.method == "POST":
            resp = jwc_client.session.post(target_url, data=request.form,
                                           headers=EVAL_HEADERS, timeout=15)
        else:
            _warm_eval_session()
            resp = jwc_client.session.get(target_url, headers=EVAL_HEADERS, timeout=15)
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
    auto_login_error = ""
    if not jwc_client.logged_in and student_id:
        if not _auto_login_attempted or (time.time() - _last_auto_login_time) > 30:
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
    return base64.b64encode(pwd.encode()).decode()


def _decode_pwd(encoded: str) -> str:
    """解码密码"""
    try:
        return base64.b64decode(encoded.encode()).decode()
    except Exception:
        return ""


_auto_login_attempted = False  # 全局标记：是否已尝试过自动登录（给前端展示用）
_last_auto_login_time = 0.0   # 上次自动登录尝试时间戳（避免频繁重试）

def _auto_login() -> bool:
    """尝试用存储的凭据自动登录"""
    global _auto_login_attempted, _last_auto_login_time
    _auto_login_attempted = True
    _last_auto_login_time = time.time()

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
        # 标记密码是否已保存（不返回原始密码）
        settings["has_password"] = bool(settings.get("password_enc", ""))
        settings.pop("password_enc", None)  # 不暴露编码密码到前端
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


# ============================================================
# 评教辅助函数（供 API 路由和批量评教复用）
# ============================================================

def _parse_eval_courses_page(html: str) -> dict:
    """从评教课程列表页 HTML 解析课程、批次标题和隐藏字段
    返回 {"batch_title": str, "courses": list, "hidden_fields": dict} 或 None
    """
    soup = BeautifulSoup(html, "lxml")

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
    """从评教表单页 HTML 解析评价指标和隐藏字段
    返回 {"course_name": str, "hidden_fields": dict, "indicators": list, "action": str} 或 None
    """
    soup = BeautifulSoup(html, "lxml")

    # 提取课程信息（教务用 &nbsp; 分隔字段）
    th = soup.find("th", class_="Nsb_r_list_thb")
    course_info = th.get_text() if th else ""
    course_name = ""
    m = re.search(r'课程名称[：:]\s*(.+?)(?:\s{2,}|\xa0|$)', course_info)
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

    # 提取评价指标（同时收集所有 pj0601fz_* 分值隐藏字段）
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
        # 先构建分值映射: {radio_uuid: score}，同时将 pj0601fz_* 存入 hidden_fields
        fz_map = {}
        for inp in tds[1].find_all("input", type="hidden"):
            fz_name = inp.get("name", "")
            fz_value = inp.get("value", "")
            if fz_name.startswith("pj0601fz_"):
                hidden_fields[fz_name] = fz_value  # ★ 批量评教提交时需要这些分值字段
                parts = fz_name.rsplit("_", 1)
                if len(parts) == 2:
                    fz_map[parts[1]] = fz_value

        options = []
        for radio in tds[1].find_all("input", type="radio"):
            opt_name = radio.get("name", "")
            opt_value = radio.get("value", "")
            opt_score = fz_map.get(opt_value, "")
            opt_checked = radio.has_attr("checked")
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
                "checked": opt_checked,
            })
        indicators.append({"seq": seq, "label": label, "options": options})

    # 提取表单 action URL
    form_action = form.get("action", "") if form else ""

    return {
        "course_name": course_name,
        "hidden_fields": hidden_fields,
        "indicators": indicators,
        "action": form_action,
    }


# ============================================================
# 自动填写算法（从 evaluations.js autoFillEval() 移植）
# ============================================================

def _auto_fill_eval_indicators(indicators: list, target_score: float = 95.0) -> dict:
    """根据目标分数自动选择每个指标的 radio 选项
    算法：贪心选择 + 防同列作弊 + 微调优化

    参数:
        indicators: 指标列表，每项含 seq, label, options（options 中含 name/value/score/checked）
        target_score: 目标总分（满分通常为指标数*各指标最高分之和）

    返回:
        {seq: (radio_name, radio_value)} 映射 + {"_total": 实际总分}
    """
    if not indicators:
        return {"_total": 0}

    # 步骤 0: 计算满分和各指标的目标分
    indicator_scores = []  # [{seq, max_score, options_with_idx}]
    total_max = 0
    for ind in indicators:
        opts = ind.get("options", [])
        ind_max = 0
        scored_opts = []
        for i, opt in enumerate(opts):
            s = float(opt.get("score", 0) or 0)
            scored_opts.append({"idx": i, "score": s, "name": opt["name"], "value": opt["value"]})
            if s > ind_max:
                ind_max = s
        total_max += ind_max
        indicator_scores.append({
            "seq": ind.get("seq", ""),
            "max_score": ind_max,
            "options": scored_opts,
        })

    if total_max <= 0:
        return {"_total": 0}

    # 步骤 1: 贪心选择 — 每个指标选最接近目标比例的选项
    selections = []  # [{seq, colIndex, score}]
    for iscore in indicator_scores:
        ind_target = (target_score / total_max) * iscore["max_score"] if total_max > 0 else 0
        best_idx = 0
        best_dist = float('inf')
        for opt in iscore["options"]:
            dist = abs(opt["score"] - ind_target)
            if dist < best_dist:
                best_dist = dist
                best_idx = opt["idx"]
        chosen = iscore["options"][best_idx]
        selections.append({
            "seq": iscore["seq"],
            "colIndex": best_idx,
            "score": chosen["score"],
            "name": chosen["name"],
            "value": chosen["value"],
            "options": iscore["options"],  # 保留完整选项供微调
        })

    # 步骤 2: 防作弊 — 不能所有指标选同一列
    if len(selections) > 1:
        all_same = all(s["colIndex"] == selections[0]["colIndex"] for s in selections)
        if all_same:
            current_total = sum(s["score"] for s in selections)
            best_penalty = abs(current_total - target_score)
            best_combo = None

            for sacrifice_idx in range(len(selections)):
                for alt_opt in selections[sacrifice_idx]["options"]:
                    if alt_opt["idx"] == selections[sacrifice_idx]["colIndex"]:
                        continue
                    new_total = current_total - selections[sacrifice_idx]["score"] + alt_opt["score"]
                    penalty = abs(new_total - target_score)
                    if penalty < best_penalty:
                        best_penalty = penalty
                        best_combo = {
                            "sacrifice_idx": sacrifice_idx,
                            "colIndex": alt_opt["idx"],
                            "score": alt_opt["score"],
                            "name": alt_opt["name"],
                            "value": alt_opt["value"],
                        }

            if best_combo:
                idx = best_combo["sacrifice_idx"]
                selections[idx]["colIndex"] = best_combo["colIndex"]
                selections[idx]["score"] = best_combo["score"]
                selections[idx]["name"] = best_combo["name"]
                selections[idx]["value"] = best_combo["value"]

    # 步骤 3: 微调 — 单指标 + 双指标组合交换，防作弊收敛
    # 辅助：检查是否所有指标在同一列
    def _all_same_column(sels):
        if len(sels) <= 1:
            return False
        return all(s["colIndex"] == sels[0]["colIndex"] for s in sels)

    # 阶段 A: 单指标微调（最多 10 轮，连续 3 轮无改善则进入双指标阶段）
    no_improve_rounds = 0
    for _ in range(10):
        current_total = sum(s["score"] for s in selections)
        current_penalty = abs(current_total - target_score)
        if current_penalty < 0.5:
            break

        best_swap = None
        best_penalty = current_penalty

        for i in range(len(selections)):
            for alt_opt in selections[i]["options"]:
                if alt_opt["idx"] == selections[i]["colIndex"]:
                    continue
                new_total = current_total - selections[i]["score"] + alt_opt["score"]
                new_penalty = abs(new_total - target_score)

                # 模拟应用后检查是否全同列（用 save/restore 避免副作用）
                saved_col = selections[i]["colIndex"]
                saved_score = selections[i]["score"]
                selections[i]["colIndex"] = alt_opt["idx"]
                selections[i]["score"] = alt_opt["score"]
                all_same = _all_same_column(selections)
                selections[i]["colIndex"] = saved_col
                selections[i]["score"] = saved_score

                if all_same:
                    continue

                if new_penalty < best_penalty:
                    best_penalty = new_penalty
                    best_swap = {
                        "idx": i,
                        "colIndex": alt_opt["idx"],
                        "score": alt_opt["score"],
                        "name": alt_opt["name"],
                        "value": alt_opt["value"],
                    }

        if best_swap and best_penalty < current_penalty:
            idx = best_swap["idx"]
            selections[idx]["colIndex"] = best_swap["colIndex"]
            selections[idx]["score"] = best_swap["score"]
            selections[idx]["name"] = best_swap["name"]
            selections[idx]["value"] = best_swap["value"]
            no_improve_rounds = 0
        else:
            no_improve_rounds += 1
            if no_improve_rounds >= 3:
                break

    # 阶段 B: 双指标组合交换 — 突破单指标局部最优
    # 同时调整两个指标可能达到任何单指标调整都达不到的精度
    current_total = sum(s["score"] for s in selections)
    current_penalty = abs(current_total - target_score)
    if current_penalty >= 0.5:
        best_pair = None
        best_penalty = current_penalty

        for i in range(len(selections)):
            for j in range(i + 1, len(selections)):
                for alt_i in selections[i]["options"]:
                    if alt_i["idx"] == selections[i]["colIndex"]:
                        continue
                    for alt_j in selections[j]["options"]:
                        if alt_j["idx"] == selections[j]["colIndex"]:
                            continue
                        new_total = (current_total
                                     - selections[i]["score"] - selections[j]["score"]
                                     + alt_i["score"] + alt_j["score"])
                        new_penalty = abs(new_total - target_score)

                        if new_penalty >= best_penalty:
                            continue

                        # 模拟应用后检查防作弊
                        saved_i_col = selections[i]["colIndex"]
                        saved_j_col = selections[j]["colIndex"]
                        selections[i]["colIndex"] = alt_i["idx"]
                        selections[j]["colIndex"] = alt_j["idx"]
                        all_same = _all_same_column(selections)
                        selections[i]["colIndex"] = saved_i_col
                        selections[j]["colIndex"] = saved_j_col

                        if all_same:
                            continue

                        best_penalty = new_penalty
                        best_pair = [
                            {"idx": i, "colIndex": alt_i["idx"], "score": alt_i["score"],
                             "name": alt_i["name"], "value": alt_i["value"]},
                            {"idx": j, "colIndex": alt_j["idx"], "score": alt_j["score"],
                             "name": alt_j["name"], "value": alt_j["value"]},
                        ]

        if best_pair:
            for swap in best_pair:
                idx = swap["idx"]
                selections[idx]["colIndex"] = swap["colIndex"]
                selections[idx]["score"] = swap["score"]
                selections[idx]["name"] = swap["name"]
                selections[idx]["value"] = swap["value"]

    # 阶段 C: 兜底 — 如果误差仍超过 5% 且前面都没能收敛，放松防作弊
    final_penalty = abs(sum(s["score"] for s in selections) - target_score)
    if final_penalty > max(2.0, total_max * 0.05):
        for i in range(len(selections)):
            best_cost = float('inf')
            best_opt = None
            saved_col = selections[i]["colIndex"]
            saved_score = selections[i]["score"]
            for alt_opt in selections[i]["options"]:
                new_total = current_total - saved_score + alt_opt["score"]
                new_penalty = abs(new_total - target_score)
                if new_penalty < best_cost:
                    # 快速检查防作弊
                    selections[i]["colIndex"] = alt_opt["idx"]
                    is_ok = not _all_same_column(selections)
                    if is_ok:
                        best_cost = new_penalty
                        best_opt = alt_opt
            selections[i]["colIndex"] = saved_col
            selections[i]["score"] = saved_score
            if best_opt and best_cost < current_penalty * 0.8:
                selections[i]["colIndex"] = best_opt["idx"]
                selections[i]["score"] = best_opt["score"]
                selections[i]["name"] = best_opt["name"]
                selections[i]["value"] = best_opt["value"]
                current_total = sum(s["score"] for s in selections)
                current_penalty = abs(current_total - target_score)
            if current_penalty < 1.0:
                break

    # 构建返回结果
    result = {}
    for s in selections:
        result[s["seq"]] = (s["name"], s["value"])
    result["_total"] = sum(s["score"] for s in selections)
    return result


# ============================================================
# POST 数据有序构建（从 api_submit_eval 提取，批量评教复用）
# ============================================================

def _build_ordered_eval_post_data(form_data: dict, batch_hidden_fields: dict = None,
                                  auto_fill_selections: dict = None,
                                  submit_type: str = "1") -> list:
    """构建有序 POST 数据，模拟浏览器原生表单提交顺序。

    教务原始表单每个指标行都有 <input name="pj06xh" value="N">，
    浏览器会提交 N 个 pj06xh=N。必须为每个指标插入 pj06xh 作为行分隔符，
    否则教务只保存最后一项。

    参数:
        form_data: 表单隐藏字段 + 指标数据（与前端提交格式一致）
        batch_hidden_fields: 课程列表页的隐藏字段（如 cj0701id），会合并进去
        auto_fill_selections: 自动填写的选择 {seq: (name, value)}，如果提供则覆盖 form_data 中的 radio 值
        submit_type: "0"=保存, "1"=提交

    返回: [(key, value), ...] 有序参数列表
    """
    # 合并批次级隐藏字段
    merged = dict(form_data)
    if batch_hidden_fields:
        for k, v in batch_hidden_fields.items():
            if k not in merged:
                merged[k] = v

    # 如果提供了自动填写结果，覆盖 radio 值
    if auto_fill_selections:
        for seq, val in auto_fill_selections.items():
            if seq == "_total":
                continue
            name, value = val  # val 是 (radio_name, radio_value) 元组
            merged[name] = value

    # 按指标序号分组
    indicator_groups = {}  # {seq: [(key, value), ...]}
    form_level_pairs = []  # 非指标级字段

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
            continue  # 丢弃，随后为每个指标重新生成
        else:
            form_level_pairs.append((k, v))

    # 按 seq 数值排序
    sorted_seqs = sorted(indicator_groups.keys(), key=int)

    # 构建 POST 数据：表单头部 → 每个指标(pj06xh + 分值 + radio) → 尾部(issubmit)
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


@app.route("/api/eval-courses")
def api_eval_courses():
    """解析评教课程列表页（批次点击后的第二级页面）"""
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


@app.route("/api/eval-form")
def api_eval_form():
    """解析评教表单为结构化 JSON（xspj_edit.do 页面）"""
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
            return jsonify({"success": False, "message": "教务系统拒绝了请求，请重新登录后重试"}), 403
    except Exception as e:
        return jsonify({"success": False, "message": f"请求失败: {e}"}), 500

    parsed = _parse_eval_form_page(resp.text)
    if not parsed or (not parsed.get("course_name") and not parsed.get("indicators")):
        return jsonify({"success": False, "message": "未找到评价表单内容，请返回课程列表重试"}), 500

    return jsonify({
        "success": True,
        "course_name": parsed["course_name"],
        "hidden_fields": parsed["hidden_fields"],
        "indicators": parsed["indicators"],
        "action": parsed["action"],
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
    submit_headers = dict(EVAL_HEADERS)  # 与 eval_headers 相同

    try:
        # 调试：记录收到的 form_data 中有多少 radio 值（仅在 DEBUG_EVAL 开启时）
        radio_keys = [k for k in form_data if k.startswith("pj0601id_")]
        if DEBUG_EVAL:
            debug_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "debug_submit.json")
            with open(debug_path, "w", encoding="utf-8") as f:
                json.dump({
                    "radio_count": len(radio_keys),
                    "radio_keys": radio_keys,
                    "radio_values": {k: form_data[k] for k in radio_keys},
                    "total_keys": len(form_data),
                    "all_keys": list(form_data.keys()),
                }, f, ensure_ascii=False, indent=2)

        _warm_eval_session()

        # 使用提取的有序 POST 数据构建函数（确保 pj06xh 参数顺序正确）
        post_data = _build_ordered_eval_post_data(form_data, submit_type=submit_type)

        resp = jwc_client.session.post(target_url, data=post_data, headers=submit_headers, timeout=15)

        # 调试：记录教务响应（仅在 DEBUG_EVAL 开启时）
        if DEBUG_EVAL:
            debug_path2 = os.path.join(os.path.dirname(os.path.abspath(__file__)), "debug_submit.json")
            try:
                with open(debug_path2, "r", encoding="utf-8") as f:
                    dbg = json.load(f)
            except Exception:
                dbg = {}
            dbg["post_param_order"] = [k for k, v in post_data]  # POST 参数顺序
            dbg["jw_status"] = resp.status_code
            dbg["jw_response_len"] = len(resp.text)
            dbg["jw_response_preview"] = resp.text[:500]
            # 检查各种可能的关键字
            for kw in ["评价成功", "提交成功", "保存成功", "alert", "错误", "失败", "成功", "不能", "必须"]:
                if kw in resp.text:
                    dbg.setdefault("jw_keywords_found", {})[kw] = True
            with open(debug_path2, "w", encoding="utf-8") as f:
                json.dump(dbg, f, ensure_ascii=False, indent=2)

        if "评价成功" in resp.text or "提交成功" in resp.text or "保存成功" in resp.text:
            return jsonify({"success": True, "message": "评教提交成功！"})
        return jsonify({"success": True, "message": "已提交（请返回教务确认）"})
    except Exception as e:
        return jsonify({"success": False, "message": f"提交失败: {e}"}), 500


# ============================================================
# 批量评教 — 后台 worker + API 端点
# ============================================================

def _run_batch_eval(batch_id: str, courses: list, action_path: str,
                    batch_hidden_fields: dict, target_score: float,
                    submit_type: str):
    """后台线程：逐个课程自动填写并提交评教"""
    total = len(courses)

    for i, course in enumerate(courses):
        with _batch_progress_lock:
            _batch_progress[batch_id].update({
                "current": i + 1,
                "course": course["name"],
                "status": "fetching_form",
                "message": f"正在加载 {course['name']} 的评价表单...",
            })

        try:
            # 1. 获取评价表单
            eval_target = f"http://202.119.81.112:9080{course['eval_url']}" if course["eval_url"].startswith("/") else course["eval_url"]

            with jwc_lock:
                _warm_eval_session()
                form_resp = jwc_client.session.get(eval_target, headers=EVAL_HEADERS, timeout=15)

            if "非法访问" in form_resp.text or "非法操作" in form_resp.text:
                with _batch_progress_lock:
                    _batch_progress[batch_id]["results"].append({
                        "course": course["name"],
                        "status": "failed",
                        "error": "教务系统拒绝了请求",
                    })
                continue

            parsed = _parse_eval_form_page(form_resp.text)
            if not parsed or not parsed.get("indicators"):
                with _batch_progress_lock:
                    _batch_progress[batch_id]["results"].append({
                        "course": course["name"],
                        "status": "failed",
                        "error": "无法解析评价表单",
                    })
                continue

            # 2. 自动填写
            with _batch_progress_lock:
                _batch_progress[batch_id].update({
                    "status": "auto_filling",
                    "message": f"正在为 {course['name']} 自动评分...",
                })

            selections = _auto_fill_eval_indicators(parsed["indicators"], target_score)

            # 3. 构建有序 POST 数据并提交
            with _batch_progress_lock:
                _batch_progress[batch_id].update({
                    "status": "submitting",
                    "message": f"正在提交 {course['name']} 的评价...",
                })

            # 合并表单数据和批次隐藏字段
            form_data = dict(parsed["hidden_fields"])
            form_data["issubmit"] = submit_type
            action = parsed.get("action") or action_path
            target_url = f"http://202.119.81.112:9080{action}"

            post_data = _build_ordered_eval_post_data(
                form_data,
                batch_hidden_fields=batch_hidden_fields,
                auto_fill_selections=selections,
                submit_type=submit_type,
            )

            with jwc_lock:
                _warm_eval_session()
                resp = jwc_client.session.post(target_url, data=post_data,
                                               headers=EVAL_HEADERS, timeout=15)

            # 4. 检查结果
            if "评价成功" in resp.text or "提交成功" in resp.text or "保存成功" in resp.text:
                with _batch_progress_lock:
                    _batch_progress[batch_id]["results"].append({
                        "course": course["name"],
                        "status": "success",
                        "score": round(selections.get("_total", 0), 1),
                    })
            else:
                with _batch_progress_lock:
                    _batch_progress[batch_id]["results"].append({
                        "course": course["name"],
                        "status": "failed",
                        "error": "教务未确认提交",
                    })

        except Exception as e:
            with _batch_progress_lock:
                _batch_progress[batch_id]["results"].append({
                    "course": course["name"],
                    "status": "failed",
                    "error": str(e),
                })

    # 全部完成
    with _batch_progress_lock:
        _batch_progress[batch_id].update({
            "status": "completed",
            "message": "批量评教完成",
            "done": True,
            "course": "",
        })


@app.route("/api/batch-submit-eval", methods=["POST"])
def api_batch_submit_eval():
    """一键评教：自动完成某个批次下所有未提交课程的评价"""
    if not jwc_client.logged_in:
        return jsonify({"success": False, "message": "请先登录"}), 401

    data = request.get_json()
    batch_url = data.get("batch_url", "")
    target_score = float(data.get("target_score", 95))
    submit_type = str(data.get("submit_type", "1"))

    if not batch_url:
        return jsonify({"success": False, "message": "缺少批次 URL"}), 400
    if not (0 < target_score <= 100):
        return jsonify({"success": False, "message": "目标分数需在 1~100 之间"}), 400

    # 获取批次课程列表
    target = f"http://202.119.81.112:9080{batch_url}" if batch_url.startswith("/") else batch_url

    try:
        with jwc_lock:
            _warm_eval_session()
            resp = jwc_client.session.get(target, headers=EVAL_HEADERS, timeout=15)
    except Exception as e:
        return jsonify({"success": False, "message": f"获取课程列表失败: {e}"}), 500

    if "非法访问" in resp.text or "非法操作" in resp.text:
        return jsonify({"success": False, "message": "教务系统拒绝了请求，请重新登录后重试"}), 403

    parsed = _parse_eval_courses_page(resp.text)
    if not parsed or not parsed.get("courses"):
        return jsonify({"success": False, "message": "未找到课程列表"}), 500

    # 过滤未提交的课程
    unsubmitted = [c for c in parsed["courses"] if not c.get("submitted")]
    if not unsubmitted:
        return jsonify({
            "success": True,
            "message": "所有课程已提交，无需评价",
            "total": 0,
        })

    # 生成 batch_id，初始化进度，启动后台线程
    import uuid
    batch_id = str(uuid.uuid4())[:8]

    # 从已有 api_eval_form 调用中获知 action_path（默认值）
    action_path = data.get("action_path", "/njlgdx/xspj/xspj_save.do")
    batch_hidden_fields = parsed.get("hidden_fields", {})
    # 合并请求中额外传入的隐藏字段
    if data.get("hidden_fields"):
        batch_hidden_fields.update(data["hidden_fields"])

    with _batch_progress_lock:
        _batch_progress[batch_id] = {
            "current": 0,
            "total": len(unsubmitted),
            "course": "",
            "status": "starting",
            "message": f"准备评价 {len(unsubmitted)} 门课程...",
            "done": False,
            "results": [],
            "created_at": time.time(),
        }

    thread = threading.Thread(
        target=_run_batch_eval,
        args=(batch_id, unsubmitted, action_path, batch_hidden_fields,
              target_score, submit_type),
        daemon=True,
    )
    thread.start()

    return jsonify({
        "success": True,
        "batch_id": batch_id,
        "total": len(unsubmitted),
        "message": f"已开始批量评教，共 {len(unsubmitted)} 门课程",
    })


@app.route("/api/batch-progress/<batch_id>")
def api_batch_progress(batch_id):
    """查询批量评教进度"""
    with _batch_progress_lock:
        # 清理超过 10 分钟的已完成条目
        now = time.time()
        stale_ids = [
            bid for bid, p in _batch_progress.items()
            if p.get("done") and now - p.get("created_at", 0) > 600
        ]
        for bid in stale_ids:
            del _batch_progress[bid]

        progress = _batch_progress.get(batch_id)
        if not progress:
            return jsonify({"success": False, "message": "未找到此批次"}), 404

        return jsonify({
            "success": True,
            "batch_id": batch_id,
            "current": progress["current"],
            "total": progress["total"],
            "course": progress.get("course", ""),
            "status": progress["status"],
            "message": progress["message"],
            "done": progress["done"],
            "results": progress.get("results", []),
        })


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
