# -*- coding: utf-8 -*-
"""LoginMixin(Phase 2 从 jwc_client.py 拆出)。"""
from wxcloudrun.jwc.common import *  # noqa: F401,F403
from wxcloudrun.jwc.common import (  # noqa: F401
    _DedupCookieJar, _encrypt_sso_password, _dedupe_schedule_courses, _HAS_CRYPTO)


class LoginMixin:
    # ================================================================
    # 登录入口
    # ================================================================

    def login(self, student_id: str, password: str) -> bool:
        self.student_id = student_id
        self.last_error = ""
        self.logged_in = False
        self.token = None
        self._captcha_ready = False
        self._setup_session()

        # 8080 端口 Web 登录 + OCR（密码被拒时自动按初始密码规则再试一次）
        if self._try_web_auto_candidates(student_id, password):
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
                self.logon_page,
                data=payload,
                timeout=TIMEOUT,
                allow_redirects=True,  # ← 自动跟随 302 → 9080 → ...
                headers={"Referer": self.logon_page},
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

    def _jw_password_candidates(self, student_id: str, given: str = "") -> list:
        """教务登录密码候选：先用手上这个，再用初始密码规则（学号@Njust）

        用户只登智慧理工时，后端手上只有智慧理工密码；而教务密码通常是学校
        初始密码，多试一次就能免去用户额外输入。关闭见 JW_TRY_DEFAULT_PWD。
        """
        cands = []
        for pwd in (given,):
            if pwd and pwd not in cands:
                cands.append(pwd)
        if JW_TRY_DEFAULT_PWD and JW_DEFAULT_PWD_TEMPLATE:
            try:
                default_pwd = JW_DEFAULT_PWD_TEMPLATE.format(sid=student_id)
            except Exception:  # noqa: BLE001 — 模板写错不该影响登录
                default_pwd = ""
            if default_pwd and default_pwd not in cands:
                cands.append(default_pwd)
        return cands

    # ---- 登录入口(教务双节点)选择 ----
    @property
    def logon_base(self) -> str:
        bases = JW_LOGON_BASES or [BASE_URL]
        return bases[min(self._logon_base_idx, len(bases) - 1)]

    @property
    def logon_page(self) -> str:
        return f"{self.logon_base}/Logon.do?method=logon"

    @property
    def logon_sess(self) -> str:
        return f"{self.logon_base}/Logon.do?method=logon&flag=sess"

    def _captcha_candidates(self) -> list:
        b = self.logon_base
        return [f"{b}/CheckCode?date=", f"{b}/verifycode.servlet",
                f"{b}/Logon.do?method=logon&rand="]

    def _use_logon_base(self, idx: int):
        self._logon_base_idx = idx
        self._active_captcha_url = self._captcha_candidates()[0]

    def _try_web_auto_candidates(self, student_id: str, given: str) -> bool:
        """带兜底的 OCR 登录：密码被拒 → 换初始密码规则；入口不通 → 换备用节点"""
        cands = self._jw_password_candidates(student_id, given)
        bases = JW_LOGON_BASES or [BASE_URL]
        for base_idx in range(len(bases)):
            self._use_logon_base(base_idx)
            network_failed = False
            for idx, pwd in enumerate(cands):
                self.last_error = ""
                if self._try_web_auto(student_id, pwd):
                    if idx > 0:
                        self._log(f"[JW-PWD] 候选 #{idx + 1}（初始密码规则）登录成功")
                    return True
                err = self.last_error or ""
                if self._is_network_error():
                    self._log(f"[JW-HOST] 登录入口 {self.logon_base} 不可达（{err}）")
                    network_failed = True
                    break
                if "密码错误" not in err and "用户名或密码错误" not in err:
                    return False  # 验证码/其它问题：换密码和换节点都没用
                if idx + 1 < len(cands):
                    self._log(f"[JW-PWD] 候选 #{idx + 1} 被拒（{err}），改用初始密码规则重试")
            if not network_failed:
                return False
            if base_idx + 1 < len(bases):
                self._log(f"[JW-HOST] 切换到备用登录入口 {bases[base_idx + 1]}")
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

    def _log(self, msg: str):
        """记录调试日志（登录失败时可通过接口返回诊断信息）"""
        self.debug_log.append(msg)
        if DEBUG_WEBVPN:
            logger.debug("[SSO] %s", msg)

    def _is_network_error(self) -> bool:
        """上次失败是否属于网络层问题（可改走 WebVPN 代理重试）"""
        msg = self.last_error or ""
        return any(k in msg for k in (
            "无法连接", "连接超时", "超时", "timed out", "Timeout",
            "Connection", "Max retries", "unreachable", "拒绝",
        ))

    # ================================================================
    # SSO 会话复用（减少智慧理工认证次数, 避免账号被风控冻结）
    # ================================================================

    @staticmethod
    def _session_store():
        """core 层的会话持久化/节流仓储（延迟导入, 避免包初始化循环）。"""
        from wxcloudrun.core import session_store
        return session_store

    def _persist_sso_session(self) -> None:
        """登录成功后把会话 cookie 交给 core 持久化, 供下次免密码复用。"""
        if not self.student_id:
            return
        try:
            saved = self._session_store().save_session(self.student_id,
                                                       self.session.cookies)
            if saved:
                self._log(f"[SSO-Reuse] 会话已持久化({saved} cookies)")
        except Exception as e:  # noqa: BLE001 持久化失败不应影响登录结果
            self._log(f"[SSO-Reuse] 持久化失败: {type(e).__name__}: {e}")

    def _try_resume_sso_session(self) -> bool:
        """用持久化的 cookie 直接恢复教务会话; 成功则完全不提交密码。"""
        if not self.student_id:
            return False
        try:
            cookies = self._session_store().load_session(self.student_id)
            if not cookies:
                return False
            for c in cookies:
                try:
                    self.session.cookies.set(c["name"], c["value"],
                                             domain=c.get("domain"),
                                             path=c.get("path") or "/")
                except Exception:  # noqa: BLE001 单个 cookie 异常直接跳过
                    continue
            self._log(f"[SSO-Reuse] 载入 {len(cookies)} 个持久化 cookie, 试探教务入口...")
            resp = self.session.get(JW_SSO_ENTRY, timeout=TIMEOUT, allow_redirects=True)
            self._dedupe_cookies()
            if not self._check_success(resp):
                self._log("[SSO-Reuse] 会话已失效, 需要重新认证")
                return False
            self._extract_name(resp.text)
            self.webvpn.enable_sso_direct(JW_SSO_BASE)
            self.logged_in = True
            self.login_method = "sso-cached"
            self._log("[SSO-Reuse] [OK] 复用持久化会话成功(未提交密码)")
            return True
        except Exception as e:  # noqa: BLE001 复用失败就走正常登录流程
            self._log(f"[SSO-Reuse] 复用异常: {type(e).__name__}: {e}")
            return False

    def login_webvpn(self, student_id: str, password: str,
                     jwc_password: str = "", use_webvpn: bool = False) -> bool:
        """通过智慧理工 SSO 登录 + 直连教务（可选 WebVPN 代理）

        流程：
        1. 直连 SSO（ids.njust.edu.cn）登录验证身份
        2. 用 CAS 票据建立 WebVPN 会话（校外只开放 WebVPN 入口时使用）
        3. 尝试直连教务（CAS ticket 自动登录）
        4. 否则走标准 8080 Logon.do 登录 → 302 → 9080 重定向链
        5. 直连被网络阻断时，自动改走 WebVPN 代理重试（WEBVPN_ENABLED=auto）

        password = 智慧理工密码; jwc_password = 教务密码(可与前者不同,
        未提供时回退为智慧理工密码)。SSO 用前者, 教务登录用后者。
        use_webvpn=True 时强制教务请求走 WebVPN 代理。
        """
        jwc_pwd = jwc_password or password
        self.student_id = student_id
        self.student_name = None
        self.last_error = ""
        self.logged_in = False
        self.login_method = ""
        self.token = None
        self._captcha_ready = False
        self.debug_log = []
        self._setup_session()

        if not _HAS_CRYPTO:
            self.last_error = "SSO 登录需要 pycryptodome 模块，请重新部署服务"
            return False

        try:
            # Step 0: 复用持久化会话（不提交密码, 大幅减少智慧理工认证次数）
            if self._try_resume_sso_session():
                return True

            left = self._session_store().cooldown_left(student_id)
            if left > 0:
                self.last_error = f"为避免账号被冻结，请 {left} 秒后再试"
                return False

            # Step 1: 直连 SSO 登录
            if not self._direct_sso_login_with_retry(student_id, password):
                self._session_store().mark_failure(student_id)
                return False
            self._session_store().clear_failure(student_id)
            self._persist_sso_session()

            # Step 2: 需要代理时建立 WebVPN 会话（网关登录入口即统一身份认证 CAS）
            # 注意: auto 模式不在这里建会话 —— 每个账号的 WebVPN 会话可能互踢，
            # 无谓地登录会把用户浏览器自己的 WebVPN 会话顶掉，只在直连网络
            # 失败时（Step 5）才建。
            want_webvpn = use_webvpn or WEBVPN_ENABLED == "on"
            if want_webvpn:
                if WEBVPN_ENABLED == "off":
                    self.last_error = "WebVPN 已关闭（WEBVPN_ENABLED=off）"
                    return False
                if not self.webvpn.authenticate():
                    self.last_error = "WebVPN 会话建立失败，请稍后重试"
                    return False
                self.webvpn.verify()
                self.webvpn.activate()

            # Step 3: SSO 直连教务（首选：免教务密码、免验证码）
            if self._try_indexsso_login():
                self._persist_sso_session()
                return True

            # Step 4: 尝试 CAS 自动登录教务（旧的 service 猜测，保留兜底）
            if self._try_direct_jw_access():
                self._persist_sso_session()
                return True

            # Step 5: 标准 8080 Logon.do 流程（教务直连已下线, 默认跳过）
            if JW_ALLOW_FORM_FALLBACK:
                self._log("[SSO-JW] 教务需要表单登录，走 8080 Logon.do 标准流程...")
                if self._try_web_auto_candidates(student_id, jwc_pwd):
                    self.logged_in = True
                    self.login_method = "webvpn"
                    self._persist_sso_session()
                    return True
            else:
                self._log("[SSO-JW] 8080 表单登录已下线（教务直连）, 跳过表单兜底")

            # Step 6: 直连被网络阻断时改走 WebVPN 代理重试
            if not self.webvpn.active and WEBVPN_ENABLED == "auto" and self._is_network_error():
                self._log(f"[WebVPN] 直连失败({self.last_error})，尝试建会话并改走代理...")
                if self.webvpn.authenticate():
                    self.webvpn.verify()
                    self.webvpn.activate()
                    self.last_error = ""
                    if JW_ALLOW_FORM_FALLBACK:
                        if self._try_web_auto_candidates(student_id, jwc_pwd):
                            self.logged_in = True
                            self.login_method = "webvpn-proxy"
                            self._persist_sso_session()
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

    def _direct_sso_login_with_retry(self, student_id: str, password: str,
                                     attempts: int = None) -> bool:
        """SSO 验证码 OCR 偶发失败: 换一张验证码重试。

        重试次数可用环境变量 SSO_CAPTCHA_RETRY 覆盖(默认 1, 防止频繁认证触发风控冻结);
        每次重试重建会话/取登录页, 保证 execution/lt/salt 与验证码配套;
        非验证码类失败(账号密码错误等)不重试。
        """
        if attempts is None:
            try:
                attempts = max(1, int(SSO_CAPTCHA_RETRY))
            except (TypeError, ValueError):
                attempts = 1
        for i in range(1, attempts + 1):
            if self._direct_sso_login(student_id, password):
                return True
            err = self.last_error or ""
            if "验证码" not in err:
                return False
            self._log(f"[SSO-Direct] 第 {i}/{attempts} 次验证码未通过, 换一张重试")
            self._setup_session()
            if i < attempts:
                time.sleep(0.8)   # 稍作间隔, 避免连续请求触发风控
        return False

    def _direct_sso_login(self, student_id: str, password: str) -> bool:
        """直连 SSO 登录（ids.njust.edu.cn，不走 WebVPN 代理）"""
        from urllib.parse import urljoin, urlparse

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
                        sso_captcha_text = self._ocr_with_preprocess(ocr, cap_resp.content)
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

            # ★ 必须保留 service 参数: 登录页表单 action 是 '/authserver/login'(不含
            #   service), 直接按 action POST 会让 CAS 不知道该为哪个服务发票据 ——
            #   实测结果是被重定向到 error.njust.edu.cn/errorTips500.html 且没有 CASTGC。
            _query = urlparse(resp.url).query
            if "service=" in _query and "service=" not in post_url:
                post_url = f"{post_url}{'&' if '?' in post_url else '?'}{_query}"
                self._log("[SSO-Direct]   已为 POST 补回 service 参数")

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

            # ★ NJUST 出错页(出错啦)不是登录成功: 未带 service 参数 POST 时会跳到这里
            if "error.njust.edu.cn" in login_resp.url or "errorTips" in login_resp.url:
                self.last_error = "智慧理工登录未被接受（被跳转到出错页，请稍后重试）"
                self._log(f"[SSO-Direct] [FAIL] {self.last_error} url={login_resp.url[:80]}")
                return False

            # ★ 以 CASTGC(统一身份认证票据 cookie) 为准: 有它才是真的登录成功
            has_castgc = any("CASTGC" in c.name for c in self.session.cookies)
            if not has_castgc:
                self.last_error = "智慧理工未建立有效会话（未获得 CASTGC 票据）"
                self._log(f"[SSO-Direct] [FAIL] {self.last_error}")
                return False

            self._log("[SSO-Direct] [OK] SSO 登录成功 (CASTGC 已获取)")
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

    def _try_indexsso_login(self) -> bool:
        """智慧理工 SSO 直连教务（免教务密码、免验证码）

        教务的 CAS 单点登录入口是 /njlgdx/indexsso.jsp：带着 CASTGC 访问它，它会
        跳 ids 换 ST 票据再回来建立教务会话。实测链路：
            indexsso.jsp → ids/authserver/login?service=…indexsso.jsp
            → indexsso.jsp?ticket=ST-… → xk/LoginToXk?method=ptdl → framework/main.jsp

        会话 cookie 落在 JW_SSO_BASE（bkjw.njust.edu.cn）域上，因此成功后必须把
        后续教务请求都改写到该入口（enable_sso_direct），否则 cookie 跟不过去。
        """
        try:
            self._log(f"[SSO-JW] 尝试 SSO 直连入口: {JW_SSO_ENTRY}")
            resp = self.session.get(JW_SSO_ENTRY, timeout=TIMEOUT, allow_redirects=True)
            self._dedupe_cookies()
            chain = " → ".join(
                f"{h.status_code} {h.headers.get('Location', '')[:60]}" for h in resp.history[-4:])
            self._log(f"[SSO-JW]   链路: {chain or '(无跳转)'}")
            self._log(f"[SSO-JW]   最终 {resp.status_code} {resp.url[:80]} "
                      f"标题={self._page_title(resp)}")
            if not self._check_success(resp):
                self._log("[SSO-JW]   SSO 入口未建立教务会话")
                return False
            self._extract_name(resp.text)
            self.webvpn.enable_sso_direct(JW_SSO_BASE)
            self.logged_in = True
            self.login_method = "sso"
            self._log("[SSO-JW] [OK] SSO 直连教务成功（无需教务密码/验证码）")
            return True
        except Exception as e:  # noqa: BLE001 — 失败就走后面的密码登录兜底
            self._log(f"[SSO-JW]   SSO 直连异常: {type(e).__name__}: {e}")
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

    def _is_jw_login_page(self, resp) -> bool:
        """检测是否为教务登录页面（强智教务）

        注意 t 已 lower()，特征串必须用小写（原来写 "USERNAME"/"Verifyservlet"
        永远匹配不到，导致表单字段这一条判据形同虚设）。
        """
        t = resp.text.lower()
        url = resp.url.lower() if hasattr(resp, 'url') else ""
        indicators = [
            "logon.do" in url,
            "verifyservlet" in t,
            "verifycode.servlet" in t,
            ("username" in t and "password" in t and "randomcode" in t),
        ]
        return any(indicators)
