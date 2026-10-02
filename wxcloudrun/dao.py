"""
数据访问层 — SQLAlchemy ORM
===========================
课表助手/考试/评教/设置/成绩/四六级
多用户：业务数据（课表/考试/评教/成绩/四六级）全部按 student_id 隔离，
学期等用户级设置以 "{student_id}:{key}" 前缀存储。
"""
import json
import hashlib
import re
from datetime import datetime
from sqlalchemy import func, or_
from wxcloudrun import db
from wxcloudrun.model import (Course, Exam, Evaluation, Setting, UserSetting,
                              Grade, CetScore, Feedback, AuditCourse,
                              AuditFavorite)


# ============================================================
# 课表助手 — 设置（全局 + 用户级）
# ============================================================
def get_setting(key: str, default: str = "") -> str:
    row = Setting.query.filter(Setting.k == key).first()
    return row.v if row else default


def set_setting(key: str, value: str):
    try:
        row = Setting.query.filter(Setting.k == key).first()
        if row:
            row.v = value
        else:
            db.session.add(Setting(k=key, v=value))
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise


def get_user_setting(student_id: str, key: str, default: str = "") -> str:
    """读取用户级设置。"""
    if not student_id or not key:
        return default
    row = UserSetting.query.filter(
        UserSetting.student_id == str(student_id),
        UserSetting.k == str(key),
    ).first()
    return row.v if row else default


def set_user_setting(student_id: str, key: str, value: str):
    """写入用户级设置。"""
    if not student_id or not key:
        return
    try:
        row = UserSetting.query.filter(
            UserSetting.student_id == str(student_id),
            UserSetting.k == str(key),
        ).first()
        if row:
            row.v = value
            row.updated_at = datetime.now()
        else:
            db.session.add(UserSetting(
                student_id=str(student_id), k=str(key), v=value,
                updated_at=datetime.now()))
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise


def get_settings(keys: list) -> dict:
    """批量读取设置键，避免状态接口多次单键查询。"""
    wanted = [str(k) for k in keys if k]
    if not wanted:
        return {}
    rows = Setting.query.filter(Setting.k.in_(wanted)).all()
    return {row.k: row.v for row in rows}


def list_user_setting_keys(suffix: str, limit: int = 200) -> list:
    """按键名列出拥有该设置的用户学号。

    limit <= 0 表示不截断, 由调用方在完整集合上筛选或随机抽样。
    """
    suffix = str(suffix or "").strip()
    if not suffix:
        return []
    query = (UserSetting.query
             .with_entities(UserSetting.student_id)
             .filter(UserSetting.k == suffix)
             .order_by(UserSetting.student_id))
    try:
        cap = int(limit)
    except (TypeError, ValueError):
        cap = 200
    if cap > 0:
        query = query.limit(cap)
    return [row[0] for row in query.all() if row[0]]


# ============================================================
# 课表助手 — 课表（按用户隔离）
# ============================================================
def save_courses(courses: list, semester: str, student_id: str = ""):
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
    } for c in courses]
    try:
        Course.query.filter(
            Course.semester == semester,
            Course.student_id == student_id,
        ).delete()
        if rows:
            db.session.bulk_insert_mappings(Course, rows)
        db.session.commit()
    except Exception:
        db.session.rollback()
        Course.query.filter(
            Course.semester == semester,
            Course.student_id == student_id,
        ).delete()
        for row in rows:
            db.session.add(Course(**row))
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


def replace_audit_courses(courses: list, semester: str) -> int:
    """全量替换某学期的蹭课目录, 失败时回退逐条写入。"""
    now = datetime.now()
    rows = [{
        "semester": semester,
        "course_name": c.get("name", ""),
        "class_info": c.get("class_info", ""),
        "teacher": c.get("teacher", ""),
        "classroom": c.get("classroom", ""),
        "day_of_week": int(c.get("day", 0) or 0),
        "start_period": int(c.get("start", 0) or 0),
        "end_period": int(c.get("end", 0) or 0),
        "weeks": str(c.get("weeks", "")),
        "updated_at": now,
    } for c in courses]
    try:
        AuditCourse.query.filter(AuditCourse.semester == semester).delete()
        if rows:
            db.session.bulk_insert_mappings(AuditCourse, rows)
        db.session.commit()
    except Exception:
        db.session.rollback()
        AuditCourse.query.filter(AuditCourse.semester == semester).delete()
        for row in rows:
            db.session.add(AuditCourse(**row))
        db.session.commit()
    return len(rows)


