"""
南理工课表管理系统 — 集中配置
==============================
所有可配置项统一管理，方便适配不同环境。
"""

# ============================================================
# 服务器配置
# ============================================================
HOST = "0.0.0.0"  # 绑定所有接口（桌面窗口 + 手机均可访问）
PORT = 5000

# ============================================================
# 教务系统配置（南京理工大学 强智教务）
# ============================================================
JW_BASE_8080 = "http://202.119.81.112:8080"   # 登录认证服务器（.112 是正确的登录入口）
JW_BASE_9080 = "http://202.119.81.112:9080"   # 业务内容服务器

# 登录页面
JW_LOGON_PAGE = f"{JW_BASE_8080}/Logon.do?method=logon"

# NJUST 路径前缀
JW_PATH_PREFIX = "/njlgdx"

# 课表 URL
JW_SCHEDULE_URL = f"{JW_BASE_9080}{JW_PATH_PREFIX}/xskb/xskb_list.do?Ves632DSdyV=NEW_XSD_PYGL"

# 考试 URL
JW_EXAM_QUERY = f"{JW_BASE_9080}{JW_PATH_PREFIX}/xsks/xsksap_query?Ves632DSdyV=NEW_XSD_KSBM"
JW_EXAM_LIST = f"{JW_BASE_9080}{JW_PATH_PREFIX}/xsks/xsksap_list"

# 教学评价 URL
JW_EVAL_PAGE = f"{JW_BASE_9080}{JW_PATH_PREFIX}/xspj/xspj_find.do?Ves632DSdyV=NEW_XSD_JXPJ"

# 成绩查询 URL
JW_GRADE_QUERY = f"{JW_BASE_9080}{JW_PATH_PREFIX}/kscj/cjcx_query?Ves632DSdyV=NEW_XSD_XJCJ"
JW_GRADE_LIST = f"{JW_BASE_9080}{JW_PATH_PREFIX}/kscj/cjcx_list"
JW_CET_LIST = f"{JW_BASE_9080}{JW_PATH_PREFIX}/kscj/djkscj_list"

# API 端点
JW_APP_DO = f"{JW_BASE_9080}{JW_PATH_PREFIX}/app.do"

# 验证码候选 URL
JW_CAPTCHA_URLS = [
    f"{JW_BASE_8080}/CheckCode?date=",
    f"{JW_BASE_8080}/verifycode.servlet",
    f"{JW_BASE_8080}/Logon.do?method=logon&rand=",
]

# ============================================================
# HTTP 请求配置
# ============================================================
HTTP_TIMEOUT = 15  # 请求超时（秒）
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
# 大节名称 → (起始小节, 结束小节)
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
# 数据库
# ============================================================
DB_FILENAME = "schedule.db"

# ============================================================
# WebVPN 配置（智慧理工 SSO 登录模式备用）
# ============================================================
WEBVPN_BASE = "https://webvpn.njust.edu.cn"

# 教务系统的 WebVPN 编码前缀（网瑞达静态编码，跨会话持久）
# 该前缀编码了教务内部服务器地址，通过 /http/{prefix}/ 路径代理
# 不同端口通过路径后缀区分（如 /http-9080/{prefix}/）
WEBVPN_PREFIX_JW = "77726476706e69737468656265737421f2fc4b8b693e62456d1cc7a99c406d361c"
# SSO 前缀（统一身份认证 authserver）
WEBVPN_PREFIX_SSO = "77726476706e69737468656265737421f9f352d2293a7d436a468ca88d1b203b"

# 智慧理工 SSO（统一身份认证平台）— 直连（不走 WebVPN 代理）
SSO_BASE = "https://ids.njust.edu.cn"
SSO_LOGIN_URL = (
    f"{SSO_BASE}/authserver/login"
    "?service=https%3A%2F%2Fehall2.njust.edu.cn%2Flogin"
)

# 智慧理工 SSO 登录页（通过 WebVPN 代理访问）
WEBVPN_SSO_LOGIN = (
    f"{WEBVPN_BASE}/https/{WEBVPN_PREFIX_SSO}"
    "/authserver/login"
)

# 教务系统基础 URL（通过 WebVPN 代理）
JW_BASE_8080_VPN = f"{WEBVPN_BASE}/http/{WEBVPN_PREFIX_JW}"
JW_BASE_9080_VPN = f"{WEBVPN_BASE}/http/{WEBVPN_PREFIX_JW}{JW_PATH_PREFIX}"

# ============================================================
# 调试开关
# ============================================================
DEBUG_EVAL = False  # 开启后每次评教提交时写 debug_submit.json
DEBUG_WEBVPN = False  # 开启后 WebVPN 登录流程输出详细日志
