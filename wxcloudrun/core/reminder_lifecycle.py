# -*- coding: utf-8 -*-
"""课程提醒生命周期: 培养方案匹配、结课日期和刷新池任务生成。

这里不直接访问教务。课程、培养方案和校历都来自已有缓存，只有在用户持有
考试/成绩订阅额度时才创建后台刷新任务。
"""
import datetime
import hashlib
import json
import re
import unicodedata

from wxcloudrun import dao, db
from wxcloudrun.core import subscribe_store
from wxcloudrun.core.timeutil import _beijing_datetime
from wxcloudrun.model import ReminderTask

GRADE_PHASE_DAYS = 28
EXAM_FALLBACK_DAYS = 28

_WEEK_RE = re.compile(r'(\d{1,2})(?:\s*[-~至]\s*(\d{1,2}))?')
_TEACHER_SPLIT_RE = re.compile(r'[,，、;；/]+')


def normalize_course_name(value: str) -> str:
    """课程名规范化: 保留编号和序号，只统一安全的字符差异。"""
    text = unicodedata.normalize("NFKC", str(value or "")).strip().lower()
    text = text.replace("（", "(").replace("）", ")")
    text = text.replace("【", "[").replace("】", "]")
    text = re.sub(r'[\s\u3000]+', '', text)
    text = re.sub(r'[‐‑‒–—−]', '-', text)
    return text


def normalize_teacher_key(value: str) -> str:
    """把教师字符串规范成稳定集合键，忽略顺序和重复。"""
    text = unicodedata.normalize("NFKC", str(value or "")).strip()
    if not text:
        return "unknown"
    names = []
    for item in _TEACHER_SPLIT_RE.split(text):
        name = re.sub(r'\s+', '', item).strip()
        if name and name not in names:
            names.append(name)
    if not names:
        return "unknown"
    return ",".join(sorted(names))


def _hash_key(value: str) -> str:
    return hashlib.sha256(str(value or "").encode("utf-8")).hexdigest()


def parse_week_numbers(raw: str) -> list:
    """解析 "1-16周" / "2,4,6-8" / 单双周。"""
    text = unicodedata.normalize("NFKC", str(raw or ""))
    text = text.replace("周", "").replace(" ", "")
    out = set()
    for start_s, end_s in _WEEK_RE.findall(text):
        try:
            start = int(start_s)
            end = int(end_s or start_s)
        except (TypeError, ValueError):
            continue
        if start > end:
            start, end = end, start
        for week in range(max(1, start), min(30, end) + 1):
            out.add(week)
    return sorted(out)


