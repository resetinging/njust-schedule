# -*- coding: utf-8 -*-
"""QrLoginMixin: 智慧理工「微信扫码登录」（后端代跑扫码流程）。

链路（读自登录页 qrcode.js / 实测通过）:
    GET  登录页(带 service)                    → 会话 + lt/execution
    POST /authserver/qrCode/getToken           → token
    GET  /authserver/qrCode/getCode?uuid=token → 二维码图片
    POST /authserver/qrCode/getStatus.htl      → 0未扫 1已确认 2已扫码 3失效
    1 时 POST /authserver/login?display=qrLogin&service=…
            (uuid/lt/cllt=qrLogin/dllt=generalLogin/execution/_eventId=submit)
         → CASTGC → indexsso.jsp → 教务会话 → 从主框架页提取学号

整条链路不提交账号密码, 因此不会触发密码风控；扫码确认在用户微信里完成。
"""
from urllib.parse import parse_qs, quote, urlparse

from wxcloudrun.jwc.common import *  # noqa: F401,F403
from wxcloudrun.jwc.common import (  # noqa: F401
    _DedupCookieJar, _encrypt_sso_password, _dedupe_schedule_courses, _HAS_CRYPTO)


class QrLoginMixin:
    def _qr_init(self):
        """每次申请二维码前重置状态。"""
        self._qr_token = ""
        self._qr_lt = ""
        self._qr_execution = "e1s1"
        self._qr_login_url = SSO_LOGIN_URL
        self._qr_image = b""      # 二维码原始 PNG, 供图片 URL 接口直接返回

    # ---------- 1) 申请二维码 ----------
    def start_qr_login(self):
        """申请一张登录二维码，返回 (base64图片, 错误信息)。"""
        self._setup_session()
        self._qr_init()
        try:
            resp = self.session.get(SSO_LOGIN_URL, timeout=TIMEOUT,
                                    allow_redirects=True)
            self._qr_login_url = resp.url
            soup = BeautifulSoup(resp.text, "lxml")

            def _val(name):
                el = (soup.find("input", attrs={"name": name, "id": name})
                      or soup.find("input", attrs={"name": name}))
                return (el.get("value") or "").strip() if el else ""

            self._qr_lt = _val("lt")
            self._qr_execution = _val("execution") or "e1s1"

            tok = self.session.post(f"{SSO_BASE}/authserver/qrCode/getToken",
                                    data={"uuid": ""}, timeout=TIMEOUT,
                                    headers={"Referer": self._qr_login_url})
            self._qr_token = (tok.text or "").strip()
            if not self._qr_token:
                return "", "获取二维码失败（未拿到 token）"

            img = self.session.get(
                f"{SSO_BASE}/authserver/qrCode/getCode?uuid={self._qr_token}",
                timeout=TIMEOUT, headers={"Referer": self._qr_login_url})
            ctype = (img.headers.get("Content-Type") or "").lower()
            if not ctype.startswith("image/") or len(img.content) < 200:
                return "", "获取二维码图片失败"
            self._qr_image = img.content
            return base64.b64encode(img.content).decode(), ""
        except requests.exceptions.ConnectionError:
            return "", "无法连接智慧理工（请检查网络）"
        except Exception as e:  # noqa: BLE001
            logger.debug("[QR] 申请二维码异常: %s", e, exc_info=True)
            return "", f"申请二维码异常: {e}"

    # ---------- 2) 轮询状态 ----------
    def poll_qr_login(self) -> str:
        """查询二维码状态: 0未扫描 1已确认 2已扫码待确认 3失效 -1异常。"""
        if not self._qr_token:
            return "-1"
        try:
            r = self.session.post(f"{SSO_BASE}/authserver/qrCode/getStatus.htl",
                                  data={"uuid": self._qr_token}, timeout=TIMEOUT,
                                  headers={"Referer": self._qr_login_url})
            return (r.text or "").strip()
        except Exception:  # noqa: BLE001 轮询异常不致命, 下次继续
            return "-1"

    # ---------- 3) 确认后换票据并建立教务会话 ----------
    def finish_qr_login(self) -> bool:
        service = (parse_qs(urlparse(self._qr_login_url).query)
                   .get("service") or [""])[0]
        url = f"{SSO_BASE}/authserver/login?display=qrLogin"
        if service:
            url += f"&service={quote(service, safe='')}"
        data = {"uuid": self._qr_token, "lt": self._qr_lt, "cllt": "qrLogin",
                "dllt": "generalLogin", "execution": self._qr_execution,
                "_eventId": "submit", "rmShown": "1"}
        try:
            self.session.post(url, data=data, timeout=TIMEOUT,
                              allow_redirects=True,
                              headers={"Referer": self._qr_login_url})
        except Exception as e:  # noqa: BLE001
            self.last_error = f"扫码换取票据异常: {e}"
            return False
        if not any("CASTGC" in c.name for c in self.session.cookies):
            self.last_error = "扫码确认后未获取票据"
            return False

        # 复用现有「SSO 直连教务」链路拿教务会话
        self.webvpn.enable_sso_direct(JW_SSO_BASE)
        if not self._try_indexsso_login():
            self.last_error = self.last_error or "扫码后未能建立教务会话"
            return False

        # 扫码登录没有外部传入学号 → 从教务主框架页提取
        if not self.student_id:
            try:
                page = self.session.get(URL_MAIN_PAGE, timeout=TIMEOUT,
                                        allow_redirects=True)
                self._extract_sid(page.text)
            except Exception:  # noqa: BLE001 提取失败下面统一报错
                pass
        if not self.student_id:
            self.last_error = "扫码成功但未能识别学号"
            return False

        self.logged_in = True
        self.login_method = "sso-qr"
        self._persist_sso_session()
        return True
