"""
南京理工大学强智教务系统客户端
===================================
NJUST 教务路径前缀: /njlgdx/（不是 /jsxsd/）
登录: 8080/Logon.do → POST 9080/LoginToXk?method=jwxt
"""

import logging
import requests
import re
import json
import base64
import time
import os
from typing import Optional, Tuple
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

from config import (
    JW_BASE_8080, JW_BASE_9080, JW_PATH_PREFIX,
    JW_LOGON_PAGE, JW_SCHEDULE_URL, JW_EXAM_QUERY, JW_EXAM_LIST,
    JW_EVAL_PAGE, JW_GRADE_QUERY, JW_GRADE_LIST, JW_CET_LIST,
    JW_APP_DO, JW_CAPTCHA_URLS, BIG_PERIOD_MAP,
    HTTP_TIMEOUT, HTTP_HEADERS,
    SSO_BASE, SSO_LOGIN_URL,
    WEBVPN_BASE, WEBVPN_PREFIX_JW,
    JW_BASE_8080_VPN, JW_BASE_9080_VPN, DEBUG_WEBVPN,
)

# === 加密模块（WebVPN 密码加密） ===
try:
    from Crypto.Cipher import AES
    from Crypto.Util.Padding import pad as aes_pad
    _HAS_CRYPTO = True
except ImportError:
    _HAS_CRYPTO = False

# === URL 别名（保持向后兼容） ===
BASE_URL = JW_BASE_8080
BASE_9080 = JW_BASE_9080
URL_LOGON_PAGE = JW_LOGON_PAGE
URL_LOGON_SESS = f"{BASE_URL}/Logon.do?method=logon&flag=sess"
URL_LOGIN_9080 = f"{BASE_9080}{JW_PATH_PREFIX}/xk/LoginToXk"
URL_APP_DO = JW_APP_DO
URL_SCHEDULE_HTML = JW_SCHEDULE_URL
URL_EXAM_QUERY = JW_EXAM_QUERY
URL_EXAM_LIST = JW_EXAM_LIST
URL_EVAL_PAGE = JW_EVAL_PAGE
URL_GRADE_QUERY = JW_GRADE_QUERY
URL_GRADE_LIST = JW_GRADE_LIST
URL_CET_LIST = JW_CET_LIST
URL_MAIN_PAGE = f"{BASE_9080}{JW_PATH_PREFIX}/framework/main.jsp"
URL_CAPTCHA_CANDIDATES = JW_CAPTCHA_URLS
HEADERS = HTTP_HEADERS
TIMEOUT = HTTP_TIMEOUT


