# -*- coding: utf-8 -*-
"""请求级日志(rid 关联 / 慢请求告警)与 after_request 记录。

- rid: before_request 生成, 关联错误/业务日志, 云托管按关键词过滤
- sid: 由 token 反查当前用户, 调试时按学号过滤
- 慢请求(>=SLOW_MS)自动升为 WARNING, 便于告警
"""
import os
import time
import uuid

from flask import g, request

from wxcloudrun.core.sessions import TOKEN_HEADER, _sid_by_token

SLOW_MS = int(os.environ.get("SLOW_MS", "2000"))


def _rid() -> str:
    """当前请求 ID(无请求上下文时返回 '-', 如测试/后台调用)"""
    try:
        return g.get("rid", "-")
    except Exception:
        return "-"


def register_request_logging(app):
    """注册请求级日志(before/after_request)。"""

    @app.before_request
    def _log_request_start():
        g.rid = "r-" + uuid.uuid4().hex[:8]
        request._log_t0 = time.time()

    @app.after_request
    def _log_request_end(resp):
        if request.path.startswith(("/api/", "/proxy/")):
            dur_ms = (time.time() - getattr(request, "_log_t0", time.time())) * 1000
            token = request.headers.get(TOKEN_HEADER, "") or ""
            tok = f"{token[:6]}…" if token else "-"
            sid = _sid_by_token(token)
            xff = request.headers.get("X-Forwarded-For") or ""
            ip = xff.split(",")[0].strip() if xff else (request.remote_addr or "-")
            rid = _rid()
            # 记录到管理面板的实时请求缓冲(线程安全)
            try:
                from wxcloudrun import admin as _admin
                _admin.record_request(request.method, request.path,
                                      resp.status_code, dur_ms, sid, ip)
            except Exception:
                pass
            line = (f"[req] rid={rid} {request.method} {request.path} "
                    f"status={resp.status_code} sid={sid} tok={tok} ip={ip} d={dur_ms:.0f}ms")
            if dur_ms >= SLOW_MS:
                app.logger.warning("[slow] %s", line)
            else:
                app.logger.info(line)
        return resp
