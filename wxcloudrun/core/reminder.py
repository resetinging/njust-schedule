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
from wxcloudrun.model import Exam, ReminderTask
from wxcloudrun.core import mp, subscribe_store
from wxcloudrun.core.timeutil import _beijing_date, _beijing_datetime

LOOP_INTERVAL = 600          # 每 10 分钟检查一次
_HHMM = re.compile(r"(\d{1,2}):(\d{2})")
_reminder_start_lock = threading.Lock()
_reminder_thread = None


def _template_content(kind: str = "exam") -> list:
    """模板字段: 优先环境变量覆盖(SUBSCRIBE_TPL_EXAM_FIELDS), 其次在线拉取, 最后默认映射。"""
    env_name = "SUBSCRIBE_TPL_%s_FIELDS" % str(kind or "exam").upper()
    raw = (os.environ.get(env_name) or "").strip()
    if raw:
        return [{"key": k.strip(), "name": ""} for k in raw.split(",") if k.strip()]
    content = mp.template_content(mp.template_id(kind))
    if content:
        return content
    if kind == "grade":
        return [{"key": "thing1", "name": "日程主题"},
                {"key": "thing2", "name": "课程名称"},
                {"key": "time3", "name": "时间"},
                {"key": "thing4", "name": "地点"},
                {"key": "thing5", "name": "备注"}]
    return [{"key": "thing1", "name": "日程主题"},
            {"key": "thing2", "name": "时长"},
            {"key": "time3", "name": "时间"},
            {"key": "thing4", "name": "地点"},
            {"key": "thing5", "name": "备注"}]


def _first_hhmm(text: str) -> str:
    m = _HHMM.search(text or "")
    return "%02d:%s" % (int(m.group(1)), m.group(2)) if m else ""


def _clip(value, limit: int = 20) -> str:
    return str(value or "")[:max(1, int(limit))]


def _exam_duration(text: str) -> str:
    values = re.findall(r'(\d{1,2}):(\d{2})', text or "")
    if len(values) < 2:
        return "考试"
    try:
        h1, m1 = (int(values[0][0]), int(values[0][1]))
        h2, m2 = (int(values[1][0]), int(values[1][1]))
        minutes = (h2 * 60 + m2) - (h1 * 60 + m1)
    except (TypeError, ValueError):
        return "考试"
    if minutes <= 0:
        return "考试"
    hours = minutes / 60.0
    if abs(hours - round(hours)) < 0.05:
        return "%d小时" % round(hours)
    return "%d分钟" % minutes


def _get_value(obj, key: str, default=""):
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _build_template_data(kind: str, obj, content: list = None,
                         detected_at: str = "") -> dict:
    """按模板字段语义组装 data; 考试与成绩共用同一模板时也能正确映射。"""
    content = content or _template_content(kind)
    course = str(_get_value(obj, "course_name", "") or "").strip()
    if kind == "grade":
        score = str(_get_value(obj, "score", "") or "").strip()
        point = _get_value(obj, "grade_point", "")
        topic = "成绩发布"
        event_time = detected_at or _beijing_datetime().strftime("%Y-%m-%d %H:%M")
        location = "教务成绩查询"
        duration = "成绩提醒"
        detail = score or "已出成绩"
        try:
            if point not in (None, "", 0, 0.0):
                detail = ("%s · %s绩点" % (detail, point))[:20]
        except Exception:
            pass
    else:
        date = str(_get_value(obj, "exam_date", "") or "").strip()
        hm = _first_hhmm(_get_value(obj, "exam_time", ""))
        topic = "考试提醒"
        event_time = ("%s %s" % (date, hm)).strip() if hm else date
        location = str(_get_value(obj, "location", "") or "以教务为准")
        duration = _exam_duration(_get_value(obj, "exam_time", ""))
        seat = str(_get_value(obj, "seat", "") or "").strip()
        exam_type = str(_get_value(obj, "exam_type", "") or "考试").strip()
        detail = ("座位%s · %s" % (seat, exam_type)).strip(" ·")
    data = {}
    for item in content:
        key = item.get("key") or ""
        name = item.get("name") or ""
        field_type = "".join(ch for ch in key if ch.isalpha())  # thing / time / date / number ...
        if field_type == "date":
            val = event_time[:10]
        elif field_type == "time" or any(w in name for w in ("日期", "时间")):
            val = event_time
        elif any(w in name for w in ("课程名称", "课程", "科目")):
            val = course or topic
        elif "主题" in name or "名称" in name or "考试" in name:
            val = topic
        elif "地点" in name or "考场" in name or "教室" in name or "地址" in name:
            val = location
        elif "时长" in name:
            val = duration
        elif any(w in name for w in ("备注", "说明", "结果", "成绩", "详情")):
            val = detail
        else:
            val = detail or topic
        data[key] = {"value": _clip(val)}
    return data


