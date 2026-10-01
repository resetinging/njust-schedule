# -*- coding: utf-8 -*-
"""ProgrammeMixin: 专业培养方案(整份, 按页抓取)。

来源: 教务 `/njlgdx/pyfa/zxjh_query_find`(查询表单) → POST `/njlgdx/pyfa/pyfa_query`。
表单字段: `xnxq`(学期, 留空=全部) / `kctxs`(课程体系, 页面 JS 拼成形如 '49','48') / `kcsx`(课程属性)
          / `pageIndex`(页码)。
结果表列: 序号 | 开课学期 | 课程编号 | 课程名称 | 开课单位 | 学分 | 总学时 | 考核方式 | 课程属性 | 是否考试 | 操作列
分页信息: "共N页 M条"。
"""
import re

from wxcloudrun.jwc.common import *  # noqa: F401,F403
from wxcloudrun.jwc.common import (  # noqa: F401
    _DedupCookieJar, _encrypt_sso_password, _dedupe_schedule_courses, _HAS_CRYPTO)

URL_PROGRAMME_QUERY = f"{BASE_9080}{JW_PATH_PREFIX}/pyfa/pyfa_query"

MAX_PAGES = 12          # 兜底上限(实测 6 页), 防止页面异常时无限翻页

_ROW_RE = re.compile(r"<tr[^>]*>(.*?)</tr>", re.S | re.I)
_CELL_RE = re.compile(r"<t[dh][^>]*>(.*?)</t[dh]>", re.S | re.I)
_TAG_RE = re.compile(r"<[^>]+>")
_TOTAL_RE = re.compile(r"共\s*(\d+)\s*页(?:&nbsp;|\s)*(\d+)\s*条")


def _text(html: str) -> str:
    return _TAG_RE.sub("", html).replace("&nbsp;", " ").strip()


def _to_float(v) -> float:
    try:
        return float(str(v).strip())
    except (TypeError, ValueError):
        return 0.0


def parse_programme_page(html: str) -> dict:
    """单页培养方案 → {courses:[...], total_pages, total_count}"""
    courses = []
    for row in _ROW_RE.findall(html):
        cells = [_text(c) for c in _CELL_RE.findall(row)]
        cells = [c for c in cells if c != ""]
        if len(cells) < 9 or not cells[0].isdigit():
            continue                      # 表头/空行
        courses.append({
            "semester": cells[1],
            "code": cells[2],
            "name": cells[3],
            "dept": cells[4],
            "credit": _to_float(cells[5]),
            "hours": _to_float(cells[6]),
            "exam_type": cells[7],
            "attribute": cells[8],
            "is_exam": cells[9] if len(cells) > 9 else "",
        })
    m = _TOTAL_RE.search(html)
    return {
        "courses": courses,
        "total_pages": int(m.group(1)) if m else 0,
        "total_count": int(m.group(2)) if m else 0,
    }


class ProgrammeMixin:

    def fetch_programme(self) -> dict:
        """抓取整份专业培养方案(自动翻页); 失败返回 {} 并置 last_error。"""
        if not self.logged_in:
            self.last_error = "未登录"
            return {}
        courses, pages, seen = [], 0, set()
        total_pages = None
        for page in range(1, MAX_PAGES + 1):
            try:
                resp = self.session.post(
                    URL_PROGRAMME_QUERY,
                    data={"kctxs": "", "xnxq": "", "kcsx": "", "pageIndex": str(page)},
                    timeout=TIMEOUT)
            except Exception as e:  # noqa: BLE001
                self.last_error = f"培养方案请求失败: {e}"
                return {}
            if self._is_jw_login_page(resp):
                self.logged_in = False
                self.last_error = "登录状态已失效，请重新登录"
                return {}
            one = parse_programme_page(resp.text)
            if page == 1:
                total_pages = one["total_pages"] or 1
                if not one["courses"]:
                    self.last_error = "培养方案解析为空(页面结构可能已调整)"
                    return {}
            pages = page
            for c in one["courses"]:
                key = (c["semester"], c["code"])
                if key in seen:
                    continue
                seen.add(key)
                courses.append(c)
            if page >= total_pages:
                break
        return {"courses": courses, "pages": pages, "count": len(courses)}