def _load_json(raw: str) -> dict:
    try:
        data = json.loads(raw or "")
    except (TypeError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _course_end_at(courses: list, calendar: dict):
    """返回课程组最晚的上课日期；无法计算时返回 None。"""
    weeks = calendar.get("weeks") if isinstance(calendar, dict) else []
    by_week = {}
    last_date = None
    for item in weeks or []:
        try:
            week_no = int(item.get("week") or 0)
        except (TypeError, ValueError):
            continue
        days = item.get("days") or []
        if week_no > 0 and len(days) >= 7:
            by_week[week_no] = days
            for day_text in days[:7]:
                try:
                    value = datetime.date.fromisoformat(str(day_text)[:10])
                except ValueError:
                    continue
                if last_date is None or value > last_date:
                    last_date = value

    latest = None
    fallback = False
    for course in courses or []:
        try:
            day = int(course.get("day") or 0)
        except (TypeError, ValueError):
            day = 0
        week_numbers = parse_week_numbers(course.get("weeks"))
        try:
            week_type = int(course.get("week_type") or 0)
        except (TypeError, ValueError):
            week_type = 0
        if week_type == 1:
            week_numbers = [week for week in week_numbers if week % 2 == 1]
        elif week_type == 2:
            week_numbers = [week for week in week_numbers if week % 2 == 0]
        if not week_numbers:
            fallback = True
            if last_date is not None and (latest is None or last_date > latest):
                latest = last_date
            continue
        for week_no in week_numbers:
            days = by_week.get(week_no)
            if not days or day < 1 or day > 7:
                continue
            try:
                value = datetime.date.fromisoformat(str(days[day - 1])[:10])
            except (ValueError, IndexError):
                continue
            if latest is None or value > latest:
                latest = value
    if latest is None:
        return None, False
    return datetime.datetime.combine(latest, datetime.time(23, 59)), fallback


def _assessment_type(exam_type: str) -> str:
    return "exam" if str(exam_type or "").strip() == "考试" else "assessment"


def match_programme_course(course_name: str, semester: str, credit,
                           programme_courses: list):
    """按学期和规范化课程名匹配培养方案，学分只用于消歧。"""
    target = normalize_course_name(course_name)
    if not target:
        return None
    candidates = []
    for item in programme_courses or []:
        if not isinstance(item, dict):
            continue
        if semester and str(item.get("semester") or "") != semester:
            continue
        if normalize_course_name(item.get("name")) != target:
            continue
        candidates.append(item)
    if not candidates:
        return None
    if len(candidates) == 1:
        return candidates[0]

    try:
        wanted_credit = float(credit or 0)
    except (TypeError, ValueError):
        wanted_credit = 0.0
    if wanted_credit > 0:
        by_credit = []
        for item in candidates:
            try:
                if abs(float(item.get("credit") or 0) - wanted_credit) < 0.01:
                    by_credit.append(item)
            except (TypeError, ValueError):
                continue
        if len(by_credit) == 1:
            return by_credit[0]
        if by_credit:
            candidates = by_credit

    modes = {
        _assessment_type(item.get("exam_type"))
        for item in candidates
    }
    return candidates[0] if len(modes) == 1 else None


def grade_next_check(now: datetime.datetime,
                     started_at: datetime.datetime):
    """按 7 + 14 + 7 天窗口计算下一次成绩检查时间。"""
    if not now or not started_at:
        return None
    start_day = started_at.date()
    day_index = max(0, (now.date() - start_day).days)
    if day_index >= GRADE_PHASE_DAYS:
        return None

    phase = 1
    if 7 <= day_index < 21:
        phase = 2
    elif 21 <= day_index < 28:
        phase = 3

    cur = now.replace(second=0, microsecond=0)
    if cur < started_at.replace(second=0, microsecond=0):
        cur = started_at.replace(second=0, microsecond=0)
    for _ in range(60 * 24 * 3):
        elapsed = max(0, (cur.date() - start_day).days)
        if elapsed >= GRADE_PHASE_DAYS:
            return None
        phase_now = 2 if 7 <= elapsed < 21 else 1
        if phase_now == 1:
            if (cur.hour == 10 or cur.hour == 14 or cur.hour == 18) \
                    and cur.minute == 0 and cur > now:
                return cur
        else:
            if 6 <= cur.hour <= 23 and cur.minute == 0 and cur > now:
                return cur
        cur += datetime.timedelta(minutes=1)
    return None


def _next_check_for_grade(now: datetime.datetime,
                          started_at: datetime.datetime):
    """优先返回当前/之后最近的允许检查时间。"""
    candidate = grade_next_check(now, started_at)
    if candidate is not None:
        return candidate
    # grade_next_check 使用严格大于 now，允许调用方立刻检查时显式处理。
    return grade_next_check(now - datetime.timedelta(seconds=1), started_at)


def _upsert_task(sid: str, semester: str, kind: str, course_key: str,
                 teacher_key: str, values: dict):
    row = ReminderTask.query.filter(
        ReminderTask.student_id == sid,
        ReminderTask.semester == semester,
        ReminderTask.kind == kind,
        ReminderTask.course_key == course_key,
        ReminderTask.teacher_key == teacher_key,
    ).first()
    if row is None:
        row = ReminderTask(
            student_id=sid,
            semester=semester,
            kind=kind,
            course_key=course_key,
            teacher_key=teacher_key,
        )
        db.session.add(row)
    if row.stage in ("done", "expired") and row.sent_at:
        return row
    for key, value in values.items():
        setattr(row, key, value)
    return row


def sync_user_reminder_tasks(sid: str, semester: str = "") -> dict:
    """按用户当前额度和缓存数据重建活跃任务；不访问教务。"""
    sid = str(sid or "").strip()
    semester = str(semester or "").strip()
    if not sid:
        return {"created": 0, "disabled": 0}
    if not semester:
        semester = dao.get_user_setting(sid, "semester") or ""
    if not semester:
        return {"created": 0, "disabled": 0}

    quotas = {kind: subscribe_store.quota(sid, kind)
              for kind in subscribe_store.KINDS}
    disabled = 0
    for kind, quota in quotas.items():
        if quota > 0:
            continue
        rows = ReminderTask.query.filter(
            ReminderTask.student_id == sid,
            ReminderTask.semester == semester,
            ReminderTask.kind == kind,
            ReminderTask.status == "active",
        ).all()
        for row in rows:
            row.status = "disabled"
            disabled += 1
    if not any(value > 0 for value in quotas.values()):
        db.session.commit()
        return {"created": 0, "disabled": disabled}

    courses = dao.get_courses(semester, sid)
    if not courses:
        db.session.commit()
        return {"created": 0, "disabled": disabled}
    calendar = _load_json(dao.get_setting(f"calendar:{semester}", ""))
    programme = _load_json(dao.get_user_setting(sid, "programme", ""))
    programme_courses = programme.get("courses") or []
    if not programme_courses:
        db.session.commit()
        return {"created": 0, "disabled": disabled}

    now = _beijing_datetime()
    grouped = {}
    for course in courses:
        name = str(course.get("name") or "").strip()
        teacher = str(course.get("teacher") or "").strip()
        if not name:
            continue
        teacher_norm = normalize_teacher_key(teacher)
        key = (normalize_course_name(name), teacher_norm)
        item = grouped.setdefault(key, {
            "name": name,
            "teacher": teacher,
            "teacher_norm": teacher_norm,
            "courses": [],
            "credit": course.get("credits") or course.get("credit") or 0,
        })
        item["courses"].append(course)

    created = 0
    seen = {"exam": set(), "grade": set()}
    for (norm_name, _teacher_norm), group in grouped.items():
        programme_item = match_programme_course(
            group["name"], semester, group["credit"], programme_courses)
        if not programme_item:
            continue
        mode = _assessment_type(programme_item.get("exam_type"))
        end_at, _fallback = _course_end_at(group["courses"], calendar)
        course_key = _hash_key(norm_name)
        teacher_key = _hash_key(group["teacher_norm"])
        common = {
            "course_name": group["name"],
            "teacher_snapshot": group["teacher"],
            "assessment_type": mode,
            "course_end_at": end_at,
        }

        if quotas.get("exam", 0) > 0 and mode == "exam":
            seen["exam"].add((course_key, teacher_key))
            if end_at and now >= end_at:
                stage = "wait_exam"
                next_at = now
            else:
                stage = "scheduled"
                next_at = end_at or now
            _upsert_task(
                sid, semester, "exam", course_key, teacher_key,
                dict(common, stage=stage, next_check_at=next_at,
                     exam_wait_started_at=end_at, status="active"))
            created += 1

        if quotas.get("grade", 0) > 0:
            seen["grade"].add((course_key, teacher_key))
            if mode == "exam":
                if end_at and now >= end_at:
                    stage = "pending_exam"
                    next_at = now
                else:
                    stage = "scheduled"
                    next_at = end_at or now
                _upsert_task(
                    sid, semester, "grade", course_key, teacher_key,
                    dict(common, stage=stage, next_check_at=next_at,
                         exam_wait_started_at=end_at, status="active"))
            else:
                start_at = end_at or now
                if now >= start_at:
                    if grade_expired(now, start_at):
                        stage = "expired"
                        next_at = None
                        task_status = "expired"
                    else:
                        stage = "wait_grade"
                        next_at = _next_check_for_grade(now, start_at)
                        task_status = "active"
                else:
                    stage = "scheduled"
                    next_at = start_at
                    task_status = "active"
                _upsert_task(
                    sid, semester, "grade", course_key, teacher_key,
                    dict(common, stage=stage, next_check_at=next_at,
                         grade_wait_started_at=start_at,
                         status=task_status))
            created += 1

    for kind, keys in seen.items():
        if quotas.get(kind, 0) <= 0:
            continue
        active_rows = ReminderTask.query.filter(
            ReminderTask.student_id == sid,
            ReminderTask.semester == semester,
            ReminderTask.kind == kind,
            ReminderTask.status == "active",
        ).all()
        for row in active_rows:
            if (row.course_key, row.teacher_key) in keys:
                continue
            row.status = "disabled"
            row.stage = "stale"
            row.next_check_at = None
            disabled += 1

    db.session.commit()
    return {"created": created, "disabled": disabled}


def grade_expired(now: datetime.datetime, started_at: datetime.datetime) -> bool:
    if not now or not started_at:
        return False
    return (now.date() - started_at.date()).days >= GRADE_PHASE_DAYS


def exam_fallback_expired(now: datetime.datetime,
                          started_at: datetime.datetime) -> bool:
    if not now or not started_at:
        return False
    return (now.date() - started_at.date()).days >= EXAM_FALLBACK_DAYS
