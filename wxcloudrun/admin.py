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
from flask import request, jsonify, Response, render_template, stream_with_context, g
from sqlalchemy import func

from wxcloudrun import app, db
from wxcloudrun.model import Course, Exam, Evaluation, Grade, CetScore, Setting, BoardComment
from wxcloudrun import dao
import config


def _rid():
    """当前请求 ID(无上下文时返回 '-')"""
    try:
        return g.get("rid", "-")
    except Exception:
        return "-"

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
        # 持续轮询(15s), 无新数据发心跳保持连接
        # (心跳间隔不宜过短: 减少无谓 IO; 网关空闲断开一般 >60s)
        while True:
            rows = _recent_since(last_id)
            if rows:
                for r in rows:
                    yield f"data: {json.dumps(r, ensure_ascii=False)}\n\n"
                    last_id = r["id"]
            else:
                yield ": ping\n\n"
            time.sleep(15)
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
    # 性能优化: 聚合查询一次取全量(此前每用户 4-5 次查询, 用户多时 N+1 爆炸)
    g_counts = dict(db.session.query(Grade.student_id, func.count(Grade.id))
                    .filter(Grade.student_id != "").group_by(Grade.student_id).all())
    c_counts = dict(db.session.query(Course.student_id, func.count(Course.id))
                    .filter(Course.student_id != "").group_by(Course.student_id).all())
    e_counts = dict(db.session.query(Exam.student_id, func.count(Exam.id))
                    .filter(Exam.student_id != "").group_by(Exam.student_id).all())
    best_gps = dict(db.session.query(Grade.student_id, func.max(Grade.grade_point))
                    .filter(Grade.student_id != "", Grade.grade_point > 0)
                    .group_by(Grade.student_id).all())
    sem_rows = db.session.query(Setting.k, Setting.v).filter(Setting.k.like("%:semester")).all()
    sem_map = {k.rsplit(":", 1)[0]: v for k, v in sem_rows}
    name_rows = db.session.query(Setting.k, Setting.v).filter(Setting.k.like("%:name")).all()
    name_map = {k.rsplit(":", 1)[0]: v for k, v in name_rows if v}
    users = []
    for sid in sids:
        sess_info = sess.get(sid)
        # 姓名: 在线取会话, 离线回退到持久化的 {sid}:name 设置
        name = sess_info[0].student_name if sess_info else name_map.get(sid, "")
        # 在线但历史未持久化姓名的用户: 立即补写 Setting(兜底)
        if sess_info and sess_info[0].student_name and not name_map.get(sid):
            try:
                dao.set_user_setting(sid, "name", sess_info[0].student_name)
            except Exception:
                pass
        best_gp = best_gps.get(sid)
        users.append({
            "student_id": sid,
            "courses": c_counts.get(sid, 0),
            "exams": e_counts.get(sid, 0),
            "grades": g_counts.get(sid, 0),
            "best_gpa": round(float(best_gp), 2) if best_gp else None,
            "semester": sem_map.get(sid, ""),
            "online": bool(sess_info),
            "name": name,
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


def _score_to_num(s: str):
    """成绩 → 百分制数值(等级制折算中值, 与小程序前端一致);
    无法识别(缺考/缓考/免修等)返回 None, 不参与均分统计"""
    t = (s or "").strip()
    if not t:
        return None
    if t.replace(".", "", 1).isdigit():
        return float(t)
    if "不及格" in t or "不通过" in t or "未通过" in t:
        return 55.0
    if "优" in t:
        return 95.0
    if "良" in t:
        return 85.0
    if "中" in t:
        return 75.0
    if "及格" in t or "通过" in t:
        return 65.0
    return None


# ---- 官方绩点机制(与桌面端/小程序 utils/gpa.js 一致) ----
LEVEL_MAP = {
    '优': 4.0, '优秀': 4.0, '优+': 4.0, '优秀+': 4.0,
    '优-': 3.7, '优秀-': 3.7,
    '良+': 3.3, '良好+': 3.3, '良': 3.0, '良好': 3.0, '良-': 2.7, '良好-': 2.7,
    '中+': 2.3, '中等+': 2.3, '中': 2.0, '中等': 2.0, '中-': 1.5, '中等-': 1.5,
    '及格': 1.0, '通过': 1.0, '不及格': 0, '不通过': 0,
}
NON_GRADE_STATUS = ('缓考', '缺考', '免修', '作弊', '违纪', '取消', '旷考', '休学')


def score_to_gp(score):
    """等级制/百分制成绩 → 绩点(NJUST 4.0 量表); 非正式成绩返回 -1(不参与)"""
    s = (score or "").strip()
    if s in LEVEL_MAP:
        return LEVEL_MAP[s]
    if s in NON_GRADE_STATUS:
        return -1.0
    try:
        v = float(s)
    except ValueError:
        return -1.0
    if v >= 90: return 4.0
    if v >= 85: return 3.7
    if v >= 82: return 3.3
    if v >= 78: return 3.0
    if v >= 75: return 2.7
    if v >= 72: return 2.3
    if v >= 68: return 2.0
    if v >= 64: return 1.5
    if v >= 60: return 1.0
    return 0.0


def calc_gpa_by_semester(rows):
    """按学期计算加权平均绩点 Σ(学分×绩点)/Σ学分(与桌面端 calcGpa 一致)
    rows: [(score, grade_point, credit, academic_year, semester)]"""
    sem = {}   # (学年,学期) -> [加权绩点和, 学分和]
    for score, gp, credit, ay, sem_key in rows:
        try:
            c = float(credit or 0)
        except (TypeError, ValueError):
            c = 0
        if c <= 0:
            continue
        # 绩点: 数据库 grade_point 为 0/空时按成绩折算(不及格折算也为 0, 殊途同归)
        try:
            gpv = float(gp or 0)
        except (TypeError, ValueError):
            gpv = 0
        if gpv == 0:
            gpv = score_to_gp(score)
        if gpv < 0:
            continue  # 缓考/缺考等不参与
        key = f"{ay}-{sem_key}"
        if key not in sem:
            sem[key] = [0.0, 0.0]
        sem[key][0] += c * gpv
        sem[key][1] += c
    out = []
    for k, (weighted, credits) in sem.items():
        if credits > 0:
            out.append({"sem": k, "gpa": round(weighted / credits, 2), "credits": round(credits, 1)})
    out.sort(key=lambda x: x["sem"], reverse=True)
    return out


@app.route("/api/admin/stats/grades")
@admin_required
def admin_grade_stats():
    """成绩统计: 等级分布 + GPA 分布 + 各学期平均绩点(官方绩点制)"""
    rows = db.session.query(
        Grade.student_id, Grade.score, Grade.grade_point, Grade.credit,
        Grade.academic_year, Grade.semester).all()
    level_dist = {"优秀": 0, "良好": 0, "中等": 0, "及格": 0, "不及格": 0, "其他": 0}
    for sid, score, gp, credit, ay, sem in rows:
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
        elif "不及格" in s or "不通过" in s:   # 必须先于"及格"匹配
            level_dist["不及格"] += 1
        elif "优" in s: level_dist["优秀"] += 1
        elif "良" in s: level_dist["良好"] += 1
        elif "中" in s: level_dist["中等"] += 1
        elif "及格" in s or "通过" in s: level_dist["及格"] += 1
        else: level_dist["其他"] += 1
    # 各学期平均绩点(官方口径, 等级制直接走绩点表)
    sem_gpa = calc_gpa_by_semester([(r[1], r[2], r[3], r[4], r[5]) for r in rows])
    # GPA 分布按学生最高绩点(grade_point 为空/0 时按成绩折算)
    best = {}
    for sid, score, gp, credit, ay, sem in rows:
        try:
            gpv = float(gp or 0)
        except (TypeError, ValueError):
            gpv = 0
        if gpv == 0:
            gpv = score_to_gp(score)
        if gpv <= 0:
            continue
        if sid not in best or gpv > best[sid]:
            best[sid] = gpv
    gpa_hist = {"<2.0": 0, "2.0-2.5": 0, "2.5-3.0": 0, "3.0-3.5": 0, "3.5-4.0": 0}
    for v in best.values():
        if v < 2.0: gpa_hist["<2.0"] += 1
        elif v < 2.5: gpa_hist["2.0-2.5"] += 1
        elif v < 3.0: gpa_hist["2.5-3.0"] += 1
        elif v < 3.5: gpa_hist["3.0-3.5"] += 1
        else: gpa_hist["3.5-4.0"] += 1
    return jsonify({"success": True, "level_dist": level_dist, "gpa_hist": gpa_hist, "sem_gpa": sem_gpa})


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


@app.route("/api/admin/stats/requests")
@admin_required
def admin_request_stats():
    """请求趋势统计: 最近分钟分布 + 状态分布 + 高频路径 Top10"""
    from collections import Counter
    with _admin_lock:
        recent = list(_recent)
    minutes = Counter()
    statuses = Counter()
    paths = Counter()
    for r in recent:
        minutes[r["ts"][:5]] += 1          # HH:MM
        statuses[str(r["status"])] += 1
        paths[r["path"].split("?")[0]] += 1
    return jsonify({
        "success": True,
        "minutes": dict(sorted(minutes.items())[-60:]),
        "statuses": dict(statuses),
        "top_paths": dict(paths.most_common(10)),
    })


# ============================================================
# 公告管理(小程序公告栏)
# ============================================================
@app.route("/api/admin/announcement", methods=["GET"])
@admin_required
def admin_get_announcement():
    """读取当前公告设置"""
    text = dao.get_setting("announcement_text", "")
    enabled = dao.get_setting("announcement_enabled", "1") == "1"
    updated = dao.get_setting("announcement_updated", "")
    return jsonify({"success": True, "text": text, "enabled": enabled, "updated": updated})


@app.route("/api/admin/announcement", methods=["POST"])
@admin_required
def admin_set_announcement():
    """设置公告(内容 + 显示开关), 小程序端即时生效"""
    data = request.get_json(silent=True) or {}
    text = str(data.get("text", "")).strip()
    enabled = bool(data.get("enabled", True))
    dao.set_setting("announcement_text", text)
    dao.set_setting("announcement_enabled", "1" if enabled else "0")
    dao.set_setting("announcement_updated", time.strftime("%Y-%m-%d %H:%M:%S"))
    app.logger.info("[admin] rid=%s 更新公告 len=%d enabled=%s ip=%s",
                    _rid(), len(text), enabled,
                    (request.headers.get("X-Forwarded-For") or request.remote_addr or "-"))
    return jsonify({"success": True})


# ============================================================
# 缺失姓名补齐: 用教务处默认密码(学号+@Njust)自动尝试登录
# ============================================================
@app.route("/api/admin/fetch-names", methods=["POST"])
@admin_required
def admin_fetch_names():
    """对无姓名记录的用户, 用默认密码(学号+@Njust)尝试登录教务获取姓名。

    仅对缺失姓名的用户逐个尝试; 串行 + 间隔 2 秒 + 上限 20 人,
    避免批量登录触发教务风控。改过密码的用户会失败跳过。
    """
    from wxcloudrun.jwc_client import JWCClient
    # 1) 全部学生 ID(成绩/课表/考试表并集)
    sids = sorted({r[0] for r in db.session.query(Grade.student_id).filter(Grade.student_id != "").distinct().all()} |
                  {r[0] for r in db.session.query(Course.student_id).filter(Course.student_id != "").distinct().all()} |
                  {r[0] for r in db.session.query(Exam.student_id).filter(Exam.student_id != "").distinct().all()})
    # 2) 过滤掉已有姓名的
    missing = []
    for sid in sids:
        name = dao.get_user_setting(sid, "name", "")
        if not name:
            missing.append(sid)
    if not missing:
        return jsonify({"success": True, "tried": 0, "ok": [], "fail": [],
                        "message": "所有用户均已有姓名记录"})
    missing = missing[:20]   # 单次上限, 防风控
    ok_list, fail_list = [], []
    for i, sid in enumerate(missing):
        if i > 0:
            time.sleep(2)   # 串行 + 间隔, 降低教务风控风险
        client = JWCClient()
        try:
            ok = client.login(sid, f"{sid}@Njust")
        except Exception as e:
            ok = False
            client.last_error = f"异常: {e}"
        if ok and client.student_name:
            try:
                dao.set_user_setting(sid, "name", client.student_name)
            except Exception:
                pass
            ok_list.append({"sid": sid, "name": client.student_name})
            app.logger.info("[admin] rid=%s 补齐姓名 sid=%s name=%s", _rid(), sid, client.student_name)
        else:
            fail_list.append({"sid": sid, "reason": (client.last_error or "密码可能已修改")[:80]})
        # 无论成败都尝试登出, 释放教务会话
        try:
            client.logout()
        except Exception:
            pass
    return jsonify({
        "success": True,
        "tried": len(missing),
        "ok": ok_list,
        "fail": fail_list,
        "message": f"成功 {len(ok_list)} 人, 失败 {len(fail_list)} 人(多为已改密码, 可忽略)",
    })


# ============================================================
# 留言板管理
# ============================================================
@app.route("/api/admin/board")
@admin_required
def admin_board_list():
    """留言列表(全量, 倒序, 含点赞/评论统计)"""
    from sqlalchemy import func as _f
    msgs = dao.get_board_messages(limit=500, sort="time", viewer_id="")
    ccounts = {}
    if msgs:
        ids = [m["id"] for m in msgs]
        for mid, cnt in db.session.query(BoardComment.message_id, _f.count(BoardComment.id)) \
                .filter(BoardComment.message_id.in_(ids)).group_by(BoardComment.message_id).all():
            ccounts[mid] = cnt
    for m in msgs:
        m["comments"] = ccounts.get(m["id"], 0)
    return jsonify({"success": True, "messages": msgs})


@app.route("/api/admin/board/<int:msg_id>", methods=["DELETE"])
@admin_required
def admin_board_delete(msg_id: int):
    """删除留言"""
    ok = dao.delete_board_message(msg_id)
    if not ok:
        return jsonify({"success": False, "message": "留言不存在"}), 404
    app.logger.info("[admin] rid=%s 删除留言 id=%d", _rid(), msg_id)
    return jsonify({"success": True})


# ============================================================
# 问题反馈管理
# ============================================================
@app.route("/api/admin/feedback")
@admin_required
def admin_feedback_list():
    """反馈列表(倒序; status 可选过滤 pending/done)"""
    status = request.args.get("status", "")
    if status not in ("", "pending", "done"):
        status = ""
    items = dao.list_feedback(limit=500, status=status or "")
    return jsonify({"success": True, "feedback": items})


@app.route("/api/admin/feedback/<int:fid>", methods=["POST"])
@admin_required
def admin_feedback_set_status(fid: int):
    """标记处理状态: pending 待处理 | done 已处理"""
    data = request.get_json(silent=True) or {}
    status = str(data.get("status", "done"))
    if status not in ("pending", "done"):
        status = "done"
    ok = dao.set_feedback_status(fid, status)
    if not ok:
        return jsonify({"success": False, "message": "反馈不存在"}), 404
    app.logger.info("[admin] rid=%s 反馈状态 id=%d -> %s", _rid(), fid, status)
    return jsonify({"success": True})


@app.route("/api/admin/feedback/<int:fid>", methods=["DELETE"])
@admin_required
def admin_feedback_delete(fid: int):
    """删除反馈"""
    ok = dao.delete_feedback(fid)
    if not ok:
        return jsonify({"success": False, "message": "反馈不存在"}), 404
    app.logger.info("[admin] rid=%s 删除反馈 id=%d", _rid(), fid)
    return jsonify({"success": True})


@app.route("/api/admin/check")
def admin_check():
    """前端登录态检查(不带 token 也可调, 返回是否已登录)"""
    tok = request.headers.get("X-Admin-Token") or request.args.get("token") or ""
    with _admin_lock:
        valid = bool(_admin_token and _admin_token[0] == tok and _admin_token[1] > time.time())
    return jsonify({"success": True, "logged_in": valid})
