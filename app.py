"""
南理工课表管理系统 - Flask Web 应用
=====================================
提供：
  - Web 界面展示课表、考试、成绩、教学评价
  - RESTful API 接口供前端调用
  - SQLite 数据库持久化存储
  - 多设备局域网访问支持
  - pywebview 桌面窗口模式

启动方式:
  - 桌面模式: python main.py
  - Web 模式: python app.py
"""
import socket
from flask import Flask, jsonify

from config import HOST, PORT
from database import close_db, init_db


def create_app() -> Flask:
    """Flask 应用工厂"""
    app = Flask(__name__)
    app.config["JSON_AS_ASCII"] = False
    app.config["TEMPLATES_AUTO_RELOAD"] = True

    # ---- 注册数据库连接清理 ----
    app.teardown_appcontext(close_db)

    # ---- 注册蓝图 ----
    from routes.pages import pages_bp
    from routes.api_auth import auth_bp
    from routes.api_data import data_bp
    from routes.api_eval import eval_bp
    from routes.api_settings import settings_bp

    app.register_blueprint(pages_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(data_bp)
    app.register_blueprint(eval_bp)
    app.register_blueprint(settings_bp)

    # ---- 上下文注入（模板全局变量） ----
    from routes import get_lan_ip

    @app.context_processor
    def inject_global():
        return {"lan_ip": get_lan_ip(), "port": PORT}

    # ---- 错误处理 ----
    @app.errorhandler(404)
    def not_found(e):
        return jsonify({"error": "页面不存在"}), 404

    @app.errorhandler(500)
    def server_error(e):
        return jsonify({"error": "服务器内部错误"}), 500

    return app


# 模块级 app 实例（兼容 main.py 和直接 python app.py 启动）
app = create_app()

if __name__ == "__main__":
    init_db()
    print(f"南理工课表管理系统 - http://127.0.0.1:{PORT}")
    app.run(host="127.0.0.1", port=PORT, debug=False, threaded=True)
