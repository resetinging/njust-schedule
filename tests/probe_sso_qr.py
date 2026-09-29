# -*- coding: utf-8 -*-
"""智慧理工 SSO「微信扫码登录」探针。

验证目标: 后端能否代跑整条扫码登录链路(用户只需用微信扫一次码),
          确认后由后端换到 CASTGC 并进一步建立教务会话。

链路(来自登录页 qrcode.js):
    GET  登录页(带 service)                     → JSESSIONID + uuid/lt/execution
    POST /authserver/qrCode/getToken            → token
    GET  /authserver/qrCode/getCode?uuid=token  → 二维码图片
    POST /authserver/qrCode/getStatus.htl       → 1=已确认 2=已扫描 3=失效
    1 时 POST /authserver/login?display=qrLogin&service=…
            (uuid/lt/cllt=qrLogin/dllt=generalLogin/execution/_eventId=submit)
         → CASTGC → GET bkjw…/njlgdx/indexsso.jsp → 教务会话

用法:
    # 1) 生成二维码(图片落盘), 会话状态存 json, 供下一步复用
    python tests/probe_sso_qr.py start
    # 2) 用微信扫码并在手机上确认, 然后:
    python tests/probe_sso_qr.py poll [等待秒数, 默认 240]
    # 3) 只验证已保存会话是否有效
    python tests/probe_sso_qr.py check
"""

import json
import os
import re
import sys
import time

import requests
from bs4 import BeautifulSoup
from urllib.parse import parse_qs, quote, urlparse

_here = os.path.dirname(os.path.abspath(__file__))
_root = os.path.dirname(_here)
sys.path.insert(0, _root)

from config import SSO_BASE, SSO_LOGIN_URL  # noqa: E402

STATE = os.path.join(_here, "_sso_qr.json")
IMG = os.path.join(_here, "_sso_qr.png")
TIMEOUT = 20
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/153.0.0.0 Safari/537.36 Edg/153.0.0.0")


def _session() -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": UA,
                      "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8"})
    return s


def _dump_cookies(session):
    return [{"name": c.name, "value": c.value,
             "domain": c.domain, "path": c.path or "/"}
            for c in session.cookies]


def _load_cookies(session, cookies):
    for c in cookies:
        session.cookies.set(c["name"], c["value"],
                            domain=c.get("domain"), path=c.get("path") or "/")


