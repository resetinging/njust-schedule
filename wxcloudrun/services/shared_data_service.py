# -*- coding: utf-8 -*-
"""跨用户共享数据服务。

蹭课目录是全校共享快照，抓取和替换不属于单个 HTTP 请求；这里集中放置
教务 Cookie 池到共享 Repository 的编排，API 层只负责触发和展示状态。
"""
import time

from wxcloudrun import app, dao
from wxcloudrun.core.jwc_client_pool import JWCClientPool
from wxcloudrun.core.pool import _jwc_request
from wxcloudrun.core.semester import current_semester
from wxcloudrun.repositories.audit import replace_courses


def sync_audit_catalog(semester: str = "") -> tuple:
    """使用共享本科 Cookie 池抓取并原子替换蹭课目录。"""
    from wxcloudrun.api.freeclass import _service_client_provider

    semester = str(semester or "").strip() or current_semester()
    pool = JWCClientPool(service_provider=_service_client_provider)
    last_error = "课程目录同步失败"
    for _attempt in range(10):
        client, source, sid, err = pool.next_client()
        if client is None:
            return 0, err or last_error
        try:
            with _jwc_request(client):
                courses = client.fetch_course_schedule(
                    semester=semester, keyword="", course_type="")
        except Exception as exc:  # noqa: BLE001 更换 Cookie 后重试
            last_error = f"{type(exc).__name__}: {exc}"
            pool.client = None
            continue
        if courses:
            count = replace_courses(courses, semester)
            dao.set_setting(f"audit_catalog_at:{semester}", str(int(time.time())))
            app.logger.info(
                "[audit-sync] source=%s sid=%s sem=%s count=%d",
                source, (sid or "-")[:3] + "****", semester, count)
            return count, ""
        last_error = getattr(client, "last_error", "") or "课程目录为空"
        if "登录" in last_error or "logon" in last_error.lower():
            client.logged_in = False
        pool.client = None
    return 0, last_error
