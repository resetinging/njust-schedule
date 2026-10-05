# -*- coding: utf-8 -*-
"""空教室查询路由与预热(Phase 1b 从 views.py 拆出)。

数据源: 教务「教室借用查询」→ 状态=空闲教室清单;
缓存: 进程内全局缓存, TTL 到下一个自然日 00:00,
启动补齐当天全部大节, 之后每天 00:00 全量刷新。
"""
import os
import threading
import time

from flask import Blueprint, jsonify, request

import config
from wxcloudrun import app, dao
from wxcloudrun.core.auth import _require_login, _retry_with_relogin
from wxcloudrun.core.cache import _cache_get, _cache_set
from wxcloudrun.core.jwc_client_pool import JWCClientPool
from wxcloudrun.core.pool import _jwc_request
from wxcloudrun.core.semester import current_semester
from wxcloudrun.core.timeutil import _beijing_date
from wxcloudrun.core.web import _rid
from wxcloudrun.jwc_client import JWCClient, CLASSROOM_SLOTS

freeclass_bp = Blueprint("freeclass_api", __name__)


def _current_semester() -> str:
    return current_semester()


# ============================================================
# API — 空教室查询(需登录; 数据来自教务"全校性教室课表"空闲格解析)
# ============================================================
FREE_CLASSROOM_CAMPUSES = ("孝陵卫", "江阴")
# 官方大节(key, 名称, 起节, 止节): 兼容旧版 slot 参数
FREE_CLASSROOM_SLOTS = {s[0]: (s[2], s[3]) for s in CLASSROOM_SLOTS}
WEEKDAY_NAMES = ("", "星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日")
JC_MIN, JC_MAX = 1, 13   # 一天最多 13 节(官方大节 1-3/4-5/6-7/8-10/11-13)
try:
    FREE_CLASSROOM_PREWARM_DAYS = max(
        1, min(2, int(os.environ.get("FREE_CLASSROOM_PREWARM_DAYS", "1"))))
except (TypeError, ValueError):
    FREE_CLASSROOM_PREWARM_DAYS = 1


def _current_teaching_week(first_week_date: str, on=None) -> int:
    """按学期第一周周一计算教学周(1-25); on 默认北京时间今天; 无设置/解析失败回退 1"""
    try:
        from datetime import date
        if on is None:
            on = _beijing_date()
        y, m, d = (int(x) for x in str(first_week_date).split("-")[:3])
        days = (on - date(y, m, d)).days
        w = days // 7 + 1
        return w if 1 <= w <= 25 else 1
    except Exception:
        return 1


# ── 共享服务账号(空教室全局数据抓取) ──
# 教室数据全校一致: 用单一账号查询 + 全局缓存(120s), 所有用户共享;
# 实例锁串行保证同一账号 Cookie 一致, 会话失效时自动重登。
_classroom_service_lock = threading.Lock()
_classroom_service_client = JWCClient()
_prewarm_start_lock = threading.Lock()
_prewarm_thread = None
_COOKIE_SOURCE = os.environ.get("FREE_CLASSROOM_COOKIE_SOURCE", "auto").strip().lower()
try:
    _CANDIDATE_RETRIES = max(1, int(os.environ.get("FREE_CLASSROOM_CANDIDATE_RETRIES", "5")))
except (TypeError, ValueError):
    _CANDIDATE_RETRIES = 5
try:
    _PERSISTED_LIMIT = max(1, int(os.environ.get("FREE_CLASSROOM_PERSISTED_LIMIT", "50")))
except (TypeError, ValueError):
    _PERSISTED_LIMIT = 50
_SERVICE_PASSWORD_KEY = "free_classroom_pwd"
_SERVICE_PASSWORD_PREFIX = "enc:v1:"
_SERVICE_PASSWORD_AAD = "freeclass-service-account"


def _service_credentials():
    """服务账号凭据(学号, 密码)。

    密码存在 settings 表 `free_classroom_pwd`, 由管理面板录入 —— 仓库里不留明文,
    云端也无需环境变量。学号默认取 config, 可用 `free_classroom_sid` 覆盖。
    """
    sid = (dao.get_setting("free_classroom_sid", "")
           or config.FREE_CLASSROOM_SID).strip()
    pwd = _read_service_password()
    return sid, pwd


