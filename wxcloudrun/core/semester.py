# -*- coding: utf-8 -*-
"""学期计算(独立于 Flask 视图层)。"""
import datetime as _dt


def current_semester() -> str:
    now = _dt.datetime.now(_dt.timezone(_dt.timedelta(hours=8)))
    y, m, d = now.year, now.month, now.day
    if m >= 9 or (m == 8 and d >= 20):
        return f"{y}-{y+1}-1"
    if m >= 2:
        return f"{y-1}-{y}-2"
    return f"{y-1}-{y}-1"
