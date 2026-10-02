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

from config import DATA_CACHE_TTL, SSO_SESSION_MAX_AGE  # noqa: E402
from sqlalchemy import inspect as sa_inspect  # noqa: E402

from wxcloudrun import app, dao, db  # noqa: E402
from wxcloudrun.api import study  # noqa: E402
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

try:
    os.remove(_tmp.name)
except OSError:
    pass
print("\nPerformance/cache regression checks passed.")
