"""
课表助手 — 集中配置
==============================
合并：微信云托管模板 MySQL 配置 + 教务系统配置
"""
import os


def _env_int(name, default, minimum=None, maximum=None):
    try:
        value = int(os.environ.get(name, str(default)))
    except (TypeError, ValueError):
        value = int(default)
    if minimum is not None:
        value = max(minimum, value)
    if maximum is not None:
        value = min(maximum, value)
    return value

# ============================================================
# 服务器配置
# ============================================================
HOST = "0.0.0.0"
PORT = 5000

# ============================================================
# MySQL 数据库（云托管通过环境变量注入）
# ============================================================
DEBUG = os.environ.get("DEBUG", "False").strip().lower() == "true"
MYSQL_USERNAME = os.environ.get("MYSQL_USERNAME", "")
MYSQL_PASSWORD = os.environ.get("MYSQL_PASSWORD", "")
MYSQL_ADDRESS = os.environ.get("MYSQL_ADDRESS", "")

# ============================================================
# 教务系统配置（强智教务）
# ============================================================
JW_BASE_8080 = "http://202.119.81.113:8080"
JW_BASE_9080 = "http://202.119.81.112:9080"
JW_LOGON_PAGE = f"{JW_BASE_8080}/Logon.do?method=logon"
# 登录入口候选（按序尝试）：教务是双节点，实测 .113 会整体不通（两个端口都超时），
# 而 .112:8080 形态完全一致，作为备用登录入口。环境变量 JW_LOGON_BASES 可覆盖（逗号分隔）
J_LOGON_BASES_ENV = os.environ.get("JW_LOGON_BASES", "").strip()
JW_LOGON_BASES = ([b.strip().rstrip("/") for b in J_LOGON_BASES_ENV.split(",") if b.strip()]
                  if J_LOGON_BASES_ENV
                  else [JW_BASE_8080, "http://202.119.81.112:8080"])

# ============================================================
# 智慧理工 SSO 直连教务（免教务密码/免验证码）
# ============================================================
# 教务的 CAS 单点登录入口就是 /njlgdx/indexsso.jsp：携带 CASTGC 访问它会自动
# 换到 ST 票据并建立教务会话（实测链路：
#   indexsso.jsp → ids/authserver/login?service=…indexsso.jsp
#   → indexsso.jsp?ticket=ST-… → xk/LoginToXk?method=ptdl → framework/main.jsp）
# 会话 cookie 落在 bkjw.njust.edu.cn 域上，因此 SSO 模式下教务请求统一走该入口。
# 必须用 https: 该入口对 http 一律 302 到 https, 而 SSO 直达模式会把请求统一改写回
# 本 base, 用 http 会造成 "改写 → 302 → 再改写" 的无限重定向(实测 30 次后报错)。
JW_SSO_BASE = os.environ.get("JW_SSO_BASE", "https://bkjw.njust.edu.cn")
JW_PATH_PREFIX = "/njlgdx"
JW_SSO_ENTRY = f"{JW_SSO_BASE}{JW_PATH_PREFIX}/indexsso.jsp"
JW_SCHEDULE_URL = f"{JW_BASE_9080}{JW_PATH_PREFIX}/xskb/xskb_list.do?Ves632DSdyV=NEW_XSD_PYGL"
JW_EXAM_QUERY = f"{JW_BASE_9080}{JW_PATH_PREFIX}/xsks/xsksap_query?Ves632DSdyV=NEW_XSD_KSBM"
JW_EXAM_LIST = f"{JW_BASE_9080}{JW_PATH_PREFIX}/xsks/xsksap_list"
JW_EVAL_PAGE = f"{JW_BASE_9080}{JW_PATH_PREFIX}/xspj/xspj_find.do?Ves632DSdyV=NEW_XSD_JXPJ"
JW_GRADE_QUERY = f"{JW_BASE_9080}{JW_PATH_PREFIX}/kscj/cjcx_query?Ves632DSdyV=NEW_XSD_XJCJ"
JW_GRADE_LIST = f"{JW_BASE_9080}{JW_PATH_PREFIX}/kscj/cjcx_list"
JW_CET_LIST = f"{JW_BASE_9080}{JW_PATH_PREFIX}/kscj/djkscj_list"
JW_APP_DO = f"{JW_BASE_9080}{JW_PATH_PREFIX}/app.do"
# 空教室查询: 教室借用查询(查询页 + 结果接口)
JW_BORROW_QUERY = f"{JW_BASE_9080}{JW_PATH_PREFIX}/kbxx/jsjy_query"
JW_BORROW_LIST = f"{JW_BASE_9080}{JW_PATH_PREFIX}/kbxx/jsjy_query2"

