"""
微信云托管 Flask 应用初始化
===========================
SQLAlchemy + MySQL + NJUST 路由
"""
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
import pymysql
import config

# 适配 Python 3 MySQL 驱动
pymysql.install_as_MySQLdb()

# 创建 Flask 应用
app = Flask(__name__, instance_relative_config=True)
app.config['DEBUG'] = config.DEBUG
app.config['JSON_AS_ASCII'] = False
app.config['TEMPLATES_AUTO_RELOAD'] = True

# MySQL 连接（云托管自动注入 MYSQL_USERNAME/PASSWORD/ADDRESS 环境变量）
app.config['SQLALCHEMY_DATABASE_URI'] = 'mysql://{}:{}@{}/flask_demo'.format(
    config.MYSQL_USERNAME, config.MYSQL_PASSWORD, config.MYSQL_ADDRESS)
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# 初始化 SQLAlchemy
db = SQLAlchemy(app)

# 确保数据表存在（container.config.json 的 executeSQLs 可能未执行）
from wxcloudrun import model  # noqa: E402
with app.app_context():
    db.create_all()

# 加载 NJUST 路由（必须在 db 初始化之后导入，避免循环引用）
from wxcloudrun import views  # noqa: E402, F401
