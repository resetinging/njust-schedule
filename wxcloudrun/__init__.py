"""
微信云托管 Flask 应用初始化
===========================
SQLAlchemy + MySQL + 教务路由
"""
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
import os
import pymysql
import config

config.validate()

# 适配 Python 3 MySQL 驱动
pymysql.install_as_MySQLdb()

# 创建 Flask 应用
app = Flask(__name__, instance_relative_config=True)
app.config['DEBUG'] = config.DEBUG
app.json.ensure_ascii = False
app.config['TEMPLATES_AUTO_RELOAD'] = True

# 数据库连接：优先使用 SQLALCHEMY_DATABASE_URI 环境变量（本地开发可用 sqlite:///xxx.db），
# 否则必须完整提供 MySQL 环境变量。生产环境缺失配置时直接失败，避免回退到弱默认凭据。
_db_uri = os.environ.get('SQLALCHEMY_DATABASE_URI', '').strip()
if not _db_uri:
    _missing_db_env = [
        name for name, value in (
            ("MYSQL_USERNAME", config.MYSQL_USERNAME),
            ("MYSQL_PASSWORD", config.MYSQL_PASSWORD),
            ("MYSQL_ADDRESS", config.MYSQL_ADDRESS),
        ) if not value
    ]
    if _missing_db_env:
        raise RuntimeError(
            "数据库未配置: 请设置 SQLALCHEMY_DATABASE_URI，或完整设置 "
            + ", ".join(_missing_db_env)
        )
    _db_uri = 'mysql://{}:{}@{}/flask_demo'.format(
        config.MYSQL_USERNAME, config.MYSQL_PASSWORD, config.MYSQL_ADDRESS)
app.config['SQLALCHEMY_DATABASE_URI'] = _db_uri
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# 防止 MySQL 连接空闲超时断开（云数据库默认 8 小时，但容器冷启后旧连接失效）；
# 连接池 10 + 溢出 10: 控制面板重聚合/小程序批量刷新并发时避免池耗尽
# (池耗尽会让请求线程阻塞等待连接, 叠加长连接占用即表现为整站卡死)。
# 注意: pool_size/max_overflow 仅 MySQL 队列池支持, SQLite(NullPool) 会拒绝, 故按 URI 区分
_engine_opts = {
    'pool_pre_ping': True,   # 每次使用前检测连接是否存活
    'pool_recycle': 3600,    # 每小时回收连接，避免 MySQL wait_timeout
}
if not os.environ.get("SQLALCHEMY_DATABASE_URI", "").startswith("sqlite"):
    _engine_opts.update({
        'pool_size': 10,
        'max_overflow': 10,
        'pool_timeout': 10,  # 取连接最长等待 10s, 超时报错而不是无限挂起
    })
app.config['SQLALCHEMY_ENGINE_OPTIONS'] = _engine_opts

# 初始化 SQLAlchemy
db = SQLAlchemy(app)


def _migrate_student_id():
    """存量库迁移：为业务表补充 student_id 列与索引（多用户改造）。

    旧版本的表没有该列；新模型 create_all 不会自动加列，
    这里用 ALTER TABLE 补上（MySQL / SQLite 均支持）。
    旧数据 student_id 为空，查询时会被过滤（用户重新刷新即可重建）。
    """
    from sqlalchemy import inspect as sa_inspect, text as sa_text
    tables = ["courses", "exams", "evaluations", "grades", "cet_scores"]
    insp = sa_inspect(db.engine)
    for tbl_name in tables:
        if not insp.has_table(tbl_name):
            continue
        cols = [c["name"] for c in insp.get_columns(tbl_name)]
        if "student_id" not in cols:
            with db.engine.begin() as conn:
                conn.execute(sa_text(
                    f"ALTER TABLE `{tbl_name}` "
                    "ADD COLUMN student_id VARCHAR(50) DEFAULT ''"
                ))
            app.logger.info("[migrate] %s 已补充 student_id 列", tbl_name)
        # 存量库补索引（新库由 create_all 的 index=True 自动创建）
        idx_names = {i["name"] for i in insp.get_indexes(tbl_name)}
        if not any("student_id" in n for n in idx_names):
            with db.engine.begin() as conn:
                conn.execute(sa_text(
                    f"CREATE INDEX ix_{tbl_name}_student_id "
                    f"ON `{tbl_name}` (student_id)"
                ))
            app.logger.info("[migrate] %s 已创建 student_id 索引", tbl_name)


