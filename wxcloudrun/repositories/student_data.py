# -*- coding: utf-8 -*-
"""用户学习数据 repository。

这里仅负责 SQLAlchemy 查询、快照替换和模型序列化，不处理 HTTP、教务会话
或缓存。所有全量刷新都在一个事务中完成，失败时保留原快照。
"""
import json

from datetime import datetime

from wxcloudrun.core.transactions import transaction
from wxcloudrun.model import CetScore, Course, Exam, Evaluation, Grade


def replace_courses(courses: list, semester: str, student_id: str = "") -> int:
    rows = [{
        "student_id": student_id,
        "name": c.get("name", ""),
        "teacher": c.get("teacher", ""),
        "classroom": c.get("classroom", ""),
        "day_of_week": c.get("day", 0),
        "start_period": c.get("start", 0),
        "end_period": c.get("end", 0),
        "weeks": c.get("weeks", ""),
        "week_type": c.get("week_type", 0),
        "semester": semester,
        "credits": str(c.get("credits", "")),
        "course_type": c.get("course_type", ""),
        "raw_data": json.dumps(c.get("raw", {}), ensure_ascii=False),
    } for c in courses or []]
    with transaction() as session:
        session.query(Course).filter(
            Course.semester == semester,
            Course.student_id == student_id,
        ).delete(synchronize_session=False)
        if rows:
            session.bulk_insert_mappings(Course, rows)
    return len(rows)


def get_courses(semester: str, student_id: str = "") -> list:
    rows = Course.query.filter(
        Course.semester == semester,
        Course.student_id == student_id,
    ).order_by(Course.day_of_week, Course.start_period).all()
    return [row.to_dict() for row in rows]


def count_courses(semester: str, student_id: str = "") -> int:
    return Course.query.filter(
        Course.semester == semester,
        Course.student_id == student_id,
    ).count()


def replace_exams(exams: list, semester: str, student_id: str = "") -> int:
    with transaction() as session:
        session.query(Exam).filter(
            Exam.semester == semester,
            Exam.student_id == student_id,
        ).delete(synchronize_session=False)
        for exam in exams or []:
            session.add(Exam(
                student_id=student_id,
                course_name=exam.get("course_name", ""),
                exam_date=exam.get("date", ""),
                exam_time=exam.get("time", ""),
                location=exam.get("location", ""),
                seat=exam.get("seat", ""),
                exam_type=exam.get("type", "期末考试"),
                semester=semester,
            ))
    return len(exams or [])


def get_exams(semester: str, student_id: str = "") -> list:
    rows = Exam.query.filter(
        Exam.semester == semester,
        Exam.student_id == student_id,
    ).order_by(Exam.exam_date).all()
    return [row.to_dict() for row in rows]


def count_exams(semester: str, student_id: str = "") -> int:
    return Exam.query.filter(
        Exam.semester == semester,
        Exam.student_id == student_id,
    ).count()


def replace_grades(grades: list, academic_year: str, semester: str,
                   student_id: str = "") -> int:
    rows = [{
        "student_id": student_id,
        "academic_year": grade.get("academic_year", academic_year),
        "semester": grade.get("semester", semester),
        "course_code": grade.get("course_code", ""),
        "course_name": grade.get("course_name", ""),
        "score": str(grade.get("score", "")),
        "credit": float(grade.get("credit", 0) or 0),
        "grade_point": float(grade.get("grade_point", 0) or 0),
        "course_type": grade.get("course_type", ""),
        "course_nature": grade.get("course_nature", ""),
        "exam_type": grade.get("exam_type", "正常考试"),
    } for grade in grades or []]
    with transaction() as session:
        session.query(Grade).filter(
            Grade.academic_year == academic_year,
            Grade.semester == semester,
            Grade.student_id == student_id,
        ).delete(synchronize_session=False)
        if rows:
            session.bulk_insert_mappings(Grade, rows)
    return len(rows)


def replace_grades_snapshot(grades: list, student_id: str = "") -> int:
    """原子替换用户的完整成绩快照。

    成绩接口返回的是跨学期全量结果，必须在同一个事务中完成旧快照删除
    和新快照写入。空结果不修改已有数据，避免教务短暂异常导致成绩被清空。
    """
    rows = []
    for grade in grades or []:
        if not isinstance(grade, dict):
            continue
        rows.append({
            "student_id": student_id,
            "academic_year": grade.get("academic_year", ""),
            "semester": grade.get("semester", ""),
            "course_code": grade.get("course_code", ""),
            "course_name": grade.get("course_name", ""),
            "score": str(grade.get("score", "")),
            "credit": float(grade.get("credit", 0) or 0),
            "grade_point": float(grade.get("grade_point", 0) or 0),
            "course_type": grade.get("course_type", ""),
            "course_nature": grade.get("course_nature", ""),
            "exam_type": grade.get("exam_type", "正常考试"),
        })
    if not rows:
        return 0
    with transaction() as session:
        session.query(Grade).filter(
            Grade.student_id == student_id,
        ).delete(synchronize_session=False)
        session.bulk_insert_mappings(Grade, rows)
    return len(rows)


def get_grades(academic_year: str = "", semester: str = "",
               student_id: str = "") -> list:
    query = Grade.query
    if student_id:
        query = query.filter(Grade.student_id == student_id)
    if academic_year:
        query = query.filter(Grade.academic_year == academic_year)
    if semester:
        query = query.filter(Grade.semester == semester)
    rows = query.order_by(
        Grade.academic_year.desc(), Grade.semester.desc(),
        Grade.course_type, Grade.course_name,
    ).all()
    return [row.to_dict() for row in rows]


def get_grade_semesters(student_id: str = "") -> list:
    query = Grade.query.with_entities(Grade.academic_year, Grade.semester)
    if student_id:
        query = query.filter(Grade.student_id == student_id)
    rows = query.distinct().order_by(
        Grade.academic_year.desc(), Grade.semester.desc()).all()
    return [f"{row[0]}-{row[1]}" for row in rows]


def replace_cet_scores(scores: list, student_id: str = "") -> int:
    with transaction() as session:
        session.query(CetScore).filter(
            CetScore.student_id == student_id,
        ).delete(synchronize_session=False)
        for score in scores or []:
            session.add(CetScore(
                student_id=student_id,
                cet_type=score.get("type", ""),
                total_score=float(score.get("score", 0) or 0),
                exam_date=score.get("exam_date", ""),
            ))
    return len(scores or [])


def get_cet_scores(student_id: str = "") -> list:
    query = CetScore.query
    if student_id:
        query = query.filter(CetScore.student_id == student_id)
    best = {}
    for row in query.all():
        if row.cet_type not in best or row.total_score > best[row.cet_type][0]:
            best[row.cet_type] = (row.total_score, row.exam_date)
    return [
        {"type": kind, "score": float(score or 0), "exam_date": exam_date or ""}
        for kind, (score, exam_date) in sorted(best.items())
    ]


def replace_evaluations(evaluations: list, student_id: str = "") -> int:
    with transaction() as session:
        session.query(Evaluation).filter(
            Evaluation.student_id == student_id,
        ).delete(synchronize_session=False)
        for item in evaluations or []:
            session.add(Evaluation(
                student_id=student_id,
                semester=item.get("semester", ""),
                category=item.get("category", ""),
                batch=item.get("batch", ""),
                start_date=item.get("start_date", ""),
                end_date=item.get("end_date", ""),
                is_done=1 if item.get("is_done") else 0,
                items_json=json.dumps(item.get("items", []), ensure_ascii=False),
            ))
    return len(evaluations or [])
