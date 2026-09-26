# -*- coding: utf-8 -*-
"""空教室查询路由与预热(Phase 1b 从 views.py 拆出)。

数据源: 教务「教室借用查询」→ 状态=空闲教室清单;
缓存: 进程内全局缓存, TTL 到下一个大节上课时刻,
预热线程在各大节刷新今天+明天。
"""
import os
import threading
import time

from flask import Blueprint, jsonify, request

import config
from wxcloudrun import app, dao
from wxcloudrun.core.auth import _require_login, _retry_with_relogin
from wxcloudrun.core.cache import _cache_get, _cache_set
from wxcloudrun.core.pool import _jwc_request
from wxcloudrun.core.timeutil import _beijing_date
from wxcloudrun.core.web import _rid
from wxcloudrun.jwc_client import JWCClient, CLASSROOM_SLOTS

freeclass_bp = Blueprint("freeclass_api", __name__)


def _current_semester() -> str:
    """当前学期(views 实现, 延迟导入避免循环)"""
    from wxcloudrun.views import _current_semester as _impl
    return _impl()


# ============================================================
# API — 空教室查询(需登录; 数据来自教务"全校性教室课表"空闲格解析)
# ============================================================
FREE_CLASSROOM_CAMPUSES = ("孝陵卫", "江阴")
# 官方大节(key, 名称, 起节, 止节): 兼容旧版 slot 参数
FREE_CLASSROOM_SLOTS = {s[0]: (s[2], s[3]) for s in CLASSROOM_SLOTS}
WEEKDAY_NAMES = ("", "星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日")
JC_MIN, JC_MAX = 1, 13   # 一天最多 13 节(官方大节 1-3/4-5/6-7/8-10/11-13)


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


def _service_credentials():
    """服务账号凭据(学号, 密码)。

    密码存在 settings 表 `free_classroom_pwd`, 由管理面板录入 —— 仓库里不留明文,
    云端也无需环境变量。学号默认取 config, 可用 `free_classroom_sid` 覆盖。
    """
    sid = (dao.get_setting("free_classroom_sid", "")
           or config.FREE_CLASSROOM_SID).strip()
    pwd = (dao.get_setting("free_classroom_pwd", "")
           or config.FREE_CLASSROOM_PWD).strip()
    return sid, pwd


def _reset_service_client():
    """凭据变更后丢弃旧会话, 下次查询用新账号重新登录。"""
    global _classroom_service_client
    with _classroom_service_lock:
        _classroom_service_client = JWCClient()


def _service_free_classrooms(campus, weekday, jc1, jc2, week, semester, building):
    """服务账号统一查询空闲教室。

    返回 (result_dict, None) 成功 / (None, 错误信息) 失败。
    """
    sid, pwd = _service_credentials()
    if not sid:
        return None, "未配置空教室服务账号"
    if not pwd:
        return None, "未配置空教室服务账号密码(请在管理面板「系统」中设置)"
    with _classroom_service_lock:
        for _attempt in range(2):
            if not _classroom_service_client.logged_in:
                # 教务直连已下线: 服务账号改走智慧理工 SSO(含持久化会话复用)
                ok = _classroom_service_client.login_webvpn(sid, pwd)
                if not ok:
                    return None, _classroom_service_client.last_error or "服务账号登录失败"
            res = _classroom_service_client.get_free_classrooms(
                campus=campus, weekday=weekday, jc1=jc1, jc2=jc2,
                week=week, semester=semester, building=building)
            if isinstance(res, dict):
                return res, None
            err = _classroom_service_client.last_error or "查询失败"
            if "登录" in err or "logon" in err.lower():
                # 会话过期: 标记并重登重试一次
                _classroom_service_client.logged_in = False
                continue
            return None, err
        return None, "服务账号会话异常"


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
# 空教室定时预热 — 按每天"上下课"时刻刷新当天缓存
# 每天在各大节上课时刻用服务账号刷新一次当天数据(教室占用基本按周次固定,
# 但临时调停课会变化; 上下课边界刷新保证"当前时段"数据新), 用户查询
# 基本全部命中 120s 全局缓存, 教务请求降到每天十几次。
# 开关: 环境变量 FREE_CLASSROOM_PREWARM=1(容器 envParams 已默认开启)
# ============================================================
# (本地时钟 HH:MM → 官方大节): 南京理工两校区上下课时刻(各校以教务为准,
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
    """空教室缓存有效期: 到下一个大节上课时刻 + 120s 缓冲。

    数据由后端预热线程在每天各大节上课时刻统一更新(今天+明天),
    用户请求命中缓存即可; 未命中(冷启动/周末等)按需抓取后同样缓存到
    下一个刷新时刻, 取代原先的 120s 短 TTL。
    """
    from datetime import datetime as _dt
    now = now or _dt.now()
    nxt, _slot = _next_freeclass_refresh(now)
    return max(120.0, (nxt - now).total_seconds() + 120.0)


