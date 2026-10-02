# -*- coding: utf-8 -*-
"""教务访问池: 同一用户串行(实例锁) + 全局并发限流(信号量)。"""
import logging
import threading
from contextlib import contextmanager

logger = logging.getLogger(__name__)

JW_MAX_CONCURRENT = 4
try:
    import os
    JW_MAX_CONCURRENT = int(os.environ.get("JW_MAX_CONCURRENT", "4"))
except Exception:  # pragma: no cover
    pass

_jw_semaphore = threading.BoundedSemaphore(JW_MAX_CONCURRENT)


def _operation_label() -> str:
    try:
        from flask import request
        return f"{request.method} {request.path}"
    except Exception:
        return threading.current_thread().name


def _log_jw_access(client, before_count: int, before_targets: dict) -> None:
    """输出本次访问池上下文的真实教务 HTTP 增量。"""
    after_count = int(getattr(client, "_jw_http_count", 0))
    delta = max(0, after_count - before_count)
    if delta <= 0:
        return
    try:
        from wxcloudrun.core.web import _rid
        rid = _rid()
    except Exception:
        rid = "-"
    targets = getattr(client, "_jw_http_targets", {}) or {}
    changed = []
    for target, count in sorted(targets.items()):
        extra = count - int(before_targets.get(target, 0))
        if extra > 0:
            changed.append(f"{target} x{extra}")
    logger.info("[jw-access] rid=%s sid=%s op=%s count=%d targets=%s",
                rid, getattr(client, "student_id", "") or "-",
                _operation_label(), delta, "; ".join(changed[:12]) or "-")


@contextmanager
def _jwc_request(client):
    """访问池入口: 同一用户串行(实例锁) + 全局并发限流(信号量)。"""
    before_count = int(getattr(client, "_jw_http_count", 0))
    before_targets = dict(getattr(client, "_jw_http_targets", {}) or {})
    with client._lock:
        try:
            with _jw_semaphore:
                yield client
        finally:
            _log_jw_access(client, before_count, before_targets)


@contextmanager
def _jwc_request_priority(client):
    """登录/验证码请求的优先通道: 仅实例锁串行, 不参与全局信号量排队。

    验证码时效仅几十秒, 若与其他用户的数据刷新一起排队, 轮到执行时
    验证码已过期 — 表现为"验证码一直不正确"。登录请求量极小,
    不限流风险可控。
    """
    before_count = int(getattr(client, "_jw_http_count", 0))
    before_targets = dict(getattr(client, "_jw_http_targets", {}) or {})
    with client._lock:
        try:
            yield client
        finally:
            _log_jw_access(client, before_count, before_targets)
