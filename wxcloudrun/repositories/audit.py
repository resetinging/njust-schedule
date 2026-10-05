# -*- coding: utf-8 -*-
"""蹭课目录数据访问。"""
from datetime import datetime

from wxcloudrun.core.transactions import transaction
from wxcloudrun.model import AuditCourse


def replace_courses(courses: list, semester: str) -> int:
    """原子替换一个学期的目录，写入失败时保留旧目录。"""
    now = datetime.now()
    rows = [{
        "semester": semester,
        "course_name": course.get("name", ""),
        "class_info": course.get("class_info", ""),
        "teacher": course.get("teacher", ""),
        "classroom": course.get("classroom", ""),
        "day_of_week": int(course.get("day", 0) or 0),
        "start_period": int(course.get("start", 0) or 0),
        "end_period": int(course.get("end", 0) or 0),
        "weeks": str(course.get("weeks", "")),
        "updated_at": now,
    } for course in courses or []]
    with transaction() as session:
        session.query(AuditCourse).filter(
            AuditCourse.semester == semester,
        ).delete(synchronize_session=False)
        if rows:
            session.bulk_insert_mappings(AuditCourse, rows)
    return len(rows)


def count_courses(semester: str) -> int:
    return AuditCourse.query.filter(
        AuditCourse.semester == semester,
    ).count()
