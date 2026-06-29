# -*- mode: python ; coding: utf-8 -*-
"""
南理工课表管理系统 — PyInstaller 打包配置
==========================================
使用方法:
    pyinstaller njust_schedule.spec

输出位置:
    dist/南理工课表管理/南理工课表管理.exe
"""

import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files

ROOT = Path(SPECPATH)

# ---- 图标 ----
# PyInstaller on Windows needs .ico format
icon_path = str(ROOT / "static" / "icon-512.png")
ico_path = str(ROOT / "static" / "app.ico")
if Path(ico_path).exists():
    icon_path = ico_path  # prefer .ico if it exists

# ---- 收集数据文件 ----
# ddddocr 的 .onnx 模型文件（PyInstaller 不会自动收集）
ddddocr_datas = collect_data_files('ddddocr')
# onnxruntime 的 DLL 等
onnx_datas = collect_data_files('onnxruntime')

# ============================================================
# Analysis — 收集所有依赖
# ============================================================
a = Analysis(
    [str(ROOT / "main.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=[
        (str(ROOT / "templates"), "templates"),
        (str(ROOT / "static"), "static"),
    ] + ddddocr_datas + onnx_datas,
    hiddenimports=[
        # Flask 全家桶
        "flask", "flask.json.provider", "flask.cli",
        "werkzeug", "werkzeug.debug", "werkzeug.serving",
        "jinja2", "jinja2.ext", "markupsafe",
        "click", "itsdangerous", "blinker",
        # HTTP
        "requests", "urllib3", "urllib3.packages",
        "certifi", "charset_normalizer", "idna",
        # HTML 解析
        "bs4", "bs4.builder._lxml",
        "lxml", "lxml.etree", "lxml._elementpath", "lxml.html",
        # OCR (ddddocr + onnxruntime + numpy)
        "ddddocr", "onnxruntime", "onnxruntime.capi",
        "onnxruntime.transformers", "onnxruntime.tools",
        "numpy", "numpy.core", "numpy.linalg", "numpy.fft",
        # 图像
        "PIL", "PIL.Image", "PIL._imaging", "PIL._webp",
        "PIL.ImageDraw", "PIL.ImageFont", "PIL.ImageFilter",
        # 桌面窗口（pywebview + pythonnet）
        "webview", "webview.js", "webview.platforms.winforms",
        "clr", "pythonnet", "clr_loader",
        # 标准库常被遗漏的
        "logging.handlers", "json.encoder",
        "webbrowser",
        "sqlite3.dbapi2", "sqlite3.dump",
        "http.cookies", "http.server",
        "importlib.metadata", "importlib.resources",
        "platform", "uuid",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # 不可能用到的庞大库
        "tkinter", "tcl", "tk",
        "matplotlib", "scipy", "pandas",
        "jupyter", "ipykernel", "notebook",
        "sphinx", "pytest", "setuptools", "pip",
        "lib2to3",
        "PyQt5", "PyQt6", "PySide2", "PySide6",
        "wx", "gtk", "cairo",
        "tornado", "twisted", "aiohttp",
        "curses", "readline",
        "doctest", "pdb", "profile",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=None,
    noarchive=False,
)

# ============================================================
# PYZ
# ============================================================
pyz = PYZ(a.pure, a.zipped_data, cipher=None)

# ============================================================
# EXE
# ============================================================
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="南理工课表管理",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,          # EXE 层面不压缩，COLLECT 层面压缩
    console=False,      # ★ 无控制台窗口
    icon=icon_path if Path(ico_path).exists() else None,
)

# ============================================================
# COLLECT — 收集到输出目录
# ============================================================
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,           # UPX 压缩 DLL / PYD
    upx_exclude=[],
    name="南理工课表管理",
)
