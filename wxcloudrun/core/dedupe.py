"""并发/连点去重: 同一令牌对同一刷新接口的重复请求, 在短窗口内直接复用上一次结果。

背景: 刷新类接口会去抓教务, 用户连点两下、或前端预取 + 手动刷新撞在一起时,
会并发抓两遍, 既浪费又容易触发学校风控。这里做一层"结果窗口"去重。

注意: 按 token 去重(覆盖同一设备的连点/重试); 若要跨设备去重需要按学号, 见 _key_of。
"""
import threading
import time
from functools import wraps

from flask import request

_CACHE = {}
_GUARD = threading.Lock()
_MAX_ENTRIES = 500


def _key_of(prefix: str) -> str:
    tok = request.headers.get('X-Token') or request.headers.get('token') or ''
    if not tok:
        body = request.get_json(silent=True) or {}
        tok = str(body.get('token') or '')
    return '%s:%s' % (prefix, tok or request.remote_addr or '-')


def dedupe(prefix: str, window: float = 15.0):
    """装饰刷新类接口: window 秒内相同令牌的重复请求直接返回上一次结果"""
    def deco(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            key = _key_of(prefix)
            now = time.time()
            with _GUARD:
                hit = _CACHE.get(key)
                if hit and now - hit[0] < window:
                    return hit[1]
            resp = fn(*args, **kwargs)
            with _GUARD:
                if len(_CACHE) > _MAX_ENTRIES:
                    _CACHE.clear()
                _CACHE[key] = (now, resp)
            return resp
        return wrapper
    return deco
