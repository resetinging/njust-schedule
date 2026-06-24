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
    """代理教务系统页面，解决跨域和 Cookie 问题"""
    if not jwc_client.logged_in:
        return "请先登录教务系统", 401
    target_url = f"http://202.119.81.112:9080/njlgdx/{target_path}"
    qs = request.query_string.decode()
    if qs:
        target_url += "?" + qs
    proxy_headers = {
        "Referer": "http://202.119.81.112:9080/njlgdx/",
        "Origin": "http://202.119.81.112:9080",
    }
    try:
        if request.method == "POST":
            resp = jwc_client.session.post(target_url, data=request.form,
                                           headers=proxy_headers, timeout=15)
        else:
            resp = jwc_client.session.get(target_url, headers=proxy_headers, timeout=15)
    except Exception as e:
        return f"代理请求失败: {e}", 502
    if "text/html" in (resp.headers.get("content-type") or ""):
        content = resp.text
        content = content.replace('src="/njlgdx/', 'src="/proxy/jw/')
        content = content.replace('href="/njlgdx/', 'href="/proxy/jw/')
        content = content.replace("src='/njlgdx/", "src='/proxy/jw/")
        content = content.replace("href='/njlgdx/", "href='/proxy/jw/")
        content = content.replace('action="/njlgdx/', 'action="/proxy/jw/')
        content = content.replace("action='/njlgdx/", "action='/proxy/jw/")
        content = content.replace('"/njlgdx/js/', '"/proxy/jw/js/')
        content = content.replace("'/njlgdx/js/", "'/proxy/jw/js/")
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

    return jsonify({
        "logged_in": jwc_client.logged_in,
        "student_id": student_id,
        "student_name": student_name or jwc_client.student_name or "",
        "semester": semester or jwc_client._current_semester(),
        "has_courses": has_courses,
        "has_exams": has_exams,
        "login_method": jwc_client.login_method or "",
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
        return _on_login_success(student_id)
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
        return _on_login_success(student_id)
    else:
        return jsonify({
            "success": False,
            "message": jwc_client.last_error or "登录失败，请检查验证码是否正确",
        }), 401


def _on_login_success(student_id: str):
    """登录成功后的公共处理"""
    set_setting("student_id", student_id)
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
    """检查登录状态，未登录返回错误响应，已登录返回 None"""
    if not jwc_client.logged_in:
        student_id = get_setting("student_id")
        if not student_id:
            return jsonify({
                "success": False,
                "message": "尚未登录，请先在设置页面登录教务系统",
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