def count_audit_courses(semester: str) -> int:
    return AuditCourse.query.filter(AuditCourse.semester == semester).count()


def _audit_favorite_key(course: dict) -> str:
    """生成收藏组合的稳定键: 课程、班级和全部时段共同去重。"""
    course = course or {}
    schedules = course.get("schedules") or []
    signatures = []
    for item in schedules:
        if not isinstance(item, dict):
            continue
        signatures.append(":".join([
            str(item.get("day", item.get("day_of_week", "")) or "").strip(),
            str(item.get("start", item.get("start_period", "")) or "").strip(),
            str(item.get("end", item.get("end_period", "")) or "").strip(),
            str(item.get("weeks", "") or "").strip(),
            str(item.get("teacher", "") or "").strip(),
            str(item.get("classroom", "") or "").strip(),
        ]))
    raw = "|".join([
        str(course.get("name", "") or "").strip(),
        str(course.get("class_info", "") or "").strip(),
        str(course.get("teacher", "") or "").strip(),
        str(course.get("classroom", "") or "").strip(),
        "||".join(sorted(signatures)),
    ])
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def list_audit_favorites(student_id: str, semester: str) -> list:
    rows = (AuditFavorite.query
            .filter(AuditFavorite.student_id == str(student_id),
                    AuditFavorite.semester == str(semester))
            .order_by(AuditFavorite.created_at.desc(),
                      AuditFavorite.id.desc())
            .all())
    return [row.to_dict() for row in rows]


def save_audit_favorite(student_id: str, semester: str,
                       course: dict) -> dict:
    course = course or {}
    name = str(course.get("name", "") or "").strip()
    if not name:
        raise ValueError("课程名称不能为空")

    schedules = course.get("schedules") or []
    if not isinstance(schedules, list) or len(schedules) > 50:
        raise ValueError("课程时段无效")
    clean_schedules = []
    for item in schedules:
        if not isinstance(item, dict):
            continue
        try:
            day = int(item.get("day", item.get("day_of_week", 0)) or 0)
            start = int(item.get("start", item.get("start_period", 0)) or 0)
            end = int(item.get("end", item.get("end_period", 0)) or 0)
        except (TypeError, ValueError):
            continue
        if not (1 <= day <= 7 and 1 <= start <= end <= 20):
            continue
        clean_schedules.append({
            "day": day,
            "start": start,
            "end": end,
            "weeks": str(item.get("weeks", "") or "")[:100],
            "teacher": str(item.get("teacher", "") or "")[:200],
            "classroom": str(item.get("classroom", "") or "")[:200],
        })
    if not clean_schedules:
        raise ValueError("课程时段无效")

    favorite_key = _audit_favorite_key({
        "name": name[:200],
        "class_info": str(course.get("class_info", "") or ""),
        "teacher": str(course.get("teacher", "") or "")[:200],
        "classroom": str(course.get("classroom", "") or "")[:200],
        "schedules": clean_schedules,
    })
    row = AuditFavorite.query.filter(
        AuditFavorite.student_id == str(student_id),
        AuditFavorite.semester == str(semester),
        AuditFavorite.favorite_key == favorite_key,
    ).first()
    if row is None:
        row = AuditFavorite(
            student_id=str(student_id),
            semester=str(semester),
            favorite_key=favorite_key,
        )
        db.session.add(row)
    row.course_name = name[:200]
    row.class_info = str(course.get("class_info", "") or "")
    row.teacher = str(course.get("teacher", "") or "")[:200]
    row.classroom = str(course.get("classroom", "") or "")[:200]
    row.schedules_json = json.dumps(clean_schedules, ensure_ascii=False)
    row.updated_at = datetime.now()
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise
    return row.to_dict()


def delete_audit_favorite(student_id: str, favorite_id: int) -> bool:
    row = AuditFavorite.query.filter(
        AuditFavorite.id == int(favorite_id),
        AuditFavorite.student_id == str(student_id),
    ).first()
    if row is None:
        return False
    db.session.delete(row)
    db.session.commit()
    return True


