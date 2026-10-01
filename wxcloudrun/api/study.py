# -*- coding: utf-8 -*-
"""教学周历 / 培养方案(学分进度)接口。

- GET  /api/calendar?semester=   : 教学周历(全局缓存, 7 天)
- POST /api/refresh-calendar     : 强制刷新教学周历
- GET  /api/programme            : 专业培养方案(用户缓存)
- POST /api/refresh-programme    : 强制刷新培养方案
- GET  /api/profile              : 学籍卡片 + 门户身份(不含头像; 用户缓存 30 天)
- POST /api/refresh-profile      : 强制刷新学籍卡片
"""
import json
import threading
import time

from flask import Blueprint, jsonify, request

from wxcloudrun import app, dao
from wxcloudrun.core.auth import _require_login
from wxcloudrun.core.dedupe import dedupe
from wxcloudrun.core.pool import _jwc_request
from wxcloudrun.core.web import _rid

study_bp = Blueprint("study_api", __name__)

CALENDAR_TTL = 7 * 24 * 3600        # 教学周历: 全局缓存 7 天
PROFILE_TTL = 30 * 24 * 3600        # 学籍卡片: 用户缓存 30 天(信息极少变动)
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
    if cached and cached.get("courses"):
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


def schedule_study_prefetch(client, sid: str, semester: str = "", delay: float = 3.0) -> None:
    """登录成功后后台预抓(不阻塞登录, 失败静默):
    ① 教学周历 → 回写 first_week_date(课表页周次校准, 教务为准; 全局缓存 7 天)
    ② 培养方案 → 学分进度页数据源
    ③ 学籍卡片 → 「我的」页学籍信息(30 天缓存, 命中则跳过)。

    所有教务请求都走 _jwc_request(实例锁 + 全局并发限流), 与用户其它请求串行。
    """
    if not sid:
        return

    def _run():
        try:
            time.sleep(delay)                 # 让登录响应先返回
            if not getattr(client, "logged_in", False):
                return
            sem = semester or dao.get_user_setting(sid, "semester") or ""
            cached = _load_json(_calendar_key(sem))
            if cached and time.time() - int(cached.get("fetched_at") or 0) < CALENDAR_TTL:
                _sync_first_week(sid, cached)
            else:
                _fetch_calendar(client, sid, sem, cached)
            if not getattr(client, "logged_in", False):
                return
            with _jwc_request(client):
                data = client.fetch_programme()
            if not data:
                return
            data["fetched_at"] = int(time.time())
            _save_user_json(sid, PROGRAMME_KEY, data)
            # 学籍卡片: 30 天缓存, 没过期就不再抓
            prof = _load_user_json(sid, PROFILE_KEY)
            if not (prof and time.time() - int(prof.get("fetched_at") or 0) < PROFILE_TTL):
                with _jwc_request(client):
                    pdata = client.fetch_profile()
                if pdata:
                    pdata["fetched_at"] = int(time.time())
                    _save_user_json(sid, PROFILE_KEY, pdata)
            app.logger.info("[prefetch] rid=%s 周历+培养方案+学籍 sid=%s sem=%s count=%s",
                            _rid(), sid, sem, data.get("count"))
        except Exception:                     # noqa: BLE001 预抓失败不影响用户
            pass

    threading.Thread(target=_run, name="study-prefetch", daemon=True).start()
