# -*- coding: utf-8 -*-
"""进程内/Redis 双模式限流与客户端 IP 解析。"""
import threading
import time

from flask import request

from config import TRUSTED_PROXY_HOPS as _TRUSTED_PROXY_HOPS

_RATE_BUCKETS = {}
_RATE_LOCK = threading.Lock()
TRUSTED_PROXY_HOPS = max(1, int(_TRUSTED_PROXY_HOPS))


def prune_locked(max_keys: int = 5000) -> None:
    while len(_RATE_BUCKETS) > max_keys:
        _RATE_BUCKETS.pop(next(iter(_RATE_BUCKETS)), None)


def rate_limited(key: str, limit: int, window: float = 60.0) -> bool:
    from wxcloudrun.core import state
    if state.enabled():
        if state.rate_over(key, limit, window):
            return True
        if state.rate_hit(key, window):
            return False
    now = time.time()
    with _RATE_LOCK:
        hits = [t for t in _RATE_BUCKETS.get(key, []) if now - t < window]
        if len(hits) >= limit:
            _RATE_BUCKETS[key] = hits
            return True
        hits.append(now)
        _RATE_BUCKETS[key] = hits
        prune_locked()
    return False


def rate_over(key: str, limit: int, window: float = 60.0) -> bool:
    from wxcloudrun.core import state
    if state.enabled():
        return state.rate_over(key, limit, window)
    now = time.time()
    with _RATE_LOCK:
        hits = [t for t in _RATE_BUCKETS.get(key, []) if now - t < window]
        _RATE_BUCKETS[key] = hits
        prune_locked()
        return len(hits) >= limit


def rate_hit(key: str) -> None:
    from wxcloudrun.core import state
    if state.enabled():
        window = 300 if key.startswith("loginfail:sid:") else 60
        if state.rate_hit(key, window):
            return
    with _RATE_LOCK:
        _RATE_BUCKETS.setdefault(key, []).append(time.time())


def rate_clear(key: str) -> None:
    from wxcloudrun.core import state
    if state.enabled():
        state.rate_clear(key)
        return
    with _RATE_LOCK:
        _RATE_BUCKETS.pop(key, None)


def client_ip() -> str:
    xff = request.headers.get("X-Forwarded-For") or ""
    parts = [p.strip() for p in xff.split(",") if p.strip()]
    if parts:
        idx = max(0, len(parts) - TRUSTED_PROXY_HOPS)
        return parts[idx]
    return request.remote_addr or "-"


def login_fail_key(student_id: str, ip: str) -> str:
    return "loginfail:%s:%s" % (student_id or "-", ip)


def login_fail_sid_key(student_id: str) -> str:
    return "loginfail:sid:%s" % (student_id or "-")
