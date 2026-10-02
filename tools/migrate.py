# -*- coding: utf-8 -*-
"""显式执行数据库迁移: python tools/migrate.py"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ["MIGRATIONS_AUTO"] = "1"

from wxcloudrun import _run_migrations  # noqa: E402


if __name__ == "__main__":
    applied = _run_migrations(force=True)
    print("迁移完成: " + (", ".join(applied) if applied else "无待执行迁移"))
