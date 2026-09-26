# -*- coding: utf-8 -*-
"""抓取智慧理工 SSO(ids.njust.edu.cn) 登录验证码, 供人工识别与链路排查。

背景: 脚本全新会话访问 SSO 时 checkNeedCaptcha 返回 True, 需要验证码;
而浏览器已持有 TGT 所以看不到验证码。本工具用同一会话分两步走:

  1) fetch: 抓验证码图片, 同时把会话状态(execution/lt/salt/cookie)落到 json
     用法: python tests/fetch_sso_captcha.py fetch <学号> <图片输出路径>

  2) login: 用人工识别的验证码在同一会话里完成登录(验证整条链路)
     用法: 设置环境变量 NJUST_PASSWORD 后
           python tests/fetch_sso_captcha.py login <状态json> <验证码>

本脚本只做诊断, 不参与线上登录逻辑。
"""

import json
import importlib.util
import os
import re
import sys
import types

import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

from config import SSO_BASE, SSO_LOGIN_URL  # noqa: E402

_encrypt_sso_password = None


def _load_encrypt_helper():
    """按文件路径加载 jwc/common.py, 避开 wxcloudrun/__init__.py 的建库副作用。

    wxcloudrun/__init__.py 会连 MySQL 建表, 诊断脚本不能触发它, 所以先塞一个只带
    __path__ 的包壳进 sys.modules, 让子模块按普通文件加载。
    """
    pkg = types.ModuleType("wxcloudrun")
    pkg.__path__ = [os.path.join(_ROOT, "wxcloudrun")]
    sys.modules.setdefault("wxcloudrun", pkg)
    sys.modules.setdefault("wxcloudrun.jwc", types.ModuleType("wxcloudrun.jwc"))

    path = os.path.join(_ROOT, "wxcloudrun", "jwc", "common.py")
    spec = importlib.util.spec_from_file_location("_sso_common", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod._encrypt_sso_password

TIMEOUT = 20
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/153.0.0.0 Safari/537.36 Edg/153.0.0.0")


def _new_session() -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": UA,
                      "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8"})
    return s


def _dump_cookies(session: requests.Session) -> list:
    return [{"name": c.name, "value": c.value,
             "domain": c.domain, "path": c.path or "/"}
            for c in session.cookies]


def _load_cookies(session: requests.Session, cookies: list) -> None:
    for c in cookies:
        session.cookies.set(c["name"], c["value"],
                            domain=c.get("domain"), path=c.get("path") or "/")


def _fetch_login_form(session: requests.Session, login_url: str):
    """GET 登录页并解析 CAS 表单字段(execution/lt/pwdEncryptSalt/action)。"""
    resp = session.get(login_url, timeout=TIMEOUT, allow_redirects=True)
    print(f"[fetch] GET {login_url}")
    print(f"[fetch]   最终URL={resp.url}")
    print(f"[fetch]   状态={resp.status_code} 长度={len(resp.text)}")

    if "authserver/login" not in resp.url:
        print("[fetch] 该会话未落到登录页(已有 TGT?), 无需验证码")
        return None, None

    soup = BeautifulSoup(resp.text, "lxml")
    form = soup.find("form", id="pwdFromId") or soup.find("form")
    if not form:
        raise RuntimeError("未找到 SSO 登录表单")

    def val(field_id: str) -> str:
        inp = form.find("input", id=field_id)
        if inp is None:
            inp = form.find("input", attrs={"name": field_id})
        return (inp.get("value") or "").strip() if inp else ""

    fields = {"execution": val("execution"),
              "lt": val("lt"),
              "pwdEncryptSalt": val("pwdEncryptSalt")}
    captcha_input = form.find("input", id="captcha") or form.find(
        "input", attrs={"name": "captcha"})
    print(f"[fetch]   表单 action={form.get('action')!r} 字段={fields} "
          f"含验证码输入框={bool(captcha_input)}")
    return resp, fields


