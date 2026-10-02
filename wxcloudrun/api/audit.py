# -*- coding: utf-8 -*-
"""蹭课目录: 每日后台同步, 前端只查询服务器数据库。"""
import os
import json
import threading
import time

from flask import Blueprint, jsonify, request

from wxcloudrun import app, dao
from wxcloudrun.core.auth import _require_login
from wxcloudrun.core.jwc_client_pool import JWCClientPool
from wxcloudrun.core.pool import _jwc_request
from wxcloudrun.core.semester import current_semester
from wxcloudrun.core.web import _rid

audit_bp = Blueprint("audit_api", __name__)

AUDIT_META_PREFIX = "audit_catalog_at"
AUDIT_TTL = 24 * 3600
# 临时维护版本: 部署后不启动蹭课同步, 所有蹭课接口在查询数据库前直接返回。
# 教务表迁移完成后由下一次正常发版移除。
AUDIT_COURSE_MAINTENANCE = True
AUDIT_SYNC_STATE_KEY = "wx:audit-catalog-sync:status"
AUDIT_SYNC_STATE_TTL = 7 * 24 * 3600
AUDIT_SYNC_MAX_RUNTIME = 3600
AUDIT_OPTIONS_CHUNK_SIZE = max(
    1, int(os.environ.get("AUDIT_OPTIONS_CHUNK_SIZE", "2000")))
_OPTIONS_CACHE = {}
_OPTIONS_CACHE_LOCK = threading.Lock()
_SYNC_STATE_LOCK = threading.Lock()
_SYNC_STATE = {
    "running": False,
    "semester": "",
    "started_at": 0,
    "finished_at": 0,
    "success": None,
    "count": 0,
    "error": "",
}


def _current_semester() -> str:
    return current_semester()


def _meta_key(semester: str) -> str:
    return f"{AUDIT_META_PREFIX}:{semester}"


def _updated_at(semester: str) -> int:
    try:
        return int(dao.get_setting(_meta_key(semester), "0") or 0)
    except Exception:
        return 0


def _needs_refresh(semester: str) -> bool:
    return (dao.count_audit_courses(semester) <= 0
            or time.time() - _updated_at(semester) >= AUDIT_TTL)


def _audit_maintenance_response():
    return jsonify({
        "success": False,
        "maintenance": True,
        "message": "蹭课服务正在维护，请稍后再试",
    }), 503


def _normalize_sync_state(value) -> dict:
    state = dict(_SYNC_STATE)
    if isinstance(value, dict):
        state.update(value)
    try:
        state["started_at"] = int(state.get("started_at") or 0)
    except (TypeError, ValueError):
        state["started_at"] = 0
    try:
        state["finished_at"] = int(state.get("finished_at") or 0)
    except (TypeError, ValueError):
        state["finished_at"] = 0
    try:
        state["count"] = max(0, int(state.get("count") or 0))
    except (TypeError, ValueError):
        state["count"] = 0
    state["running"] = bool(state.get("running"))
    state["semester"] = str(state.get("semester") or "")[:50]
    state["error"] = str(state.get("error") or "")[:500]
    if state.get("success") is not None:
        state["success"] = bool(state.get("success"))
    if (state["running"]
            and time.time() - state["started_at"] > AUDIT_SYNC_MAX_RUNTIME):
        state["running"] = False
    return state


def _sync_state_snapshot() -> dict:
    remote = None
    try:
        from wxcloudrun.core import state as distributed_state
        remote = distributed_state.get_json(AUDIT_SYNC_STATE_KEY)
    except Exception:  # noqa: BLE001 状态展示失败不能影响同步
        remote = None
    if isinstance(remote, dict):
        return _normalize_sync_state(remote)
    with _SYNC_STATE_LOCK:
        return _normalize_sync_state(_SYNC_STATE)


def _persist_sync_state(state: dict):
    try:
        from wxcloudrun.core import state as distributed_state
        distributed_state.set_json(
            AUDIT_SYNC_STATE_KEY, state, ttl=AUDIT_SYNC_STATE_TTL)
    except Exception:  # noqa: BLE001 Redis 不可用时保留进程内状态
        pass


def _store_sync_state(patch: dict) -> dict:
    with _SYNC_STATE_LOCK:
        state = _normalize_sync_state(_SYNC_STATE)
        state.update(patch)
        state = _normalize_sync_state(state)
        _SYNC_STATE.update(state)
    _persist_sync_state(state)
    return state


