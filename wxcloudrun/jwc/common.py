"""
南京理工大学强智教务系统客户端
===================================
NJUST 教务路径前缀: /njlgdx/（不是 /jsxsd/）
登录: 8080/Logon.do → POST 9080/LoginToXk?method=jwxt
"""

import logging
import requests
from requests.cookies import RequestsCookieJar
import re
import base64
import time
from typing import Optional, Tuple
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)


class ClassroomBorrowError(Exception):
    """教室借用页结构异常。

    必须与"确实没有空闲教室"区分开: 结构异常时不能返回空列表, 否则接口会以
    success/True + count=0 的形式把"解析失败"伪装成"该时段没有空闲教室"。
    """


class _DedupCookieJar(RequestsCookieJar):
    """自定义 CookieJar：遇到重复 cookie 时保留最后一个，不抛异常。
    NJUST 教务系统会返回多个同名 JSESSIONID，导致默认 jar 崩溃。"""
    def _find_no_duplicates(self, name, domain=None, path=None):
        """完全重写：手动查找，自动去重，永不抛 CookieConflictError"""
        matches = []
        for cookie in self:
            if cookie.name != name:
                continue
            if domain is not None and cookie.domain != domain:
                continue
            if path is not None and cookie.path != path:
                continue
            matches.append(cookie)
        if len(matches) > 1:
            # 保留最后一个，删除其余的
            for c in matches[:-1]:
                self.clear(c.domain, c.path, c.name)
            return matches[-1]
        if len(matches) == 1:
            return matches[0]
        return None

    # ---- 发送前的同名遮蔽去重 ----
    @staticmethod
    def _domain_matches(host: str, domain: str) -> bool:
        d = (domain or "").lower()
        if not d:
            return False
        if d.startswith("."):
            d = d[1:]
        return host == d or host.endswith("." + d)

    @staticmethod
    def _domain_rank(cookie):
        """域更具体者优先：host-only 优于 .domain，域越长越具体"""
        d = (cookie.domain or "").lower()
        return (0 if d and not d.startswith(".") else -1, len(d))

    def add_cookie_header(self, request):
        """发 Cookie 头之前，丢掉被遮蔽的同名重复 cookie

        上面 `_find_no_duplicates` 只在按 (name, domain, path) 取值时生效，
        而真正拼 Cookie 头走的是 http.cookiejar 的 add_cookie_header，它会把
        同名 cookie 一起发出去。WebVPN 网关代理过程中会轮换票据
        （旧票据域 .webvpn.njust.edu.cn → 新票据域 webvpn.njust.edu.cn），
        两张票一起发时网关取到失效的那张就判「未登录」→ 302 /login。
        这里按「域更具体优先」只保留应当生效的那张；作用域限定在当前请求
        主机，避免误删其它站点的同名 cookie。
        """
        try:
            from urllib.parse import urlsplit
            host = (urlsplit(request.get_full_url()).hostname or "").lower()
            if host:
                best = {}
                for c in list(self):
                    if not self._domain_matches(host, c.domain):
                        continue
                    key = (c.name, c.path or "/")
                    cur = best.get(key)
                    if cur is None or self._domain_rank(c) > self._domain_rank(cur):
                        best[key] = c
                if best:
                    keep = {id(c) for c in best.values()}
                    for c in list(self):
                        if not self._domain_matches(host, c.domain):
                            continue
                        if (c.name, c.path or "/") in best and id(c) not in keep:
                            self.clear(c.domain, c.path, c.name)
        except Exception:
            pass
        return super().add_cookie_header(request)

from config import (
    JW_BASE_8080, JW_BASE_9080, JW_PATH_PREFIX,
    JW_LOGON_PAGE, JW_SCHEDULE_URL, JW_EXAM_QUERY, JW_EXAM_LIST,
    JW_EVAL_PAGE, JW_GRADE_QUERY, JW_GRADE_LIST, JW_CET_LIST,
    JW_APP_DO, JW_CAPTCHA_URLS, BIG_PERIOD_MAP,
    HTTP_TIMEOUT, HTTP_HEADERS,
    SSO_BASE, SSO_LOGIN_URL, DEBUG_WEBVPN,
    JW_BORROW_QUERY, JW_BORROW_LIST,
)

# 教室名前缀 → 楼名映射(345→东区平房 等, 见模块内来源说明)
try:
    from freeclass_buildings import format_room_name