def _encrypt_service_password(password: str) -> str:
    """共享服务账号密码使用与用户凭据相同的 AES-GCM 加密域。"""
    from wxcloudrun.core import cookie_crypto
    if not cookie_crypto.enabled():
        raise RuntimeError("未配置 SESSION_KEY，拒绝保存服务账号密码")
    blob = cookie_crypto.encrypt(
        _SERVICE_PASSWORD_AAD, {"pwd": str(password or "")})
    return _SERVICE_PASSWORD_PREFIX + blob


def _decrypt_service_password(value: str) -> str:
    value = str(value or "")
    if not value:
        return ""
    if not value.startswith(_SERVICE_PASSWORD_PREFIX):
        return value
    try:
        from wxcloudrun.core import cookie_crypto
        data = cookie_crypto.decrypt(
            _SERVICE_PASSWORD_AAD,
            value[len(_SERVICE_PASSWORD_PREFIX):])
        return str((data or {}).get("pwd") or "")
    except Exception:
        return ""


def set_service_password(password: str) -> bool:
    """加密保存服务账号密码；加密不可用时失败关闭。"""
    if not str(password or "").strip():
        return False
    dao.set_setting(_SERVICE_PASSWORD_KEY, _encrypt_service_password(password))
    return True


def _read_service_password() -> str:
    stored = dao.get_setting(_SERVICE_PASSWORD_KEY, "")
    if stored:
        pwd = _decrypt_service_password(stored)
        # 旧版明文记录首次读取时自动升级；升级失败不阻断读取。
        if pwd and not stored.startswith(_SERVICE_PASSWORD_PREFIX):
            try:
                set_service_password(pwd)
            except Exception:
                pass
        return pwd
    return str(config.FREE_CLASSROOM_PWD or "").strip()


def _reset_service_client():
    """凭据变更后丢弃旧会话, 下次查询用新账号重新登录。"""
    global _classroom_service_client
    with _classroom_service_lock:
        _classroom_service_client = JWCClient()


def _service_client_provider():
    """服务账号兜底: 返回 (client, sid, error)。"""
    sid, pwd = _service_credentials()
    if not sid:
        return None, "", "未配置空教室服务账号"
    if not pwd:
        return None, "", "未配置空教室服务账号密码(请在管理面板「系统」中设置)"
    with _classroom_service_lock:
        if not _classroom_service_client.logged_in:
            ok = _classroom_service_client.login_webvpn(sid, pwd, allow_resume=True)
            if not ok:
                return None, "", (_classroom_service_client.last_error
                                  or "服务账号登录失败")
    return _classroom_service_client, sid, ""


class _ClassroomQuery(JWCClientPool):
    """空教室查询适配器: 共享候选池 + 教室借用查询。"""

    def __init__(self):
        super().__init__(
            service_provider=_service_client_provider,
            source=_COOKIE_SOURCE,
            retries=_CANDIDATE_RETRIES,
            limit=_PERSISTED_LIMIT)

    def query(self, campus, weekday, jc1, jc2, week, semester, building):
        last_error = "空教室查询失败"
        for _attempt in range(_CANDIDATE_RETRIES * 3 + 2):
            client, source, sid, err = self.next_client()
            if client is None:
                return None, err or last_error
            try:
                with _jwc_request(client):
                    res = client.get_free_classrooms(
                        campus=campus, weekday=weekday, jc1=jc1, jc2=jc2,
                        week=week, semester=semester, building=building)
            except Exception as exc:  # noqa: BLE001
                last_error = f"{type(exc).__name__}: {exc}"
                self.client = None
                continue
            if isinstance(res, dict):
                app.logger.info("[freeclass] source=%s sid=%s query ok",
                                source, (sid or "-")[:3] + "****")
                return res, None
            last_error = client.last_error or "查询失败"
            if "登录" in last_error or "logon" in last_error.lower():
                client.logged_in = False
            self.client = None
        return None, last_error


