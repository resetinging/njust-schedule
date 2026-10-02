# -*- coding: utf-8 -*-
"""考试订阅提醒: 在"考前一天傍晚 ~ 开考前"的时间窗内, 有订阅额度就发送服务通知。

触发时机(窗口化, 幂等):
- 考前一天 `EXAM_REMINDER_HOUR`(默认 18) 点之后开始提示;
- 若当晚没发出去(比如用户后来才授权), 考试当天 06:00 起仍会补发, 直到开考前;
- 已开考的跳过; 每场考试只发一次(`{sid}:exam_reminded:{id}` 去重)。

微信规则(一次性订阅): 用户授权一次 = 可发 1 条; 没有额度就跳过并等用户再授权。
发送成功后才扣额度, 失败不扣(下一轮循环会自然重试)。
"""
import datetime
import os
import re
import threading
import time

from wxcloudrun import app, dao, db
from wxcloudrun.model import Exam
from wxcloudrun.core import mp, subscribe_store
from wxcloudrun.core.timeutil import _beijing_date, _beijing_datetime

LOOP_INTERVAL = 600          # 每 10 分钟检查一次
_HHMM = re.compile(r"(\d{1,2}):(\d{2})")


def _template_content() -> list:
    """模板字段: 优先环境变量覆盖(SUBSCRIBE_TPL_EXAM_FIELDS), 其次在线拉取, 最后默认映射。"""
    raw = (os.environ.get("SUBSCRIBE_TPL_EXAM_FIELDS") or "").strip()
    if raw:
        return [{"key": k.strip(), "name": ""} for k in raw.split(",") if k.strip()]
    content = mp.template_content(mp.template_id("exam"))
    if content:
        return content
    return [{"key": "thing1", "name": "考试名称"},
            {"key": "time2", "name": "考试时间"},
            {"key": "thing3", "name": "考场"}]


def _first_hhmm(text: str) -> str:
    m = _HHMM.search(text or "")
    return "%02d:%s" % (int(m.group(1)), m.group(2)) if m else ""


def build_exam_data(exam, content: list = None) -> dict:
    """按模板字段组装 data; thing 类字段自动截断到 20 字。"""
    content = content or _template_content()
    date = (exam.exam_date or "").strip()
    hm = _first_hhmm(exam.exam_time)
    data = {}
    for item in content:
        key = item.get("key") or ""
        name = item.get("name") or ""
        kind = "".join(ch for ch in key if ch.isalpha())     # thing / time / date / number ...
        if kind == "date":
            val = date
        elif kind == "time" or any(w in name for w in ("日期", "时间")):
            val = ("%s %s" % (date, hm)).strip() if hm else date
        elif "座位" in name and (exam.seat or ""):
            val = str(exam.seat)[:20]
        elif any(w in name for w in ("地点", "考场", "教室", "座位")):
            val = (exam.location or "以教务为准")[:20]
        elif any(w in name for w in ("名称", "课程", "科目", "考试")):
            val = (exam.course_name or "考试")[:20]
        else:
            val = (exam.exam_type or "考试")[:20]
        data[key] = {"value": str(val)}
    return data


def target_date() -> str:
    """提醒目标日期: 默认"明天"(北京时间)。"""
    return (_beijing_date() + datetime.timedelta(days=1)).isoformat()


def due_exams(date_str: str = "") -> list:
    """待提醒的考试: 默认扫描"今天 + 明天"(今天用于补发); 指定日期时只看该日。"""
    if date_str:
        return Exam.query.filter(Exam.exam_date.like(date_str + "%")).all()
    today = _beijing_date()
    d0, d1 = today.isoformat(), (today + datetime.timedelta(days=1)).isoformat()
    return Exam.query.filter(db.or_(Exam.exam_date.like(d0 + "%"),
                                    Exam.exam_date.like(d1 + "%"))).all()


def _exam_start(exam) -> datetime.datetime:
    """考试开始时间(datetime); 日期取前 10 位, 时间缺省按 08:00。"""
    date = (exam.exam_date or "")[:10]
    hm = _first_hhmm(exam.exam_time) or "08:00"
    try:
        return datetime.datetime.strptime("%s %s" % (date, hm), "%Y-%m-%d %H:%M")
    except ValueError:
        return datetime.datetime.max