# 空教室"服务账号"(共享抓取): 教室数据全校一致, 由该账号统一查询 + 服务端
# 缓存, 小程序所有用户共享结果(无需每个用户各自用教务会话抓取)。
# 教务直连已下线 → 该账号改用智慧理工 SSO 登录。
# **密码不写进仓库**(公开仓库, 环境变量在云端又不可用): 存 settings 表
# free_classroom_pwd, 由管理面板 /admin → ⚙️ 系统 录入; 学号默认如下,
# 也可用 settings 表 free_classroom_sid 覆盖。
FREE_CLASSROOM_SID = "924101960123"
FREE_CLASSROOM_PWD = ""      # 仅作兜底, 实际从数据库读取
JW_CAPTCHA_URLS = [
    f"{JW_BASE_8080}/CheckCode?date=",
    f"{JW_BASE_8080}/verifycode.servlet",
    f"{JW_BASE_8080}/Logon.do?method=logon&rand=",
]

# ============================================================
# HTTP 请求配置
# ============================================================
HTTP_TIMEOUT = 15
HTTP_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Accept-Encoding": "gzip, deflate",
}

# ============================================================
# 大节定义
# ============================================================
BIG_PERIOD_MAP = {
    "第一": (1, 3),
    "第二": (4, 5),
    "第三": (6, 7),
    "第四": (8, 10),
    "第五": (11, 13),
    "中午": (14, 14),
}

# ============================================================
# 智慧理工 SSO 配置（校外/备用登录方式）
# ============================================================
SSO_BASE = "https://ids.njust.edu.cn"
SSO_LOGIN_URL = (
    f"{SSO_BASE}/authserver/login"
    "?service=https%3A%2F%2Fehall2.njust.edu.cn%2Flogin"
)
# 会话复用与认证节流（频繁提交密码会被智慧理工风控冻结）
# 持久化的是会话 cookie（非密码）；CAS 票据实测有效期 30 天（登录带 rememberMe），
# 上限与之对齐，避免无谓地重新认证；复用前仍会探测有效性，退出登录会主动删除。
SSO_SESSION_SETTING_KEY = "jwc_session"
SSO_SESSION_MAX_AGE = _env_int(
    "SSO_SESSION_MAX_AGE", 30 * 24 * 3600, 60, 365 * 24 * 3600)
# 教务业务数据缓存与持久会话同周期；会话重新建立或用户主动刷新时更新。
DATA_CACHE_TTL = _env_int(
    "DATA_CACHE_TTL", 30 * 24 * 3600, 60, 365 * 24 * 3600)
# 服务端保存密码用于免 SSO 恢复的本地信任期；只有真实 SSO 登录成功才续期。
CREDENTIAL_TRUST_TTL = _env_int(
    "CREDENTIAL_TRUST_TTL", 24 * 3600, 60, 30 * 24 * 3600)
# 同一学号认证失败后的冷却秒数（冷却期内不再打智慧理工；只防连点，不长时间拦人）
SSO_LOGIN_COOLDOWN = _env_int("SSO_LOGIN_COOLDOWN", 2, 0, 3600)
# 登录密码提交次数上限：验证码识别偶发失败时换图重试的兜底。
# 实测(2026-09)智慧理工 SSO 的 checkNeedCaptcha 恒为 false、登录不需要验证码，
# 这里只是异常场景保险。1 表示不重试，2 表示最多两次提交。
SSO_CAPTCHA_RETRY = _env_int("SSO_CAPTCHA_RETRY", 2, 1, 5)
# 8080 表单登录（原「教务直连」）已于改版后失效，默认关闭；临时启用设 1
JW_ALLOW_FORM_FALLBACK = os.environ.get("JW_ALLOW_FORM_FALLBACK", "0") == "1"

# ============================================================
# WebVPN（网瑞达 wengine）代理直连
# ============================================================
# 网关地址与 CAS 服务（网关登录入口就是统一身份认证）
WEBVPN_BASE = os.environ.get("WEBVPN_BASE", "https://webvpn.njust.edu.cn")
WEBVPN_CAS_SERVICE = f"{WEBVPN_BASE}/login?cas_login=true"
# URL 改写密钥（网关 /user/info 接口返回，实测一致）
WEBVPN_KEY = "wrdvpnisthebest!"
WEBVPN_IV = "wrdvpnisthebest!"
# off = 不用；auto = 直连失败(网络不通)时自动改走代理；on = 教务请求一律走代理
WEBVPN_ENABLED = os.environ.get("WEBVPN_ENABLED", "auto").strip().lower()