def _service_free_classrooms(campus, weekday, jc1, jc2, week, semester, building,
                             query=None):
    """按候选池查询空闲教室; 返回 (result_dict, None) 或 (None, error)。"""
    return (query or _ClassroomQuery()).query(
        campus, weekday, jc1, jc2, week, semester, building)


def _freeclass_cache_key(campus, weekday, jc1, jc2, week, semester, building="") -> str:
    return (f"g_freeclass:{campus}:{weekday}:{jc1}:{jc2}:"
            f"{week}:{semester}:{building}")


def _freeclass_resp(campus, weekday, jc1, jc2, week, semester, result, updated_at=None) -> dict:
    """统一构建接口响应(含服务端更新时间, 供前端展示"更新于 xx:xx")

    兼容性: 保留 slot_name(旧版前端单时段选择器版本渲染摘要用, 与 time_text 同值);
    新增字段仅追加, 不删旧字段, 保证旧版小程序可用。
    """
    rooms = (result or {}).get("rooms") or []
    time_text = f"第{jc1}-{jc2}节"
    return {
        "success": True,
        "campus": campus, "weekday": weekday, "week": week,
        "semester": semester,
        "jc1": jc1, "jc2": jc2,
        "slot": "",                       # 旧版字段占位(单大节键, 范围查询下无法单值表达)
        "slot_name": time_text,           # 旧版兼容
        "time_text": time_text,
        "weekday_name": WEEKDAY_NAMES[weekday] if 1 <= weekday <= 7 else "",
        "building": (result or {}).get("building_name", ""),
        "buildings": (result or {}).get("buildings", []),
        "count": len(rooms), "rooms": rooms,
        "updated_at": int(updated_at or time.time()),
    }


# ============================================================
# 空教室定时预热 — 启动补齐当天, 之后每天 00:00 刷新
# 每天零点用共享本科 Cookie 池刷新当天两校区全部大节数据,
# 用户查询当天只读全局缓存, 避免请求时访问教务。
# 开关: 环境变量 FREE_CLASSROOM_PREWARM=1(容器 envParams 已默认开启)
# ============================================================
# (本地时钟 HH:MM → 官方大节): 两校区上下课时刻(各校以教务为准,
# 此处取大节开始点); 支持环境变量 FREE_CLASSROOM_PREWARM_TIMES 覆盖,
# 如 "08:00,10:10,14:00,16:10,19:00"(依次对应 5 个官方大节)
def _build_refresh_plan():
    raw = os.environ.get("FREE_CLASSROOM_PREWARM_TIMES", "")
    times = [t.strip() for t in raw.replace("，", ",").split(",") if t.strip()]
    default = [
        ("08:00", "1-3"),     # 第一大节 上课
        ("10:10", "4-5"),     # 第二大节 上课
        ("14:00", "6-7"),     # 第三大节 上课
        ("16:10", "8-10"),    # 第四大节 上课
        ("19:00", "11-13"),   # 第五大节 上课
    ]
    if not times:
        return default
    slot_keys = [s[0] for s in CLASSROOM_SLOTS]
    plan = []
    for i, hm in enumerate(times):
        try:
            parts = hm.split(":")
            if not (0 <= int(parts[0]) <= 23 and 0 <= int(parts[1]) <= 59):
                raise ValueError
        except (ValueError, IndexError):
            app.logger.warning("[freeclass] 忽略无效预热时间 %r", hm)
            continue
        plan.append((hm, slot_keys[min(i, len(slot_keys) - 1)]))
    return plan or default


FREE_CLASSROOM_REFRESH_PLAN = _build_refresh_plan()
FREE_CLASSROOM_SLOT_JC = {s[0]: (s[2], s[3]) for s in CLASSROOM_SLOTS}


def freeclass_refresh_plan(now=None):
    """当天刷新计划: [(时间, 大节key)...] 按时间升序(便于离线测试)"""
    if now is None:
        from datetime import datetime as _dt
        now = _dt.now()
    from datetime import datetime as _dt, time as _time
    return [(_time(*map(int, hm.split(":"))), slot)
            for hm, slot in FREE_CLASSROOM_REFRESH_PLAN]


