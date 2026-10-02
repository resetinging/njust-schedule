# -*- coding: utf-8 -*-
"""教学周历 / 培养方案(学分进度) / 学籍卡片接口。

- GET  /api/calendar?semester=   : 教学周历(全局缓存)
- POST /api/refresh-calendar     : 强制刷新教学周历
- GET  /api/programme            : 专业培养方案(用户缓存)
- POST /api/refresh-programme    : 强制刷新培养方案
- GET  /api/profile              : 学籍卡片 + 门户身份(不含头像)
- POST /api/refresh-profile      : 强制刷新学籍卡片
"""
from collections import defaultdict
import json
import threading
import time

from flask import Blueprint, jsonify, request

from config import DATA_CACHE_TTL
from wxcloudrun import app, dao
from wxcloudrun.core.auth import _require_login
from wxcloudrun.core.cache import _cache_set, invalidate_user_cache
from wxcloudrun.core.dedupe import dedupe
from wxcloudrun.core.pool import _jwc_request
from wxcloudrun.core.web import _rid

study_bp = Blueprint("study_api", __name__)

CALENDAR_TTL = DATA_CACHE_TTL       # 教学周历: 与教务持久会话同周期
PROGRAMME_TTL = DATA_CACHE_TTL      # 培养方案: 与教务持久会话同周期
PROFILE_TTL = DATA_CACHE_TTL        # 学籍卡片: 与教务持久会话同周期
PROGRAMME_KEY = "programme"         # settings 用户键: {sid}:programme
PROFILE_KEY = "profile"             # settings 用户键: {sid}:profile


def _calendar_key(semester: str) -> str:
    return f"calendar:{semester}" if semester else "calendar:current"


def _load_json(key: str) -> dict:
    raw = dao.get_setting(key, "")
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _save_json(key: str, data: dict) -> None:
    dao.set_setting(key, json.dumps(data, ensure_ascii=False))


def _load_user_json(sid: str, key: str) -> dict:
    raw = dao.get_user_setting(sid, key, "")
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _save_user_json(sid: str, key: str, data: dict) -> None:
    dao.set_user_setting(sid, key, json.dumps(data, ensure_ascii=False))


def _set_data_refresh_state(client, state: str, **extra) -> None:
    payload = {"state": state, "updated_at": int(time.time())}
    payload.update(extra)
    client._data_refresh_state = payload


def _sync_first_week(sid: str, data: dict) -> None:
    """教学周历 → 用户 `first_week_date`(课表页定位本周的取值来源; 教务为准)。

    写入 {sid}:first_week_date:{semester}, 与「我的」页手动设置同一键;
    教务同步值会覆盖手动值 —— 这是"以教务为准"的既定口径。
    """
    fm = data.get("first_monday")
    sem = data.get("semester") or ""
    if not (sid and fm and sem):
        return
    try:
        dao.set_setting(f"{sid}:first_week_date:{sem}", fm)
    except Exception:  # noqa: BLE001 同步失败不影响周历返回
        pass


def _fetch_calendar(client, sid: str, semester: str, cached: dict) -> dict:
    """抓取并落库; 失败时回退旧缓存(标记 stale), 完全没有则返回 {}"""
    with _jwc_request(client):
        data = client.fetch_calendar(semester)
    if not data:
        if cached:
            _sync_first_week(sid, cached)
            return dict(cached, cached=True, stale=True)
        return {}
    data["fetched_at"] = int(time.time())
    _save_json(_calendar_key(data.get("semester") or semester), data)
    _sync_first_week(sid, data)
    return dict(data, cached=False)


@study_bp.route('/api/calendar')
def api_get_calendar():
    client, err = _require_login()
    if err:
        return err
    sid = client.student_id or ""
    semester = (request.args.get("semester") or "").strip() \
        or dao.get_user_setting(sid, "semester") or ""
    cached = _load_json(_calendar_key(semester))
    if cached and time.time() - int(cached.get("fetched_at") or 0) < CALENDAR_TTL:
        _sync_first_week(sid, cached)
        return jsonify(dict({"success": True, "cached": True}, **cached))
    data = _fetch_calendar(client, sid, semester, cached)
    if not data:
        return jsonify({"success": False,
                        "message": client.last_error or "教学周历获取失败"}), 502
    return jsonify(dict({"success": True}, **data))


