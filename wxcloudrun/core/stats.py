# -*- coding: utf-8 -*-
"""数据统计缓存: (sid, semester) -> (ts, has_courses, has_exams)。

每个页面加载都会请求 /api/status, 避免每次都 COUNT 两次数据库。
"""
import threading
import time
from typing import Tuple

from wxcloudrun import dao


# 每个页面加载都会请求 /api/status, 避免每次都 COUNT 两次数据库
_stats_cache = {}
_stats_cache_lock = threading.Lock()
STATS_CACHE_TTL = 30


def _get_data_stats(student_id: str, semester: str) -> Tuple[bool, bool]:
    now = time.time()
    key = (student_id, semester)
    with _stats_cache_lock:
        item = _stats_cache.get(key)
        if item is not None and now - item[0] < STATS_CACHE_TTL:
            return item[1], item[2]
    has_courses = dao.count_courses(semester, student_id) > 0
    has_exams = dao.count_exams(semester, student_id) > 0
    with _stats_cache_lock:
        _stats_cache[key] = (now, has_courses, has_exams)
        # 防止缓存无限增长
        if len(_stats_cache) > 512:
            expired_keys = [k for k, v in _stats_cache.items() if now - v[0] > STATS_CACHE_TTL]
            for k in expired_keys:
                _stats_cache.pop(k, None)
    return has_courses, has_exams


def _invalidate_stats(student_id: str, semester: str):
    """数据变更后清除统计缓存"""
    with _stats_cache_lock:
        _stats_cache.pop((student_id, semester), None)


