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


class AuthMixin:

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

