# -*- coding: utf-8 -*-
"""可选分布式状态后端。

未配置 REDIS_URL 时返回未启用，调用方继续使用进程内实现。
配置后用于跨 worker 的限流、查询缓存、会话 Cookie 恢复和后台任务互斥。
"""
import json
import logging
import os
import secrets
from contextlib import contextmanager

logger = logging.getLogger(__name__)

try:
    import redis as _redis
except Exception:  # noqa: BLE001
    _redis = None

_client = None
_loaded = False


def client():
    """返回 Redis 客户端；未配置或依赖缺失时返回 None。"""
    global _client, _loaded
    if _loaded:
        return _client
    _loaded = True
    url = os.environ.get("REDIS_URL", "").strip()
    if not url or _redis is None:
        return None
    try:
        _client = _redis.from_url(
            url, decode_responses=True,
            socket_connect_timeout=1.5, socket_timeout=1.5,
            health_check_interval=30)
        _client.ping()
        logger.info("[state] Redis distributed state enabled")
    except Exception as exc:  # noqa: BLE001
        logger.warning("[state] Redis 不可用, 回退进程内状态: %s",
                       type(exc).__name__)
        _client = None
    return _client


def enabled() -> bool:
    return client() is not None


def get_text(key: str):
    c = client()
    if not c:
        return None
    try:
        return c.get(key)
    except Exception:  # noqa: BLE001
        return None


def set_text(key: str, value: str, ttl: float = 0) -> bool:
    c = client()
    if not c:
        return False
    try:
        if ttl and ttl > 0:
            c.set(key, value, ex=max(1, int(ttl)))
        else:
            c.set(key, value)
        return True
    except Exception:  # noqa: BLE001
        return False


def delete(key: str) -> bool:
    c = client()
    if not c:
        return False
    try:
        c.delete(key)
        return True
    except Exception:  # noqa: BLE001
        return False


def get_json(key: str):
    raw = get_text(key)
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return None


def set_json(key: str, value, ttl: float = 0) -> bool:
    try:
        raw = json.dumps(value, ensure_ascii=False)
    except (TypeError, ValueError):
        return False
    return set_text(key, raw, ttl)


def delete_prefix(prefix: str) -> bool:
    c = client()
    if not c:
        return False
    try:
        batch = []
        for key in c.scan_iter(match=prefix + "*", count=200):
            batch.append(key)
            if len(batch) >= 200:
                c.delete(*batch)
                batch = []
        if batch:
            c.delete(*batch)
        return True
    except Exception:  # noqa: BLE001
        return False


def scan_keys(prefix: str, limit: int = 100) -> list:
    c = client()
    if not c:
        return []
    out = []
    try:
        for key in c.scan_iter(match=prefix + "*", count=max(50, limit)):
            out.append(key)
            if len(out) >= max(1, int(limit)):
                break
    except Exception:  # noqa: BLE001
        return []
    return out


def expire(key: str, ttl: float) -> bool:
    c = client()
    if not c:
        return False
    try:
        return bool(c.expire(key, max(1, int(ttl))))
    except Exception:  # noqa: BLE001
        return False


def rate_over(key: str, limit: int, window: float) -> bool:
    """读取固定窗口计数是否超限；Redis 不可用时返回 False 交由本地实现。"""
    c = client()
    if not c:
        return False
    try:
        return int(c.get(key) or 0) >= int(limit)
    except Exception:  # noqa: BLE001
        return False


def rate_hit(key: str, window: float) -> bool:
    """计数 +1，并保证计数键在窗口后过期。"""
    c = client()
    if not c:
        return False
    try:
        pipe = c.pipeline()
        pipe.incr(key)
        pipe.expire(key, max(1, int(window)))
        pipe.execute()
        return True
    except Exception:  # noqa: BLE001
        return False


def rate_clear(key: str) -> bool:
    return delete(key)


@contextmanager
def distributed_lock(name: str, ttl: float = 300):
    """Redis 互斥锁；未启用时 yield True，调用方按单实例继续执行。"""
    c = client()
    if not c:
        yield True
        return
    token = secrets.token_urlsafe(16)
    acquired = False
    try:
        acquired = bool(c.set(name, token, nx=True, ex=max(1, int(ttl))))
        yield acquired
    except Exception:  # noqa: BLE001
        yield True
    finally:
        if acquired:
            try:
                if c.get(name) == token:
                    c.delete(name)
            except Exception:  # noqa: BLE001
                pass
