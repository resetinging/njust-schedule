# -*- coding: utf-8 -*-
"""教务直登替代方案探针。

背景: 教务改版后, 老入口 8080/Logon.do 的表单直登不再建立有效会话; 新入口
bkjwxt.njust.edu.cn 提供了经典登录页(Logon.do)与根路径验证码。本脚本只做
页面解析与链路探测, 用于判断「不依赖智慧理工 SSO 的直登」是否可行。

用法:
    python tests/probe_jw_logon.py               # 解析各入口登录页表单(只读)
    python tests/probe_jw_logon.py captcha <URL> # 抓验证码图片到 tests/_jw_captcha.jpg
    # 完整直登验证(密码走环境变量, 不落命令行):
    $env:NJUST_JW_PWD="<教务密码>"; python tests/probe_jw_logon.py login <登录页URL>
"""

import os
import re
import sys

import requests
from bs4 import BeautifulSoup

TIMEOUT = 20
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/153.0.0.0 Safari/537.36 Edg/153.0.0.0")

ENTRIES = [
    "http://202.119.81.113:8080/Logon.do?method=logon",
    "http://202.119.81.112:9080/Logon.do?method=logon",
    "http://bkjwxt.njust.edu.cn/Logon.do?method=logon",
    "http://bkjwxt.njust.edu.cn/njlgdx/framework/main.jsp",
    "http://bkjwxt.njust.edu.cn/njlgdx/xskb/xskb_list.do?Ves632DSdyV=NEW_XSD_PYGL",
]


def _session() -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": UA,
                      "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8"})
    return s


def _title(html: str) -> str:
    m = re.search(r"<title>(.*?)</title>", html, re.S)
    return m.group(1).strip() if m else ""


def parse_entry(session: requests.Session, url: str) -> None:
    print(f"\n=== {url}")
    try:
        resp = session.get(url, timeout=TIMEOUT, allow_redirects=True)
    except Exception as e:  # noqa: BLE001
        print(f"    请求失败: {type(e).__name__}: {e}")
        return
    print(f"    最终URL={resp.url}")
    print(f"    状态={resp.status_code} 长度={len(resp.text)} 标题={_title(resp.text)!r}")
    for h in resp.history:
        print(f"    跳转 {h.status_code} -> {h.headers.get('Location', '')[:90]}")

    soup = BeautifulSoup(resp.text, "lxml")
    forms = soup.find_all("form")
    print(f"    表单数={len(forms)}")
    for i, form in enumerate(forms[:3]):
        print(f"      表单{i}: action={form.get('action')!r} method={form.get('method')!r} "
              f"id={form.get('id')!r} name={form.get('name')!r}")
        fields = []
        for inp in form.find_all(["input", "select"]):
            n = inp.get("name")
            if not n:
                continue
            v = inp.get("value", "")
            t = inp.get("type", inp.name)
            fields.append(f"{n}({t})={str(v)[:18]}")
        print(f"        字段: {fields}")
    imgs = [img.get("src") for img in soup.find_all("img") if img.get("src")]
    caps = [s for s in imgs if "code" in s.lower() or "captcha" in s.lower()
            or "verify" in s.lower()]
    print(f"    图片数={len(imgs)} 疑似验证码={caps[:3]}")
    for s in re.findall(r"(?:src|href|url)\s*[=:]\s*['\"]([^'\"]*(?:code|Code|captcha)"
                        r"[^'\"]*)['\"]", resp.text)[:5]:
        print(f"    验证码线索: {s[:100]}")


def cmd_parse() -> int:
    for url in ENTRIES:
        parse_entry(_session(), url)
    return 0


def cmd_captcha(url: str) -> int:
    session = _session()
    resp = session.get(url, timeout=TIMEOUT)
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_jw_captcha.jpg")
    with open(out, "wb") as f:
        f.write(resp.content)
    print(f"[captcha] {resp.status_code} type={resp.headers.get('Content-Type')} "
          f"bytes={len(resp.content)} cookies={list(session.cookies.get_dict().keys())}")
    print(f"[captcha] 已保存: {out}")
    return 0


