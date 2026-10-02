# -*- coding: utf-8 -*-
"""教务连通性探测缓存(请求路径不阻塞)。"""
import os
import threading
import time

try:
    NETWORK_CACHE_TTL = max(
        30, int(os.environ.get("NETWORK_CACHE_TTL", "300")))
except (TypeError, ValueError):
    NETWORK_CACHE_TTL = 300

_cache = {"ts": 0.0, "ok": False}
_refreshing = {"on": False}
_lock = threading.Lock()
_probe_lock = threading.Lock()


def check(force: bool = False):
    if force:
        with _lock:
            should_probe = not _refreshing["on"]
            if should_probe:
                _refreshing["on"] = True
        if should_probe:
            refresh()
        else:
            with _probe_lock:
                pass
        return bool(_cache["ok"]), ""
    now = time.time()
    if (now - _cache["ts"] >= NETWORK_CACHE_TTL
            and not _refreshing["on"]):
        with _lock:
            if not _refreshing["on"]:
                _refreshing["on"] = True
                threading.Thread(target=refresh, daemon=True).start()
    if _cache["ts"] <= 0:
        return False, ""
    return _cache["ok"], ""


def refresh():
    from wxcloudrun.jwc_client import JWCClient
    with _probe_lock:
        try:
            try:
                ok, _msg = JWCClient().test_connection(timeout=3)
            except Exception:  # noqa: BLE001
                ok = False
            _cache["ok"] = ok
            _cache["ts"] = time.time()
        finally:
            _refreshing["on"] = False
