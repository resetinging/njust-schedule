"""
南理工课表管理系统 — 桌面窗口入口
================================
使用 pywebview 将 Flask 应用嵌入原生桌面窗口。
支持 PyInstaller 打包为独立 EXE。

启动方式:
  - 开发模式: python main.py
  - 仅后端:   python app.py  (浏览器打开 http://127.0.0.1:5000)
  - 打包后:   直接运行 EXE
"""

import os
import sys
import threading
import multiprocessing
import webview


def _get_base_dir():
    """获取应用根目录（兼容开发模式和 PyInstaller 打包模式）"""
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    else:
        return os.path.dirname(os.path.abspath(__file__))


def _get_resource_dir():
    """获取资源目录（模板、静态文件）"""
    if getattr(sys, 'frozen', False):
        return sys._MEIPASS
    else:
        return os.path.dirname(os.path.abspath(__file__))


# === 初始化路径 ===
BASE_DIR = _get_base_dir()
RESOURCE_DIR = _get_resource_dir()

os.environ.setdefault("NJUST_DB_DIR", BASE_DIR)

from app import app, init_db

# 覆盖 Flask 模板和静态文件路径（PyInstaller 打包后资源在 _MEIPASS）
app.template_folder = os.path.join(RESOURCE_DIR, "templates")
app.static_folder = os.path.join(RESOURCE_DIR, "static")


def start_flask():
    """后台线程启动 Flask，绑定所有接口（桌面窗口 + 手机均可访问）"""
    app.run(host="0.0.0.0", port=5000, debug=False, threaded=True)


if __name__ == "__main__":
    multiprocessing.freeze_support()
    init_db()

    # 启动 Flask 后台线程
    flask_thread = threading.Thread(target=start_flask, daemon=True)
    flask_thread.start()

    # 创建桌面窗口
    webview.create_window(
        title="南理工课表管理",
        url="http://127.0.0.1:5000",
        width=1280,
        height=800,
        min_size=(900, 600),
        text_select=True,
    )

    webview.start()
    sys.exit(0)
