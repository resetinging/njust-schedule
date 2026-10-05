# -*- coding: utf-8 -*-
"""多用户多课程提醒模拟: 额度、教师隔离、考试转成绩和跨用户不误发。"""
import datetime
import json
import os
import sys
import threading

_here = os.path.dirname(os.path.abspath(__file__))
_db_path = os.path.join(_here, "reminder_multi_user_tmp.db")
if os.path.exists(_db_path):
    os.remove(_db_path)
os.environ["SQLALCHEMY_DATABASE_URI"] = "sqlite:///" + _db_path.replace("\\", "/")
os.environ["SCHEMA_CHECK_ON_STARTUP"] = "0"
sys.path.insert(0, os.path.dirname(_here))

from wxcloudrun import app, dao, db, _run_migrations  # noqa: E402
_run_migrations(force=True)
from wxcloudrun.core import mp, reminder  # noqa: E402
from wxcloudrun.core import subscribe_store as ss  # noqa: E402
from wxcloudrun.core.reminder_lifecycle import sync_user_reminder_tasks  # noqa: E402
from wxcloudrun.model import ReminderTask  # noqa: E402

_APP_CTX = app.app_context()
_APP_CTX.push()

SEM = "2026-2027-1"
NOW = datetime.datetime(2026, 10, 4, 18, 0)
U1, U2, U3 = "924101960101", "924101960102", "924101960103"
PASS, FAIL, FAILURES = 0, 0, []


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  [PASS] " + name)
    else:
        FAIL += 1
        FAILURES.append(name)
        print("  [FAIL] " + name + (" -> " + str(detail) if detail else ""))


class FakeClient:
    def __init__(self, sid):
        self.student_id = sid
        self.logged_in = True
        self.last_error = ""
        self._lock = threading.Lock()
        self._jw_http_count = 0
        self._jw_http_targets = {}

    def get_exams(self, semester=""):
        exam_calls.append(self.student_id)
        return EXAMS.get(self.student_id, [])

    def get_grades(self, semester=""):
        grade_calls.append(self.student_id)
        return GRADES.get(self.student_id, [])


exam_calls = []
grade_calls = []
send_calls = []
EXAMS = {
    U1: [{
        "course_name": "高等数学",
        "date": "2026-10-02",
        "time": "09:00-11:00",
        "location": "I-101",
        "seat": "1",
        "type": "期末考试",
    }],
    U2: [{
        "course_name": "高等数学",
        "date": "2026-10-02",
        "time": "09:00-11:00",
        "location": "I-202",
        "seat": "2",
        "type": "期末考试",
    }],
}
GRADES = {
    U1: [{
        "academic_year": "2026-2027",
        "semester": "1",
        "course_code": "11123301",
        "course_name": "高等数学",
        "score": "92",
        "credit": 4,
        "grade_point": 4.0,
        "course_type": "必修",
        "exam_type": "考试",
    }],
    U2: [{
        "academic_year": "2026-2027",
        "semester": "1",
        "course_code": "14020602",
        "course_name": "通用英语",
        "score": "88",
        "credit": 3,
        "grade_point": 3.7,
        "course_type": "必修",
        "exam_type": "考查",
    }],
}


def fake_send(openid, template_id, data, page=""):
    send_calls.append({
        "openid": openid,
        "template_id": template_id,
        "data": data,
        "page": page,
    })
    return {"ok": True, "errcode": 0, "errmsg": ""}


reminder._load_persisted_client = lambda sid: (FakeClient(sid), "")
mp.enabled = lambda: True
mp.template_id = lambda kind: "tpl-" + kind
mp.template_content = lambda template_id: []
mp.send_subscribe = fake_send

calendar = {
    "semester": SEM,
    "weeks": [{
        "week": 1,
        "days": ["2026-09-28", "2026-09-29", "2026-09-30",
                 "2026-10-01", "2026-10-02", "2026-10-03", "2026-10-04"],
    }],
}
programme = {
    "courses": [
        {"semester": SEM, "name": "高等数学", "credit": 4, "exam_type": "考试"},
        {"semester": SEM, "name": "大学物理", "credit": 3, "exam_type": "考查"},
        {"semester": SEM, "name": "通用英语", "credit": 3, "exam_type": "考查"},
    ],
}
dao.set_setting("calendar:" + SEM, json.dumps(calendar, ensure_ascii=False))
for sid in (U1, U2, U3):
    dao.set_user_setting(sid, "semester", SEM)
    dao.set_user_setting(sid, "programme",
                         json.dumps(programme, ensure_ascii=False))

