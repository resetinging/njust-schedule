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
JW_BASE_8080 = "http://202.119.81.113:8080"   # 登录认证服务器
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
# 调试开关
# ============================================================
DEBUG_EVAL = False  # 开启后每次评教提交时写 debug_submit.json