# ============================================================
# 教务登录密码兜底规则
# ============================================================
# 用户只登智慧理工时后端手上只有智慧理工密码；教务初始密码兜底存在账号接管风险，
# 默认关闭。仅明确配置 JW_TRY_DEFAULT_PWD=true 时才允许尝试模板密码。
JW_DEFAULT_PWD_TEMPLATE = os.environ.get("JW_DEFAULT_PWD_TEMPLATE", "{sid}@Njust")
JW_TRY_DEFAULT_PWD = os.environ.get("JW_TRY_DEFAULT_PWD", "false").strip().lower() == "true"

# ============================================================
# 管理控制面板
# ============================================================
# 管理员密码(环境变量注入; 未设置时默认 admin123, 生产环境务必修改)
# 安全: 绝不留已知默认口令 —— 没配环境变量时生成一次性随机口令(重启即变),
# 并在日志里告警, 而不是退回 "admin123" 这种可被猜到默认值
ADMIN_PASSWORD_CONFIGURED = bool(
    os.environ.get("ADMIN_PASSWORD", "").strip())
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "")
if not ADMIN_PASSWORD:
    import logging as _logging
    import secrets as _secrets

    ADMIN_PASSWORD = _secrets.token_urlsafe(18)
    _logging.getLogger("config").warning(
        "[config] 未配置 ADMIN_PASSWORD 环境变量, 已生成本次运行的随机管理口令(重启即变); "
        "请在云托管环境变量中配置固定口令"
    )

# 教务会话 Cookie 持久化密钥(32 字节 base64)。未配置则"会话持久化"整体不启用
# (只告警, 绝不降级成明文存储)。生成: python -c "import os,base64;print(base64.b64encode(os.urandom(32)).decode())"
SESSION_KEY = os.environ.get("SESSION_KEY", "")
if not SESSION_KEY:
    import logging as _logging2

    _logging2.getLogger("config").warning(
        "[config] 未配置 SESSION_KEY, 教务会话持久化(重启后免重登)已禁用; "
        "需要该能力时在云托管环境变量中配置 32 字节 base64 密钥"
    )

# 可选: Redis 分布式状态。未配置时保持单实例兼容模式。
REDIS_URL = os.environ.get("REDIS_URL", "").strip()

# 生产环境建议关闭自动迁移, 改为发布流程执行 python tools/migrate.py。
MIGRATIONS_AUTO = os.environ.get(
    "MIGRATIONS_AUTO", "1").strip().lower() not in ("0", "false", "no")
REQUIRE_SECURE_CONFIG = os.environ.get(
    "REQUIRE_SECURE_CONFIG", "0").strip().lower() in ("1", "true", "yes")
TRUSTED_PROXY_HOPS = _env_int("TRUSTED_PROXY_HOPS", 1, 1, 20)
SESSION_TTL = _env_int("SESSION_TTL", 12 * 3600, 60, 30 * 24 * 3600)
MAX_SESSIONS = _env_int("MAX_SESSIONS", 200, 1, 100000)
JW_MAX_CONCURRENT = _env_int("JW_MAX_CONCURRENT", 4, 1, 64)


def validate() -> None:
    """启动配置校验；生产可设置 REQUIRE_SECURE_CONFIG=1 强制关键密钥。"""
    errors = []
    if REQUIRE_SECURE_CONFIG and not SESSION_KEY:
        errors.append("SESSION_KEY 未配置")
    if REQUIRE_SECURE_CONFIG and not ADMIN_PASSWORD_CONFIGURED:
        errors.append("ADMIN_PASSWORD 未配置")
    if SESSION_KEY:
        import base64
        try:
            if len(base64.b64decode(SESSION_KEY)) != 32:
                errors.append("SESSION_KEY 必须解码为 32 字节")
        except Exception:
            errors.append("SESSION_KEY 不是合法 base64")
    if errors:
        raise RuntimeError("生产配置无效: " + ", ".join(errors))

# ============================================================
# 微信小程序订阅消息(云托管环境变量注入; 模板 ID 非密钥, 可入库)
# ============================================================
MP_APPID = os.environ.get("MP_APPID", "wx1d76c0631bdeebac")
MP_SECRET = os.environ.get("MP_SECRET", "")          # 只从环境变量读取, 绝不写进仓库
# 订阅消息: 当前只做"考试提醒"; 将来要加成绩/截止提醒, 在此追加模板 ID 并在
# core/subscribe_store.py 的 KINDS 中登记即可(前端会自动多显示一行)。
SUBSCRIBE_TPL_EXAM = os.environ.get("SUBSCRIBE_TPL_EXAM",
                                    "ng8fatzWFGkwY5Q5X2QM-BNktLyMLQPaJl2xFi7Z180")

# ============================================================
# 调试开关
# ============================================================
DEBUG_EVAL = False
DEBUG_WEBVPN = False
