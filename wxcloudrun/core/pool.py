# -*- coding: utf-8 -*-
"""教务访问池: 同一用户串行(实例锁) + 全局并发限流(信号量)。"""
import threading
from contextlib import contextmanager

JW_MAX_CONCURRENT = 4
try:
    import os
    JW_MAX_CONCURRENT = int(os.environ.get("JW_MAX_CONCURRENT", "4"))
except Exception:  # pragma: no cover
    pass

_jw_semaphore = threading.BoundedSemaphore(JW_MAX_CONCURRENT)


@contextmanager
def _jwc_request(client):
    """访问池入口: 同一用户串行(实例锁) + 全局并发限流(信号量)。"""
    with client._lock:
        with _jw_semaphore:
            yield client


@contextmanager
def _jwc_request_priority(client):
    """登录/验证码请求的优先通道: 仅实例锁串行, 不参与全局信号量排队。

    验证码时效仅几十秒, 若与其他用户的数据刷新一起排队, 轮到执行时
    验证码已过期 — 表现为"验证码一直不正确"。登录请求量极小,
    不限流风险可控。
    """
    with client._lock:
        yield client