def _migrate_feedback_reply():
    """存量库迁移：feedback 表补充"管理员回复"相关列。

    新模型 create_all 不会给已存在的表加列；旧库缺少 reply/replied_at/reply_read,
    用户端读取回复会直接报错, 故用 ALTER TABLE 补齐(MySQL / SQLite 均支持)。
    """
    from sqlalchemy import inspect as sa_inspect, text as sa_text
    insp = sa_inspect(db.engine)
    if not insp.has_table("feedback"):
        return
    cols = [c["name"] for c in insp.get_columns("feedback")]
    stmts = []
    if "reply" not in cols:
        stmts.append("ALTER TABLE `feedback` ADD COLUMN reply VARCHAR(500) DEFAULT ''")
    if "replied_at" not in cols:
        stmts.append("ALTER TABLE `feedback` ADD COLUMN replied_at TIMESTAMP NULL")
    if "reply_read" not in cols:
        # 用 BOOLEAN 而非 TINYINT(1): MySQL 下 BOOLEAN 即 TINYINT(1)(与模型一致),
        # SQLite 下 TINYINT(1) 会在反射时报 SAWarning、BOOLEAN 则不会
        stmts.append("ALTER TABLE `feedback` ADD COLUMN reply_read BOOLEAN DEFAULT 0")
    for sql in stmts:
        try:
            with db.engine.begin() as conn:
                conn.execute(sa_text(sql))
            app.logger.info("[migrate] feedback 已补充列: %s", sql)
        except Exception as e:
            # 滚动更新时可能多个容器同时启动, 另一个实例已加过列 → 忽略重复列错误,
            # 不能让迁移异常冒泡: 它在导入期执行, 抛出会导致容器起不来(崩溃循环)
            app.logger.warning("[migrate] feedback 补列跳过(可能已被其他实例补充): %s", e)


def _migrate_audit_class_info():
    """存量库迁移：蹭课目录补充 class_info 列。"""
    from sqlalchemy import inspect as sa_inspect, text as sa_text
    insp = sa_inspect(db.engine)
    if not insp.has_table("audit_courses"):
        return
    cols = [c["name"] for c in insp.get_columns("audit_courses")]
    if "class_info" in cols:
        return
    try:
        with db.engine.begin() as conn:
            conn.execute(sa_text(
                "ALTER TABLE `audit_courses` "
                "ADD COLUMN class_info TEXT"
            ))
        app.logger.info("[migrate] audit_courses 已补充 class_info 列")
    except Exception as e:
        # 滚动更新时可能已由其他实例补充，重复列错误不能阻塞启动。
        app.logger.warning("[migrate] audit_courses 补列跳过: %s", e)


def _audit_class_info_text_statements(insp):
    """返回需要执行的 class_info 扩长 DDL，便于单测验证 MySQL 分支。"""
    from sqlalchemy import String, Text

    statements = []
    for table in ("audit_courses", "audit_favorites"):
        if not insp.has_table(table):
            continue
        columns = {
            col.get("name"): col.get("type")
            for col in insp.get_columns(table)
        }
        col_type = columns.get("class_info")
        type_name = type(col_type).__name__.upper()
        is_text_family = isinstance(col_type, Text) or "TEXT" in type_name
        if isinstance(col_type, String) and not is_text_family:
            statements.append(
                f"ALTER TABLE `{table}` MODIFY COLUMN class_info TEXT NULL")
    return statements


def _migrate_audit_class_info_text():
    """MySQL 存量库：把蹭课目录和收藏的 class_info 扩展为 TEXT。"""
    from sqlalchemy import inspect as sa_inspect, text as sa_text

    if db.engine.dialect.name != "mysql":
        return
    insp = sa_inspect(db.engine)
    statements = _audit_class_info_text_statements(insp)
    if not statements:
        return
    try:
        with db.engine.begin() as conn:
            for sql in statements:
                conn.execute(sa_text(sql))
        app.logger.info(
            "[migrate] audit class_info 已扩展为 TEXT: %s",
            ", ".join(statements))
    except Exception as e:
        app.logger.warning("[migrate] audit class_info 扩长跳过: %s", e)
        raise


