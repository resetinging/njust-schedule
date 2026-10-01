# -*- coding: utf-8 -*-
"""ProfileMixin: 学籍卡片(+ 智慧理工门户身份信息, 不含头像)。

来源: 教务 `/njlgdx/grxx/xsxx`(表格 id="xjkpTable"; 首行是"院系：/专业：/学制：/班级：/学号："式
内联标签, 其后每行按 "标签/值" 成对排列); 门户 `https://ehall2.njust.edu.cn/getLoginUser`
补充身份类别与部门(不取 userIcon 头像)。
"""
import re

from wxcloudrun.jwc.common import *  # noqa: F401,F403
from wxcloudrun.jwc.common import (  # noqa: F401
    _DedupCookieJar, _encrypt_sso_password, _dedupe_schedule_courses, _HAS_CRYPTO)

URL_PROFILE = f"{BASE_9080}{JW_PATH_PREFIX}/grxx/xsxx?Ves632DSdyV=NEW_XSD_XJCJ"
EHALL_BASE = "https://ehall2.njust.edu.cn"

_ROW_RE = re.compile(r"<tr[^>]*>(.*?)</tr>", re.S | re.I)
_CELL_RE = re.compile(r"<t[dh][^>]*>(.*?)</t[dh]>", re.S | re.I)
_TAG_RE = re.compile(r"<[^>]+>")
_STOP_WORDS = ("学习及工作简历", "起始年月", "家庭情况", "家庭成员")


def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", s.replace("&nbsp;", " ").replace("\u3000", " ")).strip()


def _text(html: str) -> str:
    return _clean(_TAG_RE.sub("", html))


def parse_profile(html: str) -> dict:
    """学籍卡片页 → {fields: {标签: 值}, base: {college, major, duration, class_name, student_id}}"""
    m = re.search(r'<table[^>]*id="xjkpTable".*?</table>', html, re.S | re.I)
    table = m.group(0) if m else html
    fields = {}
    for row in _ROW_RE.findall(table):
        cells = [_text(c) for c in _CELL_RE.findall(row)]
        if not any(cells):
            continue
        # 小标题常带空格排版("家 庭 成 员 情 况"), 去空白后再匹配停止词
        joined = re.sub(r"\s+", "", "".join(cells))
        if any(w in joined for w in _STOP_WORDS):
            break                                   # 简历/家庭成员等与学籍无关
        labeled = [c for c in cells if "：" in c or ":" in c]
        if len(labeled) >= 2:                       # 首行: "院系：xxx" 形式
            for c in labeled:
                k, v = re.split(r"[：:]", c, 1)
                if k.strip() and v.strip():
                    fields[_clean(k)] = _clean(v)
            continue
        for i in range(0, len(cells) - 1, 2):       # 常规行: 标签/值 成对
            k, v = cells[i], cells[i + 1]
            if k and v:
                fields[_clean(k)] = _clean(v)
    base = {
        "college": fields.get("院系", ""),
        "major": fields.get("专业", ""),
        "duration": fields.get("学制", ""),
        "class_name": fields.get("班级", ""),
        "student_id": fields.get("学号", ""),
    }
    return {"fields": fields, "base": base}


class ProfileMixin:

    def fetch_ehall_identity(self) -> dict:
        """门户身份信息(姓名/身份类别/部门); 明确不取头像 userIcon。"""
        try:
            resp = self.session.get(f"{EHALL_BASE}/getLoginUser", timeout=TIMEOUT)
            data = (resp.json() or {}).get("data") or {}
        except Exception:  # noqa: BLE001 门户信息缺失不影响学籍卡片
            return {}
        return {
            "name": _clean(str(data.get("userName") or "")),
            "category": _clean(str(data.get("categoryName") or "")),
            "dept": _clean(str(data.get("deptName") or "")),
        }

    def fetch_profile(self) -> dict:
        """抓取学籍卡片(+门户身份); 失败返回 {} 并置 last_error。"""
        if not self.logged_in:
            self.last_error = "未登录"
            return {}
        try:
            resp = self.session.get(URL_PROFILE, timeout=TIMEOUT)
        except Exception as e:  # noqa: BLE001
            self.last_error = f"学籍卡片请求失败: {e}"
            return {}
        if self._is_jw_login_page(resp):
            self.logged_in = False
            self.last_error = "登录状态已失效，请重新登录"
            return {}
        data = parse_profile(resp.text)
        if not data["fields"]:
            self.last_error = "学籍卡片解析为空(页面结构可能已调整)"
            return {}
        extra = self.fetch_ehall_identity()
        if extra.get("category") or extra.get("dept"):
            data["identity"] = extra
        return data
