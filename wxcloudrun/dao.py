"""
数据访问层 — SQLAlchemy ORM
===========================
NJUST 课表/考试/评教/设置/成绩/四六级
多用户：业务数据（课表/考试/评教/成绩/四六级）全部按 student_id 隔离，
学期等用户级设置以 "{student_id}:{key}" 前缀存储。
"""
import json
from wxcloudrun import db
from wxcloudrun.model import Course, Exam, Evaluation, Setting, Grade, CetScore, BoardMessage, BoardComment, BoardLike


# ============================================================
# NJUST — 设置（全局 + 用户级）
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


def get_user_setting(student_id: str, key: str, default: str = "") -> str:
    """读取用户级设置（key 带用户前缀，如 '{sid}:semester'）"""
    return get_setting(f"{student_id}:{key}", default)


def set_user_setting(student_id: str, key: str, value: str):
    """写入用户级设置（key 带用户前缀，如 '{sid}:semester'）"""
    set_setting(f"{student_id}:{key}", value)


# ============================================================
# NJUST — 课表（按用户隔离）
# ============================================================
def save_courses(courses: list, semester: str, student_id: str = ""):
    Course.query.filter(
        Course.semester == semester,
        Course.student_id == student_id,
    ).delete()
    for c in courses:
        db.session.add(Course(
            student_id=student_id,
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


def get_courses(semester: str, student_id: str = "") -> list:
    rows = Course.query.filter(
        Course.semester == semester,
        Course.student_id == student_id,
    ).order_by(Course.day_of_week, Course.start_period).all()
    return [r.to_dict() for r in rows]


def count_courses(semester: str, student_id: str = "") -> int:
    return Course.query.filter(
        Course.semester == semester,
        Course.student_id == student_id,
    ).count()


# ============================================================
# NJUST — 考试（按用户隔离）
# ============================================================
def save_exams(exams: list, semester: str, student_id: str = ""):
    Exam.query.filter(
        Exam.semester == semester,
        Exam.student_id == student_id,
    ).delete()
    for e in exams:
        db.session.add(Exam(
            student_id=student_id,
            course_name=e.get("course_name", ""),
            exam_date=e.get("date", ""),
            exam_time=e.get("time", ""),
            location=e.get("location", ""),
            seat=e.get("seat", ""),
            exam_type=e.get("type", "期末考试"),
            semester=semester,
        ))
    db.session.commit()


def get_exams(semester: str, student_id: str = "") -> list:
    rows = Exam.query.filter(
        Exam.semester == semester,
        Exam.student_id == student_id,
    ).order_by(Exam.exam_date).all()
    return [r.to_dict() for r in rows]


def count_exams(semester: str, student_id: str = "") -> int:
    return Exam.query.filter(
        Exam.semester == semester,
        Exam.student_id == student_id,
    ).count()


# ============================================================
# NJUST — 评教（按用户隔离）
# ============================================================
def save_evaluations(evaluations: list, semester: str, student_id: str = ""):
    """全量保存评教批次（评教是待办事项, 与学期切换无关:
    刷新时按用户全删全插, 批次自身的 semester 字段才是真实归属学期）"""
    Evaluation.query.filter(Evaluation.student_id == student_id).delete()
    for e in evaluations:
        db.session.add(Evaluation(
            student_id=student_id,
            semester=e.get("semester", ""),
            category=e.get("category", ""),
            batch=e.get("batch", ""),
            start_date=e.get("start_date", ""),
            end_date=e.get("end_date", ""),
            is_done=1 if e.get("is_done") else 0,
            items_json=json.dumps(e.get("items", []), ensure_ascii=False),
        ))
    db.session.commit()


def get_evaluations(semester: str, student_id: str = "") -> list:
    """获取当前用户全部评教批次（semester 参数仅作兼容, 不过滤）

    按 (batch, category, end_date) 去重: 兼容旧版按学期键存储导致的
    同一批次多份残留; 优先保留 items 最全的一条。
    """
    rows = Evaluation.query.filter(
        Evaluation.student_id == student_id,
    ).order_by(Evaluation.end_date).all()
    result = []
    seen = {}
    for r in rows:
        key = (r.batch or "", r.category or "", r.end_date or "")
        items = json.loads(r.items_json) if r.items_json else []
        if key in seen:
            # 保留 items 更全的一条
            if len(items) > len(seen[key]["items"]):
                seen[key] = {"items": items, "row": r}
            continue
        seen[key] = {"items": items, "row": r}
    for entry in seen.values():
        r = entry["row"]
        result.append({
            "id": r.id,
            "semester": r.semester,
            "category": r.category,
            "batch": r.batch,
            "start_date": r.start_date,
            "end_date": r.end_date,
            "is_done": bool(r.is_done),
            "items": entry["items"],
        })
    return result


# ============================================================
# NJUST — 清除（按用户隔离）
# ============================================================
def clear_data(semester: str, student_id: str = ""):
    Course.query.filter(
        Course.semester == semester,
        Course.student_id == student_id,
    ).delete()
    Exam.query.filter(
        Exam.semester == semester,
        Exam.student_id == student_id,
    ).delete()
    db.session.commit()


# ============================================================
# NJUST — 成绩（按用户隔离）
# ============================================================
def save_grades(grades: list, academic_year: str, semester: str, student_id: str = ""):
    """保存某学期成绩（先删后插）"""
    Grade.query.filter(
        Grade.academic_year == academic_year,
        Grade.semester == semester,
        Grade.student_id == student_id,
    ).delete()
    for g in grades:
        db.session.add(Grade(
            student_id=student_id,
            academic_year=g.get("academic_year", academic_year),
            semester=g.get("semester", semester),
            course_code=g.get("course_code", ""),
            course_name=g.get("course_name", ""),
            score=str(g.get("score", "")),
            credit=float(g.get("credit", 0) or 0),
            grade_point=float(g.get("grade_point", 0) or 0),
            course_type=g.get("course_type", ""),
            course_nature=g.get("course_nature", ""),
            exam_type=g.get("exam_type", "正常考试"),
        ))
    db.session.commit()


def get_grades(academic_year: str = "", semester: str = "", student_id: str = "") -> list:
    """查询成绩，可选按学期过滤（均限定当前用户）"""
    q = Grade.query
    if student_id:
        q = q.filter(Grade.student_id == student_id)
    if academic_year:
        q = q.filter(Grade.academic_year == academic_year)
    if semester:
        q = q.filter(Grade.semester == semester)
    rows = q.order_by(
        Grade.academic_year.desc(), Grade.semester.desc(),
        Grade.course_type, Grade.course_name,
    ).all()
    return [r.to_dict() for r in rows]


def get_grade_semesters(student_id: str = "") -> list:
    """获取当前用户已有成绩的学期列表"""
    q = db.session.query(
        Grade.academic_year, Grade.semester
    )
    if student_id:
        q = q.filter(Grade.student_id == student_id)
    rows = q.distinct().order_by(
        Grade.academic_year.desc(), Grade.semester.desc()
    ).all()
    return [f"{r[0]}-{r[1]}" for r in rows]


# ============================================================
# NJUST — 四六级（按用户隔离）
# ============================================================
def save_cet_scores(scores: list, student_id: str = ""):
    """全量替换当前用户的四六级成绩"""
    CetScore.query.filter(CetScore.student_id == student_id).delete()
    for s in scores:
        db.session.add(CetScore(
            student_id=student_id,
            cet_type=s.get("type", ""),
            total_score=float(s.get("score", 0) or 0),
            exam_date=s.get("exam_date", ""),
        ))
    db.session.commit()


def get_cet_scores(student_id: str = "") -> list:
    """获取当前用户四六级成绩（每种取最高分）

    注：不能在 SQL 里对 (cet_type) 分组并同时 SELECT exam_date ——
    MySQL 5.7+ 的 ONLY_FULL_GROUP_BY 会直接报错（SQLite 不检查，本地测不出来）。
    数据量极小，改为全量读取后在 Python 中取最高分。
    """
    q = CetScore.query
    if student_id:
        q = q.filter(CetScore.student_id == student_id)
    rows = q.all()
    best = {}
    for r in rows:
        if r.cet_type not in best or r.total_score > best[r.cet_type][0]:
            best[r.cet_type] = (r.total_score, r.exam_date)
    result = []
    for t in sorted(best):
        s, d = best[t]
        result.append({
            "type": t,
            "score": float(s or 0),
            "exam_date": d or "",
        })
    return result


# ============================================================
# 留言板(贴吧式: 留言+评论+点赞+匿名)
# ============================================================
def save_board_message(student_id: str, student_name: str, content: str, is_anonymous: int = 0) -> dict:
    """发布留言, 返回消息 dict"""
    msg = BoardMessage(student_id=student_id, student_name=student_name,
                       content=content, is_anonymous=is_anonymous)
    db.session.add(msg)
    db.session.commit()
    return msg.to_dict()


def get_board_messages(limit: int = 50, before_id: int = None, sort: str = "time",
                       viewer_id: str = "") -> list:
    """取留言列表: sort=time(最新在前, id 分页) | likes(点赞数在前)"""
    q = BoardMessage.query
    if sort == "likes":
        if before_id:
            q = q.filter(BoardMessage.id != before_id)
        rows = q.order_by(BoardMessage.likes.desc(), BoardMessage.id.desc()).limit(limit).all()
    else:
        if before_id:
            q = q.filter(BoardMessage.id < before_id)
        rows = q.order_by(BoardMessage.id.desc()).limit(limit).all()
    # 批量取当前用户点赞状态与评论数
    msg_ids = [r.id for r in rows]
    liked_ids = set()
    comment_counts = {}
    if msg_ids:
        liked_ids = {r[0] for r in db.session.query(BoardLike.message_id)
                     .filter(BoardLike.message_id.in_(msg_ids), BoardLike.student_id == viewer_id).all()}
        for mid, cnt in db.session.query(BoardComment.message_id, db.func.count(BoardComment.id)) \
                .filter(BoardComment.message_id.in_(msg_ids)).group_by(BoardComment.message_id).all():
            comment_counts[mid] = cnt
    result = []
    for r in rows:
        d = r.to_dict(liked_by_me=r.id in liked_ids)
        d["comments"] = comment_counts.get(r.id, 0)
        result.append(d)
    return result


def toggle_board_like(message_id: int, student_id: str) -> dict:
    """点赞/取消点赞(同用户对同留言只能一次), 返回 {likes, liked}"""
    existing = BoardLike.query.filter(BoardLike.message_id == message_id,
                                      BoardLike.student_id == student_id).first()
    msg = BoardMessage.query.filter(BoardMessage.id == message_id).first()
    if not msg:
        return {"likes": 0, "liked": False, "exists": False}
    if existing:
        db.session.delete(existing)
        msg.likes = max(0, (msg.likes or 0) - 1)
        liked = False
    else:
        db.session.add(BoardLike(message_id=message_id, student_id=student_id))
        msg.likes = (msg.likes or 0) + 1
        liked = True
    db.session.commit()
    return {"likes": msg.likes or 0, "liked": liked, "exists": True}


def get_board_comments(message_id: int, limit: int = 100) -> list:
    """某留言的评论(时间正序, 贴吧楼层式)"""
    rows = BoardComment.query.filter(BoardComment.message_id == message_id) \
        .order_by(BoardComment.id.asc()).limit(limit).all()
    return [r.to_dict() for r in rows]


def save_board_comment(message_id: int, student_id: str, student_name: str,
                       content: str, is_anonymous: int = 0) -> dict:
    """发表评论"""
    cm = BoardComment(message_id=message_id, student_id=student_id,
                      student_name=student_name, content=content, is_anonymous=is_anonymous)
    db.session.add(cm)
    db.session.commit()
    return cm.to_dict()


def delete_board_message(msg_id: int) -> bool:
    """管理员删除留言(级联删除评论与点赞)"""
    row = BoardMessage.query.filter(BoardMessage.id == msg_id).first()
    if not row:
        return False
    BoardComment.query.filter(BoardComment.message_id == msg_id).delete()
    BoardLike.query.filter(BoardLike.message_id == msg_id).delete()
    db.session.delete(row)
    db.session.commit()
    return True