def _next_freeclass_refresh(now=None):
    """下一个刷新时刻: (datetime, 大节key); 今日已过则取明天第一个"""
    from datetime import datetime as _dt, timedelta
    if now is None:
        now = _dt.now()
    for t, slot in freeclass_refresh_plan(now):
        when = _dt.combine(now.date(), t)
        if when >= now:
            return when, slot
    t0 = freeclass_refresh_plan(now)[0][0]
    return _dt.combine(now.date(), t0) + timedelta(days=1), freeclass_refresh_plan(now)[0][1]


def _current_slot_key(now=None) -> str:
    """当前所处的大节 key(按本地时间取 plan 中最后一个已到时刻)。

    用于容器启动时补齐缓存: 09:30 启动 → 当前大节是 08:00 对应的 "1-3";
    早于当天第一个上课时刻(如 07:30)则取第一个大节, 补的是即将开始的那一节。
    """
    from datetime import datetime as _dt
    now = now or _dt.now()
    cur = FREE_CLASSROOM_REFRESH_PLAN[0][1]
    for hm, slot in FREE_CLASSROOM_REFRESH_PLAN:
        try:
            h, m = (int(x) for x in hm.split(":"))
        except (ValueError, TypeError):
            continue
        if (h, m) <= (now.hour, now.minute):
            cur = slot
        else:
            break
    return cur


def _freeclass_ttl(now=None) -> float:
    """空教室缓存有效期: 到下一个自然日 00:00 + 120s 缓冲。

    数据由后端每天 00:00 全量更新, 当天请求只读缓存。
    """
    from datetime import datetime as _dt
    from datetime import timedelta as _td
    now = now or _dt.now()
    nxt = _dt.combine(now.date(), _dt.min.time()) + _td(days=1)
    return max(120.0, (nxt - now).total_seconds() + 120.0)


def _prewarm_targets(fwd: str, today=None):
    """预热目标: [(日期, 星期, 周次)...] —— 默认只预热今天, 明天查询时按需缓存。"""
    from datetime import timedelta as _td
    base = today or _beijing_date()
    out = []
    for offset in range(FREE_CLASSROOM_PREWARM_DAYS):
        day = base + _td(days=offset)
        out.append((day, day.isoweekday(), _current_teaching_week(fwd, on=day)))
    return out


def _prewarm_free_classrooms(slots=None):
    """预热指定大节在指定日期的缓存; 返回成功条数。

    默认只预热今天, 明天首次查询时按需抓取并缓存, 避免后台每天重复访问教务。
    需在 app 上下文中调用(内部读 first_week_date 等设置)。
    """
    semester = _current_semester()
    fwd = dao.get_setting("first_week_date", "")
    slot_keys = slots or [s[0] for s in CLASSROOM_SLOTS]
    ok_n = 0
    classroom_query = _ClassroomQuery()
    for _day, weekday, week in _prewarm_targets(fwd):
        for campus in FREE_CLASSROOM_CAMPUSES:
            for slot in slot_keys:
                jc1, jc2 = FREE_CLASSROOM_SLOT_JC.get(slot, (6, 7))
                result, err = _service_free_classrooms(
                    campus, weekday, jc1, jc2, week, semester, "",
                    query=classroom_query)
                if result is None:
                    app.logger.warning("[freeclass][prewarm] %s 星期%s %s 预热失败: %s",
                                       campus, weekday, slot, err)
                    continue
                resp = _freeclass_resp(campus, weekday, jc1, jc2, week,
                                       semester, result)
                cache_key = _freeclass_cache_key(campus, weekday, jc1, jc2,
                                                 week, semester)
                _cache_set(cache_key, resp, ttl=_freeclass_ttl())
                ok_n += 1
                app.logger.info("[freeclass][prewarm] %s 周%s 星期%s %s 空闲 %d 间",
                                campus, week, weekday, slot, resp["count"])
    return ok_n


