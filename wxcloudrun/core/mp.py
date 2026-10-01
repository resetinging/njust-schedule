# -*- coding: utf-8 -*-
"""微信小程序服务端能力: access_token 缓存 + 订阅消息发送。

配置(云托管环境变量, 见 config.py): MP_APPID / MP_SECRET / SUBSCRIBE_TPL_*。
未配置 MP_SECRET 时 enabled() 为 False, 所有发送静默跳过(不影响其它功能)。
"""
import os
import threading
import time

import requests

import config

API_BASE = "https://api.weixin.qq.com"
_TOKEN_LOCK = threading.Lock()
_TOKEN = {"value": "", "expires_at": 0.0}


def appid() -> str:
    return (os.environ.get("MP_APPID") or getattr(config, "MP_APPID", "") or "").strip()


def secret() -> str:
    return (os.environ.get("MP_SECRET") or getattr(config, "MP_SECRET", "") or "").strip()


def enabled() -> bool:
    """是否具备发送能力(需 AppID + AppSecret)。"""
    return bool(appid() and secret())


# 当前只启用考试提醒; 追加新类型时在此登记模板环境变量名
_TPL_ENV = {"exam": "SUBSCRIBE_TPL_EXAM"}


def template_id(kind: str) -> str:
    key = _TPL_ENV.get(kind)
    if not key:
        return ""
    return (os.environ.get(key) or getattr(config, key, "") or "").strip()


def access_token(force: bool = False) -> str:
    """带缓存的 access_token; 失败返回空串(调用方自行降级)。"""
    if not enabled():
        return ""
    now = time.time()
    with _TOKEN_LOCK:
        if not force and _TOKEN["value"] and _TOKEN["expires_at"] > now + 60:
            return _TOKEN["value"]
        try:
            resp = requests.get(f"{API_BASE}/cgi-bin/token", timeout=10, params={
                "grant_type": "client_credential", "appid": appid(), "secret": secret()})
            data = resp.json() or {}
        except Exception:  # noqa: BLE001
            return ""
        tok = (data.get("access_token") or "").strip()
        if not tok:
            return ""
        _TOKEN["value"] = tok
        _TOKEN["expires_at"] = now + int(data.get("expires_in") or 7200) - 300
        return tok


def send_subscribe(openid: str, template_id: str, data: dict,
                   page: str = "pages/main/main") -> dict:
    """发送一条订阅消息。返回 {ok, errcode, errmsg}。"""
    if not (openid and template_id and data):
        return {"ok": False, "errcode": -1, "errmsg": "参数不完整"}
    tok = access_token()
    if not tok:
        return {"ok": False, "errcode": -1, "errmsg": "access_token 不可用(检查 MP_SECRET)"}
    body = {"touser": openid, "template_id": template_id, "page": page,
            "miniprogram_state": os.environ.get("MP_STATE", "formal"), "data": data}
    try:
        resp = requests.post(f"{API_BASE}/cgi-bin/message/subscribe/send",
                             params={"access_token": tok}, json=body, timeout=10)
        out = resp.json() or {}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "errcode": -1, "errmsg": f"请求异常: {e}"}
    return {"ok": int(out.get("errcode") or 0) == 0,
            "errcode": out.get("errcode"), "errmsg": out.get("errmsg", "")}


def template_content(template_id: str) -> list:
    """取模板字段定义 [{'key':'thing1','name':'考试名称'}, ...]; 取不到返回 []。"""
    tok = access_token()
    if not (tok and template_id):
        return []
    try:
        resp = requests.get(f"{API_BASE}/wxaapi/newtmpl/gettemplate",
                            params={"access_token": tok}, timeout=10)
        items = (resp.json() or {}).get("data") or []
    except Exception:  # noqa: BLE001
        return []
    for it in items:
        if isinstance(it, dict) and it.get("priTmplId") == template_id:
            return [{"key": c.get("key"), "name": c.get("name") or ""}
                    for c in (it.get("content") or [])
                    if isinstance(c, dict) and c.get("key")]
    return []


def template_fields(template_id: str) -> list:
    """取模板字段 key 列表(如 ['thing1','time2','thing3']); 取不到返回 []。"""
    return [c["key"] for c in template_content(template_id)]
