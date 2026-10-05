# -*- coding: utf-8 -*-
"""Performance/cache regression checks for session-scoped data refresh."""
import os
import sys
import tempfile
import time
from types import SimpleNamespace

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

_tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_tmp.close()
os.environ["SQLALCHEMY_DATABASE_URI"] = "sqlite:///" + _tmp.name.replace("\\", "/")
os.environ["SCHEMA_CHECK_ON_STARTUP"] = "0"

from config import DATA_CACHE_TTL, SSO_SESSION_MAX_AGE  # noqa: E402
from sqlalchemy import inspect as sa_inspect  # noqa: E402

from wxcloudrun import app, dao, db, _run_migrations  # noqa: E402
_run_migrations(force=True)
from wxcloudrun.api import study  # noqa: E402
from wxcloudrun.api import freeclass as freeclass_api  # noqa: E402
from wxcloudrun.core import sessions as sessions_mod  # noqa: E402
from wxcloudrun.core.cache import (  # noqa: E402
    QUERY_CACHE_MAX_ITEMS, QUERY_CACHE_TTL, _cache_set, _query_cache,
)
from wxcloudrun.jwc_client import JWCClient  # noqa: E402


def check(name, condition, detail=""):
    if not condition:
        raise AssertionError(f"{name}: {detail}")
    print(f"  [PASS] {name}")


check("data cache and persisted SSO session share 30 days",
      DATA_CACHE_TTL == SSO_SESSION_MAX_AGE == 30 * 24 * 3600,
      (DATA_CACHE_TTL, SSO_SESSION_MAX_AGE))
check("query cache uses the shared data TTL",
      QUERY_CACHE_TTL == DATA_CACHE_TTL, QUERY_CACHE_TTL)
for i in range(QUERY_CACHE_MAX_ITEMS + 20):
    _cache_set(f"__perf_cache__:{i}", {"i": i}, ttl=60)
check("query cache enforces a hard memory bound",
      len(_query_cache) <= QUERY_CACHE_MAX_ITEMS,
      (len(_query_cache), QUERY_CACHE_MAX_ITEMS))

client = JWCClient()
client._count_jw_response(SimpleNamespace(
    request=SimpleNamespace(method="GET", url="https://example.edu/path?a=secret")))
client._count_jw_response(SimpleNamespace(
    request=SimpleNamespace(method="POST", url="https://example.edu/path?token=secret")))
check("JWC response hook counts actual HTTP",
      client._jw_http_count == 2, client._jw_http_count)
check("JWC access target log strips query parameters",
      list(client._jw_http_targets) == ["GET example.edu/path", "POST example.edu/path"],
      client._jw_http_targets)

with app.app_context():
    _index_names = {
        table: {i.get("name") for i in sa_inspect(db.engine).get_indexes(table)}
        for table in ("courses", "exams", "grades", "evaluations", "cet_scores")
    }
check("performance indexes are created",
      _index_names["courses"] >= {"ix_courses_user_semester_day"}
      and _index_names["exams"] >= {"ix_exams_user_semester_date"}
      and _index_names["grades"] >= {"ix_grades_user_year_semester"}
      and _index_names["evaluations"] >= {"ix_evaluations_user_end"}
      and _index_names["cet_scores"] >= {"ix_cet_user_type_score"},
      _index_names)

sid = "10001"
semester = "2026-2027-1"
client.logged_in = True
client.student_id = sid
client.student_name = "Perf"
client.account_type = "undergraduate"
client.last_error = ""
client.fetch_calendar = lambda semester="": {
    "semester": semester,
    "first_monday": "2026-08-24",
    "count": 1,
    "weeks": [],
}
client.get_schedule = lambda sem: [{"name": "Course", "day": 1, "start": 1, "end": 2}]
client.get_exams = lambda sem: [{"course_name": "Exam", "date": "2027-01-01"}]
client.get_grades = lambda sem: [{
    "academic_year": "2026-2027", "semester": "1", "course_name": "Course",
    "score": "90", "credit": 2.0, "grade_point": 4.0,
}]
client.get_cet_scores = lambda: [{"type": "CET4", "score": 500, "exam_date": "2026-06"}]
client.get_evaluations = lambda sem: [{"semester": semester, "batch": "Batch"}]
client.fetch_programme = lambda: {"courses": [{"code": "C1"}], "count": 1, "pages": 1}
client.fetch_profile = lambda: {"fields": {"学号": sid}, "base": {"student_id": sid}}

