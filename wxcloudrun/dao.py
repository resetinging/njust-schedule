"""
数据访问层 — SQLAlchemy ORM
===========================
包含：模板 Counter + NJUST 课表/考试/评教/设置
"""
import json
import logging
from sqlalchemy.exc import OperationalError
from wxcloudrun import db
from wxcloudrun.model import Counters, Course, Exam, Evaluation, Setting

logger = logging.getLogger('log')


# ============================================================
# 模板原有 — Counter
# ============================================================
def query_counterbyid(cid):
    try:
        return Counters.query.filter(Counters.id == cid).first()
    except OperationalError as e:
        logger.info("query_counterbyid errorMsg= {} ".format(e))
        return None


def delete_counterbyid(cid):
    try:
        counter = Counters.query.get(cid)
        if counter is None:
            return
        db.session.delete(counter)
        db.session.commit()
    except OperationalError as e:
        logger.info("delete_counterbyid errorMsg= {} ".format(e))


def insert_counter(counter):
    try:
        db.session.add(counter)
        db.session.commit()
    except OperationalError as e:
        logger.info("insert_counter errorMsg= {} ".format(e))


def update_counterbyid(counter):
    try:
        existing = query_counterbyid(counter.id)
        if existing is None:
            return
        db.session.flush()
        db.session.commit()
    except OperationalError as e:
        logger.info("update_counterbyid errorMsg= {} ".format(e))


# ============================================================
# NJUST — 设置
# ============================================================
def get_setting(key: str, default: str = "") -> str:
    row = Setting.query.filter(Setting.k == key).first()
    return row.v if row else default


def set_setting(key: str, value: str):
    row = Setting.query.filter(Setting.k == key).first()
    if row:
        row.v = value
    else:
        db.session.add(Setting(k=key, v=value))
    db.session.commit()


# ============================================================
# NJUST — 课表
# ============================================================
def save_courses(courses: list, semester: str):
    Course.query.filter(Course.semester == semester).delete()
    for c in courses:
        db.session.add(Course(
            name=c.get("name", ""),
            teacher=c.get("teacher", ""),
            classroom=c.get("classroom", ""),
            day_of_week=c.get("day", 0),
            start_period=c.get("start", 0),
            end_period=c.get("end", 0),
            weeks=c.get("weeks", ""),
            week_type=c.get("week_type", 0),
            semester=semester,
            credits=str(c.get("credits", "")),
            course_type=c.get("course_type", ""),
            raw_data=json.dumps(c.get("raw", {}), ensure_ascii=False),
        ))
    db.session.commit()


def get_courses(semester: str) -> list:
    rows = Course.query.filter(Course.semester == semester) \
        .order_by(Course.day_of_week, Course.start_period).all()
    return [r.to_dict() for r in rows]


def count_courses(semester: str) -> int:
    return Course.query.filter(Course.semester == semester).count()


# ============================================================
# NJUST — 考试
# ============================================================
def save_exams(exams: list, semester: str):
    Exam.query.filter(Exam.semester == semester).delete()
    for e in exams:
        db.session.add(Exam(
            course_name=e.get("course_name", ""),
            exam_date=e.get("date", ""),
            exam_time=e.get("time", ""),
            location=e.get("location", ""),
            seat=e.get("seat", ""),
            exam_type=e.get("type", "期末考试"),
            semester=semester,
        ))
    db.session.commit()


def get_exams(semester: str) -> list:
    rows = Exam.query.filter(Exam.semester == semester) \
        .order_by(Exam.exam_date).all()
    return [r.to_dict() for r in rows]


def count_exams(semester: str) -> int:
    return Exam.query.filter(Exam.semester == semester).count()


# ============================================================
# NJUST — 评教
# ============================================================
def save_evaluations(evaluations: list, semester: str):
    Evaluation.query.filter(Evaluation.semester == semester).delete()
    for e in evaluations:
        db.session.add(Evaluation(
            semester=e.get("semester", ""),
            category=e.get("category", ""),
            batch=e.get("batch", ""),
            start_date=e.get("start_date", ""),
            end_date=e.get("end_date", ""),
            is_done=1 if e.get("is_done") else 0,
            items_json=json.dumps(e.get("items", []), ensure_ascii=False),
        ))
    db.session.commit()


def get_evaluations(semester: str) -> list:
    rows = Evaluation.query.filter(Evaluation.semester == semester) \
        .order_by(Evaluation.end_date).all()
    result = []
    for r in rows:
        result.append({
            "id": r.id,
            "semester": r.semester,
            "category": r.category,
            "batch": r.batch,
            "start_date": r.start_date,
            "end_date": r.end_date,
            "is_done": bool(r.is_done),
            "items": json.loads(r.items_json) if r.items_json else [],
        })
    return result


# ============================================================
# NJUST — 清除
# ============================================================
def clear_data(semester: str):
    Course.query.filter(Course.semester == semester).delete()
    Exam.query.filter(Exam.semester == semester).delete()
    db.session.commit()