def cmd_login(login_url: str) -> int:
    """经典页直登: 解析表单 → OCR 验证码 → POST → 验证数据页是否可用。"""
    from urllib.parse import urljoin

    password = os.environ.get("NJUST_JW_PWD", "")
    sid = os.environ.get("NJUST_SID", "924101960123")
    if not password:
        print("[login] 请先设置环境变量 NJUST_JW_PWD")
        return 2

    session = _session()
    base = "{0.scheme}://{0.netloc}".format(requests.utils.urlparse(login_url))
    resp = session.get(login_url, timeout=TIMEOUT)
    soup = BeautifulSoup(resp.text, "lxml")
    form = soup.find("form")
    if not form:
        print("[login] 未找到登录表单")
        return 1
    action = urljoin(resp.url, form.get("action") or "")
    print(f"[login] 登录页 {resp.status_code} 长度={len(resp.text)} action={action}")

    candidates = []
    for img in soup.find_all("img"):
        src = (img.get("src") or "").strip()
        low = src.lower()
        if any(k in low for k in ("verifycode", "captcha", "randomcode", "code")):
            candidates.append(urljoin(resp.url, src.split("?")[0]))
    candidates += [urljoin(resp.url, "/njlgdx/verifycode.servlet"),
                   urljoin(resp.url, "/verifycode.servlet")]
    cap, cap_url = None, ""
    tried = []
    for url in dict.fromkeys(candidates):
        r = session.get(url, timeout=TIMEOUT, headers={"Referer": resp.url})
        ctype = (r.headers.get("Content-Type") or "").lower()
        tried.append(f"{url} -> {r.status_code} {ctype} {len(r.content)}B")
        if ctype.startswith("image/") and len(r.content) > 100:
            cap, cap_url = r, url
            break
    print("[login] 验证码候选:")
    for t in tried:
        print(f"          {t}")
    if cap is None:
        print("[login] 未取到可用验证码图片, 放弃")
        return 1
    print(f"[login] 采用验证码: {cap_url} "
          f"{cap.headers.get('Content-Type')} bytes={len(cap.content)}")

    import ddddocr
    ocr_text = ddddocr.DdddOcr(show_ad=False).classification(cap.content)
    print(f"[login] 验证码 OCR = {ocr_text!r}")

    data = {}
    for inp in form.find_all("input"):
        n = inp.get("name")
        if not n:
            continue
        data[n] = inp.get("value") or ""
    data.update({"USERNAME": sid, "PASSWORD": password, "RANDOMCODE": ocr_text,
                 "useDogCode": "", "encoded": ""})
    post = session.post(action, data=data, timeout=TIMEOUT,
                        allow_redirects=True, headers={"Referer": resp.url})
    print(f"[login] POST {action} -> {post.status_code} 最终={post.url}")
    print(f"[login]   标题={_title(post.text)!r} 长度={len(post.text)}")
    text = BeautifulSoup(post.text, "lxml").get_text(" ", strip=True)
    print(f"[login]   可见文本: {text[:300]}")
    for kw in ("验证码", "密码", "错误", "失败", "锁定"):
        idx = text.find(kw)
        if idx >= 0:
            print(f"[login]   命中 {kw!r}: ...{text[max(0, idx - 40):idx + 60]}...")
            break
    for kw in ("验证码错误", "用户名或密码错误", "密码错误", "登录失败", "账号"):
        if kw in post.text:
            print(f"[login]   页面提示包含: {kw}")
    print(f"[login]   cookies={list(session.cookies.get_dict().keys())}")

    probe = f"{base}/njlgdx/xskb/xskb_list.do?Ves632DSdyV=NEW_XSD_PYGL"
    page = session.get(probe, timeout=TIMEOUT, allow_redirects=True)
    print(f"[login] 数据页 {page.status_code} 最终={page.url}")
    print(f"[login]   标题={_title(page.text)!r} 长度={len(page.text)}")
    if len(page.text) > 20000:
        print("[login] 结论: 直登后能拿到真实课表页 -> 直登方案可行")
        return 0
    print("[login] 结论: 数据页仍是登录壳/空页 -> 该入口不可用")
    return 1


def cmd_captcha_variants(login_url: str, cap_url: str) -> int:
    """带不同请求头试探验证码端点, 判断是否因头部/来源被重定向回登录页。"""
    session = _session()
    session.get(login_url, timeout=TIMEOUT)
    variants = [
        ("plain", {}),
        ("referer", {"Referer": login_url}),
        ("xhr", {"X-Requested-With": "XMLHttpRequest", "Accept": "image/*,*/*;q=0.8"}),
        ("referer+xhr", {"Referer": login_url, "X-Requested-With": "XMLHttpRequest",
                         "Accept": "image/*"}),
        ("no-cache", {"Cache-Control": "no-cache", "Pragma": "no-cache"}),
    ]
    for name, headers in variants:
        try:
            resp = session.get(cap_url, timeout=TIMEOUT, headers=headers)
        except Exception as e:  # noqa: BLE001
            print(f"  {name:12s} 异常 {type(e).__name__}: {e}")
            continue
        print(f"  {name:12s} -> {resp.status_code} "
              f"{resp.headers.get('Content-Type')} {len(resp.content)}B "
              f"head={resp.content[:40]!r}")
    return 0


def cmd_diag() -> int:
    """补充取证: 概念版验证码接口的原始应答 + 老入口数据页的错误内容。"""
    s1 = _session()
    r1 = s1.get("http://bkjwxt.njust.edu.cn/njlgdx/verifycode.servlet?t=0.5",
                timeout=TIMEOUT, headers={"X-Requested-With": "XMLHttpRequest"})
    print(f"[diag] 概念版验证码接口(XHR): {r1.status_code} "
          f"{r1.content.decode('utf-8', 'replace')}")

    s2 = _session()
    r2 = s2.get("http://202.119.81.113:8080/njlgdx/xskb/xskb_list.do",
                timeout=TIMEOUT)
    print(f"[diag] 老入口数据页: {r2.status_code} {len(r2.text)} {r2.url}")
    print(f"[diag]   文本: {BeautifulSoup(r2.text, 'lxml').get_text(' ', strip=True)[:300]}")

    s3 = _session()
    r3 = s3.get("http://bkjwxt.njust.edu.cn/njlgdx/xskb/xskb_list.do"
                "?Ves632DSdyV=NEW_XSD_PYGL", timeout=TIMEOUT)
    print(f"[diag] 新域名数据页: {r3.status_code} {len(r3.text)} {r3.url}")
    print(f"[diag]   文本: {BeautifulSoup(r3.text, 'lxml').get_text(' ', strip=True)[:300]}")
    return 0


def main() -> int:
    if len(sys.argv) >= 3 and sys.argv[1] == "captcha":
        return cmd_captcha(sys.argv[2])
    if len(sys.argv) >= 3 and sys.argv[1] == "login":
        return cmd_login(sys.argv[2])
    if len(sys.argv) >= 4 and sys.argv[1] == "capvariants":
        return cmd_captcha_variants(sys.argv[2], sys.argv[3])
    if sys.argv[1:2] == ["diag"]:
        return cmd_diag()
    return cmd_parse()


if __name__ == "__main__":
    raise SystemExit(main())
