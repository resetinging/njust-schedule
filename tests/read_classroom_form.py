# -*- coding: utf-8 -*-
"""读取教务「教室课表 / 空教室」查询表单结构, 并抓真实网格做判定依据统计。

对应 docs/freeclass-fix-plan.md 的:
  Step 0  取真实数据 → 空闲格到底是"空文本"还是字面"空闲"
  Step 6  时段范围语义 → 教务是否按 jc1/jc2 只返回命中的大节列

凭据走环境变量, 不落仓库:
    $env:NJUST_SID="<学号>"; $env:NJUST_SSO_PWD="<智慧理工密码>"

用法:
    python tests/read_classroom_form.py              # 全部(表单 + 网格 + 时段对比)
    python tests/read_classroom_form.py --form       # 只读表单结构
    python tests/read_classroom_form.py --grid       # 只抓网格 + 单元格统计
    python tests/read_classroom_form.py --range      # 只做时段范围对比
    python tests/read_classroom_form.py --weekday 1 --week 3 --campus 孝陵卫

产出:
    控制台报告 + tests/_freeclass_probe.txt (完整报告)
    tests/_classroom_grid_sample.html (真实网格原文, 供离线加测试夹具)
"""
import io
import os
import sys
from collections import Counter

_here = os.path.dirname(os.path.abspath(__file__))
_root = os.path.dirname(_here)
sys.path.insert(0, _root)
sys.path.insert(0, os.path.join(_root, "wxcloudrun"))

os.environ.setdefault(
    "SQLALCHEMY_DATABASE_URI",
    "sqlite:///" + os.path.join(_here, "webvpn_tmp.db").replace("\\", "/"))

REPORT = os.path.join(_here, "_freeclass_probe.txt")
GRID_HTML = os.path.join(_here, "_classroom_grid_sample.html")

_buf = []


def out(line=""):
    print(line)
    _buf.append(line)


def head(title):
    out()
    out("=" * 74)
    out(title)
    out("=" * 74)


def arg(name, default=None):
    if name in sys.argv:
        i = sys.argv.index(name)
        if i + 1 < len(sys.argv):
            return sys.argv[i + 1]
    return default


