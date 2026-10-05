# -*- coding: utf-8 -*-
"""pytest 测试环境：由测试进程显式负责创建临时 SQLite Schema。"""
import os


# 生产默认关闭自动迁移；单元测试使用内存 SQLite，显式调用迁移入口建表。
os.environ.setdefault("SQLALCHEMY_DATABASE_URI", "sqlite:///:memory:")
os.environ.setdefault("SESSION_KEY", "MDEyMzQ1Njc4OWFiY2RlZjAxMjM0NTY3ODlhYmNkZWY=")
os.environ.setdefault("MIGRATIONS_AUTO", "0")
os.environ.setdefault("SCHEMA_CHECK_ON_STARTUP", "0")

from wxcloudrun import _run_migrations  # noqa: E402

_run_migrations(force=True)