def _prewarm_loop():
    """后台守护线程: 启动补齐当天全部大节, 之后每天 00:00 全量更新。"""
    from datetime import datetime as _dt
    from datetime import timedelta as _td

    try:
        from wxcloudrun import app as _app
        with _app.app_context():
            from wxcloudrun.core.state import distributed_lock
            with distributed_lock(
                    "wx:lock:freeclass-prewarm", ttl=900) as acquired:
                if acquired:
                    app.logger.info("[freeclass][prewarm] 启动补当天全量缓存")
                    _prewarm_free_classrooms()
                else:
                    app.logger.info("[freeclass][prewarm] 已有实例负责启动预热")
    except Exception as e:  # noqa: BLE001 补缓存失败不影响定时循环
        app.logger.warning("[freeclass][prewarm] 启动补缓存失败: %s", e)
    while True:
        try:
            now = _dt.now()
            nxt = _dt.combine(now.date(), _dt.min.time()) + _td(days=1)
            wait = max(10, (nxt - now).total_seconds())
            time.sleep(wait)
            from wxcloudrun import app as _app
            with _app.app_context():
                from wxcloudrun.core.state import distributed_lock
                with distributed_lock(
                        "wx:lock:freeclass-prewarm", ttl=900) as acquired:
                    if acquired:
                        _prewarm_free_classrooms()
        except Exception as e:
            app.logger.warning("[freeclass][prewarm] 线程异常: %s", e)
            time.sleep(300)


def _start_freeclass_prewarm():
    """启动预热线程: 默认开启(空教室数据由后端负责更新)。

    关闭方式: 环境变量 FREE_CLASSROOM_PREWARM=0(本地联调时可临时关掉)。
    """
    global _prewarm_thread
    if os.environ.get("FREE_CLASSROOM_PREWARM", "1").strip() == "0":
        app.logger.info("[freeclass] 定时预热已关闭(FREE_CLASSROOM_PREWARM=0)")
        return False
    try:
        with _prewarm_start_lock:
            if _prewarm_thread is not None and _prewarm_thread.is_alive():
                return False
            _prewarm_thread = threading.Thread(
                target=_prewarm_loop, daemon=True, name="freeclass-prewarm")
            _prewarm_thread.start()
        app.logger.info("[freeclass] 定时预热已启用(启动补当天 + 每日 00:00 全量刷新)")
        return True
    except Exception as e:
        app.logger.warning("[freeclass] 预热线程启动失败: %s", e)
        return False


