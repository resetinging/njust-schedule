"""
南理工课表管理系统 — 集中配置
==============================
合并：微信云托管模板 MySQL 配置 + NJUST 教务系统配置
"""
import os

# ============================================================
# 服务器配置
# ============================================================
HOST = "0.0.0.0"
PORT = 5000

# ============================================================
# MySQL 数据库（云托管通过环境变量注入）
# ============================================================
DEBUG = os.environ.get("DEBUG", "False").strip().lower() == "true"
MYSQL_USERNAME = os.environ.get("MYSQL_USERNAME", "root")
MYSQL_PASSWORD = os.environ.get("MYSQL_PASSWORD", "root")
MYSQL_ADDRESS = os.environ.get("MYSQL_ADDRESS", "127.0.0.1:3306")

# ============================================================
# 教务系统配置（南京理工大学 强智教务）
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
JW_SSO_BASE = os.environ.get("JW_SSO_BASE", "http://bkjw.njust.edu.cn")
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
# 空教室查询: 全校性教室课表(查询页 + 提交接口 + 教学楼联动接口)
JW_CLASSROOM_QUERY = f"{JW_BASE_9080}{JW_PATH_PREFIX}/kbcx/kbxx_classroom"
JW_CLASSROOM_LIST = f"{JW_BASE_9080}{JW_PATH_PREFIX}/kbcx/kbxx_classroom_ifr"
JW_CLASSROOM_BUILDINGS = f"{JW_BASE_9080}{JW_PATH_PREFIX}/kbcx/getJxlByAjax"

# 空教室"服务账号"(共享抓取): 教室数据全校一致, 由该账号统一查询 + 服务端
# 缓存, 小程序所有用户共享结果(无需每个用户各自用教务会话抓取)。
# 未配置 FREE_CLASSROOM_PWD 时按教务默认密码规则(学号+@Njust)尝试。
FREE_CLASSROOM_SID = os.environ.get("FREE_CLASSROOM_SID", "924101960123")
FREE_CLASSROOM_PWD = os.environ.get("FREE_CLASSROOM_PWD", "")
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
# NJUST 大节定义
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
# 用户只登智慧理工时后端手上只有智慧理工密码，而教务密码通常是学校初始密码。
# 按此规则多试一次(仅在密码被拒时才换候选)，用户就只需输一次智慧理工密码。
# 关闭：JW_TRY_DEFAULT_PWD=false，或把模板置空
JW_DEFAULT_PWD_TEMPLATE = os.environ.get("JW_DEFAULT_PWD_TEMPLATE", "{sid}@Njust")
JW_TRY_DEFAULT_PWD = os.environ.get("JW_TRY_DEFAULT_PWD", "true").strip().lower() != "false"

# ============================================================
# 管理控制面板
# ============================================================
# 管理员密码(环境变量注入; 未设置时默认 admin123, 生产环境务必修改)
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "admin123")

# ============================================================
# 调试开关
# ============================================================
DEBUG_EVAL = False
DEBUG_WEBVPN = False