def _migrate_user_settings():
    """把旧 settings 表中的 {sid}:{key} 行迁移到独立 user_settings 表。"""
    from sqlalchemy import inspect as sa_inspect
    from wxcloudrun.model import Setting, UserSetting

    insp = sa_inspect(db.engine)
    if not (insp.has_table("settings") and insp.has_table("user_settings")):
        return
    rows = Setting.query.filter(Setting.k.like("%:%")).all()
    moved = 0
    for row in rows:
        sid, key = str(row.k or "").split(":", 1)
        if not sid or not key:
            continue
        current = UserSetting.query.filter(
            UserSetting.student_id == sid,
            UserSetting.k == key,
        ).first()
        if current is None:
            db.session.add(UserSetting(student_id=sid, k=key, v=row.v or ""))
        db.session.delete(row)
        moved += 1
        if moved % 500 == 0:
            db.session.commit()
    if moved:
        db.session.commit()
        app.logger.info("[migrate] user_settings 迁移完成 rows=%d", moved)


def _migrate_audit_course_rooms():
    """修正存量蹭课目录中把教室编号写入教师列的数据。"""
    import re as _re
    import time as _time
    from wxcloudrun.model import AuditCourse, Setting

    pattern = _re.compile(r'(?:设传外教|设传教室|设传实验)\s*\d+$')
    rows = AuditCourse.query.filter(
        AuditCourse.classroom == "",
        AuditCourse.teacher != "",
    ).all()
    changed = 0
    affected_semesters = set()
    for row in rows:
        teacher = str(row.teacher or "").strip()
        if not pattern.fullmatch(teacher):
            continue
        row.classroom = teacher
        row.teacher = ""
        affected_semesters.add(str(row.semester or ""))
        changed += 1
    if changed:
        for semester in affected_semesters:
            if not semester:
                continue
            key = f"audit_catalog_at:{semester}"
            setting = Setting.query.filter(Setting.k == key).first()
            if setting:
                setting.v = str(int(_time.time()))
            else:
                db.session.add(Setting(k=key, v=str(int(_time.time()))))
        db.session.commit()
        app.logger.info("[migrate] audit_courses 教室挪列完成 rows=%d", changed)


_PERF_INDEXES = (
    ("courses", "ix_courses_user_semester_day",
     ("student_id", "semester", "day_of_week", "start_period")),
    ("exams", "ix_exams_user_semester_date",
     ("student_id", "semester", "exam_date")),
    ("grades", "ix_grades_user_year_semester",
     ("student_id", "academic_year", "semester")),
    ("evaluations", "ix_evaluations_user_end",
     ("student_id", "end_date")),
    ("cet_scores", "ix_cet_user_type_score",
     ("student_id", "cet_type", "total_score")),
)


def _ensure_perf_indexes():
    """为高频多用户查询补充复合索引; 幂等, 失败不阻塞容器启动。"""
    from sqlalchemy import inspect as sa_inspect, text as sa_text

    for table, index_name, columns in _PERF_INDEXES:
        try:
            insp = sa_inspect(db.engine)
            if not insp.has_table(table):
                continue
            indexes = insp.get_indexes(table)
            if any(i.get("name") == index_name for i in indexes):
                continue
            wanted = list(columns)
            if any(list(i.get("column_names") or []) == wanted for i in indexes):
                continue
            quoted_cols = ", ".join(f"`{c}`" for c in columns)
            with db.engine.begin() as conn:
                conn.execute(sa_text(
                    f"CREATE INDEX `{index_name}` ON `{table}` ({quoted_cols})"
                ))
            app.logger.info("[migrate] %s 已创建性能索引 %s", table, index_name)
        except Exception as e:
            # 滚动发布时可能多个实例同时建索引, 或旧库权限不足; 不能影响启动。
            app.logger.warning("[migrate] 性能索引跳过 %s.%s: %s",
                               table, index_name, e)


from wxcloudrun import model  # noqa: E402
from wxcloudrun.model import SchemaMigration  # noqa: E402


