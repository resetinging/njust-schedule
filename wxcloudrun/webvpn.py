"""南京理工大学 WebVPN（网瑞达 wengine）代理直连

用途：当教务（202.119.81.112 / 202.119.81.113）在校外无法直连、或只开放
WebVPN 入口时，把教务请求经 WebVPN 网关转发。

算法来源（实测逆向，非猜测）：
  * URL 改写器：门户 bundle /wengine-vpn/js/new-portal/37e9fa0.js 的模块 146
  * 密钥 / IV：网关 /user/info 接口自证返回
        {"wrdvpnKey": "wrdvpnisthebest!", "wrdvpnIV": "wrdvpnisthebest!"}

改写规则（与 bundle 逐句对齐）：
    token(host) = hex(iv) + hex(AES-CFB128(key, iv, pad16(host)))[:2*len(host)]
    proxy_url   = {BASE}/{proto}[-{port}]/{token}{path}

  * pad16 用字符 '0' 右补齐到 16 的整数倍
  * aes-js 的 CFB segmentSize 参数单位是「字节」，传 16 => CFB128
    （对应 pycryptodome 的 segment_size=128，注意其默认是 8）
  * 端口不参与加密，只体现在 {proto}-{port} 前缀里

实测（2026-01，本地）：
    http://bkjw.njust.edu.cn/njlgdx/framework/main.jsp
      → https://webvpn.njust.edu.cn/http/77726476706e69737468656265737421
        a2a713d27661311e2659c7fdc906/njlgdx/framework/main.jsp
    网关返回教务页面（200，URL 已被网关重写）；密钥错误则 302 /wengine-vpn/failed。

注意：
  * 校内地址 202.119.81.113:8080 / 202.119.81.112:9080 经网关返回「出错页面」或
    302 → /login，必须映射到 bkjw.njust.edu.cn（无端口）才能到达教务；根路径
    servlet 还要补 /njlgdx 前缀。
  * 网关只解决「网络可达」，不解决「身份」：经已认证的网关代理访问教务仍是登录页，
    且网关不透传 POST body 到教务登录端点（/njlgdx/xk/Verifyservlet 收到空表单
    →「验证码不能为空」），直连可用的根端点 /Logon.do 经网关 302 → /login。
  * 「身份」由教务自己的 CAS 入口 /njlgdx/indexsso.jsp 解决（见 remap_jw_url 与
    jwc_client._try_indexsso_login）：带 CASTGC 访问它即可换票建立教务会话，
    免教务密码、免验证码。会话 cookie 落在 bkjw 域上，所以那条路径要把教务请求
    统一改写到 SSO 入口（remap_jw_url），而不是走 /http…/ 代理形式。
"""

import logging
from urllib.parse import quote, urlparse

from requests.adapters import HTTPAdapter
from requests.cookies import merge_cookies

logger = logging.getLogger(__name__)

# === 网关常量（可被 config 覆盖） ===
WEBVPN_BASE = "https://webvpn.njust.edu.cn"
WEBVPN_CAS_SERVICE = f"{WEBVPN_BASE}/login?cas_login=true"
WRD_KEY = "wrdvpnisthebest!"
WRD_IV = "wrdvpnisthebest!"
SSO_BASE = "https://ids.njust.edu.cn"

# === 教务主机 → 网关可达入口 ===
# 校内地址经网关代理会「出错页面」，统一换成 bkjw（网关内部能到教务）
JW_HOST_MAP = {
    "202.119.81.113": "bkjw.njust.edu.cn",
    "202.119.81.112": "bkjw.njust.edu.cn",
}
JW_HOSTS = set(JW_HOST_MAP) | {"bkjw.njust.edu.cn"}
# bkjw 只暴露 /njlgdx 上下文：直连 8080 用的根 servlet
# (/Logon.do、/verifycode.servlet、/CheckCode) 经网关必须补前缀，
# 否则网关对根路径一律 302 到 /login（实测）
JW_PATH_PREFIX = "/njlgdx"

# === 已验证的改写向量（网关真实接受过，作为回归基准） ===
VECTOR_HOST = "202.119.81.113"
VECTOR_TOKEN = "77726476706e69737468656265737421a2a713d27661311e2659c7fdc906"


def _pad16(text: str) -> str:
    """用 '0' 右补齐到 16 的整数倍（bundle 里的 d(text,"utf8")）"""
    if len(text) % 16 == 0:
        return text
    return text + "0" * (16 - len(text) % 16)


