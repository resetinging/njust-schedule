# -*- coding: utf-8 -*-
"""BaseMixin(Phase 2 从 jwc_client.py 拆出)。"""
from wxcloudrun.jwc.common import *  # noqa: F401,F403
from wxcloudrun.jwc.common import (  # noqa: F401
    _DedupCookieJar, _encrypt_sso_password, _dedupe_schedule_courses)


class BaseMixin:

    # 每实例独立的并发锁：同一用户的教务请求串行（保证 Cookie/会话一致性），
    # 不同用户实例互不阻塞（配合 views 的全局信号量限流 = 访问池）
    def __init__(self, pool_maxsize: int = 8):
        import threading
        self._lock = threading.Lock()
        self._pool_maxsize = pool_maxsize
        self.debug_log = []  # 智慧理工 SSO 诊断日志
        self.webvpn = None
        self._logon_base_idx = 0  # 登录入口候选下标（节点不通时自动切换）
        self._setup_session()
        self.token = None
        self.student_id = None
        self.student_name = None
        self.logged_in = False
        self.login_method = ""
        self.last_error = ""
        self._captcha_ready = False
        self._active_captcha_url = URL_CAPTCHA_CANDIDATES[0]
        # 智慧理工手动验证码中间状态
        self._webvpn_manual_ready = False
        self._webvpn_post_url = ""
        self._webvpn_login_page_url = ""
        # 会话有效性探测缓存（避免每个请求都访问教务主页探测）
        self._validity_cache_ts = 0.0
        self._validity_cache_ok = False

    def _setup_session(self):
        """（重）建 HTTP 会话：连接池适配器 + WebVPN 改写适配器

        适配器只在 WebVPNTransport.active 为真时改写教务请求；未开启时
        行为与普通 HTTPAdapter 一致（保留原连接池参数）。
        """
        self.session = requests.Session()
        self.session.cookies = _DedupCookieJar()
        self.session.headers.update(HEADERS)
        self.webvpn = WebVPNTransport(self.session, base=WEBVPN_BASE,
                                      service=WEBVPN_CAS_SERVICE, log=self._log)
        adapter = WebVPNAdapter(self.webvpn,
                                pool_connections=self._pool_maxsize,
                                pool_maxsize=self._pool_maxsize,
                                pool_block=True)
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)
        return self.session