def build_exam_data(exam, content: list = None) -> dict:
    return _build_template_data("exam", exam, content)


def build_grade_data(grade, content: list = None, detected_at: str = "") -> dict:
    return _build_template_data("grade", grade, content, detected_at)


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
        try:
            from wxcloudrun.core.reminder_lifecycle import (
                normalize_course_name)
            task = (ReminderTask.query
                    .filter(ReminderTask.student_id == sid,
                            ReminderTask.kind == "exam",
                            ReminderTask.status == "active")
                    .all())
            matched = [
                item for item in task
                if normalize_course_name(item.course_name)
                == normalize_course_name(exam.course_name)
            ]
            if len({item.teacher_key for item in matched}) > 1:
                skipped += 1
                details.append({
                    "sid": sid, "exam": exam.course_name,
                    "reason": "同名课程任务存在歧义",
                })
                continue
            if matched and all(item.stage != "wait_exam" for item in matched):
                skipped += 1
                continue
        except Exception as exc:
            if (os.environ.get("REMINDER_LIFECYCLE", "1")
                    or "").strip() != "0":
                app.logger.warning(
                    "[reminder] 考试任务匹配失败，跳过发送 sid=%s: %s",
                    sid, type(exc).__name__)
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
                        if acquired:
                            res = run_exam_reminders()
                            pool = run_reminder_pool()
                        else:
                            res, pool = {}, {}
                if res.get("sent") or res.get("failed"):
                    app.logger.info("[reminder] 考试提醒 %s", res)
                if pool.get("sent") or pool.get("failed"):
                    app.logger.info("[reminder] 生命周期提醒 %s", pool)
        except Exception as e:  # noqa: BLE001 循环内异常不致命
            app.logger.warning("[reminder] 循环异常: %s", e)
        time.sleep(LOOP_INTERVAL)


def start_exam_reminder() -> bool:
    """启动考试提醒线程; 未配置 MP_SECRET 或 EXAM_REMINDER=0 时不启动。"""
    global _reminder_thread
    if (os.environ.get("EXAM_REMINDER", "1") or "").strip() == "0":
        app.logger.info("[reminder] 考试提醒已关闭(EXAM_REMINDER=0)")
        return False
    if not mp.enabled():
        app.logger.info("[reminder] 未配置 MP_SECRET, 考试提醒未启动")
        return False
    with _reminder_start_lock:
        if _reminder_thread is not None and _reminder_thread.is_alive():
            return False
        _reminder_thread = threading.Thread(
            target=_loop, daemon=True, name="exam-reminder")
        _reminder_thread.start()
    app.logger.info("[reminder] 考试提醒已启用(考前一天 %s 点起提醒, 当天 06:00 起补发)",
                    os.environ.get("EXAM_REMINDER_HOUR", "18"))
    return True


def _load_persisted_client(sid: str):
    """为后台任务加载用户持久化教务会话；不提交密码。"""
    from config import JW_SSO_BASE
    from wxcloudrun.core import session_store
    from wxcloudrun.jwc_client import JWCClient

    record = session_store.load_session_record(sid)
    if not record:
        return None, "无持久化教务会话"
    client = JWCClient()
    if not session_store.attach_session(client, record):
        return None, "会话 Cookie 无效"
    client.account_type = str(record.get("account_type") or "undergraduate")
    domains = " ".join(str(c.get("domain") or "")
                       for c in (record.get("cookies") or []))
    if "webvpn" in domains:
        client.webvpn.activate()
    else:
        client.webvpn.enable_sso_direct(JW_SSO_BASE)
    return client, ""


