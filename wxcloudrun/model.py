"""
数据模型 — 微信云托管模板 SQLAlchemy ORM
======================================
包含：模板 Counter + NJUST 课表/考试/评教/设置
"""
from datetime import datetime
from wxcloudrun import db


# ============================================================
# 模板原有 — 计数器
# ============================================================
class Counters(db.Model):
    __tablename__ = 'Counters'
    id = db.Column(db.Integer, primary_key=True)
    count = db.Column(db.Integer, default=1)
    created_at = db.Column('createdAt', db.TIMESTAMP, nullable=False, default=datetime.now())
    updated_at = db.Column('updatedAt', db.TIMESTAMP, nullable=False, default=datetime.now())


# ============================================================
# NJUST — 课表
# ============================================================
class Course(db.Model):
    __tablename__ = 'courses'
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    name = db.Column(db.String(200), nullable=False, default='')
    teacher = db.Column(db.String(100), default='')
    classroom = db.Column(db.String(100), default='')
    day_of_week = db.Column(db.Integer, default=0)
    start_period = db.Column(db.Integer, default=0)
    end_period = db.Column(db.Integer, default=0)
    weeks = db.Column(db.String(50), default='')
    week_type = db.Column(db.Integer, default=0)
    semester = db.Column(db.String(50), default='')
    credits = db.Column(db.String(20), default='')
    course_type = db.Column(db.String(50), default='')
    raw_data = db.Column(db.Text, default='')
    created_at = db.Column(db.TIMESTAMP, default=datetime.now)

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "teacher": self.teacher,
            "classroom": self.classroom,
            "day": self.day_of_week,
            "start": self.start_period,
            "end": self.end_period,
            "weeks": self.weeks,
            "week_type": self.week_type,
            "credits": self.credits,
            "course_type": self.course_type,
        }


# ============================================================
# NJUST — 考试
# ============================================================
class Exam(db.Model):
    __tablename__ = 'exams'
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    course_name = db.Column(db.String(200), nullable=False, default='')
    exam_date = db.Column(db.String(50), default='')
    exam_time = db.Column(db.String(50), default='')
    location = db.Column(db.String(100), default='')
    seat = db.Column(db.String(20), default='')
    exam_type = db.Column(db.String(50), default='期末考试')
    semester = db.Column(db.String(50), default='')
    created_at = db.Column(db.TIMESTAMP, default=datetime.now)

    def to_dict(self):
        return {
            "id": self.id,
            "course_name": self.course_name,
            "date": self.exam_date,
            "time": self.exam_time,
            "location": self.location,
            "seat": self.seat,
            "type": self.exam_type,
        }


# ============================================================
# NJUST — 评教批次
# ============================================================
class Evaluation(db.Model):
    __tablename__ = 'evaluations'
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    semester = db.Column(db.String(50), default='')
    category = db.Column(db.String(100), default='')
    batch = db.Column(db.String(200), default='')
    start_date = db.Column(db.String(50), default='')
    end_date = db.Column(db.String(50), default='')
    is_done = db.Column(db.Integer, default=0)
    items_json = db.Column(db.Text, default='')
    created_at = db.Column(db.TIMESTAMP, default=datetime.now)


# ============================================================
# NJUST — 设置（键值对）
# ============================================================
class Setting(db.Model):
    __tablename__ = 'settings'
    k = db.Column(db.String(100), primary_key=True)
    v = db.Column(db.Text, default='')
