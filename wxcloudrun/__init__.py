"""
微信云托管 Flask 应用初始化
===========================
SQLAlchemy + MySQL + NJUST 路由
"""
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
import os
import pymysql
import config

# 适配 Python 3 MySQL 驱动
pymysql.install_as_MySQLdb()

# 创建 Flask 应用
app = Flask(__name__, instance_relative_config=True)
app.config['DEBUG'] = config.DEBUG
app.json.ensure_ascii = False
app.config['TEMPLATES_AUTO_RELOAD'] = True

# 数据库连接：优先使用 SQLALCHEMY_DATABASE_URI 环境变量（本地开发可用 sqlite:///xxx.db），
# 否则使用 MySQL（云托管自动注入 MYSQL_USERNAME/PASSWORD/ADDRESS 环境变量）
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get(
    'SQLALCHEMY_DATABASE_URI',
    'mysql://{}:{}@{}/flask_demo'.format(
        config.MYSQL_USERNAME, config.MYSQL_PASSWORD, config.MYSQL_ADDRESS))
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# 防止 MySQL 连接空闲超时断开（云数据库默认 8 小时，但容器冷启后旧连接失效）
app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
    'pool_pre_ping': True,   # 每次使用前检测连接是否存活
    'pool_recycle': 3600,    # 每小时回收连接，避免 MySQL wait_timeout
}

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


# 确保数据表存在（container.config.json 的 executeSQLs 可能未执行）
from wxcloudrun import model  # noqa: E402
with app.app_context():
    db.create_all()
    _migrate_student_id()


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


# 加载 NJUST 路由（必须在 db 初始化之后导入，避免循环引用）
from wxcloudrun import views  # noqa: E402, F401
