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
import json
import base64
import time
from typing import Optional, Tuple
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)


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

from config import (
    JW_BASE_8080, JW_BASE_9080, JW_PATH_PREFIX,
    JW_LOGON_PAGE, JW_SCHEDULE_URL, JW_EXAM_QUERY, JW_EXAM_LIST,
    JW_EVAL_PAGE, JW_GRADE_QUERY, JW_GRADE_LIST, JW_CET_LIST,
    JW_APP_DO, JW_CAPTCHA_URLS, BIG_PERIOD_MAP,
    HTTP_TIMEOUT, HTTP_HEADERS,
    SSO_BASE, SSO_LOGIN_URL, DEBUG_WEBVPN,
)

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
URL_MAIN_PAGE = f"{BASE_9080}{JW_PATH_PREFIX}/framework/main.jsp"
URL_CAPTCHA_CANDIDATES = JW_CAPTCHA_URLS
HEADERS = HTTP_HEADERS
TIMEOUT = HTTP_TIMEOUT


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


class JWCClient:
    # 每实例独立的并发锁：同一用户的教务请求串行（保证 Cookie/会话一致性），
    # 不同用户实例互不阻塞（配合 views 的全局信号量限流 = 访问池）
    def __init__(self, pool_maxsize: int = 8):
        import threading
        from requests.adapters import HTTPAdapter
        self._lock = threading.Lock()
        self.session = requests.Session()
        self.session.cookies = _DedupCookieJar()
        self.session.headers.update(HEADERS)
        # HTTP 连接池：复用 keep-alive 连接，减少 TCP/TLS 握手开销
        adapter = HTTPAdapter(pool_connections=pool_maxsize,
                              pool_maxsize=pool_maxsize,
                              pool_block=True)
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)
        self.token = None
        self.student_id = None
        self.student_name = None
        self.logged_in = False
        self.login_method = ""
        self.last_error = ""
        self._captcha_ready = False
        self._active_captcha_url = URL_CAPTCHA_CANDIDATES[0]
        self.debug_log = []  # 智慧理工 SSO 诊断日志
        # 智慧理工手动验证码中间状态
        self._webvpn_manual_ready = False
        self._webvpn_post_url = ""
        self._webvpn_login_page_url = ""
        # 会话有效性探测缓存（避免每个请求都访问教务主页探测）
        self._validity_cache_ts = 0.0
        self._validity_cache_ok = False

    # ================================================================
    # 登录入口
    # ================================================================

    def login(self, student_id: str, password: str) -> bool:
        self.student_id = student_id
        self.last_error = ""
        self.logged_in = False
        self.token = None
        self._captcha_ready = False
        self.session = requests.Session()
        self.session.cookies = _DedupCookieJar()
        self.session.headers.update(HEADERS)

        # 8080 端口 Web 登录 + OCR
        if self._try_web_auto(student_id, password):
            return True

        return False

    # ================================================================
    # 方式1: Web 表单登录（USERNAME + PASSWORD 明文 + 验证码）
    # ================================================================

    def _try_simple_login(self, student_id: str, password: str, captcha: str) -> bool:
        """
        NJUST 真实登录：
        1. POST /Logon.do?method=logon（8080）
        2. 服务器返回 302 → 9080/LoginToXk?method=jwxt&secret=...
        3. 跟随重定向链完成认证
        """
        payload = {
            "USERNAME": student_id,
            "PASSWORD": password,
            "RANDOMCODE": captcha,
            "useDogCode": "",
        }
        try:
            # ★ 用 allow_redirects=True 让 requests 自动跟随整个重定向链
            resp = self.session.post(
                URL_LOGON_PAGE,
                data=payload,
                timeout=TIMEOUT,
                allow_redirects=True,  # ← 自动跟随 302 → 9080 → ...
                headers={"Referer": URL_LOGON_PAGE},
            )
            # ★ 先去重 cookie，否则 dict() 会崩溃
            self._dedupe_cookies()

            logger.debug("[Login] POST → final status=%s final URL=%s",
                         resp.status_code, resp.url[:120])
            logger.debug("[Login] 页面标题: %s", self._page_title(resp))
            for i, h in enumerate(resp.history):
                logger.debug("[Login]   重定向#%d: %s → %s", i,
                             h.status_code, h.headers.get('Location', '')[:80])

            # 只记录 cookie 名称，不输出值（避免会话凭证进入日志）
            ck = [c.name for c in self.session.cookies]
            logger.debug("[Login] cookies: %s", ck)

            # 检查是否登录成功
            if self._check_success(resp):
                self._extract_name(resp.text)
                self.logged_in = True
                self.login_method = "web-auto"
                # ★ 访问 9080 主页巩固 session
                self.session.get(
                    URL_MAIN_PAGE,
                    timeout=TIMEOUT, allow_redirects=True,
                )
                self._dedupe_cookies()
                # 记录 cookie 名称/域名用于排查跨服务器问题，不输出值
                ck_detail = [(c.name, c.domain) for c in self.session.cookies]
                logger.debug("[Login] 登录成功! 共 %d 个 cookie:", len(ck_detail))
                for name, dom in ck_detail:
                    logger.debug("[Login]   %s domain=%s", name, dom)
                return True

            # 检查响应中的错误提示
            t = resp.text.lower()
            if "用户名或密码不能为空" in t or "密码错误" in t:
                self.last_error = "用户名或密码错误"
            elif "验证码" in t and ("错误" in t or "不正确" in t):
                self.last_error = "验证码不正确"
            else:
                self.last_error = "登录失败"
            return False

        except Exception as e:
            logger.debug("[Login] 异常: %s", e)
            return False

    # ================================================================
    # 方式2: Web 登录 + OCR
    # ================================================================

    def _try_web_auto(self, student_id: str, password: str) -> bool:
        """自动 OCR 识别验证码登录"""
        try:
            import ddddocr
            self._init_logon_session()
            ocr = ddddocr.DdddOcr(show_ad=False)

            for i in range(5):
                img = self._fetch_captcha()
                if not img:
                    break
                code = self._ocr_with_preprocess(ocr, img)
                if not code:
                    continue
                logger.debug("[OCR] #%d: '%s'", i + 1, code)

                if self._try_simple_login(student_id, password, code):
                    self.logged_in = True
                    self.login_method = "web-auto"
                    return True

                # 非验证码问题(如密码错误)不必继续 OCR 重试, 保留真实错误信息
                if self.last_error and "验证码" not in self.last_error:
                    break

            # 仅当错误是验证码相关(或未知)时才覆盖为识别失败提示
            if not self.last_error or "验证码" in self.last_error:
                self.last_error = "验证码自动识别失败，请使用手动输入（点「显示验证码」）"
            return False
        except ImportError as e:
            self.last_error = f"OCR 模块加载失败: {e}"
            return False
        except requests.exceptions.ConnectionError:
            self.last_error = "无法连接教务服务器（请检查校园网/VPN）"
            return False
        except Exception as e:
            self.last_error = str(e)
            return False

    # ================================================================
    # 手动验证码流程
    # ================================================================

    def get_captcha_base64(self) -> Tuple[str, str]:
        self._captcha_ready = False
        self.session = requests.Session()
        self.session.cookies = _DedupCookieJar()
        self.session.headers.update(HEADERS)
        try:
            self._init_logon_session()
            img = self._fetch_captcha()
            if not img:
                return "", "获取验证码失败"
            self._captcha_ready = True
            return base64.b64encode(img).decode(), ""
        except Exception as e:
            return "", str(e)

    def login_with_manual_captcha(self, sid: str, pw: str, captcha: str) -> bool:
        self.student_id = sid
        self.last_error = ""
        self.logged_in = False
        self.token = None

        if not self._captcha_ready:
            self.last_error = "会话过期，请重新获取验证码"
            return False

        if self._try_simple_login(sid, pw, captcha.strip()):
            self.logged_in = True
            self.login_method = "web-manual"
            self._captcha_ready = False
            return True

        # 保留 _try_simple_login 检测到的真实原因(如密码错误);
        # 仅当原因未知时兜底为验证码提示
        if not self.last_error or "登录失败" in self.last_error:
            self.last_error = "验证码不正确或已过期，请刷新验证码后重试"
        self._captcha_ready = False
        return False

    # ================================================================
    # 智慧理工 SSO 登录（校外/备用登录方式）
    # ================================================================

    def _log(self, msg: str):
        """记录调试日志（登录失败时可通过接口返回诊断信息）"""
        self.debug_log.append(msg)
        if DEBUG_WEBVPN:
            logger.debug("[SSO] %s", msg)

    def login_webvpn(self, student_id: str, password: str) -> bool:
        """通过智慧理工 SSO 登录 + 直连教务（不走 WebVPN 代理）

        流程：
        1. 直连 SSO（ids.njust.edu.cn）登录验证身份
        2. 尝试直连教务（CAS ticket 自动登录）
        3. 否则走标准 8080 Logon.do 登录 → 302 → 9080 重定向链
        """
        self.student_id = student_id
        self.student_name = None
        self.last_error = ""
        self.logged_in = False
        self.login_method = ""
        self.token = None
        self._captcha_ready = False
        self.debug_log = []
        self.session = requests.Session()
        self.session.cookies = _DedupCookieJar()
        self.session.headers.update(HEADERS)

        if not _HAS_CRYPTO:
            self.last_error = "SSO 登录需要 pycryptodome 模块，请重新部署服务"
            return False

        try:
            # Step 1: 直连 SSO 登录
            if not self._direct_sso_login(student_id, password):
                return False

            # Step 2: 尝试 CAS 自动登录教务
            if self._try_direct_jw_access():
                return True

            # Step 3: 标准 8080 Logon.do 流程
            self._log("[SSO-JW] 教务需要表单登录，走 8080 Logon.do 标准流程...")
            if self._try_web_auto(student_id, password):
                self.logged_in = True
                self.login_method = "webvpn"
                return True

            if not self.last_error:
                self.last_error = "教务系统登录失败，请尝试手动输入验证码"
            return False

        except requests.exceptions.ConnectionError:
            self.last_error = "无法连接教务服务器（请检查网络连接）"
            return False
        except Exception as e:
            self.last_error = f"登录异常: {e}"
            logger.debug("[SSO] 异常: %s", e, exc_info=True)
            return False

    def _direct_sso_login(self, student_id: str, password: str) -> bool:
        """直连 SSO 登录（ids.njust.edu.cn，不走 WebVPN 代理）"""
        from urllib.parse import urljoin

        try:
            # Step D1: GET SSO 登录页 → 解析表单
            self._log(f"[SSO-Direct] Step D1: GET {SSO_LOGIN_URL}")
            resp = self.session.get(SSO_LOGIN_URL, timeout=TIMEOUT, allow_redirects=True)
            self._dedupe_cookies()
            self._log(f"[SSO-Direct]   最终 URL: {resp.url[:120]}")
            self._log(f"[SSO-Direct]   状态={resp.status_code} 标题={self._page_title(resp)}")

            # 已有有效 TGC，直接跳过 SSO 登录页
            if "authserver/login" not in resp.url:
                self._log("[SSO-Direct]   未到达 SSO 登录页（可能已有 TGC）")
                return True

            soup = BeautifulSoup(resp.text, "lxml")
            form = soup.find("form", id="pwdFromId")
            if not form:
                self.last_error = "未找到 SSO 登录表单（ids.njust.edu.cn）"
                self._log(f"[SSO-Direct] [FAIL] {self.last_error}")
                return False

            def _form_val(field_id: str) -> str:
                inp = form.find("input", id=field_id)
                return (inp.get("value") or "").strip() if inp else ""

            execution_val = _form_val("execution")
            salt_val = _form_val("pwdEncryptSalt")
            lt_val = _form_val("lt")

            if not execution_val or not salt_val:
                self.last_error = "获取 SSO 表单字段失败（execution/salt 为空）"
                self._log(f"[SSO-Direct] [FAIL] {self.last_error}")
                return False

            # Step D2: 检查是否需要 SSO 验证码
            need_captcha = False
            sso_captcha_text = ""
            try:
                check_url = f"{SSO_BASE}/authserver/checkNeedCaptcha.htl"
                check_resp = self.session.post(
                    check_url,
                    data={"username": student_id},
                    timeout=TIMEOUT,
                    headers={
                        "Referer": resp.url,
                        "X-Requested-With": "XMLHttpRequest",
                        "Content-Type": "application/x-www-form-urlencoded",
                    },
                )
                need_captcha = check_resp.json().get("isNeed", False)
                self._log(f"[SSO-Direct]   needCaptcha: {need_captcha}")
            except Exception as e:
                self._log(f"[SSO-Direct]   checkNeedCaptcha 失败: {e}")

            # Step D3: OCR SSO 验证码（如需要）
            if need_captcha:
                try:
                    import ddddocr
                    captcha_url = f"{SSO_BASE}/authserver/getCaptcha.htl"
                    cap_resp = self.session.get(
                        captcha_url, timeout=TIMEOUT, headers={"Referer": resp.url})
                    if cap_resp.status_code == 200 and len(cap_resp.content) > 100:
                        ocr = ddddocr.DdddOcr(show_ad=False)
                        sso_captcha_text = ocr.classification(cap_resp.content).strip()
                        self._log(f"[SSO-Direct]   SSO OCR: '{sso_captcha_text}'")
                    else:
                        self._log(f"[SSO-Direct]   验证码获取失败 status={cap_resp.status_code}")
                except ImportError:
                    self.last_error = "SSO 需要验证码但 ddddocr 未安装"
                    return False
                except Exception as e:
                    self._log(f"[SSO-Direct]   SSO 验证码异常: {e}")

            # Step D4: AES 加密密码
            encrypted_pwd = _encrypt_sso_password(password, salt_val)
            self._log(f"[SSO-Direct]   密码已加密 (salt={salt_val})")

            # Step D5: POST SSO 登录
            form_action = (form.get("action") or "").strip()
            if form_action:
                if form_action.startswith("?"):
                    post_url = urljoin(resp.url, form_action)
                elif form_action.startswith("http"):
                    post_url = form_action
                elif form_action.startswith("/"):
                    post_url = f"{SSO_BASE}{form_action}"
                else:
                    post_url = urljoin(resp.url, form_action)
            else:
                post_url = resp.url

            form_data = {
                "username": student_id,
                "passwordText": password,
                "password": encrypted_pwd,
                "captcha": sso_captcha_text if need_captcha else "",
                "rememberMe": "true",
                "_eventId": "submit",
                "cllt": "userNameLogin",
                "dllt": "generalLogin",
                "lt": lt_val,
                "execution": execution_val,
            }

            login_resp = self.session.post(
                post_url, data=form_data, timeout=TIMEOUT,
                allow_redirects=True, headers={"Referer": resp.url})
            self._dedupe_cookies()
            self._log(f"[SSO-Direct]   最终 URL: {login_resp.url[:120]}")
            self._log(f"[SSO-Direct]   状态={login_resp.status_code} "
                      f"标题={self._page_title(login_resp)}")

            # Step D6: 检测登录结果
            t = login_resp.text.lower()
            if "密码错误" in t or "用户名或密码错误" in t or "账号或密码错误" in t:
                self.last_error = "智慧理工账号或密码错误"
                self._log(f"[SSO-Direct] [FAIL] {self.last_error}")
                return False
            if "验证码" in t and ("错误" in t or "不正确" in t):
                self.last_error = "SSO 验证码不正确"
                self._log(f"[SSO-Direct] [FAIL] {self.last_error}")
                return False
            if "用户名或密码不能为空" in t:
                self.last_error = "用户名或密码不能为空"
                self._log(f"[SSO-Direct] [FAIL] {self.last_error}")
                return False

            login_soup = BeautifulSoup(login_resp.text, "lxml")
            if ("authserver/login" in login_resp.url
                    and login_soup.find("form", id="pwdFromId")):
                self.last_error = "SSO 登录失败，请检查智慧理工账号和密码"
                self._log(f"[SSO-Direct] [FAIL] {self.last_error}")
                return False

            self._log("[SSO-Direct] [OK] SSO 登录成功")
            return True

        except requests.exceptions.ConnectionError:
            self.last_error = "无法连接智慧理工 SSO（ids.njust.edu.cn）"
            self._log(f"[SSO-Direct] [FAIL] {self.last_error}")
            return False
        except Exception as e:
            self.last_error = f"SSO 登录异常: {e}"
            self._log(f"[SSO-Direct] [FAIL] {self.last_error}")
            logger.debug("[SSO] 异常: %s", e, exc_info=True)
            return False

    def _try_direct_jw_access(self) -> bool:
        """SSO 登录后尝试通过 CAS ticket 登录教务"""
        from urllib.parse import quote

        candidate_services = [
            f"{BASE_9080}{JW_PATH_PREFIX}/framework/main.jsp",
            f"{BASE_9080}{JW_PATH_PREFIX}/",
            f"{BASE_9080}{JW_PATH_PREFIX}/xk/LoginToXk",
        ]

        for idx, service_url in enumerate(candidate_services):
            try:
                sso_service_url = (
                    f"{SSO_BASE}/authserver/login?service={quote(service_url, safe='')}")
                self._log(f"[SSO-JW] 尝试 CAS service #{idx+1}: {service_url[:100]}")
                resp = self.session.get(sso_service_url, timeout=TIMEOUT, allow_redirects=True)
                self._dedupe_cookies()
                self._log(f"[SSO-JW]   状态={resp.status_code} 标题={self._page_title(resp)}")

                if self._check_success(resp):
                    self._extract_name(resp.text)
                    self.logged_in = True
                    self.login_method = "webvpn"
                    self._log(f"[SSO-JW] [OK] CAS ticket 登录教务成功!")
                    return True

                if self._is_jw_login_page(resp):
                    self._log("[SSO-JW]   教务不支持此 CAS service，返回登录表单")
                elif "authserver" in str(resp.url):
                    self._log("[SSO-JW]   CAS 未重定向（可能 service 未注册）")
            except requests.exceptions.ConnectionError:
                self._log(f"[SSO-JW]   无法连接 (service #{idx+1})")
                continue
            except Exception as e:
                self._log(f"[SSO-JW]   异常 (service #{idx+1}): {e}")
                continue

        # 兜底: 直接访问 main.jsp
        self._log("[SSO-JW] 兜底: 直接访问 main.jsp")
        try:
            resp2 = self.session.get(URL_MAIN_PAGE, timeout=TIMEOUT, allow_redirects=True)
            self._dedupe_cookies()
            if self._check_success(resp2):
                self._extract_name(resp2.text)
                self.logged_in = True
                self.login_method = "webvpn"
                self._log("[SSO-JW] [OK] 直连教务已登录!")
                return True
            self._log("[SSO-JW]   教务未登录，需要表单登录")
        except Exception as e:
            self._log(f"[SSO-JW]   直连异常: {e}")

        return False

    def get_webvpn_captcha_base64(self, student_id: str, password: str):
        """SSO 登录后获取教务 8080 登录验证码（base64）

        返回 (b64, error)；SSO 后已有教务会话时返回 ("__ALREADY_LOGGED_IN__", "")。
        """
        self.student_id = student_id
        self.student_name = None
        self.last_error = ""
        self._webvpn_manual_ready = False
        self._webvpn_post_url = ""
        self._webvpn_login_page_url = ""
        self.debug_log = []
        self.session = requests.Session()
        self.session.cookies = _DedupCookieJar()
        self.session.headers.update(HEADERS)

        if not _HAS_CRYPTO:
            return "", "SSO 登录需要 pycryptodome 模块，请重新部署服务"

        try:
            # Step 1: 直连 SSO 登录
            self._log("[SSO-Captcha] Step 1: 直连 SSO 登录...")
            if not self._direct_sso_login(student_id, password):
                return "", self.last_error

            # Step 2: 尝试 CAS 自动登录教务
            self._log("[SSO-Captcha] Step 2: 尝试直连教务...")
            if self._try_direct_jw_access():
                self._webvpn_manual_ready = True
                return "__ALREADY_LOGGED_IN__", ""

            # Step 3: 从 8080 Logon.do 获取验证码（不清除 SSO cookie）
            self._log("[SSO-Captcha] Step 3: 从 8080 Logon.do 获取验证码...")
            self.session.get(URL_LOGON_PAGE, timeout=TIMEOUT)
            self.session.headers.update({"Referer": URL_LOGON_PAGE})
            self._dedupe_cookies()
            self._detect_captcha_url_from_page()
            try:
                self.session.get(URL_LOGON_SESS, timeout=TIMEOUT)
                self._dedupe_cookies()
            except Exception:
                pass

            img = self._fetch_captcha()
            if not img:
                return "", "获取验证码失败：无法从教务服务器获取验证码图片"

            self._webvpn_manual_ready = True
            self._webvpn_login_page_url = URL_LOGON_PAGE
            self._webvpn_post_url = URL_LOGON_PAGE
            self._log(f"[SSO-Captcha] [OK] 验证码就绪 ({len(img)} bytes)")
            return base64.b64encode(img).decode(), ""

        except requests.exceptions.ConnectionError:
            return "", "无法连接教务服务器（请检查网络连接）"
        except Exception as e:
            logger.debug("[SSO] 异常: %s", e, exc_info=True)
            return "", str(e)

    def complete_webvpn_login(self, student_id: str, password: str,
                              captcha: str) -> bool:
        """使用手动输入的验证码完成教务登录（标准 8080 Logon.do 流程）"""
        if not self._webvpn_manual_ready:
            self.last_error = "会话已过期，请重新获取验证码"
            return False

        self.student_id = student_id
        self.student_name = None
        self.last_error = ""
        self.logged_in = False
        self.login_method = ""

        try:
            self._log("[SSO-Login] 使用手动验证码完成 8080 标准登录...")
            if self._try_simple_login(student_id, password, captcha.strip()):
                self.logged_in = True
                self.login_method = "webvpn"
                self._log("[SSO-Login] [OK] 登录成功!")
                return True

            if not self.last_error:
                self.last_error = "教务系统登录失败，请重新获取验证码重试"
            return False
        except Exception as e:
            self._log(f"[SSO-Login] 异常: {e}")
            logger.debug("[SSO] 异常: %s", e, exc_info=True)
            self.last_error = f"登录异常: {e}"
            return False

    def _is_jw_login_page(self, resp) -> bool:
        """检测是否为教务登录页面（强智教务）"""
        t = resp.text.lower()
        url = resp.url.lower() if hasattr(resp, 'url') else ""
        indicators = [
            "Logon.do" in url,
            "Verifyservlet" in t,
            "verifycode.servlet" in t,
            ("USERNAME" in t and "PASSWORD" in t and "RANDOMCODE" in t),
        ]
        return any(indicators)

    # ================================================================
    # 核心方法
    # ================================================================

    def _init_logon_session(self):
        self.session.cookies.clear()
        self.session.get(URL_LOGON_PAGE, timeout=TIMEOUT)
        self.session.headers.update({"Referer": URL_LOGON_PAGE})
        self._dedupe_cookies()
        self._detect_captcha_url_from_page()
        try:
            self.session.get(URL_LOGON_SESS, timeout=TIMEOUT)
            self._dedupe_cookies()
        except Exception:
            pass

    def _detect_captcha_url_from_page(self):
        try:
            resp = self.session.get(URL_LOGON_PAGE, timeout=TIMEOUT)
            m = re.search(
                r'<img[^>]+src=["\']([^"\']*(?:verifycode|checkcode|code)[^"\']*)["\']',
                resp.text, re.IGNORECASE)
            if m:
                src = m.group(1)
                self._active_captcha_url = src if src.startswith("http") else f"{BASE_URL}{src}"
                logger.debug("CaptchaURL: %s", self._active_captcha_url)
        except Exception:
            pass

    def _fetch_captcha(self) -> bytes:
        for url in [self._active_captcha_url] + URL_CAPTCHA_CANDIDATES:
            try:
                r = self.session.get(url, timeout=TIMEOUT)
                self._dedupe_cookies()
                if r.status_code == 200 and len(r.content) > 100:
                    self._active_captcha_url = url
                    return r.content
            except Exception:
                continue
        return b""

    def _dedupe_cookies(self):
        """按域名去重 JSESSIONID：每个 (domain, path) 只保留最后一个。
        之前 jar.clear() 全清的写法会误删不同服务器的 cookie，
        导致 .112 和 .113 的 JSESSIONID 被合并成只剩一个。"""
        jar = self.session.cookies
        # 按 (domain, path) 分组
        groups = {}
        for c in jar:
            if c.name == "JSESSIONID":
                key = (c.domain or "", c.path or "")
                groups.setdefault(key, []).append(c)
        for key, cookies in groups.items():
            if len(cookies) > 1:
                # 每个 (domain, path) 只保留最后一个
                for c in cookies[:-1]:
                    jar.clear(c.domain, c.path, c.name)

    def _ocr_with_preprocess(self, ocr, data: bytes) -> str:
        """多候选预处理提高识别率: 原图 → 二值化 → 2x放大 → 反色。

        每个候选分别识别, 取第一个非空结果; 验证码可能白底黑字
        或深底浅字, 反色候选覆盖后一种情况。
        """
        cands = [data]
        try:
            from PIL import Image
            from io import BytesIO
            img = Image.open(BytesIO(data)).convert("L")
            bw = img.point(lambda x: 0 if x < 140 else 255, "1")
            b = BytesIO(); bw.save(b, format="PNG"); cands.append(b.getvalue())
            big = img.resize((img.width * 2, img.height * 2), Image.LANCZOS)
            b2 = BytesIO(); big.save(b2, format="PNG"); cands.append(b2.getvalue())
            inv = img.point(lambda x: 255 - x)
            b3 = BytesIO(); inv.save(b3, format="PNG"); cands.append(b3.getvalue())
        except Exception:
            pass
        for c in cands:
            r = ocr.classification(c).strip()
            if r:
                return r
        return ""

    def _check_success(self, resp) -> bool:
        t = resp.text
        # 明确的失败标记
        for kw in ["验证码错误", "密码错误", "账号错误", "用户不存在"]:
            if kw in t:
                return False
        # 检测是教务登录页面（而非已登录状态）
        if self._is_jw_login_page(resp):
            return False
        # 明确的成功标记
        for kw in ["课程表", "学期理论课表", "学生首页", "学生个人中心",
                    "xs_main", "framemain", "安全退出", "退出系统"]:
            if kw in t:
                return True
        # URL fallback：登录页地址视为失败，SSO 登录页也视为失败
        url_str = resp.url if hasattr(resp, 'url') else ""
        if "Logon.do" in url_str:
            return False
        return "authserver" not in url_str

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

    def get_schedule(self, semester: str = "", week: int = 0) -> list[dict]:
        if not self.logged_in:
            self.last_error = "未登录"
            return []
        courses = self._schedule_api(semester, week) or self._schedule_html(semester)
        if courses:
            self.last_error = ""   # 成功获取后清除 API 失败的残留错误
        return _dedupe_schedule_courses(courses)

    def _schedule_api(self, semester: str, week: int) -> list[dict]:
        try:
            if not semester:
                semester = self._current_semester()
            params = {"method": "getKbcxAzc", "xh": self.student_id, "xnxqid": semester}
            if week > 0:
                params["zc"] = str(week)
            resp = self.session.post(
                URL_APP_DO, params=params,
                headers={"token": self.token} if self.token else {},
                timeout=TIMEOUT)
            data = resp.json()
            items = data if isinstance(data, list) else data.get("data", [])
            if not isinstance(items, list):
                self.last_error = "课表API返回格式异常"
                return []
            return self._parse_schedule(items)
        except Exception as e:
            # 记录失败原因(供诊断: API 经常失败导致降级 HTML, 而 HTML 默认学期)
            self.last_error = f"课表API失败: {e}"
            return []

    def _post_schedule_semester(self, soup, url: str, semester: str):
        """通过课表页面的学期下拉表单提交目标学期, 返回响应或 None。

        强智课表列表页通常带学期 select; 直接 GET 只显示教务默认学期,
        指定学期时必须走表单提交, 否则不同学期会拿到同一份默认课表。
        """
        try:
            form = soup.find("form")
            if not form:
                return None
            form_data = {}
            for inp in form.find_all("input"):
                n, v = inp.get("name", ""), inp.get("value", "")
                if n:
                    form_data[n] = v
            found_select = False
            for sel in form.find_all("select"):
                n = sel.get("name", "")
                if not n:
                    continue
                matched = None
                for opt in sel.find_all("option"):
                    ov = opt.get("value", "")
                    if semester and semester in ov:
                        matched = ov
                        break
                if matched:
                    form_data[n] = matched
                    found_select = True
                else:
                    s = sel.find("option", selected=True)
                    form_data[n] = s.get("value", "") if s else ""
            if not found_select:
                return None
            action = form.get("action", "")
            if action:
                if action.startswith("/"):
                    target = f"{BASE_9080}{action}"
                elif action.startswith("http"):
                    target = action
                else:
                    target = f"{BASE_9080}/njlgdx/xskb/{action}"
            else:
                target = url
            logger.debug("[课表] 提交学期 %s → %s", semester, target[:80])
            resp = self.session.post(target, data=form_data, timeout=TIMEOUT,
                                     allow_redirects=True)
            if resp.status_code == 200 and len(resp.text) > 2000:
                return resp
            return None
        except Exception as e:
            logger.debug("[课表] 学期表单提交失败: %s", e)
            return None

    def _schedule_html(self, semester: str) -> list[dict]:
        """NJUST 课表 HTML 解析 — 从主页链接获取正确的 Ves632DSdyV 参数

        指定学期时优先通过页面学期下拉提交目标学期, 避免拿到
        教务默认学期的课表(不同学期内容相同的问题)。
        """
        def _parse_soup(soup):
            # 合并两个表格：kbtable(周次/教室) + dataList(精确小节)
            grid = soup.find("table", id="kbtable")
            data_table = soup.find("table", id="dataList")
            if grid and data_table:
                courses = self._parse_merged(grid, data_table)
                if courses:
                    return courses
            if data_table:
                courses = self._parse_datalist(data_table)
                if courses:
                    return courses
            if grid:
                courses = self._parse_kbtable(grid, {})
                if courses:
                    return courses
            return None

        try:
            # Debug: 看看当前 cookie 状态（含域名，不含值）
            cks = [(c.name, c.domain) for c in self.session.cookies]
            logger.debug("[课表] 请求前 cookies (%d个): %s", len(cks), cks)

            # 先访问主页，提取课表链接中的 Ves632DSdyV 参数
            main_resp = self.session.get(
                URL_MAIN_PAGE,
                timeout=TIMEOUT, allow_redirects=True,
            )
            logger.debug("[课表] 主页 GET → status=%s title=%s",
                         main_resp.status_code, self._page_title(main_resp))
            real_schedule_url = URL_SCHEDULE_HTML  # 默认
            m = re.search(r'xskb/xskb_list\.do\?([^"\']+)', main_resp.text)
            if m:
                real_schedule_url = f"{BASE_9080}/njlgdx/xskb/xskb_list.do?{m.group(1)}"
                logger.debug("[课表] 从主页提取真实URL参数: %s", m.group(1)[:50])

            resp = self.session.get(real_schedule_url, timeout=TIMEOUT, allow_redirects=True)
            logger.debug("[课表] GET → status=%s len=%d title=%s",
                         resp.status_code, len(resp.text), self._page_title(resp))

            if resp.status_code != 200 or len(resp.text) < 2000:
                self.last_error = "课表页面访问失败，请重新登录"
                return []

            soup = BeautifulSoup(resp.text, "lxml")

            # ★ 指定学期时: 优先通过页面学期下拉提交目标学期
            #   (直接 GET 只显示教务默认学期, 会导致不同学期拿到同一份课表)
            if semester:
                posted = self._post_schedule_semester(soup, real_schedule_url, semester)
                if posted is not None:
                    resp = posted
                    soup = BeautifulSoup(resp.text, "lxml")

            courses = _parse_soup(soup)
            if courses:
                logger.debug("[课表] 解析完成: %d 条 (semester=%s)", len(courses), semester)
                return courses

            self.last_error = "课表表格未找到"
            return []
        except Exception as e:
            logger.debug("[课表HTML] %s", e, exc_info=True)
            return []

    def _parse_datalist(self, table) -> list[dict]:
        """解析 dataList 表格"""
        courses = []
        rows = table.find_all("tr")
        for row in rows[1:]:  # 跳过表头
            cells = row.find_all("td")
            if len(cells) < 10:
                continue
            texts = [c.get_text(strip=True) for c in cells]

            course_name = texts[3]  # 课程名称
            teacher = texts[4]      # 教师
            time_text = texts[5]    # 时间（如 "星期二(04-05小节)<br/>星期五(08-09小节)"）
            credits = texts[6]      # 学分
            location_text = texts[7]  # 地点
            course_type = texts[8]  # 课程属性

            if not course_name:
                continue

            # 解析时间列：从原始 HTML 中用正则提取所有 "星期X(数字-数字小节)"
            raw_time = str(cells[5])
            raw_loc = str(cells[7])
            time_matches = re.findall(
                r'星期([一二三四五六日])\((\d+)-(\d+)小节\)', raw_time)
            # 从原始 HTML 按 <br> 分割取教室
            loc_splits = re.split(r'<br\s*/?>|</br>', raw_loc)
            location_list = []
            for s in loc_splits:
                txt = re.sub(r'<[^>]+>', '', s).strip()
                if txt:
                    location_list.append(txt)
            # 如果没解析到，降级用逗号分割
            if not location_list:
                location_list = [l.strip() for l in re.split(r'[,，]',
                    cells[7].get_text(strip=True)) if l.strip()]

            day_map = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "日": 7}
            for i, (day_char, start_str, end_str) in enumerate(time_matches):
                day = day_map.get(day_char, 0)
                start = int(start_str)
                end = int(end_str)
                loc = location_list[i] if i < len(location_list) else ""
                if not loc and location_list:
                    loc = location_list[0]  # 如果教室不够分配，用第一个

                courses.append({
                    "name": course_name,
                    "teacher": teacher,
                    "classroom": loc,
                    "day": day,
                    "start": start,
                    "end": end,
                    "weeks": "",
                    "week_type": 0,
                    "credits": credits,
                    "course_type": course_type,
                    "raw": dict(zip(
                        ["num", "course_id", "class_seq", "name", "teacher",
                         "time", "credits", "location", "type", "stage"],
                        texts
                    )),
                })

        logger.debug("[课表] dataList 解析完成: %d 条", len(courses))
        return courses

    def _parse_merged(self, grid, data_table) -> list[dict]:
        """
        合并 kbtable（周次/教室/教师） + dataList（精确小节/学分/类型）
        kbtable 有正确的周次和教室分配，dataList 有精准的小节号
        """
        # Step 1: 从 dataList 提取精确小节信息
        day_map = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "日": 7}
        period_info = {}  # {(name, day): (start, end, credits, course_type)}
        dl_rows = data_table.find_all("tr")
        for row in dl_rows[1:]:
            cells = row.find_all("td")
            if len(cells) < 9:
                continue
            name = cells[3].get_text(strip=True)
            credits = cells[6].get_text(strip=True)
            ctype = cells[8].get_text(strip=True)
            raw_time = str(cells[5])
            matches = re.findall(r'星期([一二三四五六日])\((\d+)-(\d+)小节\)', raw_time)
            for day_char, s, e in matches:
                d = day_map.get(day_char, 0)
                period_info[(name, d)] = (int(s), int(e), credits, ctype)

        # Step 2: 从 kbtable 提取课程条目（含周次、教室），用 period_info 补小节
        # 大节 → 小节（粗略，period_info 会覆盖）
        block_map = BIG_PERIOD_MAP
        rows = grid.find_all("tr")
        # 解析列映射
        hdr = rows[0].find_all(["td", "th"])
        col_day = {}
        for i, c in enumerate(hdr):
            for d, n in enumerate("一二三四五六日", 1):
                if n in c.get_text():
                    col_day[i] = d
                    break

        courses = []
        for row in rows[1:]:
            cells = row.find_all(["td", "th"])
            if len(cells) < 2:
                continue
            # 大节标签
            label = cells[0].get_text(strip=True)
            rough = None
            for k, v in block_map.items():
                if k in label:
                    rough = v
                    break
            if not rough:
                continue

            for ci, cell in enumerate(cells[1:], 1):
                if ci not in col_day:
                    continue
                day = col_day[ci]

                # 找详细 div
                for div in cell.find_all("div", class_="kbcontent"):
                    raw = str(div)
                    entries = re.split(r'-{10,}', raw)
                    for entry in entries:
                        if not entry.strip() or '&nbsp;' in entry:
                            continue
                        soup = BeautifulSoup(entry, "lxml")
                        lines = [l.strip() for l in soup.get_text("\n", strip=True).split("\n") if l.strip()]
                        if len(lines) < 2:
                            continue
                        name = lines[0]

                        # ★ 用 font title 属性提取
                        teacher = weeks = classroom = ""
                        for ft in soup.find_all("font"):
                            t = ft.get("title", "")
                            v = ft.get_text(strip=True)
                            if "老师" in t or "教师" in t:
                                teacher = v
                            elif "周次" in t:
                                weeks = v.replace("(周)", "").strip()
                            elif "教室" in t:
                                classroom = v
                            elif "分组名" in t and not teacher:
                                teacher = v

                        if not name or name == '\xa0':
                            continue

                        # ★ 从 period_info 获取精确小节
                        p_start, p_end = rough
                        credits = ctype = ""
                        exact = period_info.get((name, day))
                        if exact:
                            p_start, p_end, credits, ctype = exact

                        courses.append({
                            "name": name,
                            "teacher": teacher,
                            "classroom": classroom,
                            "day": day,
                            "start": p_start,
                            "end": p_end,
                            "weeks": weeks,
                            "week_type": 0,
                            "credits": credits,
                            "course_type": ctype,
                            "raw": {},
                        })

        return courses

    def _parse_kbtable(self, table, period_info: dict = None) -> list[dict]:
        """
        解析视觉课表 kbtable — 包含完整的周次、教室、教师信息
        结构：每行=一个大节，每列=星期几，kbcontent div 内含详细课程信息
        """
        courses = []
        rows = table.find_all("tr")
        if len(rows) < 2:
            return []

        # 表头解析星期列映射
        hdr = rows[0].find_all(["td", "th"])
        day_map = {}
        for i, c in enumerate(hdr):
            for d, n in enumerate("一二三四五六日", 1):
                if n in c.get_text():
                    day_map[i] = d
                    break
        logger.debug("[kbtable] 列映射: %s", day_map)

        # 大节 → 小节映射（从 th 文本提取）
        # NJUST 大节 → 小节映射
        # 上午8:00起, 下午14:00起, 晚上19:00起
        # 大节内小节间隔5min, 大节间隔15min
        period_map = BIG_PERIOD_MAP

        for row in rows[1:]:
            cells = row.find_all(["td", "th"])
            if len(cells) < 2:
                continue

            # 第一列是时段标签
            period_label = cells[0].get_text(strip=True)
            period_range = None
            for key, val in period_map.items():
                if key in period_label:
                    period_range = val
                    break
            if not period_range:
                continue
            p_start, p_end = period_range

            # 遍历每天
            for ci, cell in enumerate(cells[1:], 1):
                if ci not in day_map:
                    continue
                day = day_map[ci]

                # 取详细 div（class="kbcontent"，不是 kbcontent1）
                detail_divs = cell.find_all("div", class_="kbcontent")
                for div in detail_divs:
                    # 用 --------------------- 分割多个课程条目
                    raw = str(div)
                    entries = re.split(r'-{10,}', raw)
                    for entry in entries:
                        if not entry.strip() or '&nbsp;' in entry:
                            continue
                        soup = BeautifulSoup(entry, "lxml")
                        # 获取纯文本第一行作为课程名
                        text = soup.get_text("\n", strip=True)
                        lines = [l.strip() for l in text.split("\n") if l.strip()]
                        if len(lines) < 2:
                            continue
                        name = lines[0]

                        # ★ 用 font 标签的 title 属性提取各字段
                        teacher = ""
                        weeks = ""
                        classroom = ""
                        for font_tag in soup.find_all("font"):
                            title_attr = font_tag.get("title", "")
                            val = font_tag.get_text(strip=True)
                            if "老师" in title_attr or "教师" in title_attr:
                                teacher = val
                            elif "周次" in title_attr:
                                weeks = val.replace("(周)", "").strip()
                            elif "教室" in title_attr:
                                classroom = val
                            elif "分组名" in title_attr:
                                if not teacher:
                                    teacher = val

                        if name and name != '\xa0':
                            # 从 dataList 获取精确小节号
                            if period_info:
                                exact = period_info.get((name, day))
                                if exact:
                                    p_start, p_end = exact

                            courses.append({
                                "name": name,
                                "teacher": teacher,
                                "classroom": classroom,
                                "day": day,
                                "start": p_start,
                                "end": p_end,
                                "weeks": weeks,
                                "week_type": 0,
                                "credits": "",
                                "course_type": "",
                                "raw": {},
                            })

        return courses

    def _parse_schedule(self, items: list) -> list[dict]:
        courses = []
        for item in items:
            if not isinstance(item, dict):
                continue
            kcsj = str(item.get("kcsj", ""))
            d = s = e = 0
            if len(kcsj) >= 5:
                try:
                    d = int(kcsj[0]); s = int(kcsj[1:3]); e = int(kcsj[3:5])
                except ValueError:
                    pass
            sjbz = str(item.get("sjbz", "0"))
            wt = 1 if sjbz == "1" else (2 if sjbz == "2" else 0)
            courses.append({
                "name": str(item.get("kcmc", "")).strip(),
                "teacher": str(item.get("jsxm", "") or item.get("jsm", "")).strip(),
                "classroom": str(item.get("jsmc", "") or item.get("jsm", "")).strip(),
                "day": d, "start": s, "end": e,
                "weeks": str(item.get("kkzc", "") or item.get("zcsm", "")),
                "week_type": wt,
                "credits": item.get("xf", ""),
                "course_type": str(item.get("kclb", "") or item.get("kcType", "")).strip(),
                "raw": item,
            })
        return courses

    # ================================================================
    # 考试
    # ================================================================

    def get_exams(self, semester: str = "") -> list[dict]:
        if not self.logged_in:
            self.last_error = "未登录"
            return []
        # 先尝试 API，失败则降级到 HTML（API 空结果也降级, HTML 能识别"暂无考试"）
        result = self._exams_api(semester)
        if result:
            return result
        # API 失败是预期的（NJUST 可能不支持），清除错误信息
        self.last_error = ""
        return self._exams_html(semester)

    def _exams_api(self, semester: str) -> list[dict]:
        try:
            if not semester:
                semester = self._current_semester()
            resp = self.session.post(
                URL_APP_DO,
                params={"method": "getXsksap", "xh": self.student_id, "xnxqid": semester},
                headers={"token": self.token} if self.token else {},
                timeout=TIMEOUT)
            data = resp.json()
            items = data if isinstance(data, list) else data.get("data", [])
            if not isinstance(items, list):
                return []
            exams = []
            for it in items:
                if not isinstance(it, dict):
                    continue
                exams.append({
                    "course_name": str(it.get("kcmc", "")).strip(),
                    "date": str(it.get("ksrq", "") or it.get("examDate", "")).strip(),
                    "time": str(it.get("kssj", "") or it.get("examTime", "")).strip(),
                    "location": str(it.get("ksdd", "") or it.get("examRoom", "")).strip(),
                    "seat": str(it.get("zwh", "") or it.get("seatNum", "")).strip(),
                    "type": str(it.get("kslx", "") or "期末考试").strip(),
                })
            return exams
        except Exception as e:
            self.last_error = f"考试API请求失败: {e}"
            return []

    def _exams_html(self, semester: str) -> list[dict]:
        """解析考试安排列表页面（HTML 表格）
        流程：查询页提交表单 → 列表页显示数据
        表格结构：序号 | 考试场次 | 课程编号 | 课程名称 | 考试时间 | 考场 | 座位号
        """
        def _parse_table(soup):
            """返回 None=未找到考试表格; list=找到标准表格(可能为空, 空即"暂无考试")"""
            # 候选表格: 优先标准 id/class, 其次任意表头匹配考试关键字的表格
            candidates = []
            t = soup.find("table", id="dataList")
            if t:
                candidates.append(t)
            t = soup.find("table", class_="Nsb_r_list")
            if t:
                candidates.append(t)
            for tbl in soup.find_all("table"):
                if tbl in candidates:
                    continue
                head_text = " ".join(
                    c.get_text(strip=True) for c in (tbl.find("tr") or []) if c)
                if any(kw in head_text for kw in ("考试", "课程名称", "考场")):
                    candidates.append(tbl)

            for t in candidates:
                rows = t.find_all("tr")[1:]
                exams = []
                for row in rows:
                    cells = row.find_all(["td", "th"])
                    if len(cells) < 6:
                        continue
                    texts = [c.get_text(strip=True) for c in cells]
                    course_name = texts[3] if len(texts) > 3 else ""
                    if not course_name:
                        continue
                    raw_time = texts[4] if len(texts) > 4 else ""
                    if " " in raw_time:
                        parts = raw_time.split(" ", 1)
                        date, time = parts[0].strip(), parts[1].strip()
                    else:
                        date, time = raw_time, ""
                    exams.append({
                        "course_name": course_name,
                        "date": date,
                        "time": time,
                        "location": texts[5] if len(texts) > 5 else "",
                        "seat": texts[6] if len(texts) > 6 else "",
                        "type": "期末考试",
                    })
                # 找到标准考试表格: 无论有无数据行都算解析成功(空=暂无考试)
                return exams
            return None

        try:
            # 策略1：先访问查询页，获取表单，提交查询
            resp = self.session.get(URL_EXAM_QUERY, timeout=TIMEOUT)
            soup = BeautifulSoup(resp.text, "lxml")
            # 查找表单
            form = soup.find("form")
            if form:
                action = form.get("action", "")
                form_data = {}
                for inp in form.find_all("input"):
                    name = inp.get("name", "")
                    value = inp.get("value", "")
                    if name:
                        form_data[name] = value
                for sel in form.find_all("select"):
                    name = sel.get("name", "")
                    if name:
                        # 选中学期对应的 option
                        selected = sel.find("option", selected=True)
                        options = sel.find_all("option")
                        if options:
                            # 优先匹配当前学期
                            matched = None
                            for opt in options:
                                v = opt.get("value", "")
                                if semester and semester in v:
                                    matched = v
                                    break
                            if matched:
                                form_data[name] = matched
                            elif selected:
                                form_data[name] = selected.get("value", "")
                            else:
                                form_data[name] = options[0].get("value", "")
                # 如果有 action，构造完整 URL
                if action:
                    if action.startswith("/"):
                        target_url = f"{BASE_9080}{action}"
                    elif action.startswith("http"):
                        target_url = action
                    else:
                        target_url = f"{BASE_9080}/njlgdx/xsks/{action}"
                else:
                    target_url = URL_EXAM_LIST
                resp = self.session.post(target_url, data=form_data, timeout=TIMEOUT)
            else:
                # 没有表单，可能直接重定向了
                resp = self.session.get(URL_EXAM_LIST, timeout=TIMEOUT)

            soup = BeautifulSoup(resp.text, "lxml")
            result = _parse_table(soup)
            if result is not None:
                return result

            # 策略2：直接 POST 学期参数到列表页
            resp = self.session.post(URL_EXAM_LIST,
                data={"xnxqid": semester, "method": "query"},
                timeout=TIMEOUT)
            soup = BeautifulSoup(resp.text, "lxml")
            result = _parse_table(soup)
            if result is not None:
                return result

            # 策略3：GET 列表页（可能查询页已设置会话状态）
            resp = self.session.get(URL_EXAM_LIST, timeout=TIMEOUT)
            soup = BeautifulSoup(resp.text, "lxml")
            result = _parse_table(soup)
            if result is not None:
                return result

            # 全部失败，诊断（记录各表格结构, 便于排查"暂无考试"还是"解析失败"）
            title = soup.find("title")
            page_title = title.get_text(strip=True) if title else "无标题"
            has_login = "logon" in resp.text.lower() or "登录" in resp.text
            form_count = len(soup.find_all("form"))
            table_count = len(soup.find_all("table"))
            logger.info("[考试HTML] 未找到数据表格")
            logger.info("  页面标题: %s", page_title)
            logger.info("  响应长度: %d", len(resp.text))
            logger.info("  表单数量: %d, 表格数量: %d", form_count, table_count)
            logger.info("  疑似登录页: %s", has_login)
            diag_parts = []
            for ti, tbl in enumerate(soup.find_all("table")):
                trs = tbl.find_all("tr")
                head = " | ".join(
                    c.get_text(strip=True) for c in trs[0].find_all(["td", "th"])
                )[:80] if trs else "(空表)"
                rows_text = " | ".join(
                    c.get_text(strip=True)
                    for c in (trs[1].find_all(["td", "th"]) if len(trs) > 1 else [])
                )[:80]
                logger.info("  表格#%d id=%s class=%s 行数=%d 表头=[%s] 首行=[%s]",
                            ti, tbl.get("id", "-"), tbl.get("class", "-"),
                            len(trs), head, rows_text)
                diag_parts.append(
                    f"表格#{ti} id={tbl.get('id', '-')} 行数={len(trs)} 表头=[{head}]")
            if has_login:
                self.last_error = "考试页面需要重新登录，请先在设置页登录"
            else:
                # 诊断摘要随错误返回, 前端 toast 可见
                self.last_error = ("考试解析失败（页面标题=%s）：%s" % (
                    page_title, "；".join(diag_parts))) if diag_parts else \
                    f"考试页面解析失败（表格数={table_count}），可能本学期暂无考试"
            return []
        except Exception as e:
            self.last_error = f"考试HTML解析失败: {e}"
            return []

    # ================================================================
    # 工具
    # ================================================================

    def _current_semester(self) -> str:
        """计算当前学期（强制使用北京时间，不依赖容器系统时区）

        NJUST 秋季学期 8 月下旬开学: 8 月 20 日起视为秋季学期,
        否则按传统 9 月/2 月边界。
        """
        import datetime as _dt
        now = _dt.datetime.now(_dt.timezone(_dt.timedelta(hours=8)))
        y, m, d = now.year, now.month, now.day
        if m >= 9 or (m == 8 and d >= 20):
            return f"{y}-{y+1}-1"
        elif m >= 2:
            return f"{y-1}-{y}-2"
        else:
            return f"{y-1}-{y}-1"

    def get_semester_list(self) -> list[str]:
        cur = self._current_semester()
        try:
            by = int(cur.split("-")[0])
        except Exception:
            by = 2025
        return [f"{y}-{y+1}-{s}" for y in range(by-2, by+3) for s in (1, 2)]

    # ================================================================
    # 教学评价
    # ================================================================

    def get_evaluations(self, semester: str = "") -> list[dict]:
        """获取教学评价列表"""
        if not self.logged_in:
            self.last_error = "未登录"
            return []
        return self._eval_html(semester)

    def _eval_html(self, semester: str = "") -> list[dict]:
        """解析教学评价页面
        表格结构：序号 | 学年学期 | 评价分类 | 评价批次 | 开始时间 | 结束时间 | 是否已完成 | 操作
        """
        try:
            resp = self.session.get(URL_EVAL_PAGE, timeout=TIMEOUT)
            soup = BeautifulSoup(resp.text, "lxml")
            table = soup.find("table", class_="Nsb_r_list")
            if not table:
                self.last_error = "评价页面未找到数据表格"
                return []
            rows = table.find_all("tr")[1:]
            evals = []
            for row in rows:
                cells = row.find_all("td")
                if len(cells) < 7:
                    continue
                texts = [c.get_text(strip=True) for c in cells]
                batch_name = texts[3] if len(texts) > 3 else ""
                if not batch_name:
                    continue
                start_date = texts[4] if len(texts) > 4 else ""
                end_date = texts[5] if len(texts) > 5 else ""
                is_done = texts[6] if len(texts) > 6 else ""
                items = []
                if len(cells) > 7:
                    for a in cells[7].find_all("a"):
                        items.append({
                            "name": a.get_text(strip=True),
                            "url": a.get("href", ""),
                        })
                evals.append({
                    "semester": texts[1] if len(texts) > 1 else "",
                    "category": texts[2] if len(texts) > 2 else "",
                    "batch": batch_name,
                    "start_date": start_date,
                    "end_date": end_date,
                    "is_done": is_done == "是",
                    "items": items,
                })
            return evals
        except Exception as e:
            self.last_error = f"评价解析失败: {e}"
            return []

    def is_session_valid(self, cache_ttl: float = 300.0) -> bool:
        """检测 NJUST 教务 Session 是否仍然有效（轻量级检查）。

        - 结果缓存: 明确结论缓存 5 分钟; 探测无结论(网络/网关异常)
          只缓存 60 秒, 尽快重试
        - 只有「页面明确显示登录表单」才判定会话过期;
          网络故障/网关异常不踢人(实际数据请求失败时再提示重新登录)
        """
        if not self.logged_in:
            return False
        now = time.time()
        ttl = getattr(self, "_validity_cache_ttl", cache_ttl)
        if now - self._validity_cache_ts < ttl:
            return self._validity_cache_ok
        decided = True
        try:
            # 短超时探测: 教务无响应时保守信任现有会话(不踢人), 不拖慢数据请求
            resp = self.session.get(URL_MAIN_PAGE, timeout=5, allow_redirects=True)
            self._dedupe_cookies()
            if resp.status_code == 200:
                t = resp.text.lower()
                if "logon.do" in t or "userrname" in t or "randmcode" in t:
                    ok = False   # 明确过期: 返回了登录表单
                else:
                    ok = True
            else:
                ok = True        # 网关/服务器异常: 探测无结论, 保守不踢人
                decided = False
        except Exception:
            ok = True            # 网络故障: 探测无结论, 保守不踢人
            decided = False
        self._validity_cache_ts = now
        self._validity_cache_ok = ok
        self._validity_cache_ttl = 300.0 if decided else 60.0
        return ok

    def test_connection(self, timeout: float = None) -> Tuple[bool, str]:
        """教务连通性探测（可指定短超时, 避免阻塞调用方接口响应）"""
        try:
            r = self.session.get(URL_LOGON_PAGE, timeout=timeout or TIMEOUT)
            return (True, "连接正常") if r.status_code == 200 else (False, f"{r.status_code}")
        except requests.exceptions.ConnectionError:
            return False, "无法连接，请确认校园网/VPN"
        except Exception as e:
            return False, str(e)

    # ================================================================
    # 成绩查询
    # ================================================================

    def get_grades(self, semester: str = "") -> list[dict]:
        """获取成绩数据"""
        if not self.logged_in:
            self.last_error = "未登录"
            return []
        # 先尝试 API，失败则降级到 HTML（API 空结果也降级）
        result = self._grades_api(semester)
        if result:
            return result
        self.last_error = ""
        return self._grades_html(semester)

    def _grades_api(self, semester: str) -> list[dict]:
        """通过 app.do API 获取成绩"""
        try:
            if not semester:
                semester = self._current_semester()
            resp = self.session.post(
                URL_APP_DO,
                params={"method": "getCjcx", "xh": self.student_id, "xnxqid": semester},
                headers={"token": self.token} if self.token else {},
                timeout=TIMEOUT,
            )
            data = resp.json()
            items = data if isinstance(data, list) else data.get("data", [])
            if not isinstance(items, list):
                return []
            grades = []
            for it in items:
                if not isinstance(it, dict):
                    continue
                grades.append({
                    "academic_year": str(it.get("xn", "") or it.get("xnm", "")).strip(),
                    "semester": str(it.get("xq", "") or it.get("xqm", "")).strip(),
                    "course_code": str(it.get("kcdm", "") or it.get("kch", "")).strip(),
                    "course_name": str(it.get("kcmc", "")).strip(),
                    "score": str(it.get("cj", "") or it.get("kscj", "")).strip(),
                    "credit": self._to_float(it.get("xf", 0)),
                    "grade_point": self._to_float(it.get("jd", 0) or it.get("jdn", 0)),
                    "course_type": str(it.get("kclb", "") or it.get("kclbmc", "")).strip(),
                    "exam_type": str(it.get("kslx", "") or it.get("khfsmc", "") or "正常考试").strip(),
                })
            return grades
        except Exception as e:
            self.last_error = f"成绩API请求失败: {e}"
            return []

    def _grades_html(self, semester: str) -> list[dict]:
        """解析成绩页面（HTML 表格）"""
        def _parse_table(soup, label=""):
            """通过表头行确定列索引，然后逐行提取"""
            candidates = []
            candidates.append(soup.find("table", id="dataList"))
            candidates.append(soup.find("table", class_="Nsb_r_list"))
            candidates.extend(soup.find_all("table", class_=lambda c: c and "Nsb" in c if c else False))
            for tbl in soup.find_all("table"):
                if tbl not in candidates:
                    candidates.append(tbl)

            for t in candidates:
                if t is None:
                    continue
                rows = t.find_all("tr")
                if len(rows) < 2:
                    continue
                hdr_cells = rows[0].find_all(["td", "th"])
                hdr_texts = [c.get_text(strip=True) for c in hdr_cells]
                logger.info(f"[成绩] {label} 候选表格: {len(rows)}行, 表头: {hdr_texts[:12]}")

                hdr_joined = " ".join(hdr_texts)
                if not any(kw in hdr_joined for kw in ("课程名称", "课程", "成绩", "学分", "绩点", "分数")):
                    continue

                # 建立列映射
                col = {}
                for i, txt in enumerate(hdr_texts):
                    if txt == "课程名称":
                        col["course_name"] = i
                    elif txt == "课程编号" or txt == "课程代码":
                        col["course_code"] = i
                    elif txt == "成绩":
                        col["score"] = i
                    elif txt == "学分":
                        col["credit"] = i
                    elif txt == "绩点":
                        col["grade_point"] = i
                    elif txt == "课程属性":
                        col["course_type"] = i
                    elif txt == "课程性质":
                        col["course_nature"] = i
                    elif txt in ("考核方式", "考试类型", "考试性质"):
                        col["exam_type"] = i
                    elif txt in ("开课学期", "学年学期"):
                        col["semester"] = i

                # 兜底：强智教务常见布局
                if "course_name" not in col:
                    col = {"course_name": 3, "score": 4, "credit": 6,
                           "grade_point": None, "course_type": 9, "exam_type": 8,
                           "course_nature": 10, "course_code": 2, "semester": 1}
                    logger.info(f"[成绩] {label} 表头匹配失败，使用固定位置")
                else:
                    logger.info(f"[成绩] {label} 表头映射: {col}")

                if "grade_point" not in col:
                    col["grade_point"] = None
                break
            else:
                logger.info(f"[成绩] {label} 未找到合适的表格")
                return None

            grades = []
            for row in rows[1:]:
                cells = row.find_all(["td", "th"])
                texts = [c.get_text(strip=True) for c in cells]
                if len(texts) < 5:
                    continue

                def _get(key, default=""):
                    idx = col.get(key)
                    if idx is not None and idx < len(texts):
                        return texts[idx]
                    return default

                course_name = _get("course_name")
                if not course_name:
                    continue
                if any(kw in course_name for kw in ("平均", "合计", "必修课合计")):
                    continue

                sem_raw = _get("semester")
                ay, sm = "", ""
                if sem_raw and "-" in sem_raw:
                    parts = sem_raw.split("-")
                    if len(parts) >= 2:
                        ay = f"{parts[0]}-{parts[1]}"
                        sm = parts[2] if len(parts) > 2 else ""

                grades.append({
                    "academic_year": ay,
                    "semester": sm,
                    "course_code": _get("course_code"),
                    "course_name": course_name,
                    "score": _get("score"),
                    "credit": self._to_float(_get("credit")),
                    "grade_point": self._to_float(_get("grade_point")),
                    "course_type": _get("course_type"),
                    "course_nature": _get("course_nature"),
                    "exam_type": _get("exam_type") or "正常考试",
                })

            logger.info(f"[成绩] {label} 解析完成: {len(grades)} 条")
            # 找到标准成绩表格即算解析成功: 空列表 = 暂无成绩(正常场景)
            return grades

        # 策略执行
        strategies = []

        # 策略1: GET 查询页
        try:
            resp = self.session.get(URL_GRADE_QUERY, timeout=TIMEOUT)
            soup = BeautifulSoup(resp.text, "lxml")
            form = soup.find("form")
            if form:
                action = form.get("action", "")
                form_data = {}
                for inp in form.find_all("input"):
                    n, v = inp.get("name", ""), inp.get("value", "")
                    if n:
                        form_data[n] = v
                for sel in form.find_all("select"):
                    n = sel.get("name", "")
                    if n:
                        opts = sel.find_all("option")
                        if opts:
                            picked = None
                            for o in opts:
                                ov = o.get("value", "")
                                if semester and semester in ov:
                                    picked = ov; break
                            if not picked:
                                s = sel.find("option", selected=True)
                                picked = s.get("value", "") if s else opts[0].get("value", "")
                            form_data[n] = picked
                if action:
                    if action.startswith("/"):
                        target = f"{BASE_9080}{action}"
                    elif action.startswith("http"):
                        target = action
                    else:
                        target = f"{BASE_9080}/njlgdx/kscj/{action}"
                else:
                    target = URL_GRADE_LIST
                strategies.append(("POST表单", lambda t=target, d=form_data: self.session.post(t, data=d, timeout=TIMEOUT)))

            result = _parse_table(soup, "策略1直接")
            if result is not None:
                return result
        except Exception as e:
            logger.info(f"[成绩] 策略1异常: {e}")

        # 策略2: 直接 POST 列表页
        strategies.append(("POST列表页", lambda: self.session.post(
            URL_GRADE_LIST, data={"xnxqid": semester}, timeout=TIMEOUT)))

        # 策略3: GET 列表页
        strategies.append(("GET列表页", lambda: self.session.get(
            URL_GRADE_LIST, timeout=TIMEOUT)))

        # 执行策略
        last_soup = None
        for sname, sfn in strategies:
            logger.info(f"[成绩] {sname}...")
            try:
                resp = sfn()
                soup = BeautifulSoup(resp.text, "lxml")
                last_soup = soup
                result = _parse_table(soup, sname)
                if result is not None:
                    return result
            except Exception as e:
                logger.info(f"[成绩]   {sname} 异常: {e}")

        # 全部失败
        if last_soup:
            has_login = "logon" in str(last_soup).lower() or "登录" in str(last_soup)
            if has_login:
                self.last_error = "成绩页面需要重新登录，请先在设置页登录"
            else:
                self.last_error = "成绩解析失败"
        else:
            self.last_error = "无法访问成绩页面"
        return []

    # ================================================================
    # 四六级
    # ================================================================

    def get_cet_scores(self) -> list[dict]:
        """获取四六级成绩"""
        try:
            resp = self.session.get(URL_CET_LIST, timeout=TIMEOUT)
            if resp.status_code != 200:
                logger.info(f"[CET] 请求失败: {resp.status_code}")
                return []
        except Exception as e:
            logger.info(f"[CET] 请求异常: {e}")
            return []

        soup = BeautifulSoup(resp.text, "lxml")
        table = soup.find("table", id="dataList")
        if not table:
            logger.info("[CET] 未找到 #dataList 表格")
            return []

        rows = table.find_all("tr")
        if len(rows) < 3:
            return []

        cet_records = []
        for row in rows[2:]:
            cells = row.find_all("td")
            if len(cells) < 9:
                continue
            course_name = cells[1].get_text(strip=True)
            total_score_text = cells[4].get_text(strip=True)
            exam_date = cells[8].get_text(strip=True)

            if "CET6" in course_name:
                cet_type = "CET6"
            elif "CET4" in course_name:
                cet_type = "CET4"
            else:
                continue

            try:
                score = float(total_score_text)
            except (ValueError, TypeError):
                continue
            if score <= 0:
                continue

            cet_records.append((cet_type, score, exam_date))

        if not cet_records:
            return []

        # 取每种类型的最高分
        best = {}
        for t, s, d in cet_records:
            if t not in best or s > best[t][0]:
                best[t] = (s, d)

        result = []
        for cet_type in ("CET4", "CET6"):
            if cet_type in best:
                s, d = best[cet_type]
                result.append({"type": cet_type, "score": s, "exam_date": d})

        logger.info(f"[CET] 汇总: {result}")
        return result

    @staticmethod
    def _to_float(val) -> float:
        """安全转换为 float"""
        try:
            return float(val)
        except (ValueError, TypeError):
            return 0.0

    def logout(self):
        try:
            self.session.get(f"{BASE_9080}/njlgdx/xk/LoginToXk?method=exit", timeout=5)
        except Exception:
            pass
        self.logged_in = False
        self.token = None
        self.student_name = None
        self.session = requests.Session()
        self.session.cookies = _DedupCookieJar()
        self.session.headers.update(HEADERS)
