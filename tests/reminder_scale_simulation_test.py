# -*- coding: utf-8 -*-
"""规模模拟: 10 用户 / 30 教学班 / 多轮额度和跨用户隔离。"""
import datetime
import json
import os
import sys
import threading
from collections import defaultdict

_here = os.path.dirname(os.path.abspath(__file__))
_db_path = os.path.join(_here, "reminder_scale_tmp.db")
if os.path.exists(_db_path):
    os.remove(_db_path)
os.environ["SQLALCHEMY_DATABASE_URI"] = "sqlite:///" + _db_path.replace("\\", "/")
sys.path.insert(0, os.path.dirname(_here))

from wxcloudrun import app, dao, db  # noqa: E402
from wxcloudrun.core import mp, reminder  # noqa: E402
from wxcloudrun.core import subscribe_store as ss  # noqa: E402
from wxcloudrun.core.reminder_lifecycle import sync_user_reminder_tasks  # noqa: E402
from wxcloudrun.model import ReminderTask  # noqa: E402

_APP_CTX = app.app_context()
_APP_CTX.push()

SEM = "2026-2027-1"
NOW = datetime.datetime(2026, 10, 4, 18, 0)
USERS = ["9241019610%02d" % i for i in range(10)]
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
openid_to_sid = {}
EXAMS = {}
GRADES = {}


