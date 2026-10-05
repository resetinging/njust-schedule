# -*- coding: utf-8 -*-
"""蹭课目录定时同步任务适配器。"""


def start() -> bool:
    from wxcloudrun.api.audit import start_audit_catalog_scheduler
    return start_audit_catalog_scheduler()