with app.app_context():
    result = study._prefetch_undergraduate(client, sid, semester)

check("session prefetch has no failed data source", result["failed"] == [], result)
check("session prefetch fetches all undergraduate sources",
      set(result["ok"]) == {
          "calendar", "courses", "exams", "grades", "cet",
          "evaluations", "programme", "profile",
      }, result)

aborting = JWCClient()
aborting.logged_in = True
aborting.student_id = sid
aborting.student_name = "Abort"
aborting.account_type = "undergraduate"
aborting.last_error = ""
aborting.fetch_calendar = lambda semester="": {
    "semester": semester, "first_monday": "2026-08-24", "count": 1, "weeks": [],
}
abort_calls = []


def abort_schedule(sem):
    abort_calls.append("courses")
    aborting.logged_in = False
    aborting.last_error = "登录已过期"
    return []


def unexpected_call(name):
    def _inner(*args):
        abort_calls.append(name)
        return []
    return _inner


aborting.get_schedule = abort_schedule
aborting.get_exams = unexpected_call("exams")
aborting.get_grades = unexpected_call("grades")
aborting.get_cet_scores = lambda: abort_calls.append("cet") or []
aborting.get_evaluations = unexpected_call("evaluations")
aborting.fetch_programme = lambda: abort_calls.append("programme") or {}
aborting.fetch_profile = lambda: abort_calls.append("profile") or {}
with app.app_context():
    aborted = study._prefetch_undergraduate(aborting, sid, semester)
check("undergraduate prefetch aborts immediately after session expiry",
      aborted.get("aborted") == "session_expired"
      and abort_calls == ["courses"], (aborted, abort_calls))

graduate_abort = JWCClient()
graduate_abort.logged_in = True
graduate_calls = []


def graduate_courses():
    graduate_calls.append("courses")
    graduate_abort.logged_in = False
    return {"courses": [], "semesters": [], "timetable": []}


graduate_abort.fetch_courses = graduate_courses
graduate_abort.fetch_grades = lambda: graduate_calls.append("grades") or {
    "stats": [], "rows": [], "semesters": [],
}
graduate_abort.fetch_exams = lambda: graduate_calls.append("exams") or {
    "stats": [], "rows": [], "semesters": [],
}
graduate_result = study._prefetch_graduate(graduate_abort, sid)
check("graduate prefetch aborts immediately after session expiry",
      graduate_result.get("aborted") == "session_expired"
      and graduate_calls == ["courses"], (graduate_result, graduate_calls))

study.schedule_data_prefetch(client, sid, semester, delay=0)
deadline = time.time() + 5
while time.time() < deadline:
    if not getattr(client, "_data_prefetch_running", False):
        break
    time.sleep(0.05)
state = getattr(client, "_data_refresh_state", {})
check("background prefetch publishes terminal state",
      state.get("state") in ("done", "partial"), state)

with app.app_context():
    check("prefetched courses are persisted",
          len(dao.get_courses(semester, sid)) == 1)
    check("prefetched grades are persisted",
          len(dao.get_grades(student_id=sid)) == 1)
    check("complete prefetch writes cache metadata",
          int(dao.get_user_setting(sid, "data_cache_at", "0") or 0) > 0)

_schedule_before = client.get_schedule
_schedule_calls = []


def _counted_schedule(sem):
    _schedule_calls.append(sem)
    return _schedule_before(sem)


client.get_schedule = _counted_schedule
with app.app_context():
    study.schedule_data_prefetch(client, sid, semester, delay=0, mode="if_stale")
state = getattr(client, "_data_refresh_state", {})
check("fresh cache skips repeated full prefetch",
      state.get("skipped") is True and _schedule_calls == [], state)

optional_client = JWCClient()
optional_sid = "10004"
optional_client.logged_in = True
optional_client.student_id = optional_sid
optional_client.student_name = "Optional"
optional_client.account_type = "undergraduate"
optional_client.last_error = ""
optional_client.fetch_calendar = lambda semester="": {
    "semester": semester,
    "first_monday": "2026-08-24",
    "count": 1,
    "weeks": [],
}
optional_client.get_schedule = lambda sem: [
    {"name": "Course", "day": 1, "start": 1, "end": 2}]
