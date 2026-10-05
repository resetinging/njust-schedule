# -*- coding: utf-8 -*-
"""课程提醒生命周期离线测试: 匹配、时间窗和额度池。"""
import datetime
import json
import os
import sys

_here = os.path.dirname(os.path.abspath(__file__))
_db_path = os.path.join(_here, "reminder_lifecycle_tmp.db")
if os.path.exists(_db_path):
    os.remove(_db_path)
os.environ["SQLALCHEMY_DATABASE_URI"] = "sqlite:///" + _db_path.replace("\\", "/")
os.environ["SCHEMA_CHECK_ON_STARTUP"] = "0"
sys.path.insert(0, os.path.dirname(_here))

from wxcloudrun import app, dao, db, _run_migrations  # noqa: E402
_run_migrations(force=True)
from wxcloudrun.core import subscribe_store as ss  # noqa: E402
from wxcloudrun.core.reminder_lifecycle import (  # noqa: E402
    _course_end_at, grade_expired, grade_next_check, match_programme_course,
    normalize_course_name, normalize_teacher_key, parse_week_numbers,
    sync_user_reminder_tasks)
from wxcloudrun.core.reminder import (  # noqa: E402
    _ambiguous_course_names, _exam_end_datetime)
from wxcloudrun.model import ReminderTask  # noqa: E402

_APP_CTX = app.app_context()
_APP_CTX.push()

SID = "924101960123"
SEM = "2026-2027-1"
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


print("== 纯函数 ==")
check("课程名全半角和空格规范化",
      normalize_course_name(" 高等数学（Ⅰ） ") == "高等数学(i)",
      normalize_course_name(" 高等数学（Ⅰ） "))
check("教师集合去重排序",
      normalize_teacher_key("王老师，李老师,王老师") == "李老师,王老师",
      normalize_teacher_key("王老师，李老师,王老师"))
check("周次范围解析",
      parse_week_numbers("2,4,6-8周") == [2, 4, 6, 7, 8],
      parse_week_numbers("2,4,6-8周"))
check("学分唯一消歧",
      match_programme_course("高等数学", SEM, 4, [
          {"semester": SEM, "name": "高等数学", "credit": 3, "exam_type": "考查"},
          {"semester": SEM, "name": "高等数学", "credit": 4, "exam_type": "考试"},
      ])["exam_type"] == "考试")
check("考核方式冲突不解析",
      match_programme_course("高等数学", SEM, 0, [
          {"semester": SEM, "name": "高等数学", "credit": 3, "exam_type": "考查"},
          {"semester": SEM, "name": "高等数学", "credit": 4, "exam_type": "考试"},
      ]) is None)

start = datetime.datetime(2026, 10, 1, 8, 0)
check("第一阶段 09:00 -> 10:00",
      grade_next_check(datetime.datetime(2026, 10, 1, 9, 0), start)
      == datetime.datetime(2026, 10, 1, 10, 0))
check("第一阶段 23:00 -> 次日 10:00",
      grade_next_check(datetime.datetime(2026, 10, 1, 23, 0), start)
      == datetime.datetime(2026, 10, 2, 10, 0))
check("第二阶段 05:30 -> 06:00",
      grade_next_check(datetime.datetime(2026, 10, 8, 5, 30), start)
      == datetime.datetime(2026, 10, 8, 6, 0))
check("第二阶段 10:30 -> 11:00",
      grade_next_check(datetime.datetime(2026, 10, 8, 10, 30), start)
      == datetime.datetime(2026, 10, 8, 11, 0))
check("第 28 天后停止",
      grade_next_check(datetime.datetime(2026, 10, 29, 10, 0), start) is None)
check("第 28 天判定过期",
      grade_expired(datetime.datetime(2026, 10, 29, 10, 0), start) is True)

week_calendar = {"weeks": [
    {"week": 1, "days": ["2026-09-07"] * 7},
    {"week": 2, "days": ["2026-09-14"] * 7},
    {"week": 3, "days": ["2026-09-21"] * 7},
    {"week": 4, "days": ["2026-09-28"] * 7},
]}
odd_end, _ = _course_end_at(
    [{"day": 1, "weeks": "1-4", "week_type": 1}], week_calendar)
even_end, _ = _course_end_at(
    [{"day": 1, "weeks": "1-4", "week_type": 2}], week_calendar)
check("单周结课以教务 week_type 为准",
      odd_end.strftime("%Y-%m-%d") == "2026-09-21",
      odd_end)
check("双周结课以教务 week_type 为准",
      even_end.strftime("%Y-%m-%d") == "2026-09-28",
      even_end)

class _ExamTime:
    exam_date = "2026-10-08"
    exam_time = "09:00-11:30"
check("考试结束时间取教务时间范围",
      _exam_end_datetime(_ExamTime()).strftime("%H:%M") == "11:30")
check("同名不同教师标记为歧义",
      _ambiguous_course_names([
          type("T", (), {"course_name": "高等数学", "teacher_key": "a"})(),
          type("T", (), {"course_name": "高等数学", "teacher_key": "b"})(),
      ]) == {"高等数学"})