def query_audit_options(semester: str, field: str, keyword: str = "",
                        limit: int = 20) -> list:
    """查询蹭课目录中的去重候选值。"""
    keyword = str(keyword or "").strip()
    limit = min(50, max(1, int(limit)))
    if field in ("teacher", "classroom"):
        column = (AuditCourse.teacher if field == "teacher"
                  else AuditCourse.classroom)
        rows = (AuditCourse.query
                .with_entities(column)
                .filter(AuditCourse.semester == semester,
                        column != "")
                .all())
        values = set()
        for row in rows:
            for value in _split_audit_values(row[0]):
                if value and keyword.lower() in value.lower():
                    values.add(value)
        return sorted(values)[:limit]

    columns = {"name": AuditCourse.course_name}
    column = columns.get(str(field or "").strip())
    if column is None:
        return []
    q = (AuditCourse.query
         .with_entities(column)
         .filter(AuditCourse.semester == semester, column != ""))
    if keyword:
        q = q.filter(column.like(f"%{keyword}%"))
    rows = (q.distinct()
            .order_by(column)
            .limit(limit)
            .all())
    return [row[0] for row in rows if row[0]]


def _split_audit_values(value) -> list:
    """按中英文逗号拆分教务同一格中的多个值。"""
    return [
        part.strip() for part in re.split(r'[,，]', str(value or ""))
        if part.strip()
    ]


def _audit_exact_token_filter(column, value):
    """匹配逗号分隔字段中的单个值, 忽略多余空格和中英文逗号差异。"""
    normalized_value = str(value or "").strip().replace("，", ",").replace(
        " ", "")
    if not normalized_value:
        return None
    normalized_column = func.replace(
        func.replace(column, "，", ","), " ", "")
    return or_(
        normalized_column == normalized_value,
        normalized_column.like(f"{normalized_value},%"),
        normalized_column.like(f"%,{normalized_value}"),
        normalized_column.like(f"%,{normalized_value},%"),
    )


def _audit_text_filter(column, value, exact: bool = False):
    value = str(value or "").strip()
    if not value:
        return None
    if exact:
        return _audit_exact_token_filter(column, value)
    return column.like(f"%{value}%")


def _audit_dimension_filter(column, values, exact: bool = False):
    """同一维度多值取 OR; 空维度不生成条件。"""
    if values is None:
        values = []
    if not isinstance(values, (list, tuple, set)):
        values = [values]
    filters = []
    for value in values:
        value = str(value or "").strip()
        if not value:
            continue
        if exact:
            filters.append(_audit_text_filter(column, value, True))
        else:
            filters.append(column.like(f"%{value}%"))
    return or_(*filters) if filters else None


def query_audit_options_all(semester: str) -> dict:
    """生成小程序的完整本地筛选列表。"""
    names = [
        row[0] for row in (
            AuditCourse.query
            .with_entities(AuditCourse.course_name)
            .filter(AuditCourse.semester == semester,
                    AuditCourse.course_name != "")
            .distinct()
            .order_by(AuditCourse.course_name)
            .all()
        ) if row[0]
    ]
    classroom_rows = (
        AuditCourse.query
        .with_entities(AuditCourse.classroom)
        .filter(AuditCourse.semester == semester,
                AuditCourse.classroom != "")
        .all()
    )
    classrooms = set()
    for row in classroom_rows:
        classrooms.update(_split_audit_values(row[0]))
    classrooms = sorted(classrooms)
    teacher_rows = (
        AuditCourse.query
        .with_entities(AuditCourse.teacher)
        .filter(AuditCourse.semester == semester,
                AuditCourse.teacher != "")
        .all()
    )
    teachers = set()
    for row in teacher_rows:
        teachers.update(_split_audit_values(row[0]))
    rows = (AuditCourse.query
            .filter(AuditCourse.semester == semester)
            .order_by(AuditCourse.course_name, AuditCourse.class_info)
            .all())
    name_index = {value: index for index, value in enumerate(names)}
    teacher_values = sorted(teachers)
    teacher_index = {
        value: index for index, value in enumerate(teacher_values)
    }
    classroom_index = {
        value: index for index, value in enumerate(classrooms)
    }
    relations = []
    seen_relations = set()
    for row in rows:
        relation_teachers = []
        for value in _split_audit_values(row.teacher):
            if value in teacher_index and value not in relation_teachers:
                relation_teachers.append(teacher_index[value])
        relation_classrooms = []
        for value in _split_audit_values(row.classroom):
            if value in classroom_index and value not in relation_classrooms:
                relation_classrooms.append(classroom_index[value])
        relation = (
            name_index.get(row.course_name or "", -1),
            tuple(sorted(relation_teachers)),
            tuple(sorted(relation_classrooms)),
            int(row.day_of_week or 0),
            int(row.start_period or 0),
            int(row.end_period or 0),
        )
        if relation[0] < 0 or relation in seen_relations:
            continue
        seen_relations.add(relation)
        relations.append([
            relation[0], list(relation[1]), list(relation[2]),
            relation[3], relation[4], relation[5],
        ])
    return {
        "names": names,
        "teachers": teacher_values,
        "classrooms": classrooms,
        "relations": relations,
    }


