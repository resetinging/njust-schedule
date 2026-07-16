"""
南理工课表管理系统 — 数据库管理
==============================
SQLite 数据库初始化、连接管理和数据持久化。
"""
import sqlite3
import json
import os

from flask import g

from config import DB_FILENAME

BASE_DIR = os.environ.get("NJUST_DB_DIR", os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(BASE_DIR, DB_FILENAME)


def get_db() -> sqlite3.Connection:
    """获取数据库连接（Flask 请求上下文）"""
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA journal_mode=WAL")
    return g.db


def close_db(exception=None):
    """请求结束后关闭数据库（注册为 teardown_appcontext 回调）"""
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

        CREATE TABLE IF NOT EXISTS grades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            academic_year TEXT DEFAULT '',
            semester TEXT DEFAULT '',
            course_code TEXT DEFAULT '',
            course_name TEXT NOT NULL,
            score TEXT DEFAULT '',
            credit REAL DEFAULT 0,
            grade_point REAL DEFAULT 0,
            course_type TEXT DEFAULT '',
            course_nature TEXT DEFAULT '',
            exam_type TEXT DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_grades_semester
            ON grades(academic_year, semester);

        CREATE TABLE IF NOT EXISTS cet_scores (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            cet_type TEXT NOT NULL,
            total_score REAL DEFAULT 0,
            exam_date TEXT DEFAULT '',
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
            ('refresh_interval', '3600'),
            ('jwc_password_enc', '');
    """)
    db.commit()
    db.close()

    # 迁移：为旧数据库添加 course_nature 列
    _migrate_add_column("grades", "course_nature", "TEXT DEFAULT ''")


def _migrate_add_column(table: str, column: str, col_def: str):
    """安全添加列（SQLite 不支持 IF NOT EXISTS，忽略重复列错误）"""
    try:
        db = sqlite3.connect(DB_PATH)
        db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_def}")
        db.commit()
        db.close()
    except sqlite3.OperationalError:
        pass  # 列已存在


# ---- 设置读写 ----

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


# ---- 数据保存 ----

def save_courses_to_db(courses: list[dict], semester: str):
    """将课表数据保存到数据库"""
    db = get_db()
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


def save_grades_to_db(grades: list[dict], academic_year: str, semester: str):
    """将成绩数据保存到数据库"""
    db = get_db()
    db.execute(
        "DELETE FROM grades WHERE academic_year = ? AND semester = ?",
        (academic_year, semester),
    )
    for g in grades:
        db.execute(
            """INSERT INTO grades
               (academic_year, semester, course_code, course_name,
                score, credit, grade_point, course_type, course_nature, exam_type)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                g.get("academic_year", academic_year),
                g.get("semester", semester),
                g.get("course_code", ""),
                g.get("course_name", ""),
                str(g.get("score", "")),
                float(g.get("credit", 0) or 0),
                float(g.get("grade_point", 0) or 0),
                g.get("course_type", ""),
                g.get("course_nature", ""),
                g.get("exam_type", "正常考试"),
            ),
        )
    db.commit()


# ---- 等级考试（四六级） ----

def save_cet_scores(scores: list[dict]):
    """保存四六级成绩（替换全部已有记录）"""
    db = get_db()
    db.execute("DELETE FROM cet_scores")
    for s in scores:
        db.execute(
            """INSERT INTO cet_scores (cet_type, total_score, exam_date)
               VALUES (?, ?, ?)""",
            (s.get("type", ""), float(s.get("score", 0)), s.get("exam_date", "")),
        )
    db.commit()


def get_cet_scores() -> list[dict]:
    """获取已存储的四六级成绩（每种类型取最高分）"""
    db = get_db()
    rows = db.execute(
        """SELECT cet_type, MAX(total_score) AS total_score, exam_date
           FROM cet_scores GROUP BY cet_type
           ORDER BY cet_type"""
    ).fetchall()
    return [
        {"type": r["cet_type"], "score": r["total_score"], "exam_date": r["exam_date"] or ""}
        for r in rows
    ]
