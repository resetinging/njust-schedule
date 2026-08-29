"""
管理控制面板 — 私有后台
=========================
- 管理员鉴权: ADMIN_PASSWORD 环境变量, 登录签发带 TTL 的 token
- 实时请求监控: 内存环形缓冲 + SSE 推送(前端 EventSource, token 走 query)
- 用户/成绩统计: 数据库聚合(用户列表/成绩分布/等级分布/各学期均分)

说明: 在线会话池 _sessions 定义在 views.py, 本模块通过函数内
延迟导入访问, 避免循环导入。
"""
import json
import os
import secrets
import threading
import time
from collections import deque
from functools import wraps
from flask import request, jsonify, Response, render_template, stream_with_context
from sqlalchemy import func

from wxcloudrun import app, db
from wxcloudrun.model import Course, Exam, Evaluation, Grade, CetScore, Setting
import config

ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", config.ADMIN_PASSWORD)
ADMIN_TOKEN_TTL = 12 * 3600  # token 有效期 12h

_admin_token = None            # (token, expires_ts)
_admin_lock = threading.Lock()

# ---- 请求监控缓冲(进程内, 重启清空) ----
MAX_RECENT = 800
_recent = deque(maxlen=MAX_RECENT)
_req_seq = 0
_req_total = 0                 # 进程启动以来请求总数
_start_ts = time.time()


def record_request(method: str, path: str, status: int, ms: float, sid: str, ip: str):
    """记录一次 API 请求(由 views.after_request 调用; 线程安全)"""
    global _req_seq, _req_total
    if not path.startswith(("/api/", "/proxy/", "/admin")):
        return
    with _admin_lock:
        _req_seq += 1
        _req_total += 1
        _recent.append({
            "id": _req_seq,
            "ts": time.strftime("%H:%M:%S"),
            "method": method,
            "path": path,
            "status": status,
            "ms": round(ms),
            "sid": sid,
            "ip": ip,
        })


def _recent_since(since_id: int):
    with _admin_lock:
        return [r for r in _recent if r["id"] > since_id]


# ============================================================
# 鉴权
# ============================================================
def admin_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        tok = request.headers.get("X-Admin-Token") or request.args.get("token") or ""
        with _admin_lock:
            valid = bool(_admin_token and _admin_token[0] == tok and _admin_token[1] > time.time())
        if not valid:
            return jsonify({"success": False, "message": "未授权，请重新登录"}), 401
        return fn(*args, **kwargs)
    return wrapper


# ============================================================
# 页面与登录
# ============================================================
@app.route("/admin")
@app.route("/admin/")
def admin_page():
    return render_template("admin.html")


@app.route("/api/admin/login", methods=["POST"])
def admin_login():
    data = request.get_json(silent=True) or {}
    pwd = str(data.get("password", ""))
    if pwd != ADMIN_PASSWORD:
        app.logger.warning("[admin] 登录失败(密码错误) ip=%s",
                           (request.headers.get("X-Forwarded-For") or request.remote_addr or "-"))
        return jsonify({"success": False, "message": "密码错误"}), 401
    global _admin_token
    token = secrets.token_hex(16)
    with _admin_lock:
        _admin_token = (token, time.time() + ADMIN_TOKEN_TTL)
    app.logger.info("[admin] 管理员登录成功 ip=%s",
                    (request.headers.get("X-Forwarded-For") or request.remote_addr or "-"))
    return jsonify({"success": True, "token": token, "expires_in": ADMIN_TOKEN_TTL})


@app.route("/api/admin/logout", methods=["POST"])
@admin_required
def admin_logout():
    global _admin_token
    with _admin_lock:
        _admin_token = None
    return jsonify({"success": True})


# ============================================================
# 实时请求流(SSE)
# ============================================================
@app.route("/api/admin/stream")
@admin_required
def admin_stream():
    def gen():
        try:
            last_id = int(request.args.get("since", "0") or "0")
        except ValueError:
            last_id = 0
        # 先补发当前快照
        for r in _recent_since(last_id):
            yield f"data: {json.dumps(r, ensure_ascii=False)}\n\n"
            last_id = r["id"]
        # 持续轮询(1s), 无新数据发心跳保持连接
        while True:
            rows = _recent_since(last_id)
            if rows:
                for r in rows:
                    yield f"data: {json.dumps(r, ensure_ascii=False)}\n\n"
                    last_id = r["id"]
            else:
                yield ": ping\n\n"
            time.sleep(1)
    return Response(stream_with_context(gen()),
                    mimetype="text/event-stream",
                    headers={
                        "Cache-Control": "no-cache",
                        "X-Accel-Buffering": "no",
                        "Connection": "keep-alive",
                    })