def cmd_fetch(student_id: str, out_path: str) -> int:
    session = _new_session()
    resp, fields = _fetch_login_form(session, SSO_LOGIN_URL)
    if resp is None:
        return 0

    check = session.post(f"{SSO_BASE}/authserver/checkNeedCaptcha.htl",
                         data={"username": student_id}, timeout=TIMEOUT,
                         headers={"Referer": resp.url,
                                  "X-Requested-With": "XMLHttpRequest"})
    print(f"[fetch] checkNeedCaptcha -> {check.status_code} {check.text[:200]}")
    need = False
    try:
        need = bool(check.json().get("isNeed", False))
    except Exception:
        pass

    cap = session.get(f"{SSO_BASE}/authserver/getCaptcha.htl",
                      timeout=TIMEOUT, headers={"Referer": resp.url})
    print(f"[fetch] getCaptcha -> {cap.status_code} "
          f"type={cap.headers.get('Content-Type')} bytes={len(cap.content)}")

    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    with open(out_path, "wb") as f:
        f.write(cap.content)

    state_path = os.path.splitext(out_path)[0] + ".json"
    with open(state_path, "w", encoding="utf-8") as f:
        json.dump({"username": student_id, "need_captcha": need,
                   "login_url": SSO_LOGIN_URL, "post_url": resp.url,
                   "fields": fields, "cookies": _dump_cookies(session)},
                  f, ensure_ascii=False, indent=2)

    print(f"[fetch] 图片已保存: {out_path}")
    print(f"[fetch] 会话状态已保存: {state_path}")
    print(f"[fetch] needCaptcha={need} (若为 False, 说明该学号当前不需要验证码)")
    return 0


def cmd_login(state_path: str, captcha: str) -> int:
    password = os.environ.get("NJUST_PASSWORD", "")
    if not password:
        print("[login] 请先设置环境变量 NJUST_PASSWORD")
        return 2

    with open(state_path, encoding="utf-8") as f:
        state = json.load(f)
    return _post_login(state, captcha, password,
                       dump_html=os.path.splitext(state_path)[0] + ".resp.html",
                       state_path=state_path)


def _post_login(state: dict, captcha: str, password: str,
                dump_html: str = None, state_path: str = None) -> int:
    encrypt = _load_encrypt_helper()
    session = _new_session()
    _load_cookies(session, state["cookies"])
    post_url = state["post_url"]
    form_data = {
        "username": state["username"],
        "password": encrypt(password, state["fields"]["pwdEncryptSalt"]),
        "captcha": captcha.strip(),
        "rememberMe": "true",
        "_eventId": "submit",
        "cllt": "userNameLogin",
        "dllt": "generalLogin",
        "lt": state["fields"]["lt"],
        "execution": state["fields"]["execution"],
    }
    resp = session.post(post_url, data=form_data, timeout=TIMEOUT,
                        allow_redirects=True, headers={"Referer": post_url})
    print(f"[login] POST {post_url}")
    print(f"[login]   最终URL={resp.url}")
    print(f"[login]   状态={resp.status_code} 长度={len(resp.text)}")

    title = ""
    m = re.search(r"<title>(.*?)</title>", resp.text, re.S)
    if m:
        title = m.group(1).strip()
    print(f"[login]   标题={title}")
    print(f"[login]   cookies={list(session.cookies.get_dict().keys())}")

    err = _extract_error(resp.text)
    if state_path:
        # 登录成功会下发 CASTGC, 回写会话供后续链路(SSO→教务)验证使用
        state["cookies"] = _dump_cookies(session)
        state["need_captcha"] = False
        with open(state_path, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
    if dump_html:
        with open(dump_html, "w", encoding="utf-8") as f:
            f.write(resp.text)
        print(f"[login]   响应已落盘: {dump_html}")
    if err:
        print(f"[login]   页面提示: {err}")

    if "authserver/login" in resp.url:
        print("[login] 结果: 仍在登录页(失败)")
        return 1
    print("[login] 结果: 已离开登录页")
    _print_cookie_details(session, resp)
    return 0


def _print_cookie_details(session, resp) -> None:
    """打印 cookie 的过期属性, 用于判断会话能复用多久。"""
    print("[cookie] 原始 Set-Cookie:")
    try:
        raw = resp.raw.headers.getlist("Set-Cookie")
    except Exception:  # noqa: BLE001
        raw = []
    for line in raw:
        print(f"[cookie]   {line[:160]}")
    print("[cookie] 会话内 cookie 属性:")
    for c in session.cookies:
        exp = c.expires
        if exp is None:
            exp_txt = "会话级(无 Expires, 关浏览器即失效)"
        else:
            try:
                exp_txt = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(exp))
            except Exception:  # noqa: BLE001
                exp_txt = str(exp)
        print(f"[cookie]   {c.name:24s} domain={c.domain:22s} "
              f"path={c.path or '/'} expires={exp_txt}")


def _extract_error(html: str) -> str:
    """从 CAS 返回页里抠出错误提示文案。"""
    soup = BeautifulSoup(html, "lxml")
    for sel in ("#showErrorTip", "#errorMsg", ".error", "#msg", ".alert"):
        node = soup.select_one(sel)
        if node and node.get_text(strip=True):
            return node.get_text(" ", strip=True)[:120]
    for kw in ("验证码错误", "验证码不正确", "用户名或密码错误",
               "密码错误", "账号或密码错误", "该账号已被锁定", "账号已锁定"):
        if kw in html:
            return kw
    return ""