def run_exam_reminders(dry_run: bool = False, date_str: str = "",
                       force: bool = False) -> dict:
    """扫描并发送考试提醒。

    dry_run: 只组装不发送(本地验证); force: 跳过时间窗与"未到点"判断(测试用)。
    """
    target = date_str or target_date()
    tpl = mp.template_id("exam")
    if not tpl:
        return {"ok": False, "reason": "未配置考试提醒模板", "date": target, "sent": 0}
    exams = sorted(due_exams(date_str), key=_exam_start)     # 先提醒最早的一场
    content = _template_content()
    now = _beijing_datetime()
    start_hour = int(os.environ.get("EXAM_REMINDER_HOUR", "18"))
    sent = failed = skipped = 0
    details = []
    for exam in exams:
        sid = exam.student_id or ""
        if not sid:
            skipped += 1
            continue
        if dry_run:                     # 只组装: 不受额度/时间窗限制, 便于自查
            details.append({"sid": sid, "exam": exam.course_name,
                            "data": build_exam_data(exam, content)})
            continue
        mark = dao.get_user_setting(sid, "exam_reminded:%s" % exam.id, "")
        start_dt = _exam_start(exam)
        if mark:
            skipped += 1
            continue
        if not force:
            if now >= start_dt:                       # 已开考: 不再提醒
                skipped += 1
                continue
            same_day = (now.date() == start_dt.date())
            # 考前一天: 到点后才发; 考试当天: 06:00 起补发(不打扰凌晨)
            if (not same_day and now.hour < start_hour) or (same_day and now.hour < 6):
                skipped += 1
                continue
        openid = subscribe_store.get_openid(sid)
        if not (mp.enabled() and openid):
            skipped += 1
            details.append({"sid": sid, "exam": exam.course_name,
                            "reason": "未配置MP_SECRET" if not mp.enabled() else "无openid"})
            continue
        if subscribe_store.quota(sid, "exam") <= 0:
            skipped += 1
            details.append({"sid": sid, "exam": exam.course_name, "reason": "无订阅额度"})
            continue
        res = mp.send_subscribe(openid, tpl, build_exam_data(exam, content),
                                page="pages/main/main?feature=exams")
        if res.get("ok"):
            subscribe_store.consume(sid, "exam")
            dao.set_user_setting(sid, "exam_reminded:%s" % exam.id, now.date().isoformat())
            sent += 1
        else:
            failed += 1
            details.append({"sid": sid, "exam": exam.course_name, "error": res})
    out = {"ok": True, "date": target, "total": len(exams), "sent": sent,
           "failed": failed, "skipped": skipped, "dry_run": bool(dry_run)}
    if details:
        out["details"] = details[:20]
    return out


def _loop() -> None:
    while True:
        try:
            if mp.enabled():
                # 幂等: 每轮只补发"未提醒过且未开考"的考试, 成功后按考试去重
                with app.app_context():
                    from wxcloudrun.core.state import distributed_lock
                    with distributed_lock(
                            "wx:lock:exam-reminder", ttl=600) as acquired:
                        if not acquired:
                            time.sleep(LOOP_INTERVAL)
                            continue
                        res = run_exam_reminders()
                if res.get("sent") or res.get("failed"):
                    app.logger.info("[reminder] 考试提醒 %s", res)
        except Exception as e:  # noqa: BLE001 循环内异常不致命
            app.logger.warning("[reminder] 循环异常: %s", e)
        time.sleep(LOOP_INTERVAL)


def start_exam_reminder() -> None:
    """启动考试提醒线程; 未配置 MP_SECRET 或 EXAM_REMINDER=0 时不启动。"""
    if (os.environ.get("EXAM_REMINDER", "1") or "").strip() == "0":
        app.logger.info("[reminder] 考试提醒已关闭(EXAM_REMINDER=0)")
        return
    if not mp.enabled():
        app.logger.info("[reminder] 未配置 MP_SECRET, 考试提醒未启动")
        return
    threading.Thread(target=_loop, daemon=True, name="exam-reminder").start()
    app.logger.info("[reminder] 考试提醒已启用(考前一天 %s 点起提醒, 当天 06:00 起补发)",
                    os.environ.get("EXAM_REMINDER_HOUR", "18"))