def _save_state(session, **kw):
    data = {"cookies": _dump_cookies(session), "ts": int(time.time())}
    data.update(kw)
    with open(STATE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return data


def _load_state():
    with open(STATE, encoding="utf-8") as f:
        return json.load(f)


def cmd_start() -> int:
    session = _session()
    resp = session.get(SSO_LOGIN_URL, timeout=TIMEOUT, allow_redirects=True)
    print(f"[qr] 登录页 {resp.status_code} 长度={len(resp.text)}")
    if "authserver/login" not in resp.url:
        print("[qr] 未落在登录页(可能已有 TGT), 直接用现有会话验证")
        return cmd_check()

    soup = BeautifulSoup(resp.text, "lxml")
    form = soup.find("form", id="qrLoginForm") or soup.find("form", id="pwdFromId")
    def val(name):
        el = soup.find("input", attrs={"name": name}) if soup else None
        return (el.get("value") or "").strip() if el else ""
    lt, execution = val("lt"), val("execution")
    print(f"[qr] 表单字段 lt={lt!r} execution={execution!r}")

    # Step 1: 申请 token(uuid 初始为空, 由服务端下发)
    tok_resp = session.post(f"{SSO_BASE}/authserver/qrCode/getToken",
                            data={"uuid": ""}, timeout=TIMEOUT,
                            headers={"Referer": resp.url})
    token = (tok_resp.text or "").strip()
    print(f"[qr] getToken -> {tok_resp.status_code} token={token[:24]}…")
    if not token:
        print("[qr] 未取到 token, 终止")
        return 1

    # Step 2: 取二维码图片
    img = session.get(f"{SSO_BASE}/authserver/qrCode/getCode?uuid={token}",
                      timeout=TIMEOUT, headers={"Referer": resp.url})
    ctype = (img.headers.get("Content-Type") or "").lower()
    print(f"[qr] getCode -> {img.status_code} {ctype} {len(img.content)}B")
    if not ctype.startswith("image/") or len(img.content) < 200:
        print("[qr] 未取到二维码图片, 终止")
        return 1
    with open(IMG, "wb") as f:
        f.write(img.content)

    _save_state(session, token=token, lt=lt, execution=execution,
                login_url=resp.url)
    print(f"[qr] 二维码已保存: {IMG}")
    print("[qr] 请用微信扫码并在手机上确认, 然后执行: python tests/probe_sso_qr.py poll")
    return 0


def _finish_login(session, state) -> int:
    """状态=1 后: 提交 qrLoginForm 换 CASTGC, 再验证教务会话。"""
    login_url = state.get("login_url") or SSO_LOGIN_URL
    # ★ service 必须原样还原后再编码一次: 直接截取页面 URL 的 query 会被二次编码,
    #   CAS 认不出服务 → 跳到 error.njust.edu.cn/errorTips500.html 且拿不到 CASTGC
    service = (parse_qs(urlparse(login_url).query).get("service") or [""])[0]
    display_url = f"{SSO_BASE}/authserver/login?display=qrLogin"
    if service:
        display_url += f"&service={quote(service, safe='')}"
    data = {"uuid": state["token"], "lt": state.get("lt", ""),
            "cllt": "qrLogin", "dllt": "generalLogin",
            "execution": state.get("execution", "e1s1"),
            "_eventId": "submit", "rmShown": "1"}
    r = session.post(display_url, data=data, timeout=TIMEOUT,
                     allow_redirects=True, headers={"Referer": login_url})
    print(f"[qr] 提交 qrLoginForm -> {r.status_code} 最终={r.url[:110]}")
    has_tgc = any("CASTGC" in c.name for c in session.cookies)
    print(f"[qr] CASTGC: {'已获取' if has_tgc else '未获取'}")
    _save_state(session, token=state["token"], lt=state.get("lt", ""),
                execution=state.get("execution", ""),
                login_url=login_url, castgc=has_tgc)
    if not has_tgc:
        print("[qr] 结论: 扫码确认后后端未能换到票据")
        return 1
    return cmd_check()


def cmd_poll(wait: int = 240) -> int:
    state = _load_state()
    session = _session()
    _load_cookies(session, state["cookies"])
    token = state["token"]
    print(f"[qr] 轮询状态(最多 {wait}s): {SSO_BASE}/authserver/qrCode/getStatus.htl")
    last = ""
    deadline = time.time() + wait
    while time.time() < deadline:
        try:
            r = session.post(f"{SSO_BASE}/authserver/qrCode/getStatus.htl",
                             data={"uuid": token}, timeout=TIMEOUT,
                             headers={"Referer": state.get("login_url", SSO_LOGIN_URL)})
            st = (r.text or "").strip()
        except Exception as e:  # noqa: BLE001
            print(f"[qr] 轮询异常: {type(e).__name__}: {e}")
            time.sleep(3)
            continue
        if st != last:
            label = {"1": "已确认", "2": "已扫码, 等待手机确认", "3": "二维码已失效",
                     "4": "已取消"}.get(st, st)
            print(f"[qr] 状态={st} ({label})")
            last = st
        if st == "1":
            return _finish_login(session, state)
        if st == "3":
            print("[qr] 二维码失效, 需要重新 start")
            return 1
        time.sleep(2)
    print("[qr] 等待超时, 可重新执行 poll 继续等待")
    return 1


def cmd_check() -> int:
    """验证当前会话能否建立教务会话(有 CASTGC 时应当成功)。"""
    if os.path.exists(STATE):
        state = _load_state()
        session = _session()
        _load_cookies(session, state["cookies"])
    else:
        session = _session()
    print(f"[qr] 试探教务入口: {_root}")
    entry = "https://bkjw.njust.edu.cn/njlgdx/indexsso.jsp"
    r = session.get(entry, timeout=TIMEOUT, allow_redirects=True)
    m = re.search(r"<title>(.*?)</title>", r.text, re.S)
    title = m.group(1).strip() if m else ""
    print(f"[qr] {r.status_code} 最终={r.url[:100]} 标题={title!r} 长度={len(r.text)}")
    if len(r.text) > 3000 and "登录" not in title:
        print("[qr] 结论: 教务会话已建立, 扫码登录链路可用")
        _save_state(session, token="", login_url="", verified=True)
        return 0
    print("[qr] 结论: 尚未建立教务会话")
    return 1


def cmd_status() -> int:
    """一次性查询当前二维码在服务端的状态(不轮询)。

    0=未扫描/未识别  2=已扫描(识别成功, 等待手机上确认)  1=已确认  3=已失效
    用它区分「长按菜单里有没有识别图中二维码」: 只有真的识别成功才会 ≥2。
    """
    state = _load_state()
    session = _session()
    _load_cookies(session, state["cookies"])
    r = session.post(f"{SSO_BASE}/authserver/qrCode/getStatus.htl",
                     data={"uuid": state["token"]}, timeout=TIMEOUT,
                     headers={"Referer": state.get("login_url", SSO_LOGIN_URL)})
    st = (r.text or "").strip()
    label = {"0": "未扫描/未识别", "1": "已确认", "2": "已扫描, 等待手机上确认",
             "3": "已失效", "4": "已取消"}.get(st, "未知")
    print(f"[qr] 状态={st} ({label})  token={state['token'][:20]}…")
    return 0


def cmd_sid() -> int:
    """登录后能否从教务页面自动提取学号(扫码登录无人输入学号, 必须能提取)。"""
    state = _load_state()
    session = _session()
    _load_cookies(session, state["cookies"])
    for url in ("https://bkjw.njust.edu.cn/njlgdx/framework/main.jsp",
                "https://bkjw.njust.edu.cn/njlgdx/framework/main.jsp?t=1"):
        r = session.get(url, timeout=TIMEOUT, allow_redirects=True)
        hits = re.findall(r"\b(9\d{11})\b", r.text)
        print(f"[sid] {url.split('?')[0]} {r.status_code} 长度={len(r.text)} "
              f"命中12位学号={sorted(set(hits))[:3]}")
        if hits:
            return 0
    print("[sid] 结论: 主框架页未直接暴露学号, 需要另找来源或用前端已存学号")
    return 1


def main() -> int:
    action = sys.argv[1] if len(sys.argv) > 1 else "start"
    if action == "start":
        return cmd_start()
    if action == "poll":
        wait = int(sys.argv[2]) if len(sys.argv) > 2 else 240
        return cmd_poll(wait)
    if action == "check":
        return cmd_check()
    if action == "status":
        return cmd_status()
    if action == "sid":
        return cmd_sid()
    print(__doc__)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
