# -*- coding: utf-8 -*-
"""订阅消息额度与 openid 存储(复用 settings 表, 无需新表)。

- 微信一次性订阅规则: 用户授权一次 = 可发送 1 条; 额度用完需再次授权;
- 额度: `{sid}:subscribe` = {"exam": {"count": n, "updated_at": ts}, ...}（当前仅考试提醒）
- openid: `{sid}:openid`(云托管网关会透传 x-wx-openid, 无需 code2session)。
"""
import json
import threading
import time

KINDS = ("exam",)          # 目前只做考试提醒; 新增类型时在此登记
KEY = "subscribe"
OPENID_KEY = "openid"
_STORE_LOCK = threading.RLock()


def _dao():
    from wxcloudrun import dao          # 延迟导入, 避免包初始化循环
    return dao


def _load(sid: str) -> dict:
    raw = _dao().get_user_setting(sid, KEY, "")
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _save(sid: str, data: dict) -> None:
    _dao().set_user_setting(sid, KEY, json.dumps(data, ensure_ascii=False))


def save_openid(sid: str, openid: str) -> None:
    if sid and openid:
        _dao().set_user_setting(sid, OPENID_KEY, str(openid))


def get_openid(sid: str) -> str:
    return _dao().get_user_setting(sid, OPENID_KEY, "") or ""


def caller_openid() -> str:
    """取云托管透传的调用者 openid(本地/非小程序调用时为空)。"""
    try:
        from flask import request
    except Exception:  # noqa: BLE001
        return ""
    for name in ("X-WX-OPENID", "X-Wx-OpenId", "x-wx-openid"):
        val = (request.headers.get(name) or "").strip()
        if val:
            return val
    return ""


def grant(sid: str, kind: str, count: int = 1, openid: str = "") -> dict:
    """记录一次(或多次)授权额度; 返回该类型的当前额度。"""
    if kind not in KINDS or not sid:
        return {}
    with _STORE_LOCK:
        if openid:
            save_openid(sid, openid)
        data = _load(sid)
        item = data.get(kind) or {}
        # 微信一次性订阅的授权事件一次只能增加 1 条额度。
        item["count"] = int(item.get("count") or 0) + 1
        item["updated_at"] = int(time.time())
        data[kind] = item
        _save(sid, data)
        return item


def quota(sid: str, kind: str) -> int:
    item = _load(sid).get(kind) or {}
    return int(item.get("count") or 0)


def consume(sid: str, kind: str) -> bool:
    """扣减一次额度; 有额度返回 True, 无则 False。"""
    if kind not in KINDS or not sid:
        return False
    with _STORE_LOCK:
        data = _load(sid)
        item = data.get(kind) or {}
        count = int(item.get("count") or 0)
        if count <= 0:
            return False
        item["count"] = count - 1
        item["used_at"] = int(time.time())
        data[kind] = item
        _save(sid, data)
        return True


def status(sid: str) -> dict:
    """各类型剩余额度(没有记录的类型返回 0)。"""
    data = _load(sid)
    out = {}
    for kind in KINDS:
        out[kind] = int((data.get(kind) or {}).get("count") or 0)
    return out