@study_bp.route('/api/refresh-calendar', methods=['POST'])
@dedupe('refresh-calendar')
def api_refresh_calendar():
    client, err = _require_login()
    if err:
        return err
    sid = client.student_id or ""
    body = request.get_json(silent=True) or {}
    semester = (body.get("semester") or request.args.get("semester") or "").strip() \
        or dao.get_user_setting(sid, "semester") or ""
    cached = _load_json(_calendar_key(semester))
    data = _fetch_calendar(client, sid, semester, cached)
    if not data:
        return jsonify({"success": False,
                        "message": client.last_error or "教学周历获取失败"}), 502
    app.logger.info("[refresh] rid=%s 教学周历 semester=%s weeks=%s",
                    _rid(), semester, data.get("count"))
    return jsonify(dict({"success": True}, **data))


def _fetch_programme(client, sid: str, cached: dict) -> dict:
    with _jwc_request(client):
        data = client.fetch_programme()
    if not data:
        if cached:
            return dict(cached, cached=True, stale=True)
        return {}
    data["fetched_at"] = int(time.time())
    _save_user_json(sid, PROGRAMME_KEY, data)
    return dict(data, cached=False)


@study_bp.route('/api/programme')
def api_get_programme():
    client, err = _require_login()
    if err:
        return err
    if getattr(client, "account_type", "") == "graduate":
        return jsonify({"success": True, "supported": False, "courses": [],
                        "message": "研究生账号暂无培养方案数据"})
    sid = client.student_id or ""
    cached = _load_user_json(sid, PROGRAMME_KEY)
    if cached and cached.get("courses") and \
            time.time() - int(cached.get("fetched_at") or 0) < PROGRAMME_TTL:
        return jsonify(dict({"success": True, "supported": True, "cached": True}, **cached))
    data = _fetch_programme(client, sid, cached)
    if not data:
        return jsonify({"success": False,
                        "message": client.last_error or "培养方案获取失败"}), 502
    return jsonify(dict({"success": True, "supported": True}, **data))


@study_bp.route('/api/refresh-programme', methods=['POST'])
@dedupe('refresh-programme')
def api_refresh_programme():
    client, err = _require_login()
    if err:
        return err
    if getattr(client, "account_type", "") == "graduate":
        return jsonify({"success": True, "supported": False, "courses": [],
                        "message": "研究生账号暂无培养方案数据"})
    sid = client.student_id or ""
    cached = _load_user_json(sid, PROGRAMME_KEY)
    data = _fetch_programme(client, sid, cached)
    if not data:
        return jsonify({"success": False,
                        "message": client.last_error or "培养方案获取失败"}), 502
    app.logger.info("[refresh] rid=%s 培养方案 sid=%s count=%s pages=%s",
                    _rid(), sid, data.get("count"), data.get("pages"))
    return jsonify(dict({"success": True, "supported": True}, **data))


def _fetch_profile(client, sid: str, cached: dict) -> dict:
    with _jwc_request(client):
        data = client.fetch_profile()
    if not data:
        if cached:
            return dict(cached, cached=True, stale=True)
        return {}
    data["fetched_at"] = int(time.time())
    _save_user_json(sid, PROFILE_KEY, data)
    return dict(data, cached=False)


@study_bp.route('/api/profile')
def api_get_profile():
    """学籍卡片(院系/专业/班级/学号 + 身份类别); 30 天缓存, 首次访问自动抓取。"""
    client, err = _require_login()
    if err:
        return err
    sid = client.student_id or ""
    cached = _load_user_json(sid, PROFILE_KEY)
    if cached and cached.get("fields") and \
            time.time() - int(cached.get("fetched_at") or 0) < PROFILE_TTL:
        return jsonify(dict({"success": True, "cached": True}, **cached))
    data = _fetch_profile(client, sid, cached)
    if not data:
        return jsonify({"success": False,
                        "message": client.last_error or "学籍卡片获取失败"}), 502
    return jsonify(dict({"success": True}, **data))


