# -*- coding: utf-8 -*-
"""查询接口进程内缓存(按用户隔离, 默认 30s)。

- 键格式 "{sid}:{kind}:{param}"
- 数据刷新接口成功后调用 invalidate_user_cache 主动失效
"""
import threading
import time

QUERY_CACHE_TTL = 30
_query_cache = {}
_query_cache_lock = threading.Lock()


def _cache_get(key: str):
    with _query_cache_lock:
        item = _query_cache.get(key)
        if item and item[0] > time.time():
            return item[1]
    return None


def _cache_set(key: str, value, ttl: float = QUERY_CACHE_TTL):
    with _query_cache_lock:
        _query_cache[key] = (time.time() + ttl, value)
        # 惰性清理过期条目, 防内存缓慢增长
        if len(_query_cache) > 500:
            now = time.time()
            for k in [k for k, (ts, _v) in _query_cache.items() if ts <= now]:
                _query_cache.pop(k, None)


def invalidate_user_cache(sid: str, *kinds):
    """数据刷新后使该用户相关查询缓存失效(kinds 为空则全部)"""
    prefix = f"{sid}:"
    with _query_cache_lock:
        for key in list(_query_cache.keys()):
            if not key.startswith(prefix):
                continue
            if kinds and not any(f":{k}:" in key or key.endswith(f":{k}") for k in kinds):
                continue
            _query_cache.pop(key, None)