@freeclass_bp.route('/api/free-classrooms')
def api_free_classrooms():
    """空教室查询: campus(孝陵卫/江阴) + weekday(1-7)
    + 节次范围(jc1/jc2, 1-13; 兼容旧版 slot=1-3/4-5/6-7/8-10/11-13)
    + week(周次) + building(教学楼名称, 可选)

    服务端用共享服务账号查询教务「教室借用」页(教室状态=空闲), 只保留
    有楼名映射的教室; 结果缓存到下一个自然日 00:00(启动补齐当天,
    每天零点全量刷新两校区), 防止频繁查询打爆教务。
    """
    client, err = _require_login()
    if err:
        return err
    sid = client.student_id or ""
    campus = (request.args.get("campus") or "孝陵卫").strip()
    if campus not in FREE_CLASSROOM_CAMPUSES:
        campus = "孝陵卫"
    try:
        weekday = int(request.args.get("weekday") or "0")
    except ValueError:
        weekday = 0
    if weekday < 1 or weekday > 7:
        weekday = 0
    # 节次范围: jc1/jc2 优先; 旧版 slot(大节)映射兜底; 默认 第6-7节
    try:
        jc1 = int(request.args.get("jc1") or "0")
    except ValueError:
        jc1 = 0
    try:
        jc2 = int(request.args.get("jc2") or "0")
    except ValueError:
        jc2 = 0
    if jc1 < JC_MIN or jc2 < JC_MIN or jc1 > jc2:
        slot = (request.args.get("slot") or "6-7").strip()
        mapped = FREE_CLASSROOM_SLOTS.get(slot, (6, 7))
        jc1, jc2 = mapped
    jc1 = max(JC_MIN, min(jc1, JC_MAX))
    jc2 = max(JC_MIN, min(jc2, JC_MAX))
    if jc1 > jc2:
        jc1, jc2 = 6, 7
    try:
        week = int(request.args.get("week") or "0")
    except ValueError:
        week = 0
    building = (request.args.get("building") or "").strip()[:50]
    semester = (request.args.get("semester") or "").strip() or \
        dao.get_user_setting(sid, "semester") or _current_semester()
    if weekday == 0:
        weekday = _beijing_date().isoweekday()   # 默认今天(周一=1); 按北京时间取, 避免容器 UTC 偏差
    if week < 1:
        # 当前教学周: 学期设置优先, 回退全局(与设置页口径一致)
        fwd = dao.get_user_setting(sid, f"first_week_date:{semester}", "") \
            or dao.get_setting("first_week_date", "")
        week = _current_teaching_week(fwd)

    cache_key = _freeclass_cache_key(campus, weekday, jc1, jc2, week, semester, building)
    cached = _cache_get(cache_key)
    if cached is not None:
        return jsonify(cached)

    # ── 共享服务账号抓取(数据全校一致; 单实例锁串行 + 失效自动重登) ──
    result, svc_err = _service_free_classrooms(
        campus, weekday, jc1, jc2, week, semester, building)
    if result is None:
        if "解析失败" in (svc_err or ""):
            # 结构性失败(教务页面变化/返回异常页): 换会话重试结果一样,
            # 直接返回错误 —— 绝不能退化成 success + 0 间("该时段没有空闲教室")
            # 对外固定文案, 解析细节只写日志(不暴露页面结构信息)
            app.logger.warning("[freeclass] rid=%s 解析失败, 直接返回错误: %s",
                               _rid(), svc_err)
            return jsonify({"success": False,
                            "message": "教室数据暂时获取失败，请稍后重试"}), 502
        # 服务账号不可用 → 回退到当前用户自己的教务会话(兼容兜底)
        # 研究生账号(YJSClient)没有教务会话, 无法回退: 直接返回服务端错误
        if not hasattr(client, "get_free_classrooms"):
            app.logger.warning(
                "[freeclass] rid=%s 服务账号不可用(%s)且当前为研究生会话, 无法回退",
                _rid(), svc_err)
            return jsonify({"success": False,
                            "message": "教室数据暂时获取失败，请稍后重试"}), 502
        app.logger.warning("[freeclass] rid=%s 服务账号失败(%s), 回退用户会话 sid=%s",
                           _rid(), svc_err, sid)
        with _jwc_request(client):
            result, retry_err = _retry_with_relogin(
                client,
                lambda: client.get_free_classrooms(campus=campus, weekday=weekday,
                                                    jc1=jc1, jc2=jc2, week=week,
                                                    semester=semester,
                                                    building=building),
                "查询空闲教室失败")
        if retry_err:
            if "教学楼不存在" in (client.last_error or ""):
                return jsonify({"success": False,
                                "message": client.last_error}), 400
            if "解析失败" in (client.last_error or ""):
                # 用户会话兜底路径同样返回固定文案(细节只进日志)
                app.logger.warning("[freeclass] rid=%s 兜底会话解析失败: %s",
                                   _rid(), client.last_error)
                return jsonify({"success": False,
                                "message": "教室数据暂时获取失败，请稍后重试"}), 502
            return retry_err
        result = result if isinstance(result, dict) else {}
    now = int(time.time())
    resp = _freeclass_resp(campus, weekday, jc1, jc2, week, semester,
                           result, updated_at=now)
    # 全局数据: 缓存到下一个大节刷新时刻(所有用户共享, 教务请求大幅降低;
    # 另有定时预热在上下课时刻刷新今天+明天的缓存)
    _cache_set(cache_key, resp, ttl=_freeclass_ttl())
    app.logger.info("[freeclass] rid=%s sid=%s %s%s 周%s 星期%s 第%d-%d节 空闲 %d 间",
                    _rid(), sid, campus,
                    f"/{resp['building']}" if resp["building"] else "",
                    week, weekday, jc1, jc2, resp["count"])
    return jsonify(resp)