def get_audit_sync_status(semester: str = "") -> dict:
    """返回蹭课目录状态，供管理面板展示和轮询。"""
    if AUDIT_COURSE_MAINTENANCE:
        return {
            "semester": semester,
            "course_count": 0,
            "updated_at": 0,
            "empty": True,
            "needs_refresh": False,
            "db_error": "",
            "running": False,
            "running_semester": "",
            "last_started_at": 0,
            "last_finished_at": 0,
            "last_success": None,
            "last_count": 0,
            "last_error": "",
            "maintenance": True,
        }
    semester = semester or _current_semester()
    try:
        count = dao.count_audit_courses(semester)
        db_error = ""
    except Exception as exc:  # noqa: BLE001 状态接口始终返回可读错误
        count = 0
        db_error = f"{type(exc).__name__}: {exc}"
    updated_at = _updated_at(semester)
    state = _sync_state_snapshot()
    return {
        "semester": semester,
        "course_count": count,
        "updated_at": updated_at,
        "empty": count <= 0,
        "needs_refresh": bool(
            db_error or count <= 0
            or time.time() - updated_at >= AUDIT_TTL),
        "db_error": db_error,
        "running": bool(state.get("running")),
        "running_semester": state.get("semester") or "",
        "last_started_at": state.get("started_at") or 0,
        "last_finished_at": state.get("finished_at") or 0,
        "last_success": state.get("success"),
        "last_count": state.get("count") or 0,
        "last_error": state.get("error") or "",
    }


def _mark_sync_started(semester: str):
    state = _sync_state_snapshot()
    if state.get("running"):
        return False, state
    with _SYNC_STATE_LOCK:
        state = _normalize_sync_state(_SYNC_STATE)
        if state.get("running"):
            return False, state
        state = _normalize_sync_state({
            **state,
            "running": True,
            "semester": semester,
            "started_at": int(time.time()),
            "finished_at": 0,
            "success": None,
            "count": 0,
            "error": "",
        })
        _SYNC_STATE.update(state)
    _persist_sync_state(state)
    return True, state


def _mark_sync_finished(semester: str, count: int, error: str):
    return _store_sync_state({
        "running": False,
        "semester": semester,
        "finished_at": int(time.time()),
        "success": not bool(error),
        "count": max(0, int(count or 0)),
        "error": str(error or ""),
    })


def start_audit_catalog_sync(semester: str = ""):
    """后台启动一次同步并立即返回；真正抓取不在 HTTP 请求线程执行。"""
    if AUDIT_COURSE_MAINTENANCE:
        return False, get_audit_sync_status(semester)
    semester = semester or _current_semester()
    started, state = _mark_sync_started(semester)
    if not started:
        return False, state

    def _worker():
        count, error = 0, ""
        with app.app_context():
            try:
                from wxcloudrun.core.state import distributed_lock
                with distributed_lock(
                        "wx:lock:audit-catalog", ttl=3600) as acquired:
                    if not acquired:
                        error = "已有同步任务正在运行"
                    else:
                        count, error = sync_audit_catalog(semester)
            except Exception as exc:  # noqa: BLE001 后台线程不能静默退出
                error = f"{type(exc).__name__}: {exc}"
                app.logger.warning(
                    "[audit-sync] 管理员手动同步异常: %s", error)
            _mark_sync_finished(semester, count, error)

    try:
        threading.Thread(
            target=_worker, daemon=True,
            name="audit-catalog-manual-sync").start()
    except Exception as exc:  # noqa: BLE001 线程创建失败时恢复状态
        error = f"后台任务启动失败: {type(exc).__name__}"
        _mark_sync_finished(semester, 0, error)
        return False, _sync_state_snapshot()
    return True, state


def _all_options(semester: str) -> dict:
    stamp = (_updated_at(semester), dao.count_audit_courses(semester))
    cache = _OPTIONS_CACHE.get(semester)
    if cache and cache[0] == stamp:
        return cache[1]
    with _OPTIONS_CACHE_LOCK:
        cache = _OPTIONS_CACHE.get(semester)
        if cache and cache[0] == stamp:
            return cache[1]
        options = dao.query_audit_options_all(semester)
        _OPTIONS_CACHE[semester] = (stamp, options)
        return options


def _text_arg(name: str, limit: int = 50) -> str:
    return (request.args.get(name) or "").strip()[:limit]


def _int_arg(name: str, default: int = 0, minimum: int = 0,
             maximum: int = 13) -> int:
    try:
        value = int(request.args.get(name, default) or default)
    except (TypeError, ValueError):
        value = default
    return min(maximum, max(minimum, value))