def _prewarm_targets(fwd: str, today=None):
    """预热目标: [(日期, 星期, 周次)...] —— 今天 + 明天, 周次各自按**所属周**计算。

    明天可能跨周(周日→周一): 若沿用"本周"周次, 预热出的缓存键与用户端算出的
    周次不一致, 周一早上就命中不了缓存。
    """
    from datetime import timedelta as _td
    base = today or _beijing_date()
    out = []
    for offset in (0, 1):
        day = base + _td(days=offset)
        out.append((day, day.isoweekday(), _current_teaching_week(fwd, on=day)))
    return out


def _prewarm_free_classrooms(slots=None):
    """预热指定大节(默认全部)在"今天/明天 + 各自周次"的缓存; 返回成功条数。

    同时预热明天: 晚上/周日"查明天教室"是高频场景, 命中率翻倍。
    需在 app 上下文中调用(内部读 first_week_date 等设置)。
    """
    semester = _current_semester()
    fwd = dao.get_setting("first_week_date", "")
    slot_keys = slots or [s[0] for s in CLASSROOM_SLOTS]
    ok_n = 0
    for _day, weekday, week in _prewarm_targets(fwd):
        for campus in FREE_CLASSROOM_CAMPUSES:
            for slot in slot_keys:
                jc1, jc2 = FREE_CLASSROOM_SLOT_JC.get(slot, (6, 7))
                result, err = _service_free_classrooms(
                    campus, weekday, jc1, jc2, week, semester, "")
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
    """后台守护线程: 启动先补当前大节, 之后每到上课时刻预热对应大节"""
    # 容器重启后缓存为空: 由后端立即补齐"当前大节", 而不是等用户请求触发抓取
    try:
        from wxcloudrun import app as _app
        slot = _current_slot_key()
        with _app.app_context():
            app.logger.info("[freeclass][prewarm] 启动补缓存: 当前大节 %s", slot)
            _prewarm_free_classrooms([slot])
    except Exception as e:  # noqa: BLE001 补缓存失败不影响定时循环
        app.logger.warning("[freeclass][prewarm] 启动补缓存失败: %s", e)
    while True:
        try:
            from datetime import datetime as _dt
            nxt, slot = _next_freeclass_refresh(_dt.now())
            wait = max(10, (nxt - _dt.now()).total_seconds())
            time.sleep(wait)
            from wxcloudrun import app as _app
            with _app.app_context():
                _prewarm_free_classrooms([slot])
        except Exception as e:
            app.logger.warning("[freeclass][prewarm] 线程异常: %s", e)
            time.sleep(300)


def _start_freeclass_prewarm():
    """启动预热线程: 默认开启(空教室数据由后端负责更新)。

    关闭方式: 环境变量 FREE_CLASSROOM_PREWARM=0(本地联调时可临时关掉)。
    """
    if os.environ.get("FREE_CLASSROOM_PREWARM", "1").strip() == "0":
        app.logger.info("[freeclass] 定时预热已关闭(FREE_CLASSROOM_PREWARM=0)")
        return
    try:
        threading.Thread(target=_prewarm_loop, daemon=True,
                         name="freeclass-prewarm").start()
        app.logger.info("[freeclass] 定时预热已启用(启动补当前大节 + 各大节上课时刻刷新)")
    except Exception as e:
        app.logger.warning("[freeclass] 预热线程启动失败: %s", e)


@freeclass_bp.route('/api/free-classrooms')
def api_free_classrooms():
    """空教室查询: campus(孝陵卫/江阴) + weekday(1-7)
    + 节次范围(jc1/jc2, 1-13; 兼容旧版 slot=1-3/4-5/6-7/8-10/11-13)
    + week(周次) + building(教学楼名称, 可选)

    服务端用共享服务账号查询教务「教室借用」页(教室状态=空闲), 只保留
    有楼名映射的教室; 结果缓存到下一个大节刷新时刻(预热线程在每天各大节
    上课时统一更新今天+明天), 防止频繁查询打爆教务。
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
        fwd = dao.get_setting(f"{sid}:first_week_date:{semester}", "") \
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