def query_audit_courses(semester: str, name: str = "", teacher: str = "",
                        classroom: str = "", keyword: str = "", weekday: int = 0,
                        jc1: int = 0, jc2: int = 0,
                        limit: int = 20, offset: int = 0,
                        name_exact: bool = False,
                        teacher_exact: bool = False,
                        classroom_exact: bool = False,
                        names: list = None,
                        teachers: list = None,
                        classrooms: list = None):
    """查询蹭课目录, 返回 (rows, total)。"""
    q = AuditCourse.query.filter(AuditCourse.semester == semester)
    if names is None and name:
        names = [name]
    if teachers is None and teacher:
        teachers = [teacher]
    if classrooms is None and classroom:
        classrooms = [classroom]

    name_filter = _audit_dimension_filter(
        AuditCourse.course_name, names, name_exact)
    teacher_filter = _audit_dimension_filter(
        AuditCourse.teacher, teachers, teacher_exact)
    classroom_filter = _audit_dimension_filter(
        AuditCourse.classroom, classrooms, classroom_exact)
    if name_filter is not None:
        q = q.filter(name_filter)
    if teacher_filter is not None:
        q = q.filter(teacher_filter)
    if classroom_filter is not None:
        q = q.filter(classroom_filter)
    kw = str(keyword or "").strip()
    if kw:
        like = f"%{kw}%"
        q = q.filter(or_(AuditCourse.course_name.like(like),
                         AuditCourse.teacher.like(like),
                         AuditCourse.classroom.like(like)))
    if weekday:
        q = q.filter(AuditCourse.day_of_week == int(weekday))
    if jc1:
        q = q.filter(AuditCourse.end_period >= int(jc1))
    if jc2:
        q = q.filter(AuditCourse.start_period <= int(jc2))
    total = q.count()
    rows = (q.order_by(AuditCourse.day_of_week, AuditCourse.start_period,
                       AuditCourse.course_name, AuditCourse.teacher)
            .offset(max(0, int(offset))).limit(max(1, int(limit))).all())
    return [row.to_dict() for row in rows], total