# ============================================================
# 仪表盘数据
# ============================================================
@app.route("/api/admin/summary")
@admin_required
def admin_summary():
    from wxcloudrun import views as _v
    # 在线会话
    with _v._sessions_lock:
        sessions = list(_v._sessions.items())
    online = len(sessions)
    # 用户数(DB distinct)
    user_rows = db.session.query(Grade.student_id).filter(Grade.student_id != "").distinct().all()
    grade_users = {r[0] for r in user_rows}
    course_users = {r[0] for r in db.session.query(Course.student_id).filter(Course.student_id != "").distinct().all()}
    exam_users = {r[0] for r in db.session.query(Exam.student_id).filter(Exam.student_id != "").distinct().all()}
    all_users = sorted(grade_users | course_users | exam_users)
    counts = {
        "courses": db.session.query(func.count(Course.id)).scalar() or 0,
        "exams": db.session.query(func.count(Exam.id)).scalar() or 0,
        "evaluations": db.session.query(func.count(Evaluation.id)).scalar() or 0,
        "grades": db.session.query(func.count(Grade.id)).scalar() or 0,
        "cet": db.session.query(func.count(CetScore.id)).scalar() or 0,
    }
    with _admin_lock:
        req_total = _req_total
        uptime = int(time.time() - _start_ts)
    return jsonify({
        "success": True,
        "online_sessions": online,
        "total_users": len(all_users),
        "requests_total": req_total,
        "uptime_sec": uptime,
        "counts": counts,
    })


@app.route("/api/admin/users")
@admin_required
def admin_users():
    """用户列表: 学号 + 数据量 + 最高绩点 + 最近活跃"""
    from wxcloudrun import views as _v
    # 在线会话快照
    with _v._sessions_lock:
        sess = {sid: [c, ts] for sid, (c, ts) in _v._sessions.items()}
    rows = db.session.query(Grade.student_id).filter(Grade.student_id != "").distinct().all()
    sids = sorted({r[0] for r in rows} |
                  {r[0] for r in db.session.query(Course.student_id).filter(Course.student_id != "").distinct().all()} |
                  {r[0] for r in db.session.query(Exam.student_id).filter(Exam.student_id != "").distinct().all()})
    users = []
    for sid in sids:
        g_count = db.session.query(func.count(Grade.id)).filter(Grade.student_id == sid).scalar() or 0
        c_count = db.session.query(func.count(Course.id)).filter(Course.student_id == sid).scalar() or 0
        e_count = db.session.query(func.count(Exam.id)).filter(Exam.student_id == sid).scalar() or 0
        best_gp = db.session.query(func.max(Grade.grade_point)).filter(
            Grade.student_id == sid, Grade.grade_point > 0).scalar()
        sem = db.session.query(Setting.k, Setting.v).filter(Setting.k == f"{sid}:semester").first()
        sess_info = sess.get(sid)
        users.append({
            "student_id": sid,
            "courses": c_count,
            "exams": e_count,
            "grades": g_count,
            "best_gpa": round(float(best_gp), 2) if best_gp else None,
            "semester": sem[1] if sem else "",
            "online": bool(sess_info),
            "name": sess_info[0].student_name if sess_info else "",
        })
    users.sort(key=lambda u: (not u["online"], u["student_id"]))
    return jsonify({"success": True, "users": users})


@app.route("/api/admin/users/<sid>")
@admin_required
def admin_user_detail(sid: str):
    """单个用户详情: 课表(按学期)/考试/成绩(按学期)/评教"""
    courses = [c.to_dict() | {"semester": c.semester}
               for c in Course.query.filter(Course.student_id == sid).order_by(Course.semester).all()]
    exams = [e.to_dict() | {"semester": e.semester}
             for e in Exam.query.filter(Exam.student_id == sid).order_by(Exam.exam_date).all()]
    grades = [g.to_dict() for g in Grade.query.filter(Grade.student_id == sid).order_by(
        Grade.academic_year.desc(), Grade.semester.desc()).all()]
    evals = []
    for ev in Evaluation.query.filter(Evaluation.student_id == sid).all():
        try:
            items = json.loads(ev.items_json or "[]")
        except Exception:
            items = []
        evals.append({"semester": ev.semester, "batch": ev.batch, "category": ev.category,
                      "is_done": ev.is_done, "end_date": ev.end_date, "items": len(items)})
    return jsonify({"success": True, "student_id": sid, "courses": courses,
                    "exams": exams, "grades": grades, "evaluations": evals})


