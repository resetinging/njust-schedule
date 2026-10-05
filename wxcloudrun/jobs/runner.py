# -*- coding: utf-8 -*-
"""统一后台任务启动器。

任务模块保留各自的循环实现，但只允许由这里按名称启动一次，避免 WSGI
入口重复导入、开发服务器重载或测试启动器造成重复线程。
"""
import threading

from wxcloudrun import app

_LOCK = threading.Lock()
_STARTED = set()


def _start_once(name: str, starter) -> bool:
    with _LOCK:
        if name in _STARTED:
            return False
        _STARTED.add(name)
    try:
        started = starter()
        if started is False:
            with _LOCK:
                _STARTED.discard(name)
            return False
        return True
    except Exception:
        with _LOCK:
            _STARTED.discard(name)
        raise


def start_all_jobs() -> dict:
    """启动所有生产后台任务；返回本次真正启动的任务名。"""
    from wxcloudrun.jobs.audit_catalog_job import start
    from wxcloudrun.jobs.exam_reminder_job import start as start_exam
    from wxcloudrun.jobs.freeclass_job import start as start_freeclass

    started = []
    for name, starter in (
        ("freeclass", start_freeclass),
        ("audit-catalog", start),
        ("exam-reminder", start_exam),
    ):
        try:
            if _start_once(name, starter):
                started.append(name)
        except Exception as exc:  # noqa: BLE001 单个任务不能阻塞 Web 启动
            app.logger.warning("[jobs] %s 启动失败: %s", name,
                               type(exc).__name__)
    return {"started": started}


def reset_for_tests() -> None:
    """测试用：清理启动注册表，不停止已运行线程。"""
    with _LOCK:
        _STARTED.clear()