def fake_send(openid, template_id, data, page=""):
    send_calls.append({
        "openid": openid,
        "template_id": template_id,
        "course": data.get("thing2", {}).get("value", ""),
        "detail": data.get("thing5", {}).get("value", ""),
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
dao.set_setting("calendar:" + SEM, json.dumps(calendar, ensure_ascii=False))

# 15 个课程名 × 2 位教师 = 30 个教学班。每个教学班有 3 个交集用户。
offerings = []
for course_index in range(15):
    name = "课程%02d" % (course_index + 1)
    assessment = "考试" if course_index < 10 else "考查"
    for teacher_index, teacher in enumerate(("教师A", "教师B")):
        offering_id = len(offerings)
        if teacher_index == 0:
            users = [
                USERS[course_index % 10],
                USERS[(course_index + 3) % 10],
                USERS[(course_index + 6) % 10],
            ]
        else:
            users = [
                USERS[(course_index + 1) % 10],
                USERS[(course_index + 4) % 10],
                USERS[(course_index + 7) % 10],
            ]
        offerings.append({
            "id": offering_id,
            "name": name,
            "teacher": teacher,
            "assessment": assessment,
            "users": users,
        })

programme = {
    "courses": [],
}
for index in range(15):
    programme["courses"].append({
        "semester": SEM,
        "name": "课程%02d" % (index + 1),
        "credit": 3,
        "exam_type": "考试" if index < 10 else "考查",
    })

user_offerings = defaultdict(list)
for item in offerings:
    for sid in item["users"]:
        user_offerings[sid].append(item)

for sid in USERS:
    dao.set_user_setting(sid, "semester", SEM)
    dao.set_user_setting(sid, "programme",
                         json.dumps(programme, ensure_ascii=False))
    courses = []
    for item in user_offerings[sid]:
        courses.append({
            "name": item["name"],
            "teacher": item["teacher"],
            "day": item["id"] % 5 + 1,
            "start": 1,
            "end": 2,
            "weeks": "1",
            "credits": 3,
            "week_type": 0,
        })
    dao.save_courses(courses, SEM, sid)

# U0-U6 同时有考试和成绩额度；U7 只有成绩额度；U8 只有考试额度；U9 无额度。
for sid in USERS[:7]:
    ss.save_openid(sid, "openid-" + sid)
    openid_to_sid["openid-" + sid] = sid
    for _ in user_offerings[sid]:
        ss.grant(sid, "grade", 1)
    exam_count = sum(1 for item in user_offerings[sid]
                     if item["assessment"] == "考试")
    for _ in range(exam_count):
        ss.grant(sid, "exam", 1)

ss.save_openid(USERS[7], "openid-" + USERS[7])
openid_to_sid["openid-" + USERS[7]] = USERS[7]
for _ in user_offerings[USERS[7]]:
    ss.grant(USERS[7], "grade", 1)

ss.save_openid(USERS[8], "openid-" + USERS[8])
openid_to_sid["openid-" + USERS[8]] = USERS[8]
for item in user_offerings[USERS[8]]:
    if item["assessment"] == "考试":
        ss.grant(USERS[8], "exam", 1)

# 前 7 个用户全部课程均出成绩；U7 只出前两门，用于测试剩余任务等待。
expected_pairs = set()
for sid in USERS[:8]:
    grade_items = user_offerings[sid]
    if sid == USERS[7]:
        grade_items = grade_items[:2]
    GRADES[sid] = []
    for index, item in enumerate(grade_items):
        GRADES[sid].append({
            "academic_year": "2026-2027",
            "semester": "1",
            "course_code": "C%04d" % item["id"],
            "course_name": item["name"],
            "score": str(80 + index % 15),
            "credit": 3,
            "grade_point": 3.0 + (index % 5) * 0.1,
            "course_type": "必修",
            "exam_type": item["assessment"],
        })
        expected_pairs.add((sid, item["name"]))

for sid in USERS[:9]:
    EXAMS[sid] = []
    for item in user_offerings[sid]:
        if item["assessment"] != "考试":
            continue
        EXAMS[sid].append({
            "course_name": item["name"],
            "date": "2026-10-02",
            "time": "09:00-11:00",
            "location": "I-%03d" % item["id"],
            "seat": str(item["id"]),
            "type": "期末考试",
        })

for sid in USERS:
    sync_user_reminder_tasks(sid, SEM)

active_tasks = ReminderTask.query.filter_by(status="active").all()
check("创建 30 个教学班的课程数据",
      len(offerings) == 30 and len({o["name"] for o in offerings}) == 15,
      len(offerings))
check("无额度用户 U9 不生成任务",
      ReminderTask.query.filter_by(student_id=USERS[9]).count() == 0)
check("U8 只有考试任务",
      ReminderTask.query.filter_by(
          student_id=USERS[8], kind="grade").count() == 0
      and ReminderTask.query.filter_by(
          student_id=USERS[8], kind="exam", status="active").count() > 0)
check("U7 只有成绩额度",
      ss.quota(USERS[7], "exam") == 0
      and ReminderTask.query.filter_by(
          student_id=USERS[7], kind="exam").count() == 0
      and ReminderTask.query.filter_by(
          student_id=USERS[7], kind="grade", status="active").count() > 0)

same_course_tasks = ReminderTask.query.filter_by(
    kind="grade", course_name="课程01").all()
check("同名课程不同教师保持独立",
      {row.teacher_snapshot for row in same_course_tasks}
      == {"教师A", "教师B"},
      [(row.student_id, row.teacher_snapshot)
       for row in same_course_tasks])

# 让全部活动任务到期，模拟一次后台轮询。
for row in active_tasks:
    row.next_check_at = NOW - datetime.timedelta(minutes=1)
db.session.commit()

result = reminder.run_reminder_pool(now=NOW, limit=500)
actual_pairs = {
    (openid_to_sid[call["openid"]], call["course"])
    for call in send_calls
}
check("首轮发送量与预期成绩完全一致",
      len(send_calls) == len(expected_pairs)
      and actual_pairs == expected_pairs,
      {"actual": len(send_calls), "expected": len(expected_pairs),
       "missing": sorted(expected_pairs - actual_pairs)[:10],
       "extra": sorted(actual_pairs - expected_pairs)[:10]})
check("无额度 U9 不访问教务",
      USERS[9] not in exam_calls and USERS[9] not in grade_calls)
check("每个有额度用户单轮最多调用一次成绩接口",
      all(grade_calls.count(sid) == 1 for sid in USERS[:8])
      and grade_calls.count(USERS[8]) == 0,
      grade_calls)
check("没有跨用户成绩发送",
      actual_pairs <= expected_pairs)

# U0-U6 的成绩额度应全部耗尽；U7 仍有剩余额度。
for sid in USERS[:7]:
    check("用户额度耗尽 " + sid,
          ss.quota(sid, "grade") == 0)
check("U7 部分出分后仍有剩余额度",
      ss.quota(USERS[7], "grade") > 0)

send_count_before = len(send_calls)
grade_calls_before = len(grade_calls)
second = reminder.run_reminder_pool(
    now=NOW + datetime.timedelta(hours=1), limit=500)
check("第二轮不重复发送",
      len(send_calls) == send_count_before,
      {"before": send_count_before, "after": len(send_calls)})
check("第二轮只检查仍有活动的用户",
      len(grade_calls) - grade_calls_before <= 2,
      {"new_grade_calls": len(grade_calls) - grade_calls_before,
       "result": second})

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
print("10 用户 / 30 教学班规模模拟全部通过 [OK]")