def _save_grade_rows(sid: str, grades: list) -> int:
    grouped = {}
    for item in grades or []:
        if not isinstance(item, dict):
            continue
        key = (str(item.get("academic_year") or ""),
               str(item.get("semester") or ""))
        grouped.setdefault(key, []).append(item)
    count = 0
    for (year, semester), rows in grouped.items():
        dao.save_grades(rows, year, semester, sid)
        count += len(rows)
    return count


def _exam_datetime(exam) -> datetime.datetime:
    date_value = (_get_value(exam, "exam_date", "")
                  or _get_value(exam, "date", ""))
    time_value = (_get_value(exam, "exam_time", "")
                  or _get_value(exam, "time", ""))
    date = str(date_value or "")[:10]
    hm = _first_hhmm(time_value) or "08:00"
    try:
        return datetime.datetime.strptime("%s %s" % (date, hm),
                                          "%Y-%m-%d %H:%M")
    except ValueError:
        return datetime.datetime.max


def _exam_end_datetime(exam) -> datetime.datetime:
    """考试结束时间以教务时间范围为准；缺失时按考试日结束兜底。"""
    start_dt = _exam_datetime(exam)
    if start_dt == datetime.datetime.max:
        return datetime.datetime.max
    time_value = (_get_value(exam, "exam_time", "")
                  or _get_value(exam, "time", ""))
    values = re.findall(r'(\d{1,2}):(\d{2})',
                        str(time_value or ""))
    if len(values) >= 2:
        try:
            end = start_dt.replace(
                hour=int(values[-1][0]), minute=int(values[-1][1]),
                second=0, microsecond=0)
            if end >= start_dt:
                return end
        except (TypeError, ValueError):
            pass
    return datetime.datetime.combine(start_dt.date(), datetime.time(23, 59))


def _find_exam_for_task(task, exams: list, ambiguous_names=None):
    from wxcloudrun.core.reminder_lifecycle import normalize_course_name
    wanted = normalize_course_name(task.course_name)
    if wanted in (ambiguous_names or set()):
        return None
    matches = [
        exam for exam in exams or []
        if normalize_course_name(_get_value(exam, "course_name", "")) == wanted
    ]
    return matches[0] if len(matches) == 1 else None


def _ambiguous_course_names(tasks: list) -> set:
    """同名课程存在不同教师时，禁止自动绑定教学班。"""
    from wxcloudrun.core.reminder_lifecycle import normalize_course_name
    by_name = {}
    for task in tasks or []:
        key = normalize_course_name(task.course_name)
        by_name.setdefault(key, set()).add(task.teacher_key or "")
    return {name for name, teachers in by_name.items() if len(teachers) > 1}


def _send_grade_reminder(task, grade) -> dict:
    sid = task.student_id or ""
    tpl = mp.template_id("grade")
    if not tpl:
        return {"ok": False, "reason": "未配置成绩提醒模板"}
    openid = subscribe_store.get_openid(sid)
    if not (mp.enabled() and openid):
        return {"ok": False, "reason": "无openid或发送能力"}
    if subscribe_store.quota(sid, "grade") <= 0:
        task.status = "disabled"
        task.next_check_at = None
        return {"ok": False, "reason": "无成绩提醒额度"}
    now_text = _beijing_datetime().strftime("%Y-%m-%d %H:%M")
    data = build_grade_data(grade, _template_content("grade"), now_text)
    res = mp.send_subscribe(
        openid, tpl, data,
        page="pages/main/main?feature=grades")
    if res.get("ok"):
        subscribe_store.consume(sid, "grade")
    return res


def _schedule_next_grade(task, now: datetime.datetime):
    from wxcloudrun.core.reminder_lifecycle import (
        grade_expired, _next_check_for_grade)
    started = task.grade_wait_started_at or task.course_end_at or now
    if grade_expired(now, started):
        task.stage = "expired"
        task.status = "expired"
        task.next_check_at = None
        return
    task.next_check_at = _next_check_for_grade(now, started)
    if task.next_check_at is None:
        task.stage = "expired"
        task.status = "expired"