def query_audit_course_groups(semester: str, name: str = "",
                              teacher: str = "", classroom: str = "",
                              keyword: str = "", weekday: int = 0,
                              jc1: int = 0, jc2: int = 0,
                              limit: int = 20, offset: int = 0,
                              name_exact: bool = False,
                              teacher_exact: bool = False,
                              classroom_exact: bool = False,
                              names: list = None,
                              teachers: list = None,
                              classrooms: list = None):
    """按拆分记录筛选，再按课程名+班级信息聚合分页。"""
    if names is None and name:
        names = [name]
    if teachers is None and teacher:
        teachers = [teacher]
    if classrooms is None and classroom:
        classrooms = [classroom]

    def apply_filters(query):
        name_filter = _audit_dimension_filter(
            AuditCourse.course_name, names, name_exact)
        teacher_filter = _audit_dimension_filter(
            AuditCourse.teacher, teachers, teacher_exact)
        classroom_filter = _audit_dimension_filter(
            AuditCourse.classroom, classrooms, classroom_exact)
        if name_filter is not None:
            query = query.filter(name_filter)
        if teacher_filter is not None:
            query = query.filter(teacher_filter)
        if classroom_filter is not None:
            query = query.filter(classroom_filter)
        kw = str(keyword or "").strip()
        if kw:
            like = f"%{kw}%"
            query = query.filter(or_(
                AuditCourse.course_name.like(like),
                AuditCourse.class_info.like(like),
                AuditCourse.teacher.like(like),
                AuditCourse.classroom.like(like),
            ))
        if weekday:
            query = query.filter(AuditCourse.day_of_week == int(weekday))
        if jc1:
            query = query.filter(AuditCourse.end_period >= int(jc1))
        if jc2:
            query = query.filter(AuditCourse.start_period <= int(jc2))
        return query

    base = apply_filters(
        AuditCourse.query.filter(AuditCourse.semester == semester))
    key_query = (base.with_entities(
        AuditCourse.course_name, AuditCourse.class_info)
        .distinct()
        .order_by(AuditCourse.course_name, AuditCourse.class_info))
    total = key_query.count()
    keys = (key_query
            .offset(max(0, int(offset)))
            .limit(max(1, int(limit)))
            .all())
    if not keys:
        return [], total

    key_filters = [
        ((AuditCourse.course_name == course_name)
         & (AuditCourse.class_info == class_info))
        for course_name, class_info in keys
    ]
    rows = (AuditCourse.query
            .filter(AuditCourse.semester == semester, or_(*key_filters))
            .order_by(AuditCourse.course_name, AuditCourse.class_info,
                      AuditCourse.day_of_week, AuditCourse.start_period)
            .all())

    groups = {}
    for row in rows:
        key = (row.course_name or "", row.class_info or "")
        group = groups.setdefault(key, {
            "name": key[0],
            "class_info": key[1],
            "teacher": "",
            "classroom": "",
            "schedules": [],
        })
        group["schedules"].append({
            "day": row.day_of_week,
            "start": row.start_period,
            "end": row.end_period,
            "weeks": row.weeks,
            "teacher": row.teacher,
            "classroom": row.classroom,
        })

    result = []
    for key in keys:
        group = groups.get((key[0] or "", key[1] or ""))
        if not group:
            continue
        schedules = []
        seen = set()
        for item in group["schedules"]:
            sig = (item["day"], item["start"], item["end"], item["weeks"],
                   item["teacher"], item["classroom"])
            if sig in seen:
                continue
            seen.add(sig)
            schedules.append(item)
        group["schedules"] = schedules
        teachers = []
        classrooms = []
        for item in schedules:
            for value in _split_audit_values(item.get("teacher")):
                if value and value not in teachers:
                    teachers.append(value)
            for value in _split_audit_values(item.get("classroom")):
                if value and value not in classrooms:
                    classrooms.append(value)
        group["teacher"] = ",".join(teachers)
        group["classroom"] = ",".join(classrooms)
        group["schedule_count"] = len(schedules)
        result.append(group)
    return result, total


# ============================================================
# 课表助手 — 考试（按用户隔离）
# ============================================================
def save_exams(exams: list, semester: str, student_id: str = ""):
    try:
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
    except Exception:
        db.session.rollback()
        raise


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
# 课表助手 — 评教（按用户隔离）
# ============================================================
def save_evaluations(evaluations: list, semester: str, student_id: str = ""):
    """全量保存评教批次（评教是待办事项, 与学期切换无关:
    刷新时按用户全删全插, 批次自身的 semester 字段才是真实归属学期）"""
    try:
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
    except Exception:
        db.session.rollback()
        raise


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
# 课表助手 — 清除（按用户隔离）
# ============================================================
def clear_data(semester: str, student_id: str = ""):
    try:
        Course.query.filter(
            Course.semester == semester,
            Course.student_id == student_id,
        ).delete()
        Exam.query.filter(
            Exam.semester == semester,
            Exam.student_id == student_id,
        ).delete()
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise


