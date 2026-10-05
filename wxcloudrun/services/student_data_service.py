# -*- coding: utf-8 -*-
"""本科生学习数据服务。

这里不依赖 Flask request/response，统一管理一次刷新中的教务访问和快照写入。
Repository 负责事务，服务层负责业务顺序和缓存失效。
"""
from wxcloudrun import app, dao
from wxcloudrun.core.cache import invalidate_user_cache
from wxcloudrun.core.pool import _jwc_request
from wxcloudrun.core.semester import current_semester
from wxcloudrun.core.stats import _invalidate_stats
from wxcloudrun.repositories import student_data


class StudentDataError(RuntimeError):
    """可安全映射为 API 错误的刷新异常。"""

    def __init__(self, message: str, status_code: int = 500):
        super().__init__(message)
        self.message = str(message or "数据刷新失败")
        self.status_code = int(status_code or 500)


def resolve_semester(student_id: str, semester: str = "") -> str:
    """按请求参数、用户设置、当前学期的优先级解析学期。"""
    return (str(semester or "").strip()
            or dao.get_user_setting(student_id, "semester")
            or current_semester())


def _is_session_error(client) -> bool:
    error = str(getattr(client, "last_error", "") or "")
    return (not getattr(client, "logged_in", True)
            or "登录" in error
            or "logon" in error.lower()
            or "session" in error.lower())


def _fetch_locked(client, method, error_label: str, *args):
    """在已持有访问锁时执行一个教务域请求。"""
    client.last_error = ""
    result = method(*args)
    if result:
        return result
    error = str(getattr(client, "last_error", "") or "")
    if not error:
        return []
    if _is_session_error(client):
        client.logged_in = False
        raise StudentDataError("会话已过期，请重新登录", 401)
    raise StudentDataError(f"{error_label}: {error}")


def _fetch(client, method, error_label: str, *args):
    with _jwc_request(client):
        return _fetch_locked(client, method, error_label, *args)


def _sync_reminders(student_id: str, semester: str, source: str) -> None:
    try:
        from wxcloudrun.core.reminder_lifecycle import sync_user_reminder_tasks
        sync_user_reminder_tasks(student_id, semester)
    except Exception as exc:  # noqa: BLE001 提醒失败不应回滚已保存的学习数据
        app.logger.warning("[%s] 提醒任务同步失败 sid=%s: %s",
                           source, student_id, type(exc).__name__)


def refresh_schedule(client, semester: str = "") -> dict:
    """刷新本科课表并原子替换当前用户快照。"""
    student_id = str(getattr(client, "student_id", "") or "")
    semester = resolve_semester(student_id, semester)
    courses = _fetch(client, client.get_schedule, "获取课表失败", semester)
    count = student_data.replace_courses(courses, semester, student_id)
    dao.set_user_setting(student_id, "semester", semester)
    invalidate_user_cache(student_id, "courses")
    _invalidate_stats(student_id, semester)
    _sync_reminders(student_id, semester, "refresh")
    return {"semester": semester, "count": count, "courses": courses}


def refresh_exams(client, semester: str = "") -> dict:
    """刷新本科考试并原子替换当前用户快照。"""
    student_id = str(getattr(client, "student_id", "") or "")
    semester = resolve_semester(student_id, semester)
    exams = _fetch(client, client.get_exams, "获取考试失败", semester)
    count = student_data.replace_exams(exams, semester, student_id)
    invalidate_user_cache(student_id, "exams")
    _invalidate_stats(student_id, semester)
    return {"semester": semester, "count": count, "exams": exams}


def refresh_schedule_and_exams(client, semester: str = "") -> dict:
    """一次访问锁内刷新课表和考试，允许一个域失败而保留另一个成功结果。"""
    student_id = str(getattr(client, "student_id", "") or "")
    semester = resolve_semester(student_id, semester)
    result = {"semester": semester, "schedule": None, "exams": None}
    with _jwc_request(client):
        try:
            courses = _fetch_locked(client, client.get_schedule,
                                    "获取课表失败", semester)
            count = student_data.replace_courses(courses, semester, student_id)
            result["schedule"] = {"count": count, "ok": True}
        except StudentDataError as exc:
            result["schedule"] = {"count": 0, "ok": False,
                                   "error": exc.message,
                                   "status_code": exc.status_code}
            if exc.status_code == 401:
                result["aborted"] = "session_expired"

        if result.get("aborted"):
            result["exams"] = {"count": 0, "ok": False,
                                "error": "会话已过期，请重新登录",
                                "status_code": 401}
        else:
            try:
                exams = _fetch_locked(client, client.get_exams,
                                      "获取考试失败", semester)
                count = student_data.replace_exams(exams, semester, student_id)
                result["exams"] = {"count": count, "ok": True}
            except StudentDataError as exc:
                result["exams"] = {"count": 0, "ok": False,
                                    "error": exc.message,
                                    "status_code": exc.status_code}
                if exc.status_code == 401:
                    result["aborted"] = "session_expired"

    if result["schedule"]["ok"]:
        invalidate_user_cache(student_id, "courses")
    if result["exams"]["ok"]:
        invalidate_user_cache(student_id, "exams")
    dao.set_user_setting(student_id, "semester", semester)
    _invalidate_stats(student_id, semester)
    if result["schedule"]["ok"]:
        _sync_reminders(student_id, semester, "refresh-all")
    return result


def refresh_grades(client) -> dict:
    """刷新成绩，在一个事务中原子替换用户的完整成绩快照。"""
    student_id = str(getattr(client, "student_id", "") or "")
    grades = _fetch(client, client.get_grades, "获取成绩失败", "")
    valid_grades = [grade for grade in grades or []
                    if isinstance(grade, dict)]
    total = student_data.replace_grades_snapshot(valid_grades, student_id)
    invalidate_user_cache(student_id, "grades")
    semesters = {(grade.get("academic_year", ""),
                  grade.get("semester", "")) for grade in valid_grades}
    return {"count": total, "semesters": len(semesters),
            "grades": grades or []}


def refresh_cet(client) -> dict:
    """刷新四六级成绩；空结果保留为业务错误而非清空旧快照。"""
    student_id = str(getattr(client, "student_id", "") or "")
    scores = _fetch(client, client.get_cet_scores, "获取四六级成绩失败")
    if not scores:
        raise StudentDataError("未获取到四六级成绩", 404)
    count = student_data.replace_cet_scores(scores, student_id)
    invalidate_user_cache(student_id, "cet")
    return {"count": count, "scores": scores}