dao.save_courses([
    {"name": "高等数学", "teacher": "教师A", "day": 1,
     "start": 1, "end": 2, "weeks": "1", "credits": 4},
    {"name": "大学物理", "teacher": "教师P", "day": 2,
     "start": 3, "end": 4, "weeks": "1", "credits": 3},
], SEM, U1)
dao.save_courses([
    {"name": "高等数学", "teacher": "教师B", "day": 1,
     "start": 3, "end": 4, "weeks": "1", "credits": 4},
    {"name": "通用英语", "teacher": "教师E", "day": 3,
     "start": 1, "end": 2, "weeks": "1", "credits": 3},
], SEM, U2)
dao.save_courses([
    {"name": "高等数学", "teacher": "教师A", "day": 1,
     "start": 1, "end": 2, "weeks": "1", "credits": 4},
], SEM, U3)

ss.grant(U1, "exam", 1, openid="openid-u1")
ss.grant(U1, "grade", 1)
ss.grant(U1, "grade", 1)
ss.grant(U2, "grade", 1, openid="openid-u2")
ss.save_openid(U3, "openid-u3")

for sid in (U1, U2, U3):
    sync_user_reminder_tasks(sid, SEM)

check("U1 生成考试任务和两门成绩任务",
      ReminderTask.query.filter_by(student_id=U1, kind="exam").count() == 1
      and ReminderTask.query.filter_by(
          student_id=U1, kind="grade", status="active").count() == 2,
      [(r.kind, r.course_name, r.teacher_snapshot)
       for r in ReminderTask.query.filter_by(student_id=U1).all()])
check("U2 生成两门成绩任务",
      ReminderTask.query.filter_by(
          student_id=U2, kind="grade", status="active").count() == 2)
check("U3 无额度不进入池",
      ReminderTask.query.filter_by(student_id=U3).count() == 0)

math_tasks = ReminderTask.query.filter_by(
    kind="grade", course_name="高等数学").all()
check("同名课程不同教师生成独立任务",
      {row.teacher_snapshot for row in math_tasks} == {"教师A", "教师B"},
      [(row.student_id, row.teacher_snapshot) for row in math_tasks])

# 将所有活动任务设置为到期，模拟后台轮次。
for row in ReminderTask.query.filter_by(status="active").all():
    row.next_check_at = NOW - datetime.timedelta(minutes=1)
db.session.commit()

result = reminder.run_reminder_pool(now=NOW)
check("第一次轮询发送两条成绩提醒", result["sent"] == 2, result)
check("每个有额度的用户各调用一次教务",
      sorted(grade_calls) == [U1, U2], grade_calls)
check("无额度用户没有访问教务",
      U3 not in exam_calls and U3 not in grade_calls,
      {"exam_calls": exam_calls, "grade_calls": grade_calls})
check("U1 只收到自己高等数学的成绩",
      len(send_calls) == 2
      and any(c["openid"] == "openid-u1"
              and c["data"]["thing2"]["value"] == "高等数学"
              for c in send_calls),
      send_calls)
check("U2 只收到自己的通用英语成绩",
      any(c["openid"] == "openid-u2"
          and c["data"]["thing2"]["value"] == "通用英语"
          for c in send_calls),
      send_calls)
check("U2 不会因同名高等数学串课",
      not any(c["openid"] == "openid-u2"
              and c["data"]["thing2"]["value"] == "高等数学"
              for c in send_calls))

u1_math = ReminderTask.query.filter_by(
    student_id=U1, kind="grade", course_name="高等数学").first()
u1_physics = ReminderTask.query.filter_by(
    student_id=U1, kind="grade", course_name="大学物理").first()
u2_math = ReminderTask.query.filter_by(
    student_id=U2, kind="grade", course_name="高等数学").first()
check("U1 已出的高等数学任务结束",
      u1_math.status == "done" and u1_math.stage == "done")
check("U1 未出的大学物理继续等待",
      u1_physics.status == "active" and u1_physics.stage == "wait_grade")
check("U2 额度耗尽后剩余任务退出池",
      ss.quota(U2, "grade") == 0 and u2_math.status == "disabled")

second = reminder.run_reminder_pool(
    now=NOW + datetime.timedelta(hours=1))
check("第二次轮询不重复发送已出成绩", len(send_calls) == 2, second)
check("U2 无额度后不再访问教务",
      grade_calls.count(U2) == 1, grade_calls)

print()
print("结果: %d 通过, %d 失败" % (PASS, FAIL))
try:
    db.session.remove()
    _APP_CTX.pop()
    os.remove(_db_path)
except OSError:
    pass
if FAIL:
    print("失败项:", FAILURES)
    sys.exit(1)
print("多用户多课程提醒模拟全部通过 [OK]")