class BaseClient:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update(HEADERS)
        self.token = None
        self.student_id = None
        self.student_name = None
        self.logged_in = False
        self.login_method = ""
        self.last_error = ""
        self._captcha_ready = False
        self._active_captcha_url = URL_CAPTCHA_CANDIDATES[0]
        self.debug_log = []  # WebVPN 诊断日志收集
        # WebVPN 手动验证码中间状态
        self._webvpn_manual_ready = False
        self._webvpn_post_url = ""
        self._webvpn_login_page_url = ""


    def login(self, student_id: str, password: str) -> bool:
        self.student_id = student_id
        self.student_name = None
        self.last_error = ""
        self.logged_in = False
        self.login_method = ""
        self.token = None
        self._captcha_ready = False
        self.session = requests.Session()
        self.session.headers.update(HEADERS)

        # 8080 端口 Web 登录 + OCR
        if self._try_web_auto(student_id, password):
            return True

        return False

    # ================================================================
    # 核心方法
    # ================================================================

    def _resolve_url(self, url: str) -> str:
        """URL 解析（直连模式不做转换，保留原始 URL）"""
        return url

    def _get(self, url: str, **kwargs):
        """session.get 包装，自动解析 WebVPN URL"""
        resolved = self._resolve_url(url)
        if self.login_method == "webvpn":
            # 提取路径最后一段便于识别
            path_hint = url.split("/")[-1].split("?")[0][:40] if "/" in url else url[:40]
            self._log(f"[GET] {path_hint} → {resolved[:120]}")
        return self.session.get(resolved, **kwargs)

    def _post(self, url: str, **kwargs):
        """session.post 包装，自动解析 WebVPN URL"""
        resolved = self._resolve_url(url)
        if self.login_method == "webvpn":
            path_hint = url.split("/")[-1].split("?")[0][:40] if "/" in url else url[:40]
            self._log(f"[POST] {path_hint} → {resolved[:120]}")
        return self.session.post(resolved, **kwargs)

    def _init_logon_session(self):
        self.session.cookies.clear()
        self._get(URL_LOGON_PAGE, timeout=TIMEOUT)
        self.session.headers.update({"Referer": URL_LOGON_PAGE})
        self._dedupe_cookies()
        self._detect_captcha_url_from_page()
        try:
            self._get(URL_LOGON_SESS, timeout=TIMEOUT)
            self._dedupe_cookies()
        except Exception:
            pass

    def _detect_captcha_url_from_page(self):
        try:
            resp = self._get(URL_LOGON_PAGE, timeout=TIMEOUT)
            m = re.search(
                r'<img[^>]+src=["\']([^"\']*(?:verifycode|checkcode|code)[^"\']*)["\']',
                resp.text, re.IGNORECASE)
            if m:
                src = m.group(1)
                self._active_captcha_url = src if src.startswith("http") else f"{BASE_URL}{src}"
                logger.debug("CaptchaURL: %s", self._active_captcha_url)
        except Exception:
            pass

    def _log(self, msg: str):
        """记录调试日志"""
        self.debug_log.append(msg)
        if DEBUG_WEBVPN:
            try:
                print(msg)
            except UnicodeEncodeError:
                # Windows GBK 终端无法处理 emoji，降级为 ascii
                print(msg.encode("ascii", errors="replace").decode("ascii"))

    def _fetch_captcha(self) -> bytes:
        for url in [self._active_captcha_url] + URL_CAPTCHA_CANDIDATES:
            try:
                r = self.session.get(url, timeout=TIMEOUT)
                self._dedupe_cookies()
                content_type = r.headers.get("Content-Type", "")
                if r.status_code == 200 and len(r.content) > 100:
                    # 确保是图片
                    if "image" in content_type or r.content[:4] in (b"\x89PNG", b"GIF8", b"\xff\xd8\xff"):
                        self._active_captcha_url = url
                        return r.content
                    # 不是图片，记录一下
                    self._log(f"[Captcha] {url} 返回非图片: "
                              f"Content-Type={content_type}, "
                              f"前100字节={r.content[:100]}")
                else:
                    self._log(f"[Captcha] {url} 失败: status={r.status_code} "
                              f"len={len(r.content)}")
            except Exception as e:
                self._log(f"[Captcha] {url} 异常: {e}")
                continue
        return b""

    def _fix_jw_redirect(self, resp):
        """修正教务重定向 URL：.113:9080 → .112:9080

        教务 Verifyservlet 可能重定向到错误的 IP（.113 而非 .112），
        此方法检测并修正。
        LoginToXk?method=verify 使用 POST 而非 GET。
        """
        from urllib.parse import urlparse, parse_qs

        loc = resp.headers.get("Location", "")
        if not loc:
            return resp  # 不是重定向，原样返回
        original = loc
        # 修正: 202.119.81.113:9080 → 202.119.81.112:9080
        loc = loc.replace("202.119.81.113:9080", "202.119.81.112:9080")
        # 修正: 202.119.81.113/njlgdx (无端口) → 202.119.81.112:9080/njlgdx
        loc = loc.replace(
            "202.119.81.113/njlgdx", "202.119.81.112:9080/njlgdx"
        )
        if loc != original:
            self._log(f"[FixRedirect] {original[:100]} → {loc[:100]}")

        # LoginToXk?method=verify 期望 POST，不是 GET
        if "LoginToXk" in loc and "method=verify" in loc:
            parsed = urlparse(loc)
            params = parse_qs(parsed.query)
            # parse_qs 返回 {key: [value]}，转为 {key: value}
            post_data = {k: v[0] for k, v in params.items()}
            base_url = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
            self._log(f"[FixRedirect] POST {base_url} (LoginToXk verify)")
            return self.session.post(
                base_url, data=post_data, timeout=TIMEOUT,
                allow_redirects=True,
                headers={"Referer": resp.url},
            )

        # 普通重定向用 GET
        return self.session.get(
            loc, timeout=TIMEOUT, allow_redirects=True,
            headers={"Referer": resp.url},
        )

    def _dedupe_cookies(self):
        jar = self.session.cookies
        js = [c for c in jar if c.name == "JSESSIONID"]
        if len(js) > 1:
            # 只清除多余的 JSESSIONID，保留最后一个及其他 cookie
            for c in js[:-1]:
                jar.clear(c.domain or "", c.path or "", c.name)

    def _ocr_with_preprocess(self, ocr, data: bytes) -> str:
        cands = [data]
        try:
            from PIL import Image
            from io import BytesIO
            img = Image.open(BytesIO(data)).convert("L")
            bw = img.point(lambda x: 0 if x < 140 else 255, "1")
            b = BytesIO(); bw.save(b, format="PNG"); cands.append(b.getvalue())
            big = img.resize((img.width*2, img.height*2), Image.LANCZOS)
            b2 = BytesIO(); big.save(b2, format="PNG"); cands.append(b2.getvalue())
        except Exception:
            pass
        for c in cands:
            r = ocr.classification(c).strip()
            if r: return r
        return ""

    def _check_success(self, resp) -> bool:
        t = resp.text
        # 明确的失败标记
        for kw in ["验证码错误", "密码错误", "账号错误", "用户不存在"]:
            if kw in t:
                return False
        # WebVPN 错误页（网瑞达返回的"出错了"页面）
        if "vpn_eval" in t and ("errorCode" in t or "errorImg" in t):
            return False
        # 检测是教务登录页面（而非已登录状态）
        if self._is_jw_login_page(resp):
            return False
        # 明确的成功标记
        for kw in ["课程表", "学期理论课表", "学生首页", "学生个人中心",
                    "xs_main", "framemain", "安全退出", "退出系统"]:
            if kw in t:
                return True
        # URL fallback：仅当 URL 不匹配登录页地址时才认为成功
        # 注意：WebVPN 代理后的 URL 与直连 URL 不同，需要用 host+path 判断
        url_str = resp.url if hasattr(resp, 'url') else ""
        if "Logon.do" in url_str:
            return False
        return "authserver" not in url_str

    def _is_jw_login_page(self, resp) -> bool:
        """检测是否为教务登录页面（强智教务）"""
        t = resp.text.lower()
        url = resp.url.lower() if hasattr(resp, 'url') else ""
        # 任一特征匹配 → 是登录页
        indicators = [
            "Logon.do" in url,
            "Verifyservlet" in t,
            "verifycode.servlet" in t,
            ("USERNAME" in t and "PASSWORD" in t and "RANDOMCODE" in t),
        ]
        return any(indicators)

    def _page_title(self, resp) -> str:
        m = re.search(r'<title>([^<]*)</title>', resp.text)
        return m.group(1) if m else "无"

    def _extract_name(self, html: str):
        for p in [r'([^\s<]{2,4})[，,]\s*同学', r'姓名[：:]\s*([^\s<]{2,4})']:
            m = re.search(p, html)
            if m:
                self.student_name = m.group(1)
                return

    # ================================================================
    # 课表
    # ================================================================

    def check_connectivity(self) -> dict:
        """检测教务系统连通性

        返回: {reachable, method, latency_ms, label, hint}
          method: "direct" (低延迟, <50ms)
                  "remote" (高延迟, >=50ms)
                  ""       (不可达)
        """
        import time as _time
        result = {"reachable": False, "method": "", "latency_ms": 0,
                   "label": "离线", "hint": ""}

        for label, url, port in [("8080", URL_LOGON_PAGE, 8080),
                                  ("9080", f"{BASE_9080}/njlgdx/", 9080)]:
            try:
                start = _time.time()
                r = requests.get(url, timeout=5, allow_redirects=False)
                elapsed = (_time.time() - start) * 1000

                if r.status_code in (200, 302, 301):
                    result["reachable"] = True
                    if elapsed > result["latency_ms"]:
                        result["latency_ms"] = round(elapsed, 1)
            except Exception:
                pass

        if result["reachable"]:
            if result["latency_ms"] < 50:
                result["method"] = "direct"
                result["label"] = "教务在线"
            else:
                result["method"] = "remote"
                result["label"] = "教务在线"
        else:
            result["method"] = "offline"
            result["label"] = "离线"
            result["hint"] = (
                "请检查网络连接或稍后重试。"
                "已缓存的数据仍可查看。"
            )

        return result

    def test_connection(self) -> Tuple[bool, str]:
        """测试教务连接（兼容旧接口）"""
        status = self.check_connectivity()
        if status["reachable"]:
            return True, f"连接正常 ({status['label']})"
        return False, "无法连接，请检查网络"

    def logout(self):
        try:
            self._get(f"{BASE_9080}/njlgdx/xk/LoginToXk?method=exit", timeout=5)
        except Exception:
            pass
        self.logged_in = False
        self.login_method = ""
        self.token = None
        self.student_name = None
        self.session = requests.Session()
        self.session.headers.update(HEADERS)

