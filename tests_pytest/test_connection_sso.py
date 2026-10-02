# -*- coding: utf-8 -*-
import os

os.environ.setdefault(
    "SQLALCHEMY_DATABASE_URI",
    "sqlite:///:memory:",
)

from wxcloudrun.jwc import eval as eval_module  # noqa: E402
from wxcloudrun.jwc_client import JWCClient  # noqa: E402


class _Response:
    def __init__(self, status_code=200):
        self.status_code = status_code


def _client_with_requests(statuses):
    client = JWCClient()
    seen = []

    def fake_get(url, **kwargs):
        seen.append(url)
        return _Response(statuses.get(url, 200))

    client.session.get = fake_get
    return client, seen


def test_connection_uses_sso_and_indexsso_by_default(monkeypatch):
    monkeypatch.setattr(eval_module, "JW_ALLOW_FORM_FALLBACK", False)
    client, seen = _client_with_requests({})

    ok, message = client.test_connection(timeout=1)

    assert ok is True
    assert "智慧理工 SSO" in message
    assert any("ids.njust.edu.cn/authserver/login" in url for url in seen)
    assert any("bkjw.njust.edu.cn/njlgdx/indexsso.jsp" in url for url in seen)
    assert not any("Logon.do" in url for url in seen)


def test_connection_reports_sso_failure_without_old_fallback(monkeypatch):
    monkeypatch.setattr(eval_module, "JW_ALLOW_FORM_FALLBACK", False)
    client, seen = _client_with_requests({
        "https://ids.njust.edu.cn/authserver/login"
        "?service=https%3A%2F%2Fehall2.njust.edu.cn%2Flogin": 503,
    })

    ok, message = client.test_connection(timeout=1)

    assert ok is False
    assert "智慧理工统一认证" in message
    assert not any("Logon.do" in url for url in seen)
