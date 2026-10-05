# -*- coding: utf-8 -*-
"""空教室预热任务适配器。"""


def start() -> bool:
    from wxcloudrun.api.freeclass import _start_freeclass_prewarm
    return _start_freeclass_prewarm()