# ============================================================
# 课表助手 — 成绩（按用户隔离）
# ============================================================
def save_grades(grades: list, academic_year: str, semester: str, student_id: str = ""):
    """保存某学期成绩（先删后插）"""
    rows = [{
        "student_id": student_id,
        "academic_year": g.get("academic_year", academic_year),
        "semester": g.get("semester", semester),
        "course_code": g.get("course_code", ""),
        "course_name": g.get("course_name", ""),
        "score": str(g.get("score", "")),
        "credit": float(g.get("credit", 0) or 0),
        "grade_point": float(g.get("grade_point", 0) or 0),
        "course_type": g.get("course_type", ""),
        "course_nature": g.get("course_nature", ""),
        "exam_type": g.get("exam_type", "正常考试"),
    } for g in grades]
    try:
        Grade.query.filter(
            Grade.academic_year == academic_year,
            Grade.semester == semester,
            Grade.student_id == student_id,
        ).delete()
        if rows:
            db.session.bulk_insert_mappings(Grade, rows)
        db.session.commit()
    except Exception:
        db.session.rollback()
        Grade.query.filter(
            Grade.academic_year == academic_year,
            Grade.semester == semester,
            Grade.student_id == student_id,
        ).delete()
        for row in rows:
            db.session.add(Grade(**row))
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
# 课表助手 — 四六级（按用户隔离）
# ============================================================
def save_cet_scores(scores: list, student_id: str = ""):
    """全量替换当前用户的四六级成绩"""
    try:
        CetScore.query.filter(CetScore.student_id == student_id).delete()
        for s in scores:
            db.session.add(CetScore(
                student_id=student_id,
                cet_type=s.get("type", ""),
                total_score=float(s.get("score", 0) or 0),
                exam_date=s.get("exam_date", ""),
            ))
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise


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
# 问题反馈
# ============================================================
def save_feedback(student_id: str, student_name: str, fb_type: str,
                  content: str) -> dict:
    """提交反馈(不再收集联系方式, contact 列保留仅存历史数据), 返回 dict"""
    row = Feedback(student_id=student_id, student_name=student_name,
                   fb_type=fb_type, content=content, status="pending")
    try:
        db.session.add(row)
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise
    return row.to_dict()


def list_feedback(limit: int = 500, status: str = "") -> list:
    """反馈列表(倒序; status 可选过滤 pending/done)"""
    q = Feedback.query
    if status:
        q = q.filter(Feedback.status == status)
    rows = q.order_by(Feedback.id.desc()).limit(limit).all()
    return [r.to_dict() for r in rows]


def set_feedback_status(feedback_id: int, status: str) -> bool:
    """标记处理状态: pending 待处理 | done 已处理"""
    row = Feedback.query.filter(Feedback.id == feedback_id).first()
    if not row:
        return False
    try:
        row.status = status
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise
    return True


def delete_feedback(feedback_id: int) -> bool:
    """管理员删除反馈"""
    row = Feedback.query.filter(Feedback.id == feedback_id).first()
    if not row:
        return False
    try:
        db.session.delete(row)
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise
    return True


def set_feedback_reply(feedback_id: int, reply: str) -> dict:
    """管理员回复反馈: 写入回复内容 + 回复时间, 并标记已处理。

    回复非空时把 reply_read 置 False → 用户端出现"新回复"小红点;
    传入空回复 = 撤销回复(清空内容, 不动处理状态)。
    """
    row = Feedback.query.filter(Feedback.id == feedback_id).first()
    if not row:
        return {}
    text = (reply or "").strip()[:500]
    row.reply = text
    if text:
        row.replied_at = datetime.now()
        row.status = "done"
        row.reply_read = False
    else:
        row.replied_at = None
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise
    return row.to_dict()


def list_feedback_by_user(student_id: str, limit: int = 50) -> list:
    """某用户自己的反馈(倒序, 含管理员回复)"""
    if not student_id:
        return []
    rows = (Feedback.query
            .filter(Feedback.student_id == student_id)
            .order_by(Feedback.id.desc())
            .limit(limit).all())
    return [r.to_dict() for r in rows]


def count_unread_replies(student_id: str) -> int:
    """未读回复数(用户端小红点)"""
    if not student_id:
        return 0
    return (Feedback.query
            .filter(Feedback.student_id == student_id,
                    Feedback.reply.isnot(None),
                    Feedback.reply != "",
                    Feedback.reply_read.is_(False))
            .count())


def mark_replies_read(student_id: str) -> int:
    """把该用户所有未读回复标记为已读, 返回更新条数"""
    if not student_id:
        return 0
    rows = (Feedback.query
            .filter(Feedback.student_id == student_id,
                    Feedback.reply.isnot(None),
                    Feedback.reply != "",
                    Feedback.reply_read.is_(False))
            .all())
    for r in rows:
        r.reply_read = True
    if rows:
        try:
            db.session.commit()
        except Exception:
            db.session.rollback()
            raise
    return len(rows)
