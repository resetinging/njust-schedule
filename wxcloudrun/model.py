"""
数据模型 — NJUST 课表/考试/评教/设置/成绩/四六级
======================================
（微信云托管模板的 Counters 示例已移除）
"""
from datetime import datetime
from wxcloudrun import db


# ============================================================
# NJUST — 课表
# ============================================================
class Course(db.Model):
    __tablename__ = 'courses'
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    student_id = db.Column(db.String(50), default='', index=True)  # 数据归属用户
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
    student_id = db.Column(db.String(50), default='', index=True)  # 数据归属用户
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
    student_id = db.Column(db.String(50), default='', index=True)  # 数据归属用户
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


# ============================================================
# NJUST — 成绩
# ============================================================
class Grade(db.Model):
    __tablename__ = 'grades'
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    student_id = db.Column(db.String(50), default='', index=True)  # 数据归属用户
    academic_year = db.Column(db.String(20), default='')
    semester = db.Column(db.String(10), default='')
    course_code = db.Column(db.String(50), default='')
    course_name = db.Column(db.String(200), nullable=False, default='')
    score = db.Column(db.String(20), default='')
    credit = db.Column(db.Float, default=0)
    grade_point = db.Column(db.Float, default=0)
    course_type = db.Column(db.String(50), default='')
    course_nature = db.Column(db.String(50), default='')
    exam_type = db.Column(db.String(50), default='正常考试')
    created_at = db.Column(db.TIMESTAMP, default=datetime.now)

    def to_dict(self):
        return {
            "id": self.id,
            "academic_year": self.academic_year,
            "semester": self.semester,
            "course_code": self.course_code,
            "course_name": self.course_name,
            "score": self.score,
            "credit": self.credit,
            "grade_point": self.grade_point,
            "course_type": self.course_type,
            "course_nature": self.course_nature,
            "exam_type": self.exam_type,
        }


# ============================================================
# NJUST — 四六级成绩
# ============================================================
# NJUST — 四六级成绩
# ============================================================
class CetScore(db.Model):
    __tablename__ = 'cet_scores'
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    student_id = db.Column(db.String(50), default='', index=True)  # 数据归属用户
    cet_type = db.Column(db.String(10), nullable=False, default='')
    total_score = db.Column(db.Float, default=0)
    exam_date = db.Column(db.String(20), default='')
    created_at = db.Column(db.TIMESTAMP, default=datetime.now)

    def to_dict(self):
        return {
            "type": self.cet_type,
            "score": self.total_score,
            "exam_date": self.exam_date,
        }


# ============================================================
# 留言板
# ============================================================
class BoardMessage(db.Model):
    __tablename__ = 'board_messages'
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    student_id = db.Column(db.String(50), default='', index=True)
    student_name = db.Column(db.String(50), default='')
    content = db.Column(db.String(200), nullable=False, default='')
    created_at = db.Column(db.TIMESTAMP, default=datetime.now)

    def to_dict(self):
        return {
            "id": self.id,
            "student_id": self.student_id,
            "student_name": self.student_name,
            "content": self.content,
            "created_at": self.created_at.strftime("%Y-%m-%d %H:%M") if self.created_at else "",
        }