def _with_migration_lock(fn):
    """MySQL 下使用命名锁避免多实例同时执行 DDL。"""
    from sqlalchemy import text as sa_text

    dialect = db.engine.dialect.name
    if dialect != "mysql":
        return fn()
    lock_name = "njust_schedule_schema_migration"
    with db.engine.connect() as conn:
        conn.execute(sa_text("SELECT GET_LOCK(:name, 30)"), {"name": lock_name})
        try:
            return fn()
        finally:
            conn.execute(sa_text("SELECT RELEASE_LOCK(:name)"), {"name": lock_name})


_SCHEMA_MIGRATIONS = (
    ("0001_student_id", _migrate_student_id),
    ("0002_feedback_reply", _migrate_feedback_reply),
    ("0003_audit_class_info", _migrate_audit_class_info),
    ("0004_user_settings", _migrate_user_settings),
    ("0005_perf_indexes", _ensure_perf_indexes),
    ("0006_audit_course_rooms", _migrate_audit_course_rooms),
    ("0007_audit_class_info_text", _migrate_audit_class_info_text),
)


def _verify_schema():
    """自动迁移关闭时只做只读检查, Schema 缺失立即失败。"""
    from sqlalchemy import inspect as sa_inspect
    insp = sa_inspect(db.engine)
    required = {
        "courses", "exams", "evaluations", "grades", "cet_scores",
        "settings", "user_settings", "feedback", "audit_courses",
        "audit_favorites", "schema_migrations", "usage_events",
        "usage_user_daily", "usage_slot_user_daily",
    }
    missing = sorted(t for t in required if not insp.has_table(t))
    if missing:
        raise RuntimeError(
            "数据库 Schema 未迁移: " + ", ".join(missing)
            + "；请先运行 python tools/migrate.py")


def _run_migrations(force: bool = False):
    """幂等迁移入口。生产可关闭自动迁移并显式执行 tools/migrate.py。"""
    with app.app_context():
        db.create_all()
        if not (force or config.MIGRATIONS_AUTO):
            _verify_schema()
            return []
        applied = []

        def _run():
            for version, fn in _SCHEMA_MIGRATIONS:
                existing = SchemaMigration.query.filter(
                    SchemaMigration.version == version).first()
                if existing is not None:
                    continue
                fn()
                db.session.add(SchemaMigration(version=version))
                db.session.commit()
                applied.append(version)
                app.logger.info("[migrate] applied %s", version)
            return applied

        return _with_migration_lock(_run)


with app.app_context():
    if config.MIGRATIONS_AUTO:
        _run_migrations()
    else:
        _verify_schema()


# gzip 压缩文本响应（JSON/HTML/JS/CSS, >500 字节）: 移动网络下显著提速
import gzip as _gzip
import io as _io

@app.after_request
def _gzip_response(resp):
    from flask import request as _fr
    if "gzip" not in (_fr.headers.get("Accept-Encoding") or "").lower():
        return resp
    if getattr(resp, "direct_passthrough", False):
        return resp
    ct = resp.headers.get("Content-Type") or ""
    if not ct.startswith(("application/json", "text/", "application/javascript")):
        return resp
    data = resp.get_data()
    if len(data) < 500:
        return resp
    buf = _io.BytesIO()
    with _gzip.GzipFile(fileobj=buf, mode="wb", compresslevel=6) as f:
        f.write(data)
    resp.set_data(buf.getvalue())
    resp.headers["Content-Encoding"] = "gzip"
    resp.headers["Content-Length"] = str(len(resp.get_data()))
    resp.headers["Vary"] = "Accept-Encoding"
    return resp


# 静态资源长缓存（仅非 DEBUG 模式；Flask 会校验 Last-Modified/ETag，
# 文件变化时仍能 304/重新拉取）
if not config.DEBUG:
    from flask import request as _flask_request

    @app.after_request
    def _cache_static(resp):
        if _flask_request.path.startswith("/static/"):
            resp.cache_control.max_age = 86400
            resp.cache_control.public = True
        return resp


# 加载 教务路由（必须在 db 初始化之后导入，避免循环引用）
from wxcloudrun import views  # noqa: E402, F401
# 管理控制面板路由(依赖 views 的会话池, 函数内延迟访问)
from wxcloudrun import admin  # noqa: E402, F401
