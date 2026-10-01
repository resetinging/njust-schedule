# -*- coding: utf-8 -*-
"""CalendarMixin: 教学周历(第 N 教学周 → 具体日期)。

来源: 教务 `/njlgdx/jxzl/jxzl_query`(页面表单用 select `xnxq01id` 选学期, POST 提交)。
表格 `id="kbtable"`: 首列为教学周次, 每天单元格带 `title='YYYY年MM月DD'`, 末列为备注。
"""
import re

from wxcloudrun.jwc.common import *  # noqa: F401,F403
from wxcloudrun.jwc.common import (  # noqa: F401
    _DedupCookieJar, _encrypt_sso_password, _dedupe_schedule_courses, _HAS_CRYPTO)

URL_CALENDAR_QUERY = f"{BASE_9080}{JW_PATH_PREFIX}/jxzl/jxzl_query?Ves632DSdyV=NEW_XSD_WDZM"

_ROW_RE = re.compile(r"<tr[^>]*>(.*?)</tr>", re.S | re.I)
_CELL_RE = re.compile(r"<td([^>]*)>(.*?)</td>", re.S | re.I)
_DATE_RE = re.compile(r"title=['\"](\d{4})年(\d{1,2})月(\d{1,2})['\"]")
_TAG_RE = re.compile(r"<[^>]+>")
_SEM_RE = re.compile(r"<option[^>]*value=['\"](\d{4}-\d{4}-\d)['\"][^>]*selected", re.I)


def parse_calendar(html: str) -> dict:
    """教学周历页 → {semester, first_monday, weeks:[{week, monday, sunday, days, note}]}"""
    weeks = []
    for row in _ROW_RE.findall(html):
        cells = _CELL_RE.findall(row)
        if not cells:
            continue
        week_txt = _TAG_RE.sub("", cells[0][1]).replace("&nbsp;", " ").strip()
        if not week_txt.isdigit():
            continue
        days = []
        for attrs, _body in cells:
            m = _DATE_RE.search(attrs)
            if m:
                days.append("%s-%02d-%02d" % (m.group(1), int(m.group(2)), int(m.group(3))))
        if len(days) < 7:
            continue
        note = ""
        if len(cells) > 7 and not _DATE_RE.search(cells[-1][0]):
            note = _TAG_RE.sub("", cells[-1][1]).replace("&nbsp;", " ").strip()
        weeks.append({"week": int(week_txt), "days": days[:7],
                      "monday": days[0], "sunday": days[6], "note": note})
    weeks.sort(key=lambda w: w["week"])
    sem = _SEM_RE.search(html)
    return {
        "semester": sem.group(1) if sem else "",
        "first_monday": weeks[0]["monday"] if weeks else "",
        "weeks": weeks,
    }


class CalendarMixin:

    def fetch_calendar(self, semester: str = "") -> dict:
        """抓取指定学期的教学周历; 失败返回 {} 并置 last_error。"""
        if not self.logged_in:
            self.last_error = "未登录"
            return {}
        data = {"xnxq01id": semester} if semester else {}
        try:
            resp = self.session.post(URL_CALENDAR_QUERY, data=data, timeout=TIMEOUT)
        except Exception as e:  # noqa: BLE001
            self.last_error = f"教学周历请求失败: {e}"
            return {}
        if self._is_jw_login_page(resp):
            self.logged_in = False
            self.last_error = "登录状态已失效，请重新登录"
            return {}
        parsed = parse_calendar(resp.text)
        if not parsed["weeks"]:
            self.last_error = "教学周历解析为空(页面结构可能已调整)"
            return {}
        if not parsed["semester"]:
            parsed["semester"] = semester
        return {"semester": parsed["semester"],
                "first_monday": parsed["first_monday"],
                "weeks": parsed["weeks"],
                "count": len(parsed["weeks"])}
