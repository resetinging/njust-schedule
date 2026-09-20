# -*- coding: utf-8 -*-
"""UtilsMixin(Phase 2 从 jwc_client.py 拆出)。"""
from wxcloudrun.jwc.common import *  # noqa: F401,F403
from wxcloudrun.jwc.common import (  # noqa: F401
    _DedupCookieJar, _encrypt_sso_password, _dedupe_schedule_courses)


class UtilsMixin:
    # ================================================================
    # 工具
    # ================================================================

    def _current_semester(self) -> str:
        """计算当前学期（强制使用北京时间，不依赖容器系统时区）

        NJUST 秋季学期 8 月下旬开学: 8 月 20 日起视为秋季学期,
        否则按传统 9 月/2 月边界。
        """
        import datetime as _dt
        now = _dt.datetime.now(_dt.timezone(_dt.timedelta(hours=8)))
        y, m, d = now.year, now.month, now.day
        if m >= 9 or (m == 8 and d >= 20):
            return f"{y}-{y+1}-1"
        elif m >= 2:
            return f"{y-1}-{y}-2"
        else:
            return f"{y-1}-{y}-1"

    def get_semester_list(self) -> list[str]:
        cur = self._current_semester()
        try:
            by = int(cur.split("-")[0])
        except Exception:
            by = 2025
        return [f"{y}-{y+1}-{s}" for y in range(by-2, by+3) for s in (1, 2)]

