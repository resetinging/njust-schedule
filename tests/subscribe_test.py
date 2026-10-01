# -*- coding: utf-8 -*-
"""订阅消息与考试提醒测试(离线, 不联网): 额度存储 / 消息组装 / 窗口化触发与去重。"""
import datetime
import os
import sys

_here = os.path.dirname(os.path.abspath(__file__))
_db_path = os.path.join(_here, "subscribe_tmp.db")
if os.path.exists(_db_path):
    os.remove(_db_path)
os.environ["SQLALCHEMY_DATABASE_URI"] = "sqlite:///" + _db_path.replace("\\", "/")
sys.path.insert(0, os.path.dirname(_here))

from wxcloudrun import app, db, dao  # noqa: E402
from wxcloudrun.core import mp, reminder, subscribe_store as ss  # noqa: E402
from wxcloudrun.model import Exam  # noqa: E402

SID = "10001"
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


class _Exam:
    course_name = "高等工程数学I"
    exam_date = "2026-10-08"
    exam_time = "09:00-11:00"
    location = "I-301"
    seat = "12"
    exam_type = "期末考试"


print("== 订阅额度存储 ==")
check("初始额度为 0(当前仅考试提醒)", ss.status(SID) == {"exam": 0}, ss.status(SID))
ss.grant(SID, "exam", 1, openid="o_test_openid")
check("授权后额度 +1", ss.quota(SID, "exam") == 1, ss.quota(SID, "exam"))
check("openid 已保存", ss.get_openid(SID) == "o_test_openid", ss.get_openid(SID))
check("扣减成功", ss.consume(SID, "exam") is True and ss.quota(SID, "exam") == 0,
      ss.quota(SID, "exam"))
check("无额度扣减失败", ss.consume(SID, "exam") is False)
check("未知类型不记录", ss.grant(SID, "unknown", 1) == {})

print("== 模板消息组装 ==")
data = reminder.build_exam_data(_Exam(), None)
check("包含 thing/time 字段", set(data.keys()) == {"thing1", "time2", "thing3"}, list(data.keys()))
check("课程名截断<=20", data["thing1"]["value"] == "高等工程数学I", data["thing1"])
check("时间格式 yyyy-mm-dd hh:mm", data["time2"]["value"] == "2026-10-08 09:00", data["time2"])
check("地点进 thing3", data["thing3"]["value"] == "I-301", data["thing3"])

print("== 考试提醒(窗口化触发) ==")
with app.app_context():
    exam_day = (reminder._beijing_date() + datetime.timedelta(days=1)).isoformat()
    e = Exam(student_id=SID, course_name="大学物理", exam_date=exam_day,
             exam_time="14:00-16:00", location="II-202", seat="12",
             exam_type="期末考试")
    db.session.add(e)
    db.session.commit()
    start_dt = datetime.datetime.strptime(exam_day + " 14:00", "%Y-%m-%d %H:%M")

    dry = reminder.run_exam_reminders(dry_run=True)
    check("dry_run 命中 1 场", dry["total"] == 1 and dry["dry_run"] is True, dry)
    check("dry_run 含组装数据", dry["details"][0]["data"]["time2"]["value"].startswith(exam_day),
          dry["details"][0])

    # 未配置 MP_SECRET: 跳过且不扣额度
    ss.grant(SID, "exam", 1)
    res = reminder.run_exam_reminders(force=True)
    check("未配置密钥 -> 跳过", res["sent"] == 0 and res["skipped"] == 1, res)
    check("跳过不扣额度", ss.quota(SID, "exam") == 1, ss.quota(SID, "exam"))

    _orig_enabled, _orig_send = mp.enabled, mp.send_subscribe
    _orig_now = reminder._beijing_datetime
    mp.enabled = lambda: True
    mp.send_subscribe = lambda openid, tpl, data, page="": {"ok": True, "errcode": 0}

    def _reset_exam():
        dao.set_user_setting(SID, "exam_reminded:%s" % e.id, "")
        ss.grant(SID, "exam", 1)

    # 1) 考前一天 17:00(未到点) -> 不发
    reminder._beijing_datetime = lambda: start_dt - datetime.timedelta(hours=21)
    r1 = reminder.run_exam_reminders(date_str=exam_day)
    check("考前一天未到点 -> 不发", r1["sent"] == 0 and r1["skipped"] == 1, r1)

    # 2) 考前一天 19:00(到点) -> 发送并扣额度; 同一场不重发
    reminder._beijing_datetime = lambda: start_dt - datetime.timedelta(hours=19)
    r2 = reminder.run_exam_reminders(date_str=exam_day)
    check("考前一天到点 -> 发送 1 条", r2["sent"] == 1, r2)
    check("发送后扣减额度", ss.quota(SID, "exam") == 0, ss.quota(SID, "exam"))
    r2b = reminder.run_exam_reminders(date_str=exam_day)
    check("同一场考试不重发", r2b["sent"] == 0 and r2b["skipped"] == 1, r2b)

    # 3) 考试当天 05:00(凌晨不打扰) -> 不发; 07:00(补发) -> 发送
    _reset_exam()
    reminder._beijing_datetime = lambda: start_dt - datetime.timedelta(hours=9)
    r3 = reminder.run_exam_reminders(date_str=exam_day)
    check("当天凌晨 05:00 不打扰", r3["sent"] == 0, r3)
    reminder._beijing_datetime = lambda: start_dt - datetime.timedelta(hours=7)
    r4 = reminder.run_exam_reminders(date_str=exam_day)
    check("当天 07:00 补发成功", r4["sent"] == 1, r4)

    # 4) 已开考(当天 15:00) -> 不发, 且不扣额度
    _reset_exam()
    reminder._beijing_datetime = lambda: start_dt + datetime.timedelta(hours=1)
    r5 = reminder.run_exam_reminders(date_str=exam_day)
    check("已开考 -> 不发", r5["sent"] == 0 and r5["skipped"] == 1, r5)
    check("已开考不扣额度", ss.quota(SID, "exam") == 1, ss.quota(SID, "exam"))

    # 5) 发送失败: 不标记、不扣额度
    reminder._beijing_datetime = lambda: start_dt - datetime.timedelta(hours=19)
    mp.send_subscribe = lambda openid, tpl, data, page="": {"ok": False, "errcode": 43101,
                                                            "errmsg": "user refuse"}
    r6 = reminder.run_exam_reminders(date_str=exam_day)
    check("发送失败不计成功", r6["sent"] == 0 and r6["failed"] == 1, r6)
    check("失败不扣额度", ss.quota(SID, "exam") == 1, ss.quota(SID, "exam"))
    mp.enabled, mp.send_subscribe = _orig_enabled, _orig_send
    reminder._beijing_datetime = _orig_now

print()
print("结果: %d 通过, %d 失败" % (PASS, FAIL))
try:
    os.remove(os.path.join(_here, "subscribe_tmp.db"))
except OSError:
    pass
if FAIL:
    print("失败项:", FAILURES)
    sys.exit(1)
print("订阅消息测试全部通过 [OK]")
