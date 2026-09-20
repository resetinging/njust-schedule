# -*- coding: utf-8 -*-
"""北京时间工具(容器时区可能为 UTC, 统一显式 +8)。"""


def _beijing_now() -> str:
    """当前北京时间字符串"""
    import datetime as _dt
    now = _dt.datetime.now(_dt.timezone(_dt.timedelta(hours=8)))
    return now.strftime("%Y-%m-%d %H:%M:%S")


def _beijing_date():
    """北京时间"今天"。

    容器时区可能为 UTC: 直接用 date.today() 会在北京时间 00:00-08:00
    期间偏成前一天, 进而把"今天/本周"算错。
    """
    import datetime as _dt
    return _dt.datetime.now(_dt.timezone(_dt.timedelta(hours=8))).date()