def wengine_token(host: str, key: str = WRD_KEY, iv: str = WRD_IV) -> str:
    """把主机名加密成网关 token：hex(iv) + hex(CFB128(pad16(host)))[:2*len(host)]"""
    from Crypto.Cipher import AES  # pycryptodome：SSO 密码加密已在用，属既有依赖

    key_b = key.encode("utf-8")
    iv_b = iv.encode("utf-8")
    if len(key_b) not in (16, 24, 32):
        raise ValueError(f"WebVPN key 长度非法: {len(key_b)}")
    if len(iv_b) != 16:
        raise ValueError(f"WebVPN iv 长度非法: {len(iv_b)}")
    data = _pad16(host).encode("utf-8")
    cipher = AES.new(key_b, AES.MODE_CFB, iv=iv_b, segment_size=128)
    return iv_b.hex() + cipher.encrypt(data).hex()[: 2 * len(host)]


def is_jw_url(url: str) -> bool:
    """是否是教务地址（需要走 WebVPN 改写的目标）"""
    try:
        return (urlparse(url).hostname or "").lower() in JW_HOSTS
    except ValueError:
        return False


def to_proxy_url(url: str, base: str = WEBVPN_BASE, key: str = WRD_KEY,
                 iv: str = WRD_IV, host_map: dict = None,
                 path_prefix: str = JW_PATH_PREFIX) -> str:
    """把教务 URL 改写成 WebVPN 网关 URL（逐句复刻 bundle 模块 146 的 m()）"""
    host_map = JW_HOST_MAP if host_map is None else host_map
    p = urlparse(url)
    scheme = (p.scheme or "http").lower()
    host = (p.hostname or "").lower()
    port = p.port
    path = p.path or "/"
    if host in host_map:
        host = host_map[host]
        port = None  # 换主机后丢掉端口（网关走 80/443 入口）
        # bkjw 只暴露 /njlgdx 上下文，根 servlet 补前缀
        if path_prefix and not path.startswith(path_prefix):
            path = path_prefix + path
    token = wengine_token(host, key, iv)
    prefix = f"/{scheme}-{port}" if port is not None else f"/{scheme}"
    query = f"?{p.query}" if p.query else ""
    return f"{base.rstrip('/')}{prefix}/{token}{path}{query}"


def remap_jw_url(url: str, target_base: str, path_prefix: str = JW_PATH_PREFIX) -> str:
    """把教务地址改写到统一入口（智慧理工 SSO 直连模式用）

    indexsso.jsp 建立的教务会话 cookie 落在 bkjw.njust.edu.cn 域上，而配置里的
    数据地址是 202.119.81.112:9080 这类内网地址，cookie 不会跟过去。把主机统一
    换成 SSO 入口，会话才连续。bkjw 只暴露 /njlgdx 上下文，根路径 servlet 需补前缀。
    """
    p = urlparse(url)
    path = p.path or "/"
    if path_prefix and not path.startswith(path_prefix):
        path = path_prefix + path
    query = f"?{p.query}" if p.query else ""
    return f"{target_base.rstrip('/')}{path}{query}"


class WebVPNTransport:
    """教务请求的传输方式（两种互斥模式）

    * WebVPN 网关模式：authenticate() 用 CASTGC 换 wengine 票据，activate() 后
      把教务请求改写成 https://webvpn.njust.edu.cn/http…/ 形式（只解决网络可达）
    * SSO 直连模式：enable_sso_direct(base) 后把教务请求统一换到 indexsso.jsp
      所在入口（bkjw.njust.edu.cn），使 SSO 建立的教务会话连续可用
    """

    def __init__(self, session, base: str = WEBVPN_BASE,
                 service: str = WEBVPN_CAS_SERVICE, log=None,
                 timeout: float = 20.0):
        self.session = session
        self.base = base.rstrip("/")
        self.service = service
        self.timeout = timeout
        self.log = log or (lambda msg: None)
        self.active = False
        self.authenticated = False
        self.username = ""
        # SSO 直连模式：把教务地址统一换到这个入口（空串 = 关闭）
        self.remap_to = ""

    # ---------- SSO 直连模式 ----------
    def enable_sso_direct(self, base: str) -> bool:
        """开启「教务请求统一走 SSO 入口」的改写（与 WebVPN 网关模式互斥）"""
        self.remap_to = (base or "").rstrip("/")
        if self.remap_to:
            self.active = False  # 两种改写方式不能同时生效
            self.log(f"[SSO-Direct] 教务请求统一改写到 {self.remap_to}")
        return bool(self.remap_to)

    def disable_sso_direct(self):
        self.remap_to = ""

    # ---------- 会话建立 ----------
    def authenticate(self, timeout: float = None) -> bool:
        """用当前会话的 CASTGC 换 wengine 票据（https CAS 腿）"""
        timeout = timeout or self.timeout
        cas_url = (f"{SSO_BASE}/authserver/login"
                   f"?service={quote(self.service, safe='')}")
        try:
            self.log(f"[WebVPN] CAS 换票: {cas_url[:100]}")
            resp = self.session.get(cas_url, timeout=timeout, allow_redirects=False)
            loc = resp.headers.get("Location", "")
            if not loc:
                self.log(f"[WebVPN]   CAS 未下发票据（状态={resp.status_code}，"
                         f"URL={resp.url[:80]}）")
                return False
            if loc.startswith("/"):
                loc = self.base + loc
            self.log(f"[WebVPN]   票据回跳: {loc[:100]}")
            self.session.get(loc, timeout=timeout, allow_redirects=True)
            self.authenticated = any("wengine_vpn_ticket" in c.name
                                     for c in self.session.cookies)
            self.log(f"[WebVPN]   会话票据: {'已获取' if self.authenticated else '缺失'}")
            return self.authenticated
        except Exception as e:  # noqa: BLE001 — 任何异常都不应打断登录主流程
            self.log(f"[WebVPN]   建立会话异常: {type(e).__name__}: {e}")
            return False

    def verify(self, timeout: float = None) -> str:
        """查询 /user/info，返回已登录用户名（空串表示未登录）"""
        timeout = timeout or self.timeout
        try:
            r = self.session.get(f"{self.base}/user/info", timeout=timeout,
                                 headers={"Accept": "application/json, text/plain, */*"})
            data = r.json()
            self.username = data.get("username") or ""
            self.authenticated = bool(self.username)
            self.log(f"[WebVPN]   /user/info: username={self.username!r} "
                     f"userType={data.get('userType')!r}")
            return self.username
        except Exception as e:  # noqa: BLE001
            self.log(f"[WebVPN]   /user/info 异常: {type(e).__name__}: {e}")
            return ""

    # ---------- 开关 ----------
    def activate(self) -> bool:
        """开启教务请求改写（需已建立会话）"""
        self.active = True
        self.log("[WebVPN] 已开启教务请求代理改写")
        return True

    def deactivate(self):
        self.active = False

    def proxy(self, url: str) -> str:
        return to_proxy_url(url, base=self.base)


