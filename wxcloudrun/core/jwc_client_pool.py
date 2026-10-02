# -*- coding: utf-8 -*-
"""共享教务客户端候选池: 活跃本科 -> 持久化本科 -> 服务账号。"""
import os
import secrets

from wxcloudrun.jwc_client import JWCClient


def _int_env(name: str, default: int) -> int:
    try:
        return max(1, int(os.environ.get(name, str(default))))
    except (TypeError, ValueError):
        return default


COOKIE_SOURCE = os.environ.get("FREE_CLASSROOM_COOKIE_SOURCE", "auto").strip().lower()
CANDIDATE_RETRIES = _int_env("FREE_CLASSROOM_CANDIDATE_RETRIES", 5)
PERSISTED_LIMIT = _int_env("FREE_CLASSROOM_PERSISTED_LIMIT", 50)


class JWCClientPool:
    """随机选择可用的共享教务会话。"""

    def __init__(self, service_provider, source: str = "", retries: int = 0,
                 limit: int = 0):
        self._service_provider = service_provider
        self._source = (source or COOKIE_SOURCE).strip().lower()
        self._retries = retries or CANDIDATE_RETRIES
        self._limit = limit or PERSISTED_LIMIT
        self.client = None
        self.source = ""
        self.student_id = ""
        self._active = None
        self._persistent = None
        self._active_tries = 0
        self._persistent_tries = 0

    @staticmethod
    def _shuffle(items):
        out = list(items or [])
        secrets.SystemRandom().shuffle(out)
        return out

    def _next_active(self):
        if self._active is None:
            from wxcloudrun.core.sessions import _list_undergraduate_clients
            self._active = self._shuffle(_list_undergraduate_clients(self._limit))
        if not self._active or self._active_tries >= self._retries:
            return False
        self._active_tries += 1
        self.client = self._active.pop()
        self.student_id = getattr(self.client, "student_id", "") or ""
        self.source = "active"
        return True

    def _next_persistent(self):
        if self._persistent_tries >= self._retries:
            return False
        if self._persistent is None:
            from wxcloudrun.core import session_store
            self._persistent = self._shuffle(
                session_store.list_undergraduate_candidates(self._limit))
        while self._persistent:
            if self._persistent_tries >= self._retries:
                return False
            self._persistent_tries += 1
            record = self._persistent.pop()
            client = JWCClient()
            if not session_store.attach_session(client, record):
                continue
            self.client = client
            self.student_id = record.get("student_id") or client.student_id or ""
            self.source = "persistent"
            return True
        return False

    def _next_service(self):
        try:
            client, sid, err = self._service_provider()
        except Exception as exc:  # noqa: BLE001
            return False, f"{type(exc).__name__}: {exc}"
        if client is None:
            return False, err or "服务账号不可用"
        self.client = client
        self.student_id = sid or getattr(client, "student_id", "") or ""
        self.source = "service"
        return True, ""

    def next_client(self):
        if self.client is not None and getattr(self.client, "logged_in", False):
            return self.client, self.source, self.student_id, ""
        if self._source in ("auto", "active-only") and self._next_active():
            return self.client, self.source, self.student_id, ""
        if self._source in ("auto", "persistent-only") and self._next_persistent():
            return self.client, self.source, self.student_id, ""
        if self._source in ("auto", "service-only"):
            ok, err = self._next_service()
            if ok:
                return self.client, self.source, self.student_id, ""
            return None, "", "", err
        return None, "", "", "Cookie 来源配置无效"