@study_bp.route('/api/refresh-profile', methods=['POST'])
@dedupe('refresh-profile')
def api_refresh_profile():
    client, err = _require_login()
    if err:
        return err
    sid = client.student_id or ""
    cached = _load_user_json(sid, PROFILE_KEY)
    data = _fetch_profile(client, sid, cached)
    if not data:
        return jsonify({"success": False,
                        "message": client.last_error or "学籍卡片获取失败"}), 502
    app.logger.info("[refresh] rid=%s 学籍卡片 sid=%s fields=%d",
                    _rid(), sid, len(data.get("fields") or {}))
    return jsonify(dict({"success": True}, **data))


def _prefetch_grades(sid: str, grades: list) -> int:
    grouped = defaultdict(list)
    for grade in grades:
        grouped[(grade.get("academic_year", ""), grade.get("semester", ""))].append(grade)
    total = 0
    for (academic_year, semester), group in grouped.items():
        dao.save_grades(group, academic_year, semester, sid)
        total += len(group)
    return total


def _prefetch_graduate(client, sid: str) -> dict:
    """研究生系统数据预抓：课表 / 成绩 / 考试。"""
    result = {"ok": [], "failed": []}

    client.last_error = ""
    data = client.fetch_courses()
    if not getattr(client, "logged_in", False):
        result["aborted"] = "session_expired"
        return result
    if data.get("courses") or not client.last_error:
        courses = data.get("courses") or []
        semester = (data.get("semesters") or [""])[0]
        _cache_set(f"{sid}:yjs:courses", {
            "success": True, "semester": semester, "count": len(courses),
            "courses": courses, "account_type": "graduate"})
        result["ok"].append("courses")
    else:
        result["failed"].append("courses")

    client.last_error = ""
    data = client.fetch_grades()
    if not getattr(client, "logged_in", False):
        result["aborted"] = "session_expired"
        return result
    if data.get("rows") or data.get("stats") or not client.last_error:
        _cache_set(f"{sid}:yjs:grades", {
            "success": True,
            "account_type": "graduate",
            "stats": data.get("stats") or [],
            "rows": data.get("rows") or [],
            "semesters": data.get("semesters") or [],
        })
        result["ok"].append("grades")
    else:
        result["failed"].append("grades")

    client.last_error = ""
    data = client.fetch_exams()
    if not getattr(client, "logged_in", False):
        result["aborted"] = "session_expired"
        return result
    if data.get("rows") or not client.last_error:
        _cache_set(f"{sid}:yjs:exams", {
            "success": True,
            "account_type": "graduate",
            "semester": (data.get("semesters") or [""])[0],
            "count": len(data.get("rows") or []),
            "rows": data.get("rows") or [],
        })
        result["ok"].append("exams")
    else:
        result["failed"].append("exams")
    return result


