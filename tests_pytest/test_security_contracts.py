# -*- coding: utf-8 -*-
import base64
import os

os.environ.setdefault(
    "SQLALCHEMY_DATABASE_URI",
    "sqlite:///:memory:",
)
os.environ.setdefault(
    "SESSION_KEY",
    base64.b64encode(b"0123456789abcdef0123456789abcdef").decode(),
)

from wxcloudrun.api import auth as auth_api  # noqa: E402
from wxcloudrun.core import credential_store  # noqa: E402


def test_credential_resume_requires_matching_stored_password():
    assert auth_api._can_resume_credential("10001", "pwd") is False


def test_delete_token_roundtrip_and_tamper():
    token = credential_store.issue_delete_token("10001", ttl=60)
    assert credential_store.verify_delete_token(token) == "10001"
    tampered = token[:-1] + ("A" if token[-1] != "A" else "B")
    assert credential_store.verify_delete_token(tampered) == ""


def test_delete_token_rejects_malformed():
    token = credential_store.issue_delete_token("10001", ttl=60)
    assert token
    assert credential_store.verify_delete_token(token + "x") == ""
