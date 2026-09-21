# -*- coding: utf-8 -*-
"""CoreMixin(Phase 2 从 jwc_client.py 拆出)。"""
from wxcloudrun.jwc.common import *  # noqa: F401,F403
from wxcloudrun.jwc.common import (  # noqa: F401
    _DedupCookieJar, _encrypt_sso_password, _dedupe_schedule_courses, _HAS_CRYPTO)


class CoreMixin:
    # ================================================================
    # 核心方法
    # ================================================================

    def _init_logon_session(self):
        self.session.cookies.clear()
        self.session.get(self.logon_page, timeout=TIMEOUT)
        self.session.headers.update({"Referer": self.logon_page})
        self._dedupe_cookies()
        self._detect_captcha_url_from_page()
        try:
            self.session.get(self.logon_sess, timeout=TIMEOUT)
            self._dedupe_cookies()
        except Exception:
            pass

    def _detect_captcha_url_from_page(self):
        try:
            resp = self.session.get(self.logon_page, timeout=TIMEOUT)
            m = re.search(
                r'<img[^>]+src=["\']([^"\']*(?:verifycode|checkcode|code)[^"\']*)["\']',
                resp.text, re.IGNORECASE)
            if m:
                src = m.group(1).strip()
                # WebVPN 网关会改写地址并注入 JS 模板，正则可能抓到
                # "…@{${#themes.code(" 这种碎片；只接受干净的 URL 形态，
                # 且跳过带 vpn- 后缀/以 /http 开头的网关改写地址
                if (src.startswith("/http") or "vpn-" in src
                        or not re.fullmatch(r"[A-Za-z0-9_\-./?=&%:]+", src)):
                    return
                self._active_captcha_url = src if src.startswith("http") else f"{self.logon_base}{src}"
                logger.debug("CaptchaURL: %s", self._active_captcha_url)
        except Exception:
            pass

    @staticmethod
    def _looks_like_image(data: bytes) -> bool:
        """按魔数判断是否图片

        原来只校验「200 且长度>100」，经 WebVPN 代理时某些候选地址会返回
        HTML（例如 /njlgdx/CheckCode），会被当成验证码交给 OCR 直接报
        「cannot identify image file」。
        """
        if len(data) < 12:
            return False
        if data[:2] == b"\xff\xd8":                      # JPEG
            return True
        if data[:8] == b"\x89PNG\r\n\x1a\n":             # PNG
            return True
        if data[:6] in (b"GIF87a", b"GIF89a"):           # GIF
            return True
        if data[:2] == b"BM":                            # BMP
            return True
        if data[:4] == b"RIFF" and data[8:12] == b"WEBP":  # WebP
            return True
        return False

    def _fetch_captcha(self) -> bytes:
        for url in [self._active_captcha_url] + self._captcha_candidates():
            try:
                r = self.session.get(url, timeout=TIMEOUT)
                self._dedupe_cookies()
                if r.status_code == 200 and self._looks_like_image(r.content):
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
        url_str = resp.url if hasattr(resp, 'url') else ""
        # 智慧理工 SSO 页面一律不算成功: 该页面自带「安全退出」链接
        # (实测 ids.njust.edu.cn 登录页含 title="安全退出"), 否则会被下面的
        # 成功关键词误判成"已登录教务", 导致跳过取验证码步骤、后续请求全部失败。
        # 只拦 SSO 域名, 不影响教务自身页面(含 Logon.do 的原有判断顺序保持不变)
        if "authserver" in url_str or "ids.njust.edu.cn" in url_str:
            return False
        # NJUST 统一出错页(e.g. error.njust.edu.cn/errorpage/errorTips500.html,
        # 标题"出错啦")同样不是教务已登录 —— 实测会被下面的关键词/URL 兜底误判为成功
        if "error.njust.edu.cn" in url_str or "errorTips" in url_str or "出错啦" in t:
            return False
        # WebVPN 网关自身的页面(门户首页/出错页)不是教务页面: 实测门户首页
        # 「资源访问控制系统 - 资源站点」会因下面的 URL 兜底被误判为已登录教务
        if "/wengine-vpn/" in url_str or "资源访问控制系统" in t:
            return False
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

