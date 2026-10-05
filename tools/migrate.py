# -*- coding: utf-8 -*-
"""显式执行数据库迁移: python tools/migrate.py

应用启动不会再自动执行 DDL。本脚本是唯一的迁移入口，应该在部署阶段以
单实例方式运行，并确认成功后再滚动更新 Web 服务。
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
# 导入 wxcloudrun 时跳过只读 Schema 检查，并关闭导入期自动迁移；
# 迁移只在脚本 main 中通过 force=True 显式执行一次。
os.environ["MIGRATIONS_AUTO"] = "0"
os.environ["SCHEMA_CHECK_ON_STARTUP"] = "0"

from wxcloudrun import _run_migrations  # noqa: E402


if __name__ == "__main__":
    applied = _run_migrations(force=True)
    print("迁移完成: " + (", ".join(applied) if applied else "无待执行迁移"))
