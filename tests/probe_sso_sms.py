# -*- coding: utf-8 -*-
"""智慧理工 SSO「手机动态码(短信验证码)登录」探针。

用途: 验证单设备登录方案 E —— 用户只需「输学号/手机号 → 收短信 → 输验证码」,
      全程不提交账号密码(因此不触发密码风控冻结)。

依据(读自登录页 phoneFromId 表单与 login.js):
    表单 action=/authserver/login, 字段: username / captcha / dynamicCode
                                      + cllt=dynamicLogin / dllt=generalLogin
    发送短信: POST /authserver/dynamicCode/getDynamicCode.htl
              data: mobile=AES(账号, DEFAULT_SALT) + captcha=图形验证码
    图形验证码: GET /authserver/getCaptcha.htl?<ts>

用法:
    python tests/probe_sso_sms.py send 924101960123 [图形验证码]
        ← 会真发一条短信(验证码由 ddddocr 识别, 也可手动传入)
    python tests/probe_sso_sms.py verify <短信验证码>
        ← 提交登录表单并验证能否建立教务会话
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

# 页面 login.js 里的常量: 动态码登录用它对手机号加密
DEFAULT_SALT = "rjBFAaHsNkKAhpoi"

STATE = os.path.join(_here, "_sso_sms.json")
CAPTCHA_IMG = os.path.join(_here, "_sso_sms_captcha.png")
TIMEOUT = 20
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/153.0.0.0 Safari/537.36 Edg/153.0.0.0")


def _session() -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": UA,
                      "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8"})
    return s


def _encrypt(text: str) -> str:
    """复用项目里的 SSO 加密实现(与页面 encrypt.js 逐字节一致)。"""
    import importlib.util
    import types
    pkg = types.ModuleType("wxcloudrun")
    pkg.__path__ = [os.path.join(_root, "wxcloudrun")]
    sys.modules.setdefault("wxcloudrun", pkg)
    sys.modules.setdefault("wxcloudrun.jwc", types.ModuleType("wxcloudrun.jwc"))
    spec = importlib.util.spec_from_file_location(
        "_sso_common", os.path.join(_root, "wxcloudrun", "jwc", "common.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod._encrypt_sso_password(text, DEFAULT_SALT)


def _service_of(login_url: str) -> str:
    return (parse_qs(urlparse(login_url).query).get("service") or [""])[0]


def _save(session, **kw):
    data = {"cookies": [{"name": c.name, "value": c.value, "domain": c.domain,
                         "path": c.path or "/"} for c in session.cookies],
            "ts": int(time.time())}
    data.update(kw)
    with open(STATE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return data


def _load():
    with open(STATE, encoding="utf-8") as f:
        return json.load(f)


def _load_cookies(session, cookies):
    for c in cookies:
        session.cookies.set(c["name"], c["value"],
                            domain=c.get("domain"), path=c.get("path") or "/")


def _login_page(session):
    resp = session.get(SSO_LOGIN_URL, timeout=TIMEOUT, allow_redirects=True)
    soup = BeautifulSoup(resp.text, "lxml")

    def val(name):
        el = soup.find("input", attrs={"name": name, "id": name}) or \
             soup.find("input", attrs={"name": name})
        return (el.get("value") or "").strip() if el else ""

    return resp, val("lt"), val("execution")


def _fetch_captcha(session, referer):
    url = f"{SSO_BASE}/authserver/getCaptcha.htl?{int(time.time()*1000)}"
    r = session.get(url, timeout=TIMEOUT, headers={"Referer": referer})
    ctype = (r.headers.get("Content-Type") or "").lower()
    if not ctype.startswith("image/") or len(r.content) < 100:
        return b"", ""
    with open(CAPTCHA_IMG, "wb") as f:
        f.write(r.content)
    try:
        import ddddocr
        code = ddddocr.DdddOcr(show_ad=False).classification(r.content)
    except Exception:  # noqa: BLE001 OCR 不可用时交给人工
        code = ""
    return r.content, code


def cmd_send(account: str, captcha: str = "") -> int:
    session = _session()
    resp, lt, execution = _login_page(session)
    print(f"[sms] 登录页 {resp.status_code} lt={lt!r} execution={execution!r}")
    img, ocr = _fetch_captcha(session, resp.url)
    print(f"[sms] 图形验证码 {len(img)}B OCR={ocr!r} (图片: {CAPTCHA_IMG})")
    code = (captcha or ocr).strip()
    if not code:
        print("[sms] 图形验证码识别失败, 请人工查看图片后重跑: send <账号> <图形验证码>")
        return 1

    mobile = _encrypt(account)
    r = session.post(f"{SSO_BASE}/authserver/dynamicCode/getDynamicCode.htl",
                     data={"mobile": mobile, "captcha": code}, timeout=TIMEOUT,
                     headers={"Referer": resp.url,
                              "X-Requested-With": "XMLHttpRequest"})
    print(f"[sms] getDynamicCode -> {r.status_code} {r.text[:200]}")
    _save(session, account=account, lt=lt, execution=execution,
          login_url=resp.url, captcha=code)
    print("[sms] 若手机已收到短信, 执行: python tests/probe_sso_sms.py verify <短信验证码>")
    return 0


def cmd_verify(code: str) -> int:
    state = _load()
    session = _session()
    _load_cookies(session, state["cookies"])
    login_url = state.get("login_url") or SSO_LOGIN_URL
    service = _service_of(login_url)
    url = f"{SSO_BASE}/authserver/login"
    if service:
        url += f"?service={quote(service, safe='')}"
    data = {"username": state["account"], "captcha": state.get("captcha", ""),
            "dynamicCode": code.strip(), "_eventId": "submit",
            "cllt": "dynamicLogin", "dllt": "generalLogin",
            "lt": state.get("lt", ""), "execution": state.get("execution", "e1s1")}
    r = session.post(url, data=data, timeout=TIMEOUT, allow_redirects=True,
                     headers={"Referer": login_url})
    print(f"[sms] 提交动态码登录 -> {r.status_code} 最终={r.url[:110]}")
    has_tgc = any("CASTGC" in c.name for c in session.cookies)
    print(f"[sms] CASTGC: {'已获取' if has_tgc else '未获取'}")
    soup = BeautifulSoup(r.text, "lxml")
    err = soup.select_one("#showErrorTip")
    if err and err.get_text(strip=True):
        print(f"[sms] 页面提示: {err.get_text(' ', strip=True)[:120]}")
    _save(session, account=state["account"], login_url=login_url, castgc=has_tgc)
    if not has_tgc:
        print("[sms] 结论: 动态码登录未成功")
        return 1

    entry = "https://bkjw.njust.edu.cn/njlgdx/indexsso.jsp"
    r2 = session.get(entry, timeout=TIMEOUT, allow_redirects=True)
    m = re.search(r"<title>(.*?)</title>", r2.text, re.S)
    title = m.group(1).strip() if m else ""
    print(f"[sms] 教务入口 {r2.status_code} 最终={r2.url[:100]} 标题={title!r} 长度={len(r2.text)}")
    if len(r2.text) > 3000 and "登录" not in title:
        print("[sms] 结论: 短信验证码登录链路可用(单设备方案 E 成立)")
        return 0
    print("[sms] 结论: 拿到票据但未建立教务会话")
    return 1


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    action = sys.argv[1]
    if action == "send":
        if len(sys.argv) < 3:
            print("用法: send <学号或手机号> [图形验证码]")
            return 2
        return cmd_send(sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else "")
    if action == "verify":
        if len(sys.argv) < 3:
            print("用法: verify <短信验证码>")
            return 2
        return cmd_verify(sys.argv[2])
    print(__doc__)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