class WebVPNAdapter(HTTPAdapter):
    """requests 适配器：transport.active 时把教务请求透明改写到 WebVPN 网关

    在适配器层改写的好处是 jwc_client 里几十处 session.get/post 都不用改，
    且重定向链上的教务地址也会被自动改写。
    """

    def __init__(self, transport: WebVPNTransport = None, **kwargs):
        self._transport = transport
        super().__init__(**kwargs)

    def bind_transport(self, transport: WebVPNTransport):
        self._transport = transport

    @staticmethod
    def _merge_cookie_headers(orig: str, new: str) -> str:
        """合并「按原教务域算的 Cookie」和「按网关域算的 Cookie」

        按网关域重算时，教务下发的作用域 cookie（如 Path=/njlgdx 的
        JSESSIONID）会因改写后的路径 /http/<token>/... 不匹配而被丢掉，
        导致验证码/登录不是同一个后端会话；这里做并集，同名以网关域为准
        （wengine 票据轮换后的新值在网关域里）。
        """
        pairs = {}
        for part in (orig or "").split(";"):
            if "=" in part:
                k, v = part.strip().split("=", 1)
                pairs[k] = v
        for part in (new or "").split(";"):
            if "=" in part:
                k, v = part.strip().split("=", 1)
                pairs[k] = v
        return "; ".join(f"{k}={v}" for k, v in pairs.items())

    def send(self, request, **kwargs):
        t = self._transport
        if t is not None and is_jw_url(request.url):
            if t.remap_to:  # SSO 直连模式：统一换到 indexsso.jsp 所在入口
                new_url = remap_jw_url(request.url, t.remap_to)
                tag = "SSO-Direct"
            elif t.active:  # WebVPN 网关模式：改写成 /http…/ 代理地址
                new_url = t.proxy(request.url)
                tag = "WebVPN"
            else:
                return super().send(request, **kwargs)
            if new_url == request.url:
                return super().send(request, **kwargs)
            t.log(f"[{tag}] 改写: {request.url[:70]} → {new_url[:70]}")
            orig_cookie = request.headers.get("Cookie", "")
            request.url = new_url
            request.headers.pop("Host", None)  # 交给 urllib3 按新 URL 重设
            # ★ 关键：PreparedRequest 的 Cookie 头是按「改写前」的域算好的，
            #   若不重算，目标域的会话 cookie（wengine 票据 / 教务 JSESSIONID）
            #   不会被带上；但重算又会丢掉原域的作用域 cookie，所以两者取并集。
            try:
                jar = merge_cookies(t.session.cookies,
                                    getattr(request, "_cookies", None))
                request.prepare_cookies(jar)
                merged = self._merge_cookie_headers(
                    orig_cookie, request.headers.get("Cookie", ""))
                if merged:
                    request.headers["Cookie"] = merged
            except Exception as e:  # noqa: BLE001
                t.log(f"[{tag}]   Cookie 重算失败: {type(e).__name__}: {e}")
                if orig_cookie:
                    request.headers["Cookie"] = orig_cookie
        return super().send(request, **kwargs)