except ImportError:  # 以包方式导入（views/admin 的用法）
    from wxcloudrun.freeclass_buildings import format_room_name

# === WebVPN（网瑞达 wengine）代理直连 ===
try:
    from webvpn import WebVPNAdapter, WebVPNTransport
except ImportError:  # 以包方式导入（views/admin 的用法）
    from wxcloudrun.webvpn import WebVPNAdapter, WebVPNTransport

try:
    from config import WEBVPN_BASE, WEBVPN_CAS_SERVICE, WEBVPN_ENABLED
except ImportError:  # pragma: no cover
    WEBVPN_BASE = "https://webvpn.njust.edu.cn"
    WEBVPN_CAS_SERVICE = f"{WEBVPN_BASE}/login?cas_login=true"
    WEBVPN_ENABLED = "auto"

try:
    from config import JW_DEFAULT_PWD_TEMPLATE, JW_TRY_DEFAULT_PWD
except ImportError:  # pragma: no cover
    JW_DEFAULT_PWD_TEMPLATE = "{sid}@Njust"
    JW_TRY_DEFAULT_PWD = True

try:
    from config import JW_LOGON_BASES
except ImportError:  # pragma: no cover
    JW_LOGON_BASES = [JW_BASE_8080]

try:
    from config import JW_SSO_BASE, JW_SSO_ENTRY
except ImportError:  # pragma: no cover
    JW_SSO_BASE = "http://bkjw.njust.edu.cn"
    JW_SSO_ENTRY = f"{JW_SSO_BASE}{JW_PATH_PREFIX}/indexsso.jsp"

# === 加密模块（智慧理工 SSO 密码加密） ===
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
URL_BORROW_QUERY = JW_BORROW_QUERY
URL_BORROW_LIST = JW_BORROW_LIST
URL_MAIN_PAGE = f"{BASE_9080}{JW_PATH_PREFIX}/framework/main.jsp"
URL_CAPTCHA_CANDIDATES = JW_CAPTCHA_URLS
HEADERS = HTTP_HEADERS
TIMEOUT = HTTP_TIMEOUT

# ============================================================
# 空教室查询 — 官方"大节"划分(教室课表列头 010203/0405/0607/080910/111213)
# 实测规则: 提交节次范围 [jc1, jc2], 服务端选中"起点节号 ∈ [jc1,jc2]"的大节
# ============================================================
CLASSROOM_SLOTS = [
    # (key, 名称, jc1, jc2, 列头码)
    ("1-3",   "第1-3节",   1,   3,   "010203"),
    ("4-5",   "第4-5节",   4,   5,   "0405"),
    ("6-7",   "第6-7节",   6,   7,   "0607"),
    ("8-10",  "第8-10节",  8,   10,  "080910"),
    ("11-13", "第11-13节", 11,  13,  "111213"),
]


def _dedupe_schedule_courses(courses: list) -> list:
    """去掉跨大节课程在 kbtable 每个大节格产生的重复条目(解析时去重)"""
    seen = set()
    result = []
    for c in courses:
        key = (str(c.get("name", "")), c.get("day"), c.get("start"), c.get("end"),
               str(c.get("weeks", "")), str(c.get("teacher", "")),
               str(c.get("classroom", "")))
        if key in seen:
            continue
        seen.add(key)
        result.append(c)
    return result


def _encrypt_sso_password(password: str, salt: str) -> str:
    """SSO 密码加密（匹配智慧理工前端 encrypt.js encryptPassword 逻辑）

    - 生成 64 位随机字符前缀（吸收 CBC IV 差异）
    - AES-128-CBC 加密，key=salt(UTF-8)，iv=随机16字符(UTF-8)
    - 返回 Base64 密文
    """
    import secrets as _secrets

    chars = "ABCDEFGHJKMNPQRSTWXYZabcdefhijkmnprstwxyz2345678"
    random_prefix = "".join(_secrets.choice(chars) for _ in range(64))
    random_iv = "".join(_secrets.choice(chars) for _ in range(16))

    data = random_prefix + password
    key_bytes = salt.encode("utf-8")[:16].ljust(16, b"\x00")
    iv_bytes = random_iv.encode("utf-8")[:16].ljust(16, b"\x00")

    cipher = AES.new(key_bytes, AES.MODE_CBC, iv_bytes)
    padded = aes_pad(data.encode("utf-8"), AES.block_size)
    encrypted = cipher.encrypt(padded)

    return base64.b64encode(encrypted).decode()


