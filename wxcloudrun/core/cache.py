# -*- coding: utf-8 -*-
"""查询接口进程内缓存(按用户隔离, 默认与教务会话同为 30 天)。

- 键格式 "{sid}:{kind}:{param}"
- 会话重新建立/数据刷新接口成功后调用 invalidate_user_cache 主动失效
"""
import os
import threading
import time

from config import DATA_CACHE_TTL

QUERY_CACHE_TTL = DATA_CACHE_TTL
try:
    QUERY_CACHE_MAX_ITEMS = max(
        100, int(os.environ.get("QUERY_CACHE_MAX_ITEMS", "2000")))
except (TypeError, ValueError):
    QUERY_CACHE_MAX_ITEMS = 2000
_query_cache = {}
_query_cache_lock = threading.Lock()


def _cache_get(key: str):
    from wxcloudrun.core import state
    if state.enabled():
        value = state.get_json(key)
        if value is not None:
            return value
    with _query_cache_lock:
        item = _query_cache.get(key)
        if item and item[0] > time.time():
            return item[1]
    return None


def _cache_set(key: str, value, ttl: float = QUERY_CACHE_TTL):
    from wxcloudrun.core import state
    if state.enabled():
        state.set_json(key, value, ttl)
    with _query_cache_lock:
        _query_cache[key] = (time.time() + ttl, value)
        # 30 天缓存必须同时限制总量，优先清理已过期和最久将过期条目。
        if len(_query_cache) > QUERY_CACHE_MAX_ITEMS:
            now = time.time()
            for k in [k for k, (ts, _v) in _query_cache.items() if ts <= now]:
                _query_cache.pop(k, None)
            overflow = len(_query_cache) - QUERY_CACHE_MAX_ITEMS
            if overflow > 0:
                oldest = sorted(_query_cache.items(), key=lambda item: item[1][0])
                for k, _item in oldest[:overflow]:
                    _query_cache.pop(k, None)


def invalidate_user_cache(sid: str, *kinds):
    """数据刷新后使该用户相关查询缓存失效(kinds 为空则全部)"""
    prefix = f"{sid}:"
    from wxcloudrun.core import state
    if state.enabled():
        state.delete_prefix(prefix)
    with _query_cache_lock:
        for key in list(_query_cache.keys()):
            if not key.startswith(prefix):
                continue
            if kinds and not any(f":{k}:" in key or key.endswith(f":{k}") for k in kinds):
                continue
            _query_cache.pop(key, None)
