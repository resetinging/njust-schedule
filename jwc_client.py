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


class JWCClient:
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

    # ================================================================
    # 登录入口
    # ================================================================

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

    def login_webvpn(self, student_id: str, password: str) -> bool:
        """通过智慧理工 SSO 登录 + 直连教务（不走 WebVPN）

        流程：
        1. 直连 SSO（ids.njust.edu.cn）登录验证身份
        2. 尝试直连教务 main.jsp（如教务支持 CAS 则自动登录）
        3. 否则走标准 8080 Logon.do 登录 → 302 → 9080 LoginToXk 重定向链
           （与常规教务登录完全相同的流程，确保拿到有效的 9080 session）
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
        self.session.headers.update(HEADERS)

        if not _HAS_CRYPTO:
            self.last_error = (
                "SSO 登录需要 pycryptodome 模块，请运行: pip install pycryptodome"
            )
            return False

        try:
            # ========================================================
            # Step 1: 直连 SSO 登录
            # ========================================================
            if not self._direct_sso_login(student_id, password):
                return False

            # ========================================================
            # Step 2: 尝试直连教务（可能通过 CAS 自动登录）
            # ========================================================
            if self._try_direct_jw_access():
                return True

            # ========================================================
            # Step 3: 标准 8080 Logon.do 登录（和常规教务登录同一流程）
            #          NJUST 教务登录必须走 8080 → 9080 重定向链，
            #          9080 的 Verifyservlet 不是有效的登录入口。
            # ========================================================
            self._log(f"[SSO-JW] 教务需要表单登录，走 8080 Logon.do 标准流程...")
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
            if DEBUG_WEBVPN:
                import traceback
                traceback.print_exc()
            return False

    def _direct_sso_login(self, student_id: str, password: str) -> bool:
        """直连 SSO 登录（ids.njust.edu.cn，不走 WebVPN 代理）

        成功后 session 中会有 SSO TGC cookie（domain=ids.njust.edu.cn），
        后续访问 WebVPN 时可被自动识别而无需再次登录。
        返回 True/False，失败信息在 self.last_error 中。
        """
        from urllib.parse import urljoin

        try:
            # ========================================================
            # Step D1: GET SSO 登录页 → 解析表单
            # ========================================================
            if DEBUG_WEBVPN:
                self._log(f"[SSO-Direct] Step D1: GET {SSO_LOGIN_URL}")
            resp = self.session.get(
                SSO_LOGIN_URL, timeout=TIMEOUT, allow_redirects=True,
            )
            self._dedupe_cookies()

            if DEBUG_WEBVPN:
                self._log(f"[SSO-Direct]   最终 URL: {resp.url[:120]}")
                self._log(f"[SSO-Direct]   状态={resp.status_code} "
                          f"标题={self._page_title(resp)}")
                for i, h in enumerate(resp.history):
                    loc = h.headers.get('Location', '')[:120]
                    set_cookie = h.headers.get('Set-Cookie', '')[:80]
                    self._log(f"[SSO-Direct]   重定向#{i}: {h.status_code} → {loc}")
                    if set_cookie:
                        self._log(f"[SSO-Direct]     Set-Cookie: {set_cookie}")

            # 检查是否直接跳过了 SSO（已有有效 TGC）
            if "authserver/login" not in resp.url:
                self._log(f"[SSO-Direct]   未到达 SSO 登录页（可能已有 TGC），"
                          f"URL: {resp.url[:120]}")
                # 仍算成功——已有 SSO 会话
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

            if DEBUG_WEBVPN:
                self._log(f"[SSO-Direct]   execution={execution_val[:50]}...")
                self._log(f"[SSO-Direct]   pwdEncryptSalt={salt_val}")
                self._log(f"[SSO-Direct]   lt={lt_val!r}")

            if not execution_val or not salt_val:
                self.last_error = "获取 SSO 表单字段失败（execution/salt 为空）"
                self._log(f"[SSO-Direct] [FAIL] {self.last_error}")
                return False

            # ========================================================
            # Step D2: 检查是否需要 SSO 验证码
            # ========================================================
            need_captcha = False
            sso_captcha_text = ""
            try:
                check_url = f"{SSO_BASE}/authserver/checkNeedCaptcha.htl"
                if DEBUG_WEBVPN:
                    self._log(f"[SSO-Direct]   POST checkNeedCaptcha: {check_url}")
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
                data = check_resp.json()
                need_captcha = data.get("isNeed", False)
                if DEBUG_WEBVPN:
                    self._log(f"[SSO-Direct]   needCaptcha: {need_captcha}")
            except Exception as e:
                if DEBUG_WEBVPN:
                    self._log(f"[SSO-Direct]   checkNeedCaptcha 失败: {e}")

            # ========================================================
            # Step D3: 获取 SSO 验证码（如需要）
            # ========================================================
            if need_captcha:
                try:
                    import ddddocr
                    captcha_url = f"{SSO_BASE}/authserver/getCaptcha.htl"
                    if DEBUG_WEBVPN:
                        self._log(f"[SSO-Direct]   GET captcha: {captcha_url}")
                    cap_resp = self.session.get(
                        captcha_url, timeout=TIMEOUT,
                        headers={"Referer": resp.url},
                    )
                    if cap_resp.status_code == 200 and len(cap_resp.content) > 100:
                        ocr = ddddocr.DdddOcr(show_ad=False)
                        sso_captcha_text = ocr.classification(cap_resp.content).strip()
                        if DEBUG_WEBVPN:
                            self._log(f"[SSO-Direct]   SSO OCR: '{sso_captcha_text}'")
                    else:
                        self._log(f"[SSO-Direct]   验证码获取失败 "
                                  f"status={cap_resp.status_code}")
                except ImportError:
                    self.last_error = "SSO 需要验证码但 ddddocr 未安装"
                    return False
                except Exception as e:
                    self._log(f"[SSO-Direct]   SSO 验证码异常: {e}")

            # ========================================================
            # Step D4: AES 加密密码
            # ========================================================
            encrypted_pwd = self._encrypt_sso_password(password, salt_val)
            if DEBUG_WEBVPN:
                self._log(f"[SSO-Direct]   密码已加密 (salt={salt_val}, "
                          f"encrypted_len={len(encrypted_pwd)})")

            # ========================================================
            # Step D5: POST SSO 登录
            # ========================================================
            # 构造 POST URL
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

            if DEBUG_WEBVPN:
                safe = {k: (v[:40] + "..." if k == "password" and len(v) > 40 else v)
                        for k, v in form_data.items()}
                self._log(f"[SSO-Direct] Step D5: POST {post_url[:120]}")
                self._log(f"[SSO-Direct]   form_data={safe}")

            login_resp = self.session.post(
                post_url,
                data=form_data,
                timeout=TIMEOUT,
                allow_redirects=True,
                headers={"Referer": resp.url},
            )
            self._dedupe_cookies()

            if DEBUG_WEBVPN:
                self._log(f"[SSO-Direct]   最终 URL: {login_resp.url[:120]}")
                self._log(f"[SSO-Direct]   状态={login_resp.status_code} "
                          f"标题={self._page_title(login_resp)}")
                self._log(f"[SSO-Direct]   cookies: "
                          f"{ {c.name: c.value[:30] for c in self.session.cookies} }")
                for i, h in enumerate(login_resp.history):
                    loc = h.headers.get('Location', '')[:120]
                    set_cookie = h.headers.get('Set-Cookie', '')[:80]
                    self._log(f"[SSO-Direct]   重定向#{i}: {h.status_code} → {loc}")
                    if set_cookie:
                        self._log(f"[SSO-Direct]     Set-Cookie: {set_cookie}")

            # ========================================================
            # Step D6: 检测登录结果
            # ========================================================
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

            # 检查是否回到了 SSO 登录页
            login_soup = BeautifulSoup(login_resp.text, "lxml")
            if ("authserver/login" in login_resp.url
                    and login_soup.find("form", id="pwdFromId")):
                self.last_error = "SSO 登录失败，请检查智慧理工账号和密码"
                self._log(f"[SSO-Direct] [FAIL] {self.last_error}")
                return False

            self._log(f"[SSO-Direct] [OK] SSO 登录成功")
            return True

        except requests.exceptions.ConnectionError:
            self.last_error = "无法连接智慧理工 SSO（ids.njust.edu.cn）"
            self._log(f"[SSO-Direct] [FAIL] {self.last_error}")
            return False
        except Exception as e:
            self.last_error = f"SSO 登录异常: {e}"
            self._log(f"[SSO-Direct] [FAIL] {self.last_error}")
            if DEBUG_WEBVPN:
                import traceback
                traceback.print_exc()
            return False

    def _encrypt_sso_password(self, password: str, salt: str) -> str:
        """SSO 密码加密（匹配前端 encrypt.js encryptPassword 逻辑）

        - 生成 64 位随机字符作为前缀（吸收 CBC IV 差异）
        - AES-128-CBC 加密，key=salt(UTF-8), iv=随机16字符(UTF-8)
        - 返回 Base64 密文（不含 IV）
        """
        import secrets

        chars = "ABCDEFGHJKMNPQRSTWXYZabcdefhijkmnprstwxyz2345678"
        random_prefix = "".join(secrets.choice(chars) for _ in range(64))
        random_iv = "".join(secrets.choice(chars) for _ in range(16))

        data = random_prefix + password
        key_bytes = salt.encode("utf-8")[:16].ljust(16, b"\x00")
        iv_bytes = random_iv.encode("utf-8")[:16].ljust(16, b"\x00")

        cipher = AES.new(key_bytes, AES.MODE_CBC, iv_bytes)
        padded = aes_pad(data.encode("utf-8"), AES.block_size)
        encrypted = cipher.encrypt(padded)

        return base64.b64encode(encrypted).decode()

    # ================================================================
    # 直连教务访问（SSO 后尝试 CAS 自动登录）
    # ================================================================

    def _try_direct_jw_access(self) -> bool:
        """SSO 登录后尝试通过 CAS ticket 登录教务

        利用已有的 TGC cookie，通过 CAS 协议获取 ticket 自动登录教务。
        尝试多个可能的 CAS service URL（教务系统的不同入口）。
        """
        from urllib.parse import quote

        # 尝试多种可能的 CAS service URL
        # CAS service URL 必须在 SSO 服务器注册过才能用
        candidate_services = [
            # 方式 1: 教务主页面 (main.jsp)
            f"{BASE_9080}{JW_PATH_PREFIX}/framework/main.jsp",
            # 方式 2: 教务根路径
            f"{BASE_9080}{JW_PATH_PREFIX}/",
            # 方式 3: 教务 8080 入口
            f"{BASE_9080}{JW_PATH_PREFIX}/xk/LoginToXk",
        ]

        for idx, service_url in enumerate(candidate_services):
            try:
                sso_service_url = (
                    f"{SSO_BASE}/authserver/login"
                    f"?service={quote(service_url, safe='')}"
                )
                self._log(f"[SSO-JW] 尝试 CAS service #{idx+1}: {service_url[:100]}")
                self._log(f"[SSO-JW]   GET {sso_service_url[:150]}")

                resp = self.session.get(
                    sso_service_url, timeout=TIMEOUT, allow_redirects=True,
                )
                self._dedupe_cookies()

                self._log(f"[SSO-JW]   最终 URL: {str(resp.url)[:150]}")
                self._log(f"[SSO-JW]   状态={resp.status_code} "
                          f"标题={self._page_title(resp)}")

                # 记录重定向链
                for i, h in enumerate(resp.history):
                    loc = h.headers.get('Location', '')[:150]
                    self._log(f"[SSO-JW]   重定向#{i}: {h.status_code} → {loc}")

                # 检查是否到达教务且已登录
                if self._check_success(resp):
                    self._extract_name(resp.text)
                    self.logged_in = True
                    self.login_method = "webvpn"
                    self._log(f"[SSO-JW] [OK] CAS ticket 登录教务成功! "
                              f"(service={service_url[:80]})")
                    return True

                # 检查是否到了教务登录页（CAS ticket 无效/不支持）
                if self._is_jw_login_page(resp):
                    self._log(f"[SSO-JW]   教务不支持此 CAS service，返回登录表单")
                elif "authserver" in str(resp.url):
                    self._log(f"[SSO-JW]   CAS 未重定向（可能 service 未注册）")
                else:
                    self._log(f"[SSO-JW]   未识别: URL={str(resp.url)[:120]}")

            except requests.exceptions.ConnectionError:
                self._log(f"[SSO-JW]   无法连接 (service #{idx+1})")
                continue
            except Exception as e:
                self._log(f"[SSO-JW]   异常 (service #{idx+1}): {e}")
                continue

        # === 兜底: 直接访问 main.jsp ===
        main_url = f"{BASE_9080}{JW_PATH_PREFIX}/framework/main.jsp"
        self._log(f"[SSO-JW] 兜底: 直接访问 main.jsp")
        try:
            resp2 = self.session.get(main_url, timeout=TIMEOUT, allow_redirects=True)
            self._dedupe_cookies()

            if self._check_success(resp2):
                self._extract_name(resp2.text)
                self.logged_in = True
                self.login_method = "webvpn"
                self._log(f"[SSO-JW] [OK] 直连教务已登录!")
                return True

            self._log(f"[SSO-JW]   教务未登录，需要表单登录")
        except Exception as e:
            self._log(f"[SSO-JW]   直连异常: {e}")

        return False

    # ================================================================
    # 手动验证码流程（SSO → 8080 Logon.do → 返验证码给用户）
    # ================================================================

    def get_webvpn_captcha_base64(self, student_id: str, password: str):
        """SSO 登录后获取教务 8080 登录验证码（base64）

        完成 SSO 登录 → 尝试 CAS 自动登录教务 →
        如需验证码则从 8080 Logon.do 获取，返回 base64 供前端展示。
        """
        self.student_id = student_id
        self.student_name = None
        self.last_error = ""
        self._webvpn_manual_ready = False
        self._webvpn_post_url = ""
        self._webvpn_login_page_url = ""
        self.debug_log = []
        self.session = requests.Session()
        self.session.headers.update(HEADERS)

        if not _HAS_CRYPTO:
            return "", "SSO 登录需要 pycryptodome 模块: pip install pycryptodome"

        try:
            # Step 1: 直连 SSO 登录
            self._log(f"[SSO-Captcha] Step 1: 直连 SSO 登录...")
            if not self._direct_sso_login(student_id, password):
                return "", self.last_error

            # Step 2: 尝试 CAS 自动登录教务
            self._log(f"[SSO-Captcha] Step 2: 尝试直连教务...")
            if self._try_direct_jw_access():
                self._webvpn_manual_ready = True
                return "__ALREADY_LOGGED_IN__", ""

            # Step 3: 从 8080 Logon.do 获取验证码（标准教务登录入口）
            #         不能走 9080 的 Verifyservlet——那不是真正的登录入口
            self._log(f"[SSO-Captcha] Step 3: 从 8080 Logon.do 获取验证码...")
            # ★ 初始化 8080 会话但不清除 SSO cookie（保留 SSO 会话）
            #    SSO cookie 在 ids.njust.edu.cn 域，8080 在 202.119.81.113，
            #    域不同不会冲突。
            self._get(URL_LOGON_PAGE, timeout=TIMEOUT)
            self.session.headers.update({"Referer": URL_LOGON_PAGE})
            self._dedupe_cookies()
            self._detect_captcha_url_from_page()
            try:
                self._get(URL_LOGON_SESS, timeout=TIMEOUT)
                self._dedupe_cookies()
            except Exception:
                pass

            # 获取验证码图片
            img = self._fetch_captcha()
            if not img:
                return "", "获取验证码失败：无法从教务服务器获取验证码图片"

            self._webvpn_manual_ready = True
            self._webvpn_login_page_url = URL_LOGON_PAGE
            self._webvpn_post_url = URL_LOGON_PAGE  # POST 目标: 8080 Logon.do

            # 保存验证码图片到文件
            self._save_captcha_image(img)

            self._log(f"[SSO-Captcha] [OK] 验证码就绪 ({len(img)} bytes)")
            return base64.b64encode(img).decode(), ""

        except requests.exceptions.ConnectionError:
            return "", "无法连接教务服务器（请确认已连接校园网或 EasyConnect VPN）"
        except Exception as e:
            import traceback
            traceback.print_exc()
            return "", str(e)

    def _save_captcha_image(self, content: bytes):
        """保存验证码图片到磁盘（调试用）"""
        try:
            ext = ("png" if content[:4] == b"\x89PNG"
                   else "gif" if content[:4] == b"GIF8"
                   else "jpg")
            base = os.path.dirname(os.path.abspath(__file__))
            img_idx = 1
            while os.path.exists(os.path.join(base, f"debug_{img_idx:02d}_captcha_image.{ext}")):
                img_idx += 1
            img_path = os.path.join(base, f"debug_{img_idx:02d}_captcha_image.{ext}")
            with open(img_path, "wb") as f:
                f.write(content)
            self._log(f"[SSO-Captcha] 验证码图片已保存: debug_{img_idx:02d}_captcha_image.{ext}")
        except Exception:
            pass

    def complete_webvpn_login(self, student_id: str, password: str,
                               captcha: str) -> bool:
        """使用手动输入的验证码完成教务登录（标准 8080 Logon.do 流程）

        前置条件：已调用 get_webvpn_captcha_base64() 成功获取验证码。
        """
        if not self._webvpn_manual_ready:
            self.last_error = "会话已过期，请重新获取验证码"
            return False

        self.student_id = student_id
        self.student_name = None
        self.last_error = ""
        self.logged_in = False
        self.login_method = ""

        try:
            self._log(f"[SSO-Login] 使用手动验证码完成 8080 标准登录...")
            self._log(f"[SSO-Login] RANDOMCODE='{captcha.strip()}'")

            # ★ 使用标准 8080 Logon.do 登录（和常规教务登录同一流程）
            #    不能走 9080 Verifyservlet——那不是真正的登录入口
            if self._try_simple_login(student_id, password, captcha.strip()):
                self.logged_in = True
                self.login_method = "webvpn"
                self._log(f"[SSO-Login] [OK] 登录成功!")
                return True

            # _try_simple_login 内部已设置 last_error
            if not self.last_error:
                self.last_error = "教务系统登录失败，请重新获取验证码重试"
            return False

        except Exception as e:
            self._log(f"[SSO-Login] 异常: {e}")
            import traceback
            traceback.print_exc()
            self.last_error = f"登录异常: {e}"
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
            resp = self._post(
                URL_LOGON_PAGE,
                data=payload,
                timeout=TIMEOUT,
                allow_redirects=True,  # ← 自动跟随 302 → 9080 → ...
                headers={"Referer": URL_LOGON_PAGE},
            )
            # ★ 先去重 cookie，否则 dict() 会崩溃
            self._dedupe_cookies()

            print(f"[Login] POST → final status={resp.status_code} "
                  f"final URL={resp.url[:120]}")
            print(f"[Login] 页面标题: {self._page_title(resp)}")
            for i, h in enumerate(resp.history):
                print(f"[Login]   重定向#{i}: {h.status_code} → {h.headers.get('Location','')[:80]}")

            # 安全打印 cookies
            ck = {c.name: c.value for c in self.session.cookies}
            print(f"[Login] cookies: {ck}")

            # 检查是否登录成功
            if self._check_success(resp):
                self._extract_name(resp.text)
                self.logged_in = True
                self.login_method = "web-auto"
                # ★ 访问 9080 主页巩固 session
                self._get(
                    URL_MAIN_PAGE,
                    timeout=TIMEOUT, allow_redirects=True,
                )
                self._dedupe_cookies()
                print(f"[Login] 登录成功! cookies: "
                      f"{ {c.name: c.value for c in self.session.cookies} }")
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
            print(f"[Login] 异常: {e}")
            return False

    # ================================================================
    # 方式2: Web 登录 + OCR
    # ================================================================

    def _try_jw_login_9080(self, student_id: str, password: str) -> bool:
        """通过 9080 main.jsp 内嵌表单登录教务（不需要 8080）

        适用于只能访问 9080 但 8080 不可达的情况。
        从 main.jsp 解析登录表单，OCR 验证码，POST 提交。
        """
        from urllib.parse import urljoin

        try:
            import ddddocr

            # Step A: GET main.jsp 获取登录表单
            main_url = f"{BASE_9080}{JW_PATH_PREFIX}/framework/main.jsp"
            self._log(f"[JW-9080] Step A: GET {main_url}")
            resp = self.session.get(main_url, timeout=TIMEOUT, allow_redirects=True)
            self._dedupe_cookies()
            self._log(f"[JW-9080]   状态={resp.status_code} "
                      f"标题={self._page_title(resp)}")

            # 检查是否已登录
            if self._check_success(resp):
                self._extract_name(resp.text)
                self._log(f"[JW-9080] [OK] 已有教务会话!")
                return True

            # Step B: 解析表单
            soup = BeautifulSoup(resp.text, "lxml")
            form = soup.find("form")
            if not form or not soup.find("input", {"name": "USERNAME"}):
                self._log(f"[JW-9080] [FAIL] 未找到登录表单")
                self.last_error = "教务页面无登录表单"
                return False

            form_action = (form.get("action") or "").strip()
            if form_action:
                if form_action.startswith("http"):
                    post_url = form_action
                else:
                    post_url = urljoin(main_url, form_action)
            else:
                post_url = main_url

            # Step C: 找验证码 URL
            captcha_url = ""
            for img in soup.find_all("img"):
                src = img.get("src", "")
                if "verifycode" in src.lower() or "checkcode" in src.lower():
                    captcha_url = src if src.startswith("http") else urljoin(main_url, src)
                    break
            if not captcha_url:
                # 兜底：main.jsp 中验证码在 /njlgdx/verifycode.servlet
                captcha_url = f"{BASE_9080}{JW_PATH_PREFIX}/verifycode.servlet"

            self._log(f"[JW-9080]   POST URL: {post_url[:120]}")
            self._log(f"[JW-9080]   验证码 URL: {captcha_url[:120]}")

            # Step D: OCR 验证码
            ocr = ddddocr.DdddOcr(show_ad=False)
            captcha_text = ""
            for i in range(3):
                cache_bust = f"?t={int(time.time() * 1000)}" if i > 0 else ""
                self._log(f"[JW-9080] GET 验证码 #{i+1}: {captcha_url}{cache_bust}")
                cap_resp = self.session.get(
                    captcha_url + cache_bust, timeout=TIMEOUT,
                    headers={"Referer": main_url})
                content_type = cap_resp.headers.get("Content-Type", "")
                is_image = (
                    cap_resp.status_code == 200
                    and len(cap_resp.content) > 100
                    and ("image" in content_type
                         or cap_resp.content[:4] in (b"\x89PNG", b"GIF8", b"\xff\xd8\xff"))
                )
                if is_image:
                    captcha_text = self._ocr_with_preprocess(ocr, cap_resp.content)
                    self._log(f"[JW-9080] OCR #{i+1}: '{captcha_text}' "
                              f"(len={len(captcha_text)})")
                    if captcha_text and len(captcha_text) >= 4:
                        break
                else:
                    preview = cap_resp.text[:200] if cap_resp.text else "(空)"
                    self._log(f"[JW-9080] 验证码 #{i+1} 返回非图片: "
                              f"status={cap_resp.status_code} Content-Type={content_type}")
                    self._log(f"[JW-9080]   预览: {preview}")

            if not captcha_text:
                self._log(f"[JW-9080] [WARN] OCR 失败，尝试空验证码")

            # Step E: POST 登录
            payload = {
                "USERNAME": student_id,
                "PASSWORD": password,
                "RANDOMCODE": captcha_text,
                "useDogCode": "",
                "jzmmid": "1",
            }
            self._log(f"[JW-9080] Step E: POST {post_url[:120]}")
            self._log(f"[JW-9080] USERNAME={student_id} RANDOMCODE='{captcha_text}'")

            # 手动处理重定向（修正教务服务器错误的 IP 重定向）
            login_resp = self.session.post(
                post_url, data=payload, timeout=TIMEOUT,
                allow_redirects=False,
                headers={"Referer": main_url},
            )
            self._dedupe_cookies()
            self._log(f"[JW-9080] POST 响应: status={login_resp.status_code}")
            self._log(f"[JW-9080]   Location: {login_resp.headers.get('Location', '')[:150]}")

            # 手动跟随重定向（最多 5 次），修正 IP 错误
            for _ in range(5):
                if login_resp.status_code in (301, 302, 303, 307, 308):
                    login_resp = self._fix_jw_redirect(login_resp)
                    self._dedupe_cookies()
                else:
                    break

            self._log(f"[JW-9080] 最终: status={login_resp.status_code} "
                      f"URL={login_resp.url[:150]} 标题={self._page_title(login_resp)}")

            # Step F: 验证结果
            if self._check_success(login_resp):
                self._extract_name(login_resp.text)
                self._log(f"[JW-9080] [OK] 登录成功!")
                return True

            if "main.jsp" in str(login_resp.url) or "framemain" in login_resp.text:
                self._extract_name(login_resp.text)
                self._log(f"[JW-9080] [OK] 登录成功（已到达 main.jsp）!")
                return True

            # 二次验证
            main_resp2 = self.session.get(main_url, timeout=TIMEOUT, allow_redirects=True)
            self._dedupe_cookies()
            if self._check_success(main_resp2):
                self._extract_name(main_resp2.text)
                self._log(f"[JW-9080] [OK] 登录成功（二次验证）!")
                return True

            t = login_resp.text.lower()
            if "密码错误" in t or "用户名或密码错误" in t:
                self.last_error = ("教务系统：用户名或密码错误"
                                   "（注意：教务密码可能与智慧理工密码不同）")
            elif "验证码" in t and ("错误" in t or "不正确" in t):
                self.last_error = f"教务系统：验证码错误（OCR识别为: {captcha_text}）"
            else:
                self.last_error = "教务系统登录失败"
            return False

        except ImportError:
            self.last_error = "OCR 模块未安装"
            return False
        except requests.exceptions.ConnectionError:
            self.last_error = "无法连接教务服务器 9080（请检查网络连接）"
            return False
        except Exception as e:
            self._log(f"[JW-9080] 异常: {e}")
            import traceback
            traceback.print_exc()
            self.last_error = f"教务登录异常: {e}"
            return False

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
                print(f"[OCR] #{i+1}: '{code}'")

                if self._try_simple_login(student_id, password, code):
                    self.logged_in = True
                    self.login_method = "web-auto"
                    return True

            self.last_error = "验证码自动识别失败，请使用手动输入（点「显示验证码」）"
            return False
        except ImportError as e:
            self.last_error = f"OCR 模块加载失败: {e}"
            return False
        except requests.exceptions.ConnectionError:
            self.last_error = "无法连接教务服务器（请检查网络连接）"
            return False
        except Exception as e:
            self.last_error = str(e)
            return False

    # ================================================================
    # 手动验证码流程
    # ================================================================

    def get_captcha_base64(self) -> Tuple[str, str]:
        self._captcha_ready = False
        self.login_method = ""  # 验证码获取走直连
        self.session = requests.Session()
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
        self.student_name = None
        self.last_error = ""
        self.logged_in = False
        self.login_method = ""
        self.token = None

        if not self._captcha_ready:
            self.last_error = "会话过期，请重新获取验证码"
            return False

        if self._try_simple_login(sid, pw, captcha.strip()):
            self.logged_in = True
            self.login_method = "web-manual"
            self._captcha_ready = False
            return True

        self.last_error = "验证码不正确，请刷新重试"
        self._captcha_ready = False
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

    def get_schedule(self, semester: str = "", week: int = 0) -> list[dict]:
        if not self.logged_in:
            self.last_error = "未登录"
            return []
        return self._schedule_api(semester, week) or self._schedule_html(semester)

    def _schedule_api(self, semester: str, week: int) -> list[dict]:
        try:
            if not semester:
                semester = self._current_semester()
            params = {"method": "getKbcxAzc", "xh": self.student_id, "xnxqid": semester}
            if week > 0:
                params["zc"] = str(week)
            resp = self._post(
                URL_APP_DO, params=params,
                headers={"token": self.token} if self.token else {},
                timeout=TIMEOUT)
            data = resp.json()
            items = data if isinstance(data, list) else data.get("data", [])
            return self._parse_schedule(items) if isinstance(items, list) else []
        except Exception:
            return []

    def _schedule_html(self, semester: str) -> list[dict]:
        """NJUST 课表 HTML 解析 — 从主页链接获取正确的 Ves632DSdyV 参数"""
        try:
            # Debug: 看看当前 cookie 状态
            self._log(f"[课表] 请求前 cookies: { {k: v[:20] for k, v in self.session.cookies.items()} }")

            # 先访问主页，提取课表链接中的 Ves632DSdyV 参数
            main_resp = self._get(
                URL_MAIN_PAGE,
                timeout=TIMEOUT, allow_redirects=True,
            )
            self._log(f"[课表] 主页 GET → status={main_resp.status_code} "
                  f"len={len(main_resp.text)} title={self._page_title(main_resp)}")
            real_schedule_url = URL_SCHEDULE_HTML  # 默认
            m = re.search(r'xskb/xskb_list\.do\?([^"\']+)', main_resp.text)
            if m:
                real_schedule_url = f"{BASE_9080}/njlgdx/xskb/xskb_list.do?{m.group(1)}"
                self._log(f"[课表] 从主页提取真实URL参数: {m.group(1)[:50]}")
            else:
                self._log(f"[课表] [WARN] 未在主页找到课表链接，使用默认URL")

            resp = self._get(real_schedule_url, timeout=TIMEOUT, allow_redirects=True)
            self._log(f"[课表] 课表 GET → status={resp.status_code} "
                  f"len={len(resp.text)} title={self._page_title(resp)}")

            if resp.status_code != 200 or len(resp.text) < 2000:
                self.last_error = "课表页面访问失败，请重新登录"
                return []

            soup = BeautifulSoup(resp.text, "lxml")

            # ★ 合并两个表格：kbtable(周次/教室) + dataList(精确小节)
            grid = soup.find("table", id="kbtable")
            data_table = soup.find("table", id="dataList")

            if grid and data_table:
                courses = self._parse_merged(grid, data_table)
                if courses:
                    self._log(f"[课表] 合并解析完成: {len(courses)} 条")
                    return courses

            # 降级
            if data_table:
                courses = self._parse_datalist(data_table)
                if courses: return courses
            if grid:
                courses = self._parse_kbtable(grid, {})
                if courses: return courses

            self.last_error = "课表表格未找到"
            self._log(f"[课表] 所有表格: {[t.get('id', t.get('class', '')) for t in soup.find_all('table')[:10]]}")
            return []
        except Exception as e:
            print(f"[课表HTML] {e}")
            import traceback; traceback.print_exc()
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

        print(f"[课表] dataList 解析完成: {len(courses)} 条")
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
        print(f"[kbtable] 列映射: {day_map}")

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
        # 先尝试 API，失败则降级到 HTML
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
            resp = self._post(
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
            t = soup.find("table", id="dataList") or soup.find("table", class_="Nsb_r_list")
            if not t:
                return None
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
            return exams

        try:
            # 策略1：先访问查询页，获取表单，提交查询
            resp = self._get(URL_EXAM_QUERY, timeout=TIMEOUT)
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
                resp = self._post(target_url, data=form_data, timeout=TIMEOUT)
            else:
                # 没有表单，可能直接重定向了
                resp = self._get(URL_EXAM_LIST, timeout=TIMEOUT)

            soup = BeautifulSoup(resp.text, "lxml")
            result = _parse_table(soup)
            if result:
                return result

            # 策略2：直接 POST 学期参数到列表页
            resp = self._post(URL_EXAM_LIST,
                data={"xnxqid": semester, "method": "query"},
                timeout=TIMEOUT)
            soup = BeautifulSoup(resp.text, "lxml")
            result = _parse_table(soup)
            if result:
                return result

            # 策略3：GET 列表页（可能查询页已设置会话状态）
            resp = self._get(URL_EXAM_LIST, timeout=TIMEOUT)
            soup = BeautifulSoup(resp.text, "lxml")
            result = _parse_table(soup)
            if result:
                return result

            # 全部失败，诊断
            title = soup.find("title")
            page_title = title.get_text(strip=True) if title else "无标题"
            has_login = "logon" in resp.text.lower() or "登录" in resp.text
            form_count = len(soup.find_all("form"))
            table_count = len(soup.find_all("table"))
            self._log(f"[考试HTML] 未找到数据表格")
            self._log(f"  页面标题: {page_title}")
            self._log(f"  响应长度: {len(resp.text)}")
            self._log(f"  表单数量: {form_count}, 表格数量: {table_count}")
            self._log(f"  疑似登录页: {has_login}")
            self._log(f"  疑似登录页: {has_login}")
            if has_login:
                self.last_error = "考试页面需要重新登录，请先在设置页登录"
            else:
                self.last_error = f"考试页面解析失败（表格数={table_count}），可能本学期暂无考试"
            return []
        except Exception as e:
            self.last_error = f"考试HTML解析失败: {e}"
            return []

    # ================================================================
    # 成绩查询
    # ================================================================

    def get_grades(self, semester: str = "") -> list[dict]:
        """获取成绩数据"""
        if not self.logged_in:
            self.last_error = "未登录"
            return []
        # 先尝试 API，失败则降级到 HTML
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
            resp = self._post(
                URL_APP_DO,
                params={"method": "getCjcx", "xh": self.student_id, "xnxqid": semester},
                headers={"token": self.token} if self.token else {},
                timeout=TIMEOUT)
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
            # 候选表格
            candidates = []
            candidates.append(soup.find("table", id="dataList"))
            candidates.append(soup.find("table", class_="Nsb_r_list"))
            candidates.extend(soup.find_all("table", class_=lambda c: c and "Nsb" in c if c else False))
            # 兜底：所有表格
            for tbl in soup.find_all("table"):
                if tbl not in candidates:
                    candidates.append(tbl)

            for t in candidates:
                if t is None:
                    continue
                rows = t.find_all("tr")
                if len(rows) < 2:
                    continue
                # 检查表头
                hdr_cells = rows[0].find_all(["td", "th"])
                hdr_texts = [c.get_text(strip=True) for c in hdr_cells]
                print(f"[成绩] {label} 候选表格: {len(rows)}行, 表头: {hdr_texts[:12]}")

                # 必须有至少一个成绩相关关键词
                hdr_joined = " ".join(hdr_texts)
                if not any(kw in hdr_joined for kw in ("课程名称", "课程", "成绩", "学分", "绩点", "分数")):
                    continue

                # 建立列映射（精确匹配，避免 "成绩" 误匹配 "成绩标识"）
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

                # 兜底：强智教务常见布局（含成绩标识列）
                # 序号|开课学期|课程编号|课程名称|成绩|成绩标识|学分|总学时|考核方式|课程属性|课程性质
                if "course_name" not in col:
                    col = {"course_name": 3, "score": 4, "credit": 6,
                           "grade_point": None, "course_type": 9, "exam_type": 8,
                           "course_nature": 10, "course_code": 2, "semester": 1}
                    print(f"[成绩] {label} 表头匹配失败，使用固定位置")
                else:
                    print(f"[成绩] {label} 表头映射: {col}")
                # 没有绩点列时设为 None（此教务系统无绩点）
                if "grade_point" not in col:
                    col["grade_point"] = None

                def _get(key, default=""):
                    idx = col.get(key)
                    if idx is not None and idx < len(hdr_cells):
                        return hdr_cells[idx].get_text(strip=True) if False else ""
                    return default
                # 重新定义 _get 使用实际数据行
                break
            else:
                print(f"[成绩] {label} 未找到合适的表格（共检查 {len(candidates)} 个候选）")
                return None

            # 用这个表格的数据行解析
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

            print(f"[成绩] {label} 解析完成: {len(grades)} 条")
            if grades:
                print(f"[成绩] 首条: {grades[0]}")
            return grades if grades else None

        # =================================================================
        # 策略执行
        # =================================================================
        strategies = []

        # 策略1: GET 查询页（可能直接显示结果）
        try:
            print(f"[成绩] 策略1: GET {URL_GRADE_QUERY}")
            resp = self._get(URL_GRADE_QUERY, timeout=TIMEOUT)
            print(f"[成绩]   状态={resp.status_code} 长度={len(resp.text)} "
                  f"标题={self._page_title(resp)}")
            soup = BeautifulSoup(resp.text, "lxml")

            # 如果有表单，收集表单数据
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
                # 构造目标 URL
                if action:
                    if action.startswith("/"):
                        target = f"{BASE_9080}{action}"
                    elif action.startswith("http"):
                        target = action
                    else:
                        target = f"{BASE_9080}/njlgdx/kscj/{action}"
                else:
                    target = URL_GRADE_LIST

                strategies.append(("POST表单", lambda: self._post(target, data=form_data, timeout=TIMEOUT)))
                print(f"[成绩]   找到表单, action={action}, 目标={target}, form_data keys={list(form_data.keys())}")

            # 先试试查询页直接有没有表格
            result = _parse_table(soup, "策略1直接")
            if result:
                return result

            # 策略1.5：如果查询页是带学期参数直接显示，尝试带 semester 的 GET
            if semester:
                strategies.append(("GET列表页(带学期)", lambda: self._get(
                    f"{URL_GRADE_LIST}?xnxqid={semester}", timeout=TIMEOUT)))
        except Exception as e:
            print(f"[成绩] 策略1异常: {e}")

        # 策略2: 直接 POST 列表页
        strategies.append(("POST列表页", lambda: self._post(
            URL_GRADE_LIST, data={"xnxqid": semester}, timeout=TIMEOUT)))

        # 策略3: GET 列表页
        strategies.append(("GET列表页", lambda: self._get(
            URL_GRADE_LIST, timeout=TIMEOUT)))

        # 执行策略
        last_soup = None
        for sname, sfn in strategies:
            print(f"[成绩] {sname}...")
            try:
                resp = sfn()
                print(f"[成绩]   状态={resp.status_code} 长度={len(resp.text)} "
                      f"标题={self._page_title(resp)}")
                soup = BeautifulSoup(resp.text, "lxml")
                last_soup = soup
                result = _parse_table(soup, sname)
                if result:
                    return result
            except Exception as e:
                print(f"[成绩]   {sname} 异常: {e}")

        # 全部失败，诊断
        self._log(f"[成绩] ===== 所有策略均失败 =====")
        if last_soup:
            tables = last_soup.find_all("table")
            self._log(f"[成绩] 总表格数: {len(tables)}")
            for i, tbl in enumerate(tables[:5]):
                rows = tbl.find_all("tr")
                r0 = rows[0].get_text("|", strip=True)[:120] if rows else "(空)"
                self._log(f"[成绩]   表格#{i}: {len(rows)}行, 首行: {r0}")
            has_login = "logon" in str(last_soup).lower() or "登录" in str(last_soup)
            if has_login:
                self.last_error = "成绩页面需要重新登录，请先在设置页登录"
            else:
                self.last_error = "成绩解析失败"
        else:
            self.last_error = "无法访问成绩页面"
        return []

    @staticmethod
    def _to_float(val) -> float:
        """安全转换为 float"""
        try:
            return float(val)
        except (ValueError, TypeError):
            return 0

    # ================================================================
    # 等级考试（四六级）
    # ================================================================

    def get_cet_scores(self) -> list[dict]:
        """获取四六级成绩

        从 /njlgdx/kscj/djkscj_list 页面抓取等级考试成绩，
        解析 #dataList 表格，提取 CET4/CET6 的最高分。

        返回: [{type: "CET4"/"CET6", score: float, exam_date: str}, ...]
        """
        import re
        try:
            resp = self._get(URL_CET_LIST, timeout=TIMEOUT)
            if resp.status_code != 200:
                print(f"[CET] 请求失败: {resp.status_code}")
                return []
            print(f"[CET] GET {URL_CET_LIST} → status={resp.status_code} len={len(resp.text)}")
        except Exception as e:
            print(f"[CET] 请求异常: {e}")
            return []

        soup = BeautifulSoup(resp.text, "lxml")
        table = soup.find("table", id="dataList")
        if not table:
            print("[CET] 未找到 #dataList 表格")
            return []

        rows = table.find_all("tr")
        if len(rows) < 3:  # 2行表头 + 至少1行数据
            print(f"[CET] 表格行数不足: {len(rows)}")
            return []

        cet_records = []  # [(type, score, date), ...]

        for row in rows[2:]:  # 跳过前2行表头
            cells = row.find_all("td")
            if len(cells) < 9:
                continue

            course_name = cells[1].get_text(strip=True)  # 考级课程(等级)
            total_score_text = cells[4].get_text(strip=True)  # 分数类 > 总成绩
            exam_date = cells[8].get_text(strip=True)  # 考级时间

            # 识别 CET4/CET6
            if "CET6" in course_name:
                cet_type = "CET6"
            elif "CET4" in course_name:
                cet_type = "CET4"
            else:
                continue  # 跳过英语分级考试等

            try:
                score = float(total_score_text)
            except (ValueError, TypeError):
                continue

            if score <= 0:
                continue  # 0分表示未参加

            cet_records.append((cet_type, score, exam_date))
            print(f"[CET]   解析: {cet_type} {score}分 {exam_date}")

        if not cet_records:
            print("[CET] 未找到有效四六级成绩")
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

        print(f"[CET] 汇总: {result}")
        return result

    # ================================================================
    # 工具
    # ================================================================

    def _current_semester(self) -> str:
        y, m = time.localtime().tm_year, time.localtime().tm_mon
        if m >= 9: return f"{y}-{y+1}-1"
        elif m >= 2: return f"{y-1}-{y}-2"
        else: return f"{y-1}-{y}-1"

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
            resp = self._get(URL_EVAL_PAGE, timeout=TIMEOUT)
            soup = BeautifulSoup(resp.text, "lxml")
            table = soup.find("table", class_="Nsb_r_list")
            if not table:
                self.last_error = "评价页面未找到数据表格"
                self._log(f"[评价] 未找到 Nsb_r_list 表格，表格数={len(soup.find_all('table'))}")
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