def _prefetch_undergraduate(client, sid: str, semester: str) -> dict:
    """本科教务数据预抓：周历 / 课表 / 考试 / 成绩 / CET / 评教 / 培养方案 / 学籍。"""
    result = {"ok": [], "failed": []}

    def mark(name: str, success: bool) -> None:
        result["ok" if success else "failed"].append(name)

    cached_calendar = _load_json(_calendar_key(semester))
    calendar = _fetch_calendar(client, sid, semester, cached_calendar)
    mark("calendar", bool(calendar))
    if not getattr(client, "logged_in", False):
        result["aborted"] = "session_expired"
        invalidate_user_cache(sid)
        return result

    def call(method, *args):
        # 每个数据域独立占用访问池, 避免一次全量预抓长期占住全局教务并发槽。
        with _jwc_request(client):
            client.last_error = ""
            return method(*args)

    def abort_if_logged_out() -> bool:
        if getattr(client, "logged_in", False):
            return False
        result["aborted"] = "session_expired"
        invalidate_user_cache(sid)
        return True

    courses = call(client.get_schedule, semester)
    if abort_if_logged_out():
        return result
    if courses or not client.last_error:
        dao.save_courses(courses, semester, sid)
        mark("courses", True)
    else:
        mark("courses", False)

    exams = call(client.get_exams, semester)
    if abort_if_logged_out():
        return result
    if exams or not client.last_error:
        dao.save_exams(exams, semester, sid)
        mark("exams", True)
    else:
        mark("exams", False)

    grades = call(client.get_grades, "")
    if abort_if_logged_out():
        return result
    if grades or not client.last_error:
        _prefetch_grades(sid, grades)
        mark("grades", True)
    else:
        mark("grades", False)

    cet_scores = call(client.get_cet_scores)
    if abort_if_logged_out():
        return result
    if cet_scores:
        dao.save_cet_scores(cet_scores, sid)
    mark("cet", bool(cet_scores) or not client.last_error)

    evaluations = call(client.get_evaluations, "")
    if abort_if_logged_out():
        return result
    if evaluations or not client.last_error:
        dao.save_evaluations(evaluations, "", sid)
        mark("evaluations", True)
    else:
        mark("evaluations", False)

    programme = call(client.fetch_programme)
    if abort_if_logged_out():
        return result
    if programme:
        programme["fetched_at"] = int(time.time())
        _save_user_json(sid, PROGRAMME_KEY, programme)
    mark("programme", bool(programme))

    profile = call(client.fetch_profile)
    if abort_if_logged_out():
        return result
    if profile:
        profile["fetched_at"] = int(time.time())
        _save_user_json(sid, PROFILE_KEY, profile)
    mark("profile", bool(profile))

    invalidate_user_cache(sid)
    return result


def schedule_data_prefetch(client, sid: str, semester: str = "",
                           delay: float = 3.0) -> None:
    """会话建立后后台同步全部业务数据（不阻塞登录，失败保留旧缓存）。"""
    if not sid:
        return
    if getattr(client, "_data_prefetch_running", False):
        return
    client._data_prefetch_running = True
    started_at = int(time.time())
    _set_data_refresh_state(client, "pending", started_at=started_at)
    invalidate_user_cache(sid)

    def _run():
        try:
            with app.app_context():
                time.sleep(max(0.0, delay))       # 让登录响应先返回
                _set_data_refresh_state(client, "running", started_at=started_at)
                if not getattr(client, "logged_in", False):
                    raise RuntimeError("会话已失效")
                sem = semester or dao.get_user_setting(sid, "semester") or ""
                if getattr(client, "account_type", "") == "graduate":
                    result = _prefetch_graduate(client, sid)
                else:
                    result = _prefetch_undergraduate(client, sid, sem)
                if result.get("aborted"):
                    state = "failed"
                else:
                    state = "done" if not result["failed"] else "partial"
                extra = {}
                if result.get("aborted"):
                    extra["aborted"] = result["aborted"]
                _set_data_refresh_state(
                    client, state,
                    started_at=started_at,
                    fetched_at=int(time.time()),
                    ok=result["ok"], failed=result["failed"], **extra)
                app.logger.info(
                    "[prefetch] rid=%s sid=%s sem=%s state=%s aborted=%s "
                    "ok=%s failed=%s",
                    _rid(), sid, sem, state, result.get("aborted", ""),
                    result["ok"], result["failed"])
        except Exception as exc:              # noqa: BLE001 预抓失败不影响用户
            _set_data_refresh_state(
                client, "failed",
                started_at=started_at,
                fetched_at=int(time.time()),
                error=f"{type(exc).__name__}: {exc}")
            app.logger.warning("[prefetch] rid=%s sid=%s 失败: %s",
                               _rid(), sid, type(exc).__name__)
        finally:
            client._data_prefetch_running = False

    threading.Thread(target=_run, daemon=True,
                     name=f"data-prefetch-{sid}").start()


def schedule_study_prefetch(client, sid: str, semester: str = "", delay: float = 3.0) -> None:
    """兼容旧调用名；现在会同步全部业务数据。"""
    schedule_data_prefetch(client, sid, semester, delay)