def cmd_auto(student_id: str, out_path: str) -> int:
    """抓验证码 → ddddocr 识别 → 立即用同一会话登录, 模拟线上链路。"""
    password = os.environ.get("NJUST_PASSWORD", "")
    if not password:
        print("[auto] 请先设置环境变量 NJUST_PASSWORD")
        return 2

    rc = cmd_fetch(student_id, out_path)
    if rc != 0:
        return rc

    state_path = os.path.splitext(out_path)[0] + ".json"
    with open(state_path, encoding="utf-8") as f:
        state = json.load(f)
    with open(out_path, "rb") as f:
        img = f.read()

    import ddddocr
    text = ddddocr.DdddOcr(show_ad=False).classification(img)
    print(f"[auto] ddddocr 识别: {text!r} (可对照 {out_path} 人工核对)")
    rc = _post_login(state, text, password,
                     dump_html=os.path.splitext(out_path)[0] + ".resp.html",
                     state_path=state_path)
    if rc == 0:
        rc = cmd_chain(state_path)
    return rc


def cmd_chain(state_path: str) -> int:
    """用已登录(含 CASTGC)的会话走 indexsso.jsp, 看能否直接进教务。"""
    from config import JW_SSO_BASE, JW_SSO_ENTRY

    with open(state_path, encoding="utf-8") as f:
        state = json.load(f)
    session = _new_session()
    _load_cookies(session, state["cookies"])

    has_castgc = any(c["name"] == "CASTGC" for c in state["cookies"])
    print(f"[chain] 会话含 CASTGC: {has_castgc}")
    print(f"[chain] GET {JW_SSO_ENTRY}")
    resp = session.get(JW_SSO_ENTRY, timeout=TIMEOUT, allow_redirects=True)
    # indexsso 链路会给 bkjw 域下发教务 JSESSIONID, 回写以便后续探针复用完整会话
    state["cookies"] = _dump_cookies(session)
    with open(state_path, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
    for h in resp.history[-5:]:
        print(f"[chain]   {h.status_code} -> {h.headers.get('Location', '')[:90]}")
    m = re.search(r"<title>(.*?)</title>", resp.text, re.S)
    title = m.group(1).strip() if m else ""
    print(f"[chain]   最终 {resp.status_code} {resp.url}")
    print(f"[chain]   标题={title} 长度={len(resp.text)}")

    if "framework/main.jsp" in resp.url and len(resp.text) > 3000:
        print("[chain] 结果: 已进入教务主框架 (SSO 直达成功)")
        return 0
    if "authserver/login" in resp.url:
        print("[chain] 结果: 被弹回 SSO 登录页 (CASTGC 未被教务接受)")
        return 1
    print("[chain] 结果: 未确认(需人工看页面)")
    return 1


def cmd_probe(state_path: str, url: str, max_hops: int = 8) -> int:
    """手动跟一遍重定向链(不自动跳转), 定位教务改版后的跳转循环。"""
    with open(state_path, encoding="utf-8") as f:
        state = json.load(f)
    session = _new_session()
    _load_cookies(session, state["cookies"])

    cur = url
    for i in range(max_hops + 1):
        resp = session.get(cur, timeout=TIMEOUT, allow_redirects=False,
                           headers={"Referer": cur})
        loc = resp.headers.get("Location", "")
        print(f"[probe] {i}: {resp.status_code} {cur[:110]}")
        if loc:
            print(f"[probe]      -> {loc[:130]}")
        if resp.status_code not in (301, 302, 303, 307, 308) or not loc:
            body = resp.text or ""
            m = re.search(r"<title>(.*?)</title>", body, re.S)
            print(f"[probe]      标题={(m.group(1).strip() if m else '')!r} "
                  f"长度={len(body)}")
            print(f"[probe]      片段: {body[:160].replace(chr(10), ' ')}")
            return 0
        cur = urljoin(cur, loc)
    print(f"[probe] 已跳 {max_hops} 次仍未结束 -> 重定向循环")
    return 1


def main() -> int:
    if len(sys.argv) < 3:
        print(__doc__)
        return 2
    action = sys.argv[1]
    if action == "fetch":
        return cmd_fetch(sys.argv[2], sys.argv[3])
    if action == "login":
        return cmd_login(sys.argv[2], sys.argv[3])
    if action == "auto":
        return cmd_auto(sys.argv[2], sys.argv[3])
    if action == "chain":
        return cmd_chain(sys.argv[2])
    if action == "probe":
        return cmd_probe(sys.argv[2], sys.argv[3])
    print(__doc__)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
