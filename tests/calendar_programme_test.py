# -*- coding: utf-8 -*-
"""教学周历 / 培养方案 解析与应用层测试(离线, 用 tests/fixtures 里的脱敏样本)。"""
import os
import sys
from types import SimpleNamespace

_here = os.path.dirname(os.path.abspath(__file__))
os.environ.setdefault("SQLALCHEMY_DATABASE_URI",
                      "sqlite:///" + os.path.join(_here, "calendar_programme_tmp.db").replace("\\", "/"))
sys.path.insert(0, os.path.dirname(_here))

from wxcloudrun.jwc.calendar import parse_calendar, CalendarMixin  # noqa: E402
from wxcloudrun.jwc.programme import parse_programme_page, ProgrammeMixin  # noqa: E402
from wxcloudrun.jwc.profile import parse_profile  # noqa: E402

FIX = os.path.join(_here, "fixtures")
PASS, FAIL, FAILURES = 0, 0, []


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  [PASS] " + name)
    else:
        FAIL += 1
        FAILURES.append(name)
        print("  [FAIL] " + name + (" -> " + str(detail) if detail else ""))


def read(name):
    return open(os.path.join(FIX, name), encoding="utf-8").read()


class _CalClient(CalendarMixin):
    def __init__(self, html):
        self.logged_in = True
        self.last_error = ""
        self._html = html
        self.posted = None
        self.session = SimpleNamespace(post=self._post)

    def _post(self, url, data=None, timeout=None):
        self.posted = data
        return SimpleNamespace(text=self._html)

    def _is_jw_login_page(self, resp):
        return False


class _PrgClient(ProgrammeMixin):
    def __init__(self, pages):
        self.logged_in = True
        self.last_error = ""
        self._pages = pages
        self.calls = []
        self.session = SimpleNamespace(post=self._post)

    def _post(self, url, data=None, timeout=None):
        page = int((data or {}).get("pageIndex", 1))
        self.calls.append(page)
        return SimpleNamespace(text=self._pages.get(page, self._pages.get(2, "")))

    def _is_jw_login_page(self, resp):
        return False


print("== 教学周历解析 ==")
cal = parse_calendar(read("jw_calendar.html"))
check("学期识别", cal["semester"] == "2026-2027-1", cal["semester"])
check("周数 = 21", len(cal["weeks"]) == 21, len(cal["weeks"]))
check("第一周周一 = 2026-08-24", cal["first_monday"] == "2026-08-24", cal["first_monday"])
check("第 1 周 7 天日期", cal["weeks"][0]["days"][0] == "2026-08-24"
      and cal["weeks"][0]["days"][6] == "2026-08-30", cal["weeks"][0]["days"])
check("第 3 周周一 = 2026-09-07", cal["weeks"][2]["monday"] == "2026-09-07", cal["weeks"][2])

c = _CalClient(read("jw_calendar.html"))
got = c.fetch_calendar("2026-2027-1")
check("fetch_calendar 返回 21 周", got.get("count") == 21, got.get("count"))
check("fetch_calendar 提交 xnxq01id", (c.posted or {}).get("xnxq01id") == "2026-2027-1", c.posted)

empty_client = _CalClient("<html><body>无表格</body></html>")
check("空页面 → 返回空 + last_error",
      empty_client.fetch_calendar("2026-2027-1") == {} and "解析为空" in empty_client.last_error,
      empty_client.last_error)

print("== 培养方案解析 ==")
p1 = parse_programme_page(read("jw_programme_p1.html"))
p2 = parse_programme_page(read("jw_programme_p2.html"))
check("第 1 页 20 条", len(p1["courses"]) == 20, len(p1["courses"]))
check("总页数/总数 = 6 页 101 条", (p1["total_pages"], p1["total_count"]) == (6, 101),
      (p1["total_pages"], p1["total_count"]))
check("首条字段正确", p1["courses"][0]["semester"] == "2024-2025-1"
      and p1["courses"][0]["code"] == "00010701"
      and p1["courses"][0]["attribute"] == "必修"
      and p1["courses"][0]["credit"] == 0.5, p1["courses"][0])
check("第 2 页解析", len(p2["courses"]) == 20 and p2["courses"][0]["code"] == "14060602",
      p2["courses"][0] if p2["courses"] else None)

pc = _PrgClient({1: read("jw_programme_p1.html"), 2: read("jw_programme_p2.html")})
res = pc.fetch_programme()
check("多页抓取: 按总页数抓到 6 页", pc.calls == [1, 2, 3, 4, 5, 6], pc.calls)
check("多页抓取: 去重后 40 条", res.get("count") == 40, res.get("count"))

bad = _PrgClient({1: "<html><body></body></html>"})
check("空页面 → 返回空", bad.fetch_programme() == {} and "解析为空" in bad.last_error, bad.last_error)

print("== 学籍卡片解析 ==")
prof = parse_profile(read("jw_profile.html"))
fields, base = prof["fields"], prof["base"]
check("院系/专业/学制", base["college"] == "机械工程学院"
      and base["major"] == "机器人工程" and base["duration"] == "4", base)
check("学号(样本已脱敏)", base["student_id"] == "000000000000", base["student_id"])
check("姓名/性别", fields.get("姓名") == "测试学生" and fields.get("性别") == "男", fields.get("姓名"))
check("政治面貌/籍贯/民族", fields.get("政治面貌") == "共青团员"
      and fields.get("籍贯") == "吉林" and fields.get("民族") == "汉族", fields)
check("不采集简历/家庭成员段", "职务" not in fields and "与本人关系" not in fields,
      list(fields.keys())[-4:])

print()
print("结果: %d 通过, %d 失败" % (PASS, FAIL))
try:
    os.remove(os.path.join(_here, "calendar_programme_tmp.db"))
except OSError:
    pass
if FAIL:
    print("失败项:", FAILURES)
    sys.exit(1)
print("周历/培养方案测试全部通过 [OK]")
