# -*- coding: utf-8 -*-
"""Old-miniapp compatibility checks for credential-resume login."""
import base64
import os
import sys
import tempfile
import threading
import time

import requests

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

_tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_tmp.close()
os.environ["SQLALCHEMY_DATABASE_URI"] = "sqlite:///" + _tmp.name.replace("\\", "/")
os.environ["SESSION_KEY"] = base64.b64encode(os.urandom(32)).decode()

from wxcloudrun import app  # noqa: E402
from wxcloudrun.api import auth as auth_api  # noqa: E402
from wxcloudrun.core import credential_store  # noqa: E402

_app_ctx = app.app_context()
_app_ctx.push()


class FakeJWC:
    instances = []

    def __init__(self):
        type(self).instances.append(self)
        self.student_id = ""
        self.student_name = "Compat"
        self.logged_in = False
        self.login_method = ""
        self.last_error = ""
        self.account_type = "graduate"
        self.session = requests.Session()
        self._lock = threading.Lock()
        self.allow_resume = None

    def login_webvpn(self, student_id, password, jwc_password="", allow_resume=False):
        self.student_id = student_id
        self.allow_resume = bool(allow_resume)
        self.logged_in = True
        self.login_method = "sso-cached" if allow_resume else "sso"
        return True

    def _current_semester(self):
        return "2026-2027-1"

    def logout(self):
        self.logged_in = False

    def fetch_courses(self):
        return {"courses": [], "semesters": ["2026-2027-1"], "timetable": []}

    def fetch_grades(self):
        return {"stats": [], "rows": [], "semesters": ["2026-2027-1"]}

    def fetch_exams(self):
        return {"stats": [], "rows": [], "semesters": ["2026-2027-1"]}


def check(name, condition, detail=""):
    if not condition:
        raise AssertionError(f"{name}: {detail}")
    print(f"  [PASS] {name}")


SID = "224101960123"
PASSWORD = "OldClient@1234"

assert credential_store.save(SID, PASSWORD)
_orig_client = auth_api.JWCClient
auth_api.JWCClient = FakeJWC
try:
    test_client = app.test_client()
    response = test_client.post("/api/login-webvpn", json={
        "student_id": SID,
        "password": PASSWORD,
        "remember": False,   # 旧前端关闭记住密码; 新后端忽略并默认保存
    })
    payload = response.get_json()
    check("old frontend remember=false request succeeds", response.status_code == 200, payload)
    check("new backend keeps old response fields",
          {"token", "credential_saved", "credential_delete_token", "login_method"}
          <= set(payload), payload)
    check("matching trusted credential enables cookie resume",
          FakeJWC.instances[-1].allow_resume is True)
    check("local resume method is exposed", payload["login_method"] == "sso-cached", payload)

    token = payload["token"]
    logout_response = test_client.post("/api/logout", headers={"X-Auth-Token": token})
    logout_payload = logout_response.get_json()
    check("old frontend logout response stays compatible",
          logout_response.status_code == 200
          and logout_payload.get("credential_deleted") is False, logout_payload)
    check("logout retains server credential",
          credential_store.resolve(SID) == PASSWORD)

    data = credential_store._load(SID)
    data["verified_at"] = int(time.time()) - credential_store.CREDENTIAL_TRUST_TTL - 1
    assert credential_store._save_payload(SID, data)
    expired_response = test_client.post("/api/login-webvpn", json={
        "student_id": SID,
        "password": PASSWORD,
    })
    check("expired trust forces real SSO",
          expired_response.status_code == 200
          and FakeJWC.instances[-1].allow_resume is False,
          expired_response.get_json())

    wrong_response = test_client.post("/api/login-webvpn", json={
        "student_id": SID,
        "password": "WrongPassword",
    })
    check("wrong password never enables cookie resume",
          wrong_response.status_code == 200
          and FakeJWC.instances[-1].allow_resume is False,
          wrong_response.get_json())
finally:
    _app_ctx.pop()
    auth_api.JWCClient = _orig_client
    try:
        os.remove(_tmp.name)
    except OSError:
        pass

print("\nOld-miniapp compatibility checks passed.")