def run_reminder_pool(dry_run: bool = False,
                      now: datetime.datetime = None,
                      limit: int = 200) -> dict:
    """处理到期的考试/成绩生命周期任务。"""
    if (os.environ.get("REMINDER_LIFECYCLE", "1") or "").strip() == "0":
        return {"ok": True, "disabled": True, "sent": 0}
    now = now or _beijing_datetime()
    rows = (ReminderTask.query
            .filter(ReminderTask.status == "active",
                    ReminderTask.next_check_at.isnot(None),
                    ReminderTask.next_check_at <= now)
            .order_by(ReminderTask.next_check_at,
                      ReminderTask.id)
            .limit(max(1, int(limit)))
            .all())
    if not rows:
        return {"ok": True, "due": 0, "sent": 0, "failed": 0,
                "skipped": 0}

    grouped = {}
    for task in rows:
        grouped.setdefault(task.student_id or "", []).append(task)

    sent = failed = skipped = checked = 0
    details = []
    for sid, tasks in grouped.items():
        allowed_tasks = []
        for task in tasks:
            if subscribe_store.quota(sid, task.kind) <= 0:
                task.status = "disabled"
                task.next_check_at = None
                skipped += 1
                continue
            allowed_tasks.append(task)
        tasks = allowed_tasks
        if not tasks:
            continue

        client, err = _load_persisted_client(sid)
        if client is None:
            skipped += len(tasks)
            for task in tasks:
                task.last_check_at = now
                task.fail_count = int(task.fail_count or 0) + 1
                if task.kind == "grade" and task.stage == "wait_grade":
                    _schedule_next_grade(task, now)
                else:
                    task.next_check_at = now + datetime.timedelta(hours=6)
            details.append({"sid": sid, "reason": err})
            continue

        exam_tasks = [task for task in tasks if task.kind == "exam"]
        grade_tasks = [task for task in tasks if task.kind == "grade"]
        exam_ambiguous = _ambiguous_course_names(exam_tasks)
        grade_ambiguous = _ambiguous_course_names(grade_tasks)
        for task in grade_tasks:
            if (task.stage == "scheduled"
                    and task.assessment_type != "exam"
                    and now >= task.next_check_at):
                task.stage = "wait_grade"
                task.grade_wait_started_at = (
                    task.course_end_at or now)
            elif (task.stage == "scheduled"
                  and task.assessment_type == "exam"
                  and now >= task.next_check_at):
                task.stage = "pending_exam"
                task.exam_wait_started_at = (
                    task.exam_wait_started_at or task.course_end_at or now)

        pending = [task for task in grade_tasks
                   if task.stage == "pending_exam"]
        exams = []
        exam_failed = False
        if pending or exam_tasks:
            semester = ((pending or exam_tasks)[0].semester or "")
            try:
                from wxcloudrun.core.pool import _jwc_request
                with _jwc_request(client):
                    exams = client.get_exams(semester)
                if not getattr(client, "logged_in", False):
                    raise RuntimeError(client.last_error or "教务会话已失效")
                dao.save_exams(exams, semester, sid)
            except Exception as exc:  # noqa: BLE001
                exam_failed = True
                failed += len(pending) + len(exam_tasks)
                details.append({"sid": sid, "error": str(exc)[:120]})
                for task in pending + exam_tasks:
                    task.fail_count = int(task.fail_count or 0) + 1
                    task.next_check_at = now + datetime.timedelta(hours=6)

        for task in exam_tasks:
            if exam_failed:
                continue
            exam = _find_exam_for_task(task, exams, exam_ambiguous)
            if exam is not None:
                exam_dt = _exam_datetime(exam)
                task.exam_at = (None if exam_dt == datetime.datetime.max
                                else exam_dt)
                end_dt = _exam_end_datetime(exam)
                task.exam_finished_at = (
                    None if end_dt == datetime.datetime.max else end_dt)
                if (task.exam_finished_at
                        and now >= task.exam_finished_at):
                    task.stage = "done"
                    task.status = "done"
                    task.next_check_at = None
                else:
                    task.stage = "wait_exam"
                    daily = now + datetime.timedelta(days=1)
                    task.next_check_at = (
                        min(task.exam_finished_at, daily)
                        if task.exam_finished_at else daily)
                continue
            from wxcloudrun.core.reminder_lifecycle import (
                exam_fallback_expired)
            started = task.exam_wait_started_at or task.course_end_at or now
            if exam_fallback_expired(now, started):
                task.stage = "expired"
                task.status = "expired"
                task.next_check_at = None
            else:
                task.next_check_at = now + datetime.timedelta(days=1)

        if pending:
            for task in pending:
                if exam_failed:
                    continue
                exam = _find_exam_for_task(task, exams, grade_ambiguous)
                if exam is not None:
                    exam_dt = _exam_datetime(exam)
                    task.exam_at = None if exam_dt == datetime.datetime.max else exam_dt
                    end_dt = _exam_end_datetime(exam)
                    task.exam_finished_at = (
                        None if end_dt == datetime.datetime.max else end_dt)
                    if (task.exam_finished_at
                            and now >= task.exam_finished_at):
                        task.stage = "wait_grade"
                        task.grade_wait_started_at = task.exam_finished_at
                        _schedule_next_grade(task, now)
                    else:
                        task.next_check_at = (
                            task.exam_finished_at
                            or now + datetime.timedelta(hours=6))
                    continue
                from wxcloudrun.core.reminder_lifecycle import (
                    exam_fallback_expired)
                started = (task.exam_wait_started_at
                           or task.course_end_at or now)
                if exam_fallback_expired(now, started):
                    task.stage = "wait_grade"
                    task.grade_wait_started_at = now
                    _schedule_next_grade(task, now)
                else:
                    task.next_check_at = now + datetime.timedelta(days=1)

        ready = [task for task in grade_tasks
                 if task.stage == "wait_grade"]
        if not ready:
            continue
        try:
            from wxcloudrun.core.pool import _jwc_request
            with _jwc_request(client):
                grades = client.get_grades("")
            if not getattr(client, "logged_in", False):
                raise RuntimeError(client.last_error or "教务会话已失效")
            checked += 1
            _save_grade_rows(sid, grades)
        except Exception as exc:  # noqa: BLE001
            failed += len(ready)
            details.append({"sid": sid, "error": str(exc)[:120]})
            for task in ready:
                task.last_check_at = now
                task.fail_count = int(task.fail_count or 0) + 1
                _schedule_next_grade(task, now)
            continue

        from wxcloudrun.core.reminder_lifecycle import normalize_course_name
        grade_by_name = {}
        for grade in grades or []:
            if isinstance(grade, dict):
                name = normalize_course_name(grade.get("course_name"))
                if name:
                    grade_by_name.setdefault(name, []).append(grade)
        active_counts = {}
        for task in ReminderTask.query.filter(
                ReminderTask.student_id == sid,
                ReminderTask.kind == "grade",
                ReminderTask.status == "active").all():
            key = normalize_course_name(task.course_name)
            active_counts[key] = active_counts.get(key, 0) + 1

        for task in ready:
            task.last_check_at = now
            key = normalize_course_name(task.course_name)
            matches = grade_by_name.get(key) or []
            if not matches or active_counts.get(key, 0) != 1:
                _schedule_next_grade(task, now)
                continue
            grade = matches[0]
            task.grade_first_seen_at = now
            if dry_run:
                skipped += 1
                continue
            res = _send_grade_reminder(task, grade)
            if res.get("ok"):
                task.stage = "done"
                task.status = "done"
                task.sent_at = now
                task.next_check_at = None
                sent += 1
                if subscribe_store.quota(sid, "grade") <= 0:
                    others = ReminderTask.query.filter(
                        ReminderTask.student_id == sid,
                        ReminderTask.kind == "grade",
                        ReminderTask.status == "active",
                        ReminderTask.id != task.id).all()
                    for other in others:
                        other.status = "disabled"
                        other.next_check_at = None
            else:
                skipped += 1
                if task.status != "disabled":
                    _schedule_next_grade(task, now)
                details.append({"sid": sid, "reason": res.get("reason"),
                                "errcode": res.get("errcode")})

    db.session.commit()
    out = {"ok": True, "due": len(rows), "users": len(grouped),
           "checked": checked, "sent": sent, "failed": failed,
           "skipped": skipped}
    if details:
        out["details"] = details[:20]
    return out