optional_client.get_exams = lambda sem: []
optional_client.get_grades = lambda sem: []
optional_client.get_cet_scores = lambda: []
optional_client.get_evaluations = lambda sem: []
optional_client.fetch_programme = lambda: {}
optional_client.fetch_profile = lambda: {}
with app.app_context():
    optional_result = study._prefetch_undergraduate(
        optional_client, optional_sid, semester)
check("empty optional data sources still complete prefetch",
      optional_result["failed"] == [], optional_result)

_orig_source = freeclass_api._COOKIE_SOURCE
_orig_active = sessions_mod._list_undergraduate_clients
_orig_get_rooms = JWCClient.get_free_classrooms
from wxcloudrun.core import session_store  # noqa: E402
_orig_candidates = session_store.list_undergraduate_candidates
try:
    freeclass_api._COOKIE_SOURCE = "active-only"
    active_ok = JWCClient()
    active_ok.logged_in = True
    active_ok.student_id = sid
    active_ok.account_type = "undergraduate"
    sessions_mod._list_undergraduate_clients = lambda limit=50: [active_ok]
    JWCClient.get_free_classrooms = lambda self, **kw: {
        "rooms": ["A101"], "buildings": [], "jc1": kw.get("jc1"),
        "jc2": kw.get("jc2"), "building_name": "",
    }
    _res, _err = freeclass_api._ClassroomQuery().query(
        "孝陵卫", 1, 1, 3, 1, semester, "")
    check("freeclass picks an active undergraduate cookie",
          _err is None and _res["rooms"] == ["A101"], (_res, _err))

    freeclass_api._COOKIE_SOURCE = "auto"
    active_bad = JWCClient()
    active_bad.logged_in = True
    active_bad.student_id = "10002"
    active_bad.account_type = "undergraduate"

    def stale_rooms(self, **kw):
        if self.student_id == "10002":
            self.last_error = "登录已过期"
            return []
        return {"rooms": ["B202"], "buildings": [], "jc1": kw.get("jc1"),
                "jc2": kw.get("jc2"), "building_name": ""}

    sessions_mod._list_undergraduate_clients = lambda limit=50: [active_bad]
    session_store.list_undergraduate_candidates = lambda limit=50: [{
        "student_id": "10003", "account_type": "undergraduate",
        "cookies": [{"name": "JSESSIONID", "value": "x",
                     "domain": "bkjw.njust.edu.cn", "path": "/"}],
    }]
    JWCClient.get_free_classrooms = stale_rooms
    _res, _err = freeclass_api._ClassroomQuery().query(
        "孝陵卫", 1, 1, 3, 1, semester, "")
    check("freeclass rotates from stale active to persistent cookie",
          _err is None and _res["rooms"] == ["B202"], (_res, _err))

    freeclass_api._COOKIE_SOURCE = "service-only"
    service_client = JWCClient()
    service_client.logged_in = True
    service_client.student_id = "svc"
    service_client.get_free_classrooms = lambda **kw: {
        "rooms": ["C303"], "buildings": [], "jc1": kw.get("jc1"),
        "jc2": kw.get("jc2"), "building_name": "",
    }
    _orig_service = freeclass_api._classroom_service_client
    _orig_credentials = freeclass_api._service_credentials
    freeclass_api._classroom_service_client = service_client
    freeclass_api._service_credentials = lambda: ("svc", "pwd")
    _res, _err = freeclass_api._ClassroomQuery().query(
        "孝陵卫", 1, 1, 3, 1, semester, "")
    check("freeclass keeps service-account fallback",
          _err is None and _res["rooms"] == ["C303"], (_res, _err))
finally:
    session_store.list_undergraduate_candidates = _orig_candidates
    sessions_mod._list_undergraduate_clients = _orig_active
    JWCClient.get_free_classrooms = _orig_get_rooms
    freeclass_api._COOKIE_SOURCE = _orig_source
    if "_orig_service" in locals():
        freeclass_api._classroom_service_client = _orig_service
        freeclass_api._service_credentials = _orig_credentials

try:
    os.remove(_tmp.name)
except OSError:
    pass
print("\nPerformance/cache regression checks passed.")