def _list_arg(name: str, limit: int = 50) -> list:
    """解析 JSON 数组参数; 兼容单值。"""
    raw = (request.args.get(name) or "").strip()
    if not raw:
        return []
    try:
        value = json.loads(raw)
    except (TypeError, ValueError):
        value = [raw]
    if not isinstance(value, list):
        value = [value]
    out = []
    for item in value:
        item = str(item or "").strip()
        if item and item not in out:
            out.append(item)
        if len(out) >= limit:
            break
    return out


def sync_audit_catalog(semester: str = "") -> tuple:
    """用共享本科 Cookie 池抓取课程课表并替换数据库目录。"""
    from wxcloudrun.api.freeclass import _service_client_provider

    semester = semester or _current_semester()
    pool = JWCClientPool(service_provider=_service_client_provider)
    last_error = "课程目录同步失败"
    for _attempt in range(10):
        client, source, sid, err = pool.next_client()
        if client is None:
            return 0, err or last_error
        try:
            with _jwc_request(client):
                courses = client.fetch_course_schedule(
                    semester=semester, keyword="", course_type="")
        except Exception as exc:  # noqa: BLE001
            last_error = f"{type(exc).__name__}: {exc}"
            pool.client = None
            continue
        if courses:
            count = dao.replace_audit_courses(courses, semester)
            dao.set_setting(_meta_key(semester), str(int(time.time())))
            app.logger.info(
                "[audit-sync] rid=%s source=%s sid=%s sem=%s count=%d",
                _rid(), source, (sid or "-")[:3] + "****", semester, count)
            return count, ""
        last_error = client.last_error or "课程目录为空"
        if "登录" in last_error or "logon" in last_error.lower():
            client.logged_in = False
        pool.client = None
    return 0, last_error


def start_audit_catalog_scheduler() -> None:
    """启动每日 00:00 蹭课目录同步线程。"""
    if AUDIT_COURSE_MAINTENANCE:
        app.logger.info("[audit-sync] 临时维护模式, 不启动蹭课目录同步")
        return

    def _run():
        while True:
            try:
                with app.app_context():
                    semester = _current_semester()
                    if _needs_refresh(semester):
                        from wxcloudrun.core.state import distributed_lock
                        with distributed_lock(
                                "wx:lock:audit-catalog", ttl=3600) as acquired:
                            if acquired:
                                started, _state = _mark_sync_started(semester)
                                if started:
                                    try:
                                        count, error = sync_audit_catalog(
                                            semester)
                                    except Exception as exc:  # noqa: BLE001
                                        count = 0
                                        error = f"{type(exc).__name__}: {exc}"
                                        app.logger.warning(
                                            "[audit-sync] 定时同步异常: %s",
                                            error)
                                    finally:
                                        _mark_sync_finished(
                                            semester, count, error)
                    from datetime import datetime, timedelta
                    now = datetime.now()
                    nxt = datetime.combine(
                        now.date(), now.time().replace(
                            hour=0, minute=0, second=0, microsecond=0))
                    if nxt <= now:
                        nxt += timedelta(days=1)
                    time.sleep(max(60, (nxt - now).total_seconds()))
            except Exception as exc:  # noqa: BLE001
                app.logger.warning("[audit-sync] 线程异常: %s", exc)
                time.sleep(300)

    if app.config.get("AUDIT_SYNC_DISABLED"):
        return
    threading.Thread(target=_run, daemon=True, name="audit-catalog-sync").start()


@audit_bp.route('/api/audit-courses')
def api_audit_courses():
    if AUDIT_COURSE_MAINTENANCE:
        return _audit_maintenance_response()
    _client, err = _require_login()
    if err:
        return err
    semester = ((request.args.get("semester") or "").strip()
                or _current_semester())
    keyword = _text_arg("q")
    name = _text_arg("name")
    teacher = _text_arg("teacher")
    classroom = _text_arg("classroom") or _text_arg("location")
    names = _list_arg("names") or ([name] if name else [])
    teachers = _list_arg("teachers") or ([teacher] if teacher else [])
    classrooms = _list_arg("classrooms") or (
        [classroom] if classroom else [])
    page = _int_arg("page", 1, 1, 1000000)
    limit = _int_arg("limit", 20, 1, 50)
    weekday = _int_arg("weekday", 0, 0, 7)
    jc1 = _int_arg("jc1", 0, 0, 13)
    jc2 = _int_arg("jc2", 0, 0, 13)
    name_exact = bool(_int_arg("name_exact", 0, 0, 1))
    teacher_exact = bool(_int_arg("teacher_exact", 0, 0, 1))
    classroom_exact = bool(_int_arg("classroom_exact", 0, 0, 1))
    if jc1 and jc2 and jc1 > jc2:
        jc1, jc2 = jc2, jc1
    rows, total = dao.query_audit_course_groups(
        semester, names=names, teachers=teachers, classrooms=classrooms,
        keyword=keyword, weekday=weekday, jc1=jc1, jc2=jc2, limit=limit,
        offset=(page - 1) * limit, name_exact=name_exact,
        teacher_exact=teacher_exact, classroom_exact=classroom_exact)
    return jsonify({
        "success": True,
        "semester": semester,
        "courses": rows,
        "count": len(rows),
        "total": total,
        "page": page,
        "limit": limit,
        "has_more": page * limit < total,
        "updated_at": _updated_at(semester),
        "fields": [
            "name", "class_info", "teacher", "classroom", "schedules",
            "schedule_count",
        ],
    })