@app.route("/api/admin/stats/grades")
@admin_required
def admin_grade_stats():
    """成绩统计: 等级分布 + GPA 分布 + 各学期均分"""
    rows = db.session.query(Grade.score, Grade.grade_point, Grade.academic_year, Grade.semester).all()
    level_dist = {"优秀": 0, "良好": 0, "中等": 0, "及格": 0, "不及格": 0, "其他": 0}
    sem_avg = {}     # (学年, 学期) -> [均分累计, 条数]
    gpa_buckets = {} # 学生学号 -> 最高 GPA
    for score, gp, ay, sem in rows:
        s = str(score or "").strip()
        if s in ("", "缺考", "缓考", "免修"):
            level_dist["其他"] += 1
        elif s.isdigit():
            v = int(s)
            if v >= 90: level_dist["优秀"] += 1
            elif v >= 80: level_dist["良好"] += 1
            elif v >= 70: level_dist["中等"] += 1
            elif v >= 60: level_dist["及格"] += 1
            else: level_dist["不及格"] += 1
        elif "优" in s: level_dist["优秀"] += 1
        elif "良" in s: level_dist["良好"] += 1
        elif "中" in s: level_dist["中等"] += 1
        elif "及格" in s or "通过" in s: level_dist["及格"] += 1
        elif "不及格" in s or "不通过" in s: level_dist["不及格"] += 1
        else: level_dist["其他"] += 1
        if s.replace(".", "", 1).isdigit() and s != "":
            key = f"{ay}-{sem}"
            if key not in sem_avg: sem_avg[key] = [0.0, 0]
            sem_avg[key][0] += float(s)
            sem_avg[key][1] += 1
    # GPA 分布按学生最高绩点
    gp_rows = db.session.query(Grade.student_id, func.max(Grade.grade_point)).filter(
        Grade.grade_point > 0).group_by(Grade.student_id).all()
    gpa_hist = {"<2.0": 0, "2.0-2.5": 0, "2.5-3.0": 0, "3.0-3.5": 0, "3.5-4.0": 0}
    for _sid, gpv in gp_rows:
        v = float(gpv)
        if v < 2.0: gpa_hist["<2.0"] += 1
        elif v < 2.5: gpa_hist["2.0-2.5"] += 1
        elif v < 3.0: gpa_hist["2.5-3.0"] += 1
        elif v < 3.5: gpa_hist["3.0-3.5"] += 1
        else: gpa_hist["3.5-4.0"] += 1
    sem_list = [{"sem": k, "avg": round(v[0] / v[1], 2), "count": v[1]}
                for k, v in sorted(sem_avg.items(), reverse=True)]
    return jsonify({"success": True, "level_dist": level_dist, "gpa_hist": gpa_hist, "sem_avg": sem_list})


@app.route("/api/admin/requests")
@admin_required
def admin_requests():
    try:
        since_id = int(request.args.get("since", "0") or "0")
    except ValueError:
        since_id = 0
    return jsonify({"success": True, "requests": _recent_since(since_id)})


@app.route("/api/admin/sessions")
@admin_required
def admin_sessions():
    """在线会话列表(内存)"""
    from wxcloudrun import views as _v
    now = time.time()
    out = []
    with _v._sessions_lock:
        items = list(_v._sessions.items())
    for tok, (client, ts) in items:
        out.append({
            "student_id": client.student_id,
            "name": client.student_name,
            "token": f"{tok[:6]}…",
            "active_sec": int(now - ts),
            "semester": client.semester if hasattr(client, "semester") else "",
        })
    out.sort(key=lambda s: s["active_sec"])
    return jsonify({"success": True, "sessions": out})


@app.route("/api/admin/check")
def admin_check():
    """前端登录态检查(不带 token 也可调, 返回是否已登录)"""
    tok = request.headers.get("X-Admin-Token") or request.args.get("token") or ""
    with _admin_lock:
        valid = bool(_admin_token and _admin_token[0] == tok and _admin_token[1] > time.time())
    return jsonify({"success": True, "logged_in": valid})