print("== 额度和任务生成 ==")
calendar = {
    "semester": SEM,
    "weeks": [{
        "week": 1,
        "days": ["2026-09-28", "2026-09-29", "2026-09-30",
                 "2026-10-01", "2026-10-02", "2026-10-03", "2026-10-04"],
    }],
}
programme = {
    "semester": SEM,
    "courses": [
        {"semester": SEM, "name": "高等数学", "credit": 4, "exam_type": "考试"},
        {"semester": SEM, "name": "大学物理", "credit": 3, "exam_type": "考查"},
    ],
}
dao.set_setting("calendar:" + SEM, json.dumps(calendar, ensure_ascii=False))
dao.set_user_setting(SID, "semester", SEM)
dao.set_user_setting(SID, "programme", json.dumps(programme, ensure_ascii=False))
dao.save_courses([
    {"name": "高等数学", "teacher": "张老师", "day": 1,
     "start": 1, "end": 2, "weeks": "1", "credits": 4},
    {"name": "大学物理", "teacher": "李老师", "day": 2,
     "start": 3, "end": 4, "weeks": "1", "credits": 3},
], SEM, SID)

check("无额度不创建任务", sync_user_reminder_tasks(SID, SEM)["created"] == 0
      and ReminderTask.query.count() == 0)
ss.grant(SID, "exam", 1)
ss.grant(SID, "grade", 1)
result = sync_user_reminder_tasks(SID, SEM)
check("有额度后创建任务", result["created"] == 3, result)
check("考试课创建考试和成绩任务",
      ReminderTask.query.filter(ReminderTask.kind == "exam").count() == 1
      and ReminderTask.query.filter(ReminderTask.kind == "grade").count() == 2,
      [(r.kind, r.course_name, r.stage)
       for r in ReminderTask.query.order_by(ReminderTask.id).all()])
check("考查课只创建成绩任务",
      ReminderTask.query.filter_by(course_name="大学物理").count() == 1)
check("考试课成绩任务先等待考试",
      ReminderTask.query.filter_by(
          kind="grade", course_name="高等数学").first().stage == "pending_exam")
check("考查课成绩任务直接等待成绩",
      ReminderTask.query.filter_by(
          kind="grade", course_name="大学物理").first().stage == "wait_grade")

dao.save_courses([
    {"name": "高等数学", "teacher": "张老师", "day": 1,
     "start": 1, "end": 2, "weeks": "1", "credits": 4},
], SEM, SID)
sync_user_reminder_tasks(SID, SEM)
stale = ReminderTask.query.filter_by(
    student_id=SID, course_name="大学物理").first()
check("旧任务停用但保留记录",
      stale is not None and stale.status == "disabled" and stale.stage == "stale"
      and ReminderTask.query.filter_by(student_id=SID).count() == 3,
      stale.to_dict() if stale else None)
dao.save_courses([
    {"name": "高等数学", "teacher": "张老师", "day": 1,
     "start": 1, "end": 2, "weeks": "1", "credits": 4},
    {"name": "大学物理", "teacher": "李老师", "day": 2,
     "start": 3, "end": 4, "weeks": "1", "credits": 3},
], SEM, SID)
sync_user_reminder_tasks(SID, SEM)
check("课程恢复后任务重新激活",
      ReminderTask.query.filter_by(
          student_id=SID, course_name="大学物理").first().status == "active")

ss.consume(SID, "grade")
disabled = sync_user_reminder_tasks(SID, SEM)
check("成绩额度清零后退出池",
      disabled["disabled"] == 2
      and ReminderTask.query.filter_by(kind="grade", status="active").count() == 0,
      disabled)
dao.clear_data(SEM, SID)
check("清空学期数据保留任务记录并停用",
      ReminderTask.query.filter_by(student_id=SID, semester=SEM).count() > 0
      and ReminderTask.query.filter_by(
          student_id=SID, semester=SEM, status="active").count() == 0)

OLD_SID = "924101960199"
OLD_SEM = "2025-2026-1"
old_calendar = {
    "semester": OLD_SEM,
    "weeks": [{
        "week": 1,
        "days": ["2026-08-24", "2026-08-25", "2026-08-26",
                 "2026-08-27", "2026-08-28", "2026-08-29", "2026-08-30"],
    }],
}
dao.set_setting("calendar:" + OLD_SEM,
                json.dumps(old_calendar, ensure_ascii=False))
dao.set_user_setting(OLD_SID, "semester", OLD_SEM)
dao.set_user_setting(
    OLD_SID, "programme",
    json.dumps({"courses": [
        {"semester": OLD_SEM, "name": "大学物理", "credit": 3,
         "exam_type": "考查"}]}, ensure_ascii=False))
dao.save_courses([
    {"name": "大学物理", "teacher": "李老师", "day": 2,
     "start": 3, "end": 4, "weeks": "1", "credits": 3},
], OLD_SEM, OLD_SID)
ss.grant(OLD_SID, "grade", 1)
sync_user_reminder_tasks(OLD_SID, OLD_SEM)
old_task = ReminderTask.query.filter_by(student_id=OLD_SID).first()
check("超过 28 天直接标记过期",
      old_task is not None and old_task.status == "expired"
      and old_task.next_check_at is None,
      old_task.to_dict() if old_task else None)

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
print("提醒生命周期测试全部通过 [OK]")