@audit_bp.route('/api/audit-options')
def api_audit_options():
    if AUDIT_COURSE_MAINTENANCE:
        return _audit_maintenance_response()
    _client, err = _require_login()
    if err:
        return err
    field = (request.args.get("field") or "name").strip()
    if field == "location":
        field = "classroom"
    semester = ((request.args.get("semester") or "").strip()
                or _current_semester())
    if field == "version":
        return jsonify({
            "success": True,
            "semester": semester,
            "field": "version",
            "catalog_version": _updated_at(semester),
            "count": dao.count_audit_courses(semester),
        })
    if field == "all":
        options = _all_options(semester)
        chunk_size = AUDIT_OPTIONS_CHUNK_SIZE
        relation_count = len(options["relations"])
        parts = max(1, (relation_count + chunk_size - 1) // chunk_size)
        raw_part = request.args.get("part")
        if raw_part is None:
            part = 0
            parts = 1
            chunk_size = relation_count or 1
        else:
            try:
                part = int(raw_part)
            except (TypeError, ValueError):
                return jsonify({
                    "success": False,
                    "message": "分片编号无效",
                }), 400
        if part < 0 or part >= parts:
            return jsonify({
                "success": False,
                "message": "分片编号超出范围",
            }), 400
        start = part * chunk_size
        payload = {
            "success": True,
            "semester": semester,
            "field": "all",
            "catalog_version": _updated_at(semester),
            "part": part,
            "parts": parts,
            "relations_total": relation_count,
            "relations_offset": start,
            "relations": options["relations"][start:start + chunk_size],
        }
        if part == 0:
            payload.update({
                "names": options["names"],
                "teachers": options["teachers"],
                "classrooms": options["classrooms"],
            })
        return jsonify(payload)
    if field not in ("name", "teacher", "classroom"):
        return jsonify({"success": False, "message": "不支持的候选字段"}), 400
    keyword = _text_arg("q")
    limit = _int_arg("limit", 20, 1, 50)
    options = dao.query_audit_options(
        semester, field=field, keyword=keyword, limit=limit)
    return jsonify({
        "success": True,
        "semester": semester,
        "field": field,
        "options": options,
        "count": len(options),
    })


@audit_bp.route('/api/audit-favorites', methods=['GET', 'POST'])
def api_audit_favorites():
    if AUDIT_COURSE_MAINTENANCE:
        return _audit_maintenance_response()
    client, err = _require_login()
    if err:
        return err
    student_id = str(client.student_id or "")
    if request.method == 'GET':
        semester = ((request.args.get("semester") or "").strip()
                    or _current_semester())
        return jsonify({
            "success": True,
            "semester": semester,
            "favorites": dao.list_audit_favorites(student_id, semester),
        })

    data = request.get_json(silent=True) or {}
    semester = (
        str(data.get("semester") or "").strip()
        or _current_semester()
    )
    course = data.get("course")
    if not isinstance(course, dict):
        course = data
    try:
        favorite = dao.save_audit_favorite(student_id, semester, course)
    except ValueError as exc:
        return jsonify({"success": False, "message": str(exc)}), 400
    return jsonify({
        "success": True,
        "semester": semester,
        "favorite": favorite,
    })


@audit_bp.route('/api/audit-favorites/<int:favorite_id>', methods=['DELETE'])
def api_delete_audit_favorite(favorite_id):
    if AUDIT_COURSE_MAINTENANCE:
        return _audit_maintenance_response()
    client, err = _require_login()
    if err:
        return err
    if not dao.delete_audit_favorite(client.student_id or "", favorite_id):
        return jsonify({
            "success": False,
            "message": "收藏不存在",
        }), 404
    return jsonify({"success": True})
