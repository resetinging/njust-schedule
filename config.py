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
DEBUG = os.environ.get("DEBUG", "True") == "True"
MYSQL_USERNAME = os.environ.get("MYSQL_USERNAME", "root")
MYSQL_PASSWORD = os.environ.get("MYSQL_PASSWORD", "root")
MYSQL_ADDRESS = os.environ.get("MYSQL_ADDRESS", "127.0.0.1:3306")

# ============================================================
# 教务系统配置（南京理工大学 强智教务）
# ============================================================
JW_BASE_8080 = "http://202.119.81.113:8080"
JW_BASE_9080 = "http://202.119.81.112:9080"
JW_LOGON_PAGE = f"{JW_BASE_8080}/Logon.do?method=logon"
JW_PATH_PREFIX = "/njlgdx"
JW_SCHEDULE_URL = f"{JW_BASE_9080}{JW_PATH_PREFIX}/xskb/xskb_list.do?Ves632DSdyV=NEW_XSD_PYGL"
JW_EXAM_QUERY = f"{JW_BASE_9080}{JW_PATH_PREFIX}/xsks/xsksap_query?Ves632DSdyV=NEW_XSD_KSBM"
JW_EXAM_LIST = f"{JW_BASE_9080}{JW_PATH_PREFIX}/xsks/xsksap_list"
JW_EVAL_PAGE = f"{JW_BASE_9080}{JW_PATH_PREFIX}/xspj/xspj_find.do?Ves632DSdyV=NEW_XSD_JXPJ"
JW_APP_DO = f"{JW_BASE_9080}{JW_PATH_PREFIX}/app.do"
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
# 调试开关
# ============================================================
DEBUG_EVAL = False