def main():
    do_form = "--grid" not in sys.argv and "--range" not in sys.argv or "--form" in sys.argv
    do_grid = "--form" not in sys.argv and "--range" not in sys.argv or "--grid" in sys.argv
    do_range = "--form" not in sys.argv and "--grid" not in sys.argv or "--range" in sys.argv

    sid = os.environ.get("NJUST_SID", "").strip()
    sso = os.environ.get("NJUST_SSO_PWD", "")
    if not (sid and sso):
        print("缺少凭据: 请设置 NJUST_SID / NJUST_SSO_PWD")
        return 2

    campus = arg("--campus", "孝陵卫")
    weekday = int(arg("--weekday", "0") or 0)
    week = int(arg("--week", "0") or 0)

    from bs4 import BeautifulSoup  # noqa: E402
    from wxcloudrun import jwc_client  # noqa: E402
    from wxcloudrun.jwc_client import (  # noqa: E402
        JWCClient, URL_CLASSROOM_QUERY, URL_CLASSROOM_LIST)

    head("[0] 登录(SSO 直连, 免教务密码)")
    c = JWCClient()
    c.debug_log = []
    ok = c.login_webvpn(sid, sso, "")
    out("  login_webvpn → %s  方式=%r  错误=%r" % (ok, c.login_method, c.last_error))
    if not ok:
        out("  登录失败, 终止")
        _flush()
        return 1
    out("  会话有效: %s" % c.is_session_valid())

    if weekday <= 0:
        import datetime as _dt
        weekday = _dt.date.today().isoweekday()
    # 不 import views(会触发定时预热线程等副作用), 直接用教务客户端实现
    semester = c._current_semester()
    if week <= 0:
        week = 1
        out("  周次未指定, 取 1 —— 周次只影响占用数据, 不影响网格格式/状态码判定")
    out("  参数: 校区=%s 星期=%d 周次=%d 学期=%s" % (campus, weekday, week, semester))

    # ---------------------------------------------------------------- 表单
    if do_form:
        head("[1] 查询表单结构(教室课表页 select/input/form)")
        page = c.session.get(URL_CLASSROOM_QUERY, timeout=30, allow_redirects=True)
        out("  GET %s → HTTP %s  %d 字节" % (URL_CLASSROOM_QUERY, page.status_code, len(page.text)))
        soup = BeautifulSoup(page.text, "lxml")
        forms = soup.find_all("form")
        out("  <form> 数量: %d" % len(forms))
        for f in forms:
            out("    form name=%r action=%r method=%r" % (f.get("name"), f.get("action"), f.get("method")))
        for sel in soup.find_all("select"):
            opts = [(o.get_text(" ", strip=True), o.get("value")) for o in sel.find_all("option")]
            out("  <select name=%r> %d 个选项" % (sel.get("name"), len(opts)))
            for t, v in opts[:12]:
                out("      %-22r value=%r" % (t, v))
            if len(opts) > 12:
                out("      … 其余 %d 项" % (len(opts) - 12))
        for inp in soup.find_all("input"):
            out("  <input name=%r type=%r value=%r>" % (inp.get("name"), inp.get("type"), inp.get("value")))
        # 状态码所在的下拉(截图那张表): 找选项里含"调课/空闲/锁定/借用"的 select
        for sel in soup.find_all("select"):
            texts = [o.get_text(" ", strip=True) for o in sel.find_all("option")]
            joined = "".join(texts)
            if any(k in joined for k in ("调课", "空闲", "锁定", "借用")):
                out("  ★ 状态码下拉疑似: name=%r" % sel.get("name"))
                for o in sel.find_all("option"):
                    out("      %-14r value=%r" % (o.get_text(" ", strip=True), o.get("value")))

    # ---------------------------------------------------------------- 网格
    def post_grid(jc1, jc2, wd, wkk):
        """复刻 get_free_classrooms 的提交(便于拿到原文); 返回 (html, data)"""
        opts = c._classroom_page_opts()
        xnxqh = semester if (semester and semester in opts["sem_vals"]) else (
            opts["sem_vals"][0] if opts["sem_vals"] else "")
        xqid = next((v for t, v in opts["xq_map"].items() if campus and t.startswith(campus)),
                    {"孝陵卫": "01", "江阴": "4y"}.get(campus, "01"))
        wk = max(1, min(int(wkk), opts["max_week"]))
        data = {"xnxqh": xnxqh, "skyx": "", "xqid": xqid, "jzwid": "",
                "zc1": str(wk), "zc2": str(wk),
                "xq": str(wd), "xq2": str(wd), "jc1": str(jc1), "jc2": str(jc2)}
        r = c.session.post(URL_CLASSROOM_LIST, data=data, timeout=30,
                           allow_redirects=True, headers={"Referer": URL_CLASSROOM_QUERY})
        return r.text, data, xqid, xnxqh

    if do_grid:
        head("[2] 真实网格: 结构与单元格文本分布(Step 0 判定依据)")
        jc1, jc2 = 6, 7
        html, data, xqid, xnxqh = post_grid(jc1, jc2, weekday, week)
        io.open(GRID_HTML, "w", encoding="utf-8").write(html)
        out("  提交: %r" % data)
        out("  实际使用 xqid=%r xnxqh=%r (xqid 兜底映射是否被走到, 看这里)" % (xqid, xnxqh))
        out("  响应 %d 字节 → 已存 %s" % (len(html), os.path.basename(GRID_HTML)))

        soup = BeautifulSoup(html, "lxml")
        tb = soup.find("table")
        if tb is None:
            out("  ✗ 未找到 <table> —— 解析器会返回 [] 但接口仍报 success/0 间(风险 B)")
        else:
            rows = tb.find_all("tr")
            out("  行数: %d" % len(rows))
            if rows:
                heads = rows[0].find_all(["td", "th"])
                out("  第1行(星期头): %s" % [(h.get_text(strip=True), h.get("colspan")) for h in heads])
            if len(rows) > 1:
                codes = rows[1].find_all(["td", "th"])
                out("  第2行(大节码): %s" % [x.get_text(strip=True) for x in codes])
            body = rows[2:] if len(rows) > 2 else []
            out("  教室行数: %d" % len(body))
            cnt = Counter()
            for tr in body:
                cells = tr.find_all(["td", "th"])
                for cell in cells[1:]:
                    cnt[cell.get_text(strip=True)] += 1
            out("  ---- 单元格文本分布(除教室名列, 全部行×列) ----")
            for text, n in cnt.most_common(30):
                label = "(空文本)" if text == "" else ("(nbsp)" if text.strip() == "" else repr(text))
                out("      %-28s %4d 次" % (label, n))
            free_like = [t for t in cnt if t in ("空闲", "空", "-", "—")]
            out("  >>> 出现'空闲'类字面文本: %s" % (free_like if free_like else "无"))
            out("  >>> 结论: %s" % (
                "空闲格是空文本 → 现有'非空即占用'规则成立"
                if not free_like else
                "存在字面空闲标记 → 现有规则会把空闲格判为占用(风险 A 成立!)"))

        rooms = c.get_free_classrooms(campus=campus, weekday=weekday, jc1=jc1, jc2=jc2,
                                      week=week, semester=semester)
        rooms = rooms if isinstance(rooms, dict) else {}
        out("  生产解析结果: 空闲 %d 间; 前 12: %s" % (
            len(rooms.get("rooms") or []), (rooms.get("rooms") or [])[:12]))
        out("  buildings 形态: %r" % (rooms.get("buildings") or [])[:2])
        out("  last_error=%r" % c.last_error)

    # ---------------------------------------------------------------- 时段范围
    if do_range:
        head("[3] 时段范围语义实测(Step 6): 教务是否按 jc1/jc2 过滤列")
        for (a, b) in ((1, 3), (6, 7), (11, 13), (1, 13)):
            try:
                html, data, _, _ = post_grid(a, b, weekday, week)
                soup = BeautifulSoup(html, "lxml")
                tb = soup.find("table")
                cols = []
                if tb is not None:
                    rows = tb.find_all("tr")
                    if len(rows) > 1:
                        cols = [x.get_text(strip=True) for x in rows[1].find_all(["td", "th"])]
                res = c.get_free_classrooms(campus=campus, weekday=weekday, jc1=a, jc2=b,
                                            week=week, semester=semester)
                res = res if isinstance(res, dict) else {}
                out("  jc1=%2d jc2=%2d → 大节码行共 %d 列 %s | 空闲 %d 间" % (
                    a, b, len(cols), cols, len(res.get("rooms") or [])))
            except Exception as e:
                out("  jc1=%d jc2=%d → 异常 %s" % (a, b, e))
        out("  判读: 若各范围返回的列数/空闲数明显不同 → 教务按范围过滤 ✓")
        out("        若列数恒为 ≥5 且空闲数都很少 → 教务返回全部列(风险 D 成立, 需改按列头码过滤)")

    # ---------------------------------------------------------------- 矩阵取样
    if "--matrix" in sys.argv:
        head("[4] 矩阵取样: 星期×周次 的教室行数/空闲数 + 全量单元格文本分布")
        texts = Counter()
        rows_stats = []

        def sample(wd, wkk, tag):
            html, data, _, _ = post_grid(6, 7, wd, wkk)
            soup = BeautifulSoup(html, "lxml")
            tb = soup.find("table")
            rows = tb.find_all("tr") if tb else []
            body = rows[2:] if len(rows) > 2 else []
            all_empty = 0
            for tr in body:
                cells = tr.find_all(["td", "th"])
                vals = [x.get_text(strip=True) for x in cells[1:]]
                for v in vals:
                    texts[v] += 1
                if vals and not any(vals):
                    all_empty += 1
            free = len(JWCClient.parse_free_classroom_grid(html, wd))
            rows_stats.append((tag, len(body), all_empty, free))
            out("  %-16s 教室行 %3d | 全空行 %3d | 该星期空闲 %3d | jc1..jc2=%s" % (
                tag, len(body), all_empty, free, data["jc1"] + "-" + data["jc2"]))

        for wd in range(1, 8):
            try:
                sample(wd, week, "星期%d/第%d周" % (wd, week))
            except Exception as e:
                out("  星期%d 取样异常: %s" % (wd, e))
        for wkk in (1, 2, 3, 4, 6, 10, 16):
            try:
                sample(weekday, wkk, "星期%d/第%d周" % (weekday, wkk))
            except Exception as e:
                out("  第%d周 取样异常: %s" % (wkk, e))

        out("  ---- 全量单元格文本分布(所有取样, 前 40) ----")
        for text, n in texts.most_common(40):
            label = "(空/&nbsp;)" if text == "" else repr(text[:60])
            out("      %-62s %5d 次" % (label, n))
        status_like = sorted(t for t in texts if t in (
            "空闲", "L", "G", "K", "X", "J", "◆", "临时调课", "固定调课",
            "考试", "锁定", "借用", "正常上课"))
        out("  >>> 状态码字面量: %s" % (status_like if status_like else "无"))
        out("  >>> 行数是否随星期/周次变化: %s" % (
            "是" if len(set(r[1] for r in rows_stats)) > 1 else "否(恒为 %d)" % rows_stats[0][1]))
        out("  >>> 数据完整性: 若行数长期只有个位数, 说明教务只返回部分教室, "
            "'空闲教室'会漏报(需进一步确认)")

    _flush()
    return 0


def _flush():
    try:
        io.open(REPORT, "w", encoding="utf-8").write("\n".join(_buf) + "\n")
        print("\n(完整报告: %s)" % REPORT)
    except Exception as e:
        print("报告写入失败: %s" % e)


if __name__ == "__main__":
    sys.exit(main())
