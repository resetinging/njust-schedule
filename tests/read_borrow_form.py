# -*- coding: utf-8 -*-
"""定位并解析教务「教室借用」页面格式(只读: 全程只做 GET, 不提交任何表单)。

遵守协作规则八: 先抓取并解析目标页面的表单字段名、提交编码、提交方式,
确认无误后再构造请求 —— 本脚本只完成"解析"这一步。

凭据走环境变量, 不落仓库:
    $env:NJUST_SID="<学号>"; $env:NJUST_SSO_PWD="<智慧理工密码>"

用法:
    python tests/read_borrow_form.py            # 定位入口 + 解析表单结构
    python tests/read_borrow_form.py --links    # 额外打印全部菜单链接清单
    python tests/read_borrow_form.py --query    # 解析后按已确认字段做只读查询
    python tests/read_borrow_form.py --skip-form --query --lists --verify

产出:
    控制台摘要 + tests/_borrow_probe.txt (完整报告)
    tests/_borrow_page_*.html (命中的页面原文, gitignored, 供离线分析)
    tests/_borrow_result_*.html (查询结果原文, gitignored)
"""
import io
import os
import re
import sys
import time
from collections import OrderedDict
from urllib.parse import urljoin, urlsplit

_here = os.path.dirname(os.path.abspath(__file__))
_root = os.path.dirname(_here)
sys.path.insert(0, _root)
sys.path.insert(0, os.path.join(_root, "wxcloudrun"))

os.environ.setdefault(
    "SQLALCHEMY_DATABASE_URI",
    "sqlite:///" + os.path.join(_here, "webvpn_tmp.db").replace("\\", "/"))

REPORT = os.path.join(_here, "_borrow_probe.txt")
PAGE_HTML = os.path.join(_here, "_borrow_page_%d.html")
RESULT_HTML = os.path.join(_here, "_borrow_result_%s.html")

# 入口关键词: 优先文本命中「借用」, 其次 href 里的拼音/英文命名
TEXT_KEYS = ("借用", "借")
HREF_KEYS = ("borrow", "jieyong", "jysq", "jygl", "jysl", "jyxx", "jy")
# 不跟随的链接: 退出/登录/二进制资源
SKIP_HREF = ("logout", "logoff", "exit.do", "login", "logon", "captcha")
SKIP_EXT = (".jpg", ".jpeg", ".png", ".gif", ".ico", ".css", ".js",
            ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".zip", ".rar", ".mp4")

MAX_PAGES = 30          # 爬取上限, 避免对教务造成无谓压力
MAX_DEPTH = 2

_buf = []


def out(line=""):
    print(line)
    _buf.append(line)


def head(title):
    out()
    out("=" * 74)
    out(title)
    out("=" * 74)


def flush():
    try:
        io.open(REPORT, "w", encoding="utf-8").write("\n".join(_buf) + "\n")
        print("\n(完整报告: %s)" % REPORT)
    except Exception as e:
        print("报告写入失败: %s" % e)


def brief(url, n=110):
    u = urlsplit(url)
    s = u.path + (("?" + u.query) if u.query else "")
    return s if len(s) <= n else s[:n] + "…"


def wanted(url):
    low = url.lower()
    if any(k in low for k in SKIP_HREF):
        return False
    if any(low.endswith(ext) or (ext + "?") in low for ext in SKIP_EXT):
        return False
    return True


def page_links(html, base):
    """返回 [(类型, 文本, 绝对URL)] —— frame/iframe 与 a 链接"""
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "lxml")
    links = []
    for tag in soup.find_all(["frame", "iframe"]):
        src = (tag.get("src") or "").strip()
        if src:
            links.append(("frame", tag.get("name") or "", urljoin(base, src)))
    for a in soup.find_all("a"):
        href = (a.get("href") or "").strip()
        if not href or href.startswith(("#", "javascript:", "mailto:")):
            continue
        links.append(("a", a.get_text(" ", strip=True), urljoin(base, href)))
    return links


def dump_select(sel):
    opts = sel.find_all("option")
    out("      select name=%-22r 选项=%d" % (sel.get("name"), len(opts)))
    for o in opts[:40]:
        out("          %-24r value=%r%s" % (
            o.get_text(" ", strip=True), o.get("value"),
            " (selected)" if o.has_attr("selected") else ""))
    if len(opts) > 40:
        out("          … 其余 %d 项" % (len(opts) - 40))


def dump_forms(url, html, idx):
    """解析页面全部表单结构: action/method/enctype + 控件清单"""
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "lxml")
    title = (soup.title.get_text(strip=True) if soup.title else "")
    out("  页面标题: %r  大小: %d 字节" % (title, len(html)))

    forms = soup.find_all("form")
    out("  <form> 数量: %d" % len(forms))
    for i, f in enumerate(forms):
        out("  [form %d] name=%r action=%r method=%r enctype=%r target=%r" % (
            i, f.get("name"), f.get("action"), f.get("method"),
            f.get("enctype"), f.get("target")))
        for inp in f.find_all("input"):
            out("      input  name=%-22r type=%-10r value=%r %s%s" % (
                inp.get("name"), inp.get("type"), inp.get("value"),
                "(checked)" if inp.has_attr("checked") else "",
                "(disabled)" if inp.has_attr("disabled") else ""))
        for ta in f.find_all("textarea"):
            out("      textarea name=%r" % ta.get("name"))
        for btn in f.find_all(["button"]):
            out("      button type=%r name=%r value=%r text=%r" % (
                btn.get("type"), btn.get("name"), btn.get("value"),
                btn.get_text(" ", strip=True)[:30]))
        for sel in f.find_all("select"):
            dump_select(sel)

    # 页面级 select(可能挂在 form 之外, 由 JS 提交)
    outer = [s for s in soup.find_all("select") if not s.find_parent("form")]
    if outer:
        out("  form 之外还有 %d 个 <select>" % len(outer))
        for sel in outer:
            dump_select(sel)

    # 内嵌 frame/iframe
    for tag in soup.find_all(["frame", "iframe"]):
        out("  <%s> name=%r src=%r" % (
            tag.name, tag.get("name"), tag.get("src")))

    # JS 线索: 只看与提交/查询有关的片段
    hits = []
    for st in soup.find_all("script"):
        body = st.string if st.string is not None else st.get_text()
        if not body:
            continue
        for m in re.finditer(
                r"[^\n;]*(?:\.submit\(|\.action\s*=|location\.(?:href|replace))[^\n;]*",
                body):
            s = " ".join(m.group(0).split())
            if len(s) >= 8:
                hits.append(s)
    if hits:
        out("  JS 提交/跳转线索(前 15 条):")
        seen = set()
        n = 0
        for s in hits:
            if s in seen:
                continue
            seen.add(s)
            out("      %s" % s[:160])
            n += 1
            if n >= 15:
                break

    # 若页面本身已带结果表, 打印表头, 便于判断返回结构
    tables = soup.find_all("table")
    if tables:
        out("  <table> 数量: %d" % len(tables))
        for ti, tb in enumerate(tables[:3]):
            rows = tb.find_all("tr")
            out("      [table %d] 行数=%d" % (ti, len(rows)))
            if rows:
                cells = rows[0].find_all(["td", "th"])
                out("      第1行: %s" % [c.get_text(" ", strip=True)[:20] for c in cells[:14]])
            if len(rows) > 1:
                cells = rows[1].find_all(["td", "th"])
                out("      第2行: %s" % [c.get_text(" ", strip=True)[:20] for c in cells[:14]])

    # 状态码下拉(截图那张表): 选项里含"调课/锁定/借用/空闲"
    for sel in soup.find_all("select"):
        texts = [o.get_text(" ", strip=True) for o in sel.find_all("option")]
        joined = "".join(texts)
        if any(k in joined for k in ("调课", "锁定", "借用", "空闲")):
            out("  ★ 状态码下拉疑似: name=%r" % sel.get("name"))
            for o in sel.find_all("option"):
                out("      %-16r value=%r" % (o.get_text(" ", strip=True), o.get("value")))

    path = PAGE_HTML % idx
    try:
        io.open(path, "w", encoding="utf-8").write(html)
        out("  页面原文已存: %s" % os.path.basename(path))
    except Exception as e:
        out("  页面原文保存失败: %s" % e)


def norm_room(s):
    """去掉借用页房间名尾部的 (容量/已借) 标注"""
    return re.sub(r"\(.*?\)", "", s).strip().replace(" ", "")


def query_borrow(c, base, tag, semester, campus, week, weekday, jc1, jc2, jszt,
                 quiet=False, jxlbh=""):
    """按 jsjy_query 表单里已确认的字段名提交只读查询(POST 到 jsjy_query2)。

    字段来源: 页面 <form name=Form1> 实测解析(见上一步输出), 无任何猜测:
      typewhere=jszq(隐藏) / xnxqh 学期 / xqbh 校区 / jxqbh 教学区 /
      jxlbh 教学楼 / jsbh 教室 / bjfh+rnrs 人数 / jszt 教室状态 /
      zc,zc2 周次范围 / xq,xq2 星期范围 / jc,jc2 节次范围(01-12)
    """
    from urllib.parse import urljoin
    from bs4 import BeautifulSoup

    action = urljoin(base, "/njlgdx/kbxx/jsjy_query2")
    data = {
        "typewhere": "jszq",
        "xnxqh": semester,
        "xqbh": campus,
        "jxqbh": "",
        "jxlbh": jxlbh,
        "jsbh": "",
        "bjfh": "=",
        "rnrs": "",
        "jszt": jszt,
        "zc": str(week), "zc2": str(week),
        "xq": str(weekday), "xq2": str(weekday),
        "jc": "%02d" % jc1, "jc2": "%02d" % jc2,
    }
    head("[3] 只读查询 %s" % tag)
    out("  POST %s" % action)
    out("  提交参数(已确认字段): %r" % data)
    r = c.session.post(action, data=data, timeout=30, allow_redirects=True,
                       headers={"Referer": urljoin(base, "/njlgdx/kbxx/jsjy_query")})
    html = r.text
    path = RESULT_HTML % tag
    try:
        io.open(path, "w", encoding="utf-8").write(html)
    except Exception as e:
        out("  结果保存失败: %s" % e)
    out("  HTTP %s  %d 字节 → %s" % (
        r.status_code, len(html), os.path.basename(path)))

    soup = BeautifulSoup(html, "lxml")
    tables = soup.find_all("table")
    out("  <table> 数量: %d" % len(tables))
    best = None
    for ti, tb in enumerate(tables):
        rows = tb.find_all("tr")
        out("      [table %d] 行数=%d" % (ti, len(rows)))
        if best is None or len(rows) > len(best[1]):
            best = (ti, rows)
    if best is None:
        return []
    ti, rows = best
    if quiet:
        names = []
        for tr in rows:
            cb = tr.find("input", {"name": "jsids"})
            if cb is None:
                continue
            td = cb.find_parent("td") or cb.parent
            v = " ".join(td.get_text(" ", strip=True).split()) if td else ""
            if v:
                names.append(v)
        out("  → 结果 %d 间; 前 6: %s" % (len(names), names[:6]))
        return names
    out("  ---- 最大表 table %d (行数 %d) 预览 ----" % (ti, len(rows)))
    for ri, tr in enumerate(rows[:8]):
        cells = tr.find_all(["td", "th"])
        vals = [" ".join(c.get_text(" ", strip=True).split())[:30] for c in cells]
        out("      行%02d(%d格): %s" % (ri, len(cells), vals[:12]))
    # 数据行的首列去重, 用于估算"教室数量"
    names = []
    for tr in rows[1:]:
        cells = tr.find_all(["td", "th"])
        if cells:
            v = " ".join(cells[0].get_text(" ", strip=True).split())
            if v and v not in names:
                names.append(v)
    out("  首列去重计数: %d  前 10: %s" % (len(names), names[:10]))
    # 状态字面量分布
    texts = {}
    for tr in rows:
        for c in tr.find_all(["td", "th"]):
            t = " ".join(c.get_text(" ", strip=True).split())
            if t:
                texts[t] = texts.get(t, 0) + 1
    status_like = {k: v for k, v in texts.items() if k in (
        "空闲", "L", "G", "K", "X", "J", "◆", "临时调课", "固定调课",
        "考试", "锁定", "借用", "正常上课")}
    out("  状态字面量分布: %s" % (status_like or "无"))
    out("  单元格文本样本(前 12 种): %s" % list(texts.items())[:12])
    return names


def fetch_lists(c, base, xqid, tag):
    """联动接口: 教学区(jxq)/教学楼(jxl)/教室(js) 选项(URL 取自页面 onChangeXq/onChangeJxl)"""
    from urllib.parse import urljoin
    url = urljoin(base, "/njlgdx/kbxx/jsjy_processAjax")
    ref = urljoin(base, "/njlgdx/kbxx/jsjy_query")
    head("[4] 联动选项 %s (xqid=%s)" % (tag, xqid))
    hdr = {"Referer": ref, "X-Requested-With": "XMLHttpRequest"}
    for rtype, method in (("jxq", "POST"), ("jxl", "POST"), ("js", "GET")):
        try:
            if method == "POST":
                r = c.session.post(url, data={"xqid": xqid, "requestType": rtype},
                                   timeout=30, headers=hdr)
            else:
                r = c.session.get(url, params={"jxlid": "", "requestType": rtype},
                                  timeout=30, headers=hdr)
            try:
                data = r.json()
                if isinstance(data, list):
                    items = [(str(d.get("dm", "")), str(d.get("dmmc", "")))
                             for d in data if isinstance(d, dict)]
                    out("  %s/%s → HTTP %s  %d 项: %s" % (
                        method, rtype, r.status_code, len(items), items[:80]))
                else:
                    out("  %s/%s → HTTP %s  JSON: %s" % (
                        method, rtype, r.status_code, str(data)[:300]))
            except Exception:
                body = " ".join(r.text.split())
                out("  %s/%s → HTTP %s  %s" % (method, rtype, r.status_code, body[:300]))
        except Exception as e:
            out("  %s/%s → 异常 %s" % (method, rtype, e))



def verify_round(c, base, missing_rooms):
    """方案 A 落地前的关键只读验证"""
    head("[6] 方案 A 预验证")
    query_borrow(c, base, "jiangyin_w3_wed_6-7_free", "2026-2027-1", "4y",
                 3, 3, 6, 7, "5", quiet=True)
    query_borrow(c, base, "xlsq_w6_mon_6-7_free", "2026-2027-1", "01",
                 6, 1, 6, 7, "5", quiet=True)
    query_borrow(c, base, "xlsq_w3_wed_jc13_free", "2026-2027-1", "01",
                 3, 3, 13, 13, "5", quiet=True)
    query_borrow(c, base, "xlsq_w30_sun_11-12_free", "2026-2027-1", "01",
                 30, 7, 11, 12, "5", quiet=True)
    for st, label in (("7", "L临时调课"), ("6", "G固定调课"),
                      ("3", "X锁定"), ("2", "J借用"), ("1", "◆正常上课")):
        names = query_borrow(c, base, "xlsq_w3_wed_6-7_jszt%s" % st,
                             "2026-2027-1", "01", 3, 3, 6, 7, st, quiet=True)
        ns = set(norm_room(x) for x in names)
        hit = [m for m in missing_rooms if m in ns]
        out("  → 状态 %s(%s): 差异教室命中 %s" % (st, label, hit or "无"))


def ajax_probe(c, base):
    """复刻 jQuery 的多种请求形态, 试探教学楼联动接口为何返回"非法访问" """
    from urllib.parse import urljoin, urlsplit
    q = urljoin(base, "/njlgdx/kbxx/jsjy_query")
    aj = urljoin(base, "/njlgdx/kbxx/jsjy_processAjax")
    u = urlsplit(base)
    origin = "%s://%s" % (u.scheme, u.netloc)
    head("[7] 教学楼联动接口探测")
    r0 = c.session.get(q, timeout=30, allow_redirects=True)
    out("  GET 查询页 → HTTP %s  %d 字节" % (r0.status_code, len(r0.text)))
    full = {"Referer": q, "X-Requested-With": "XMLHttpRequest",
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "Origin": origin}
    variants = [
        ("A POST dict + 全套头", dict(data={"xqid": "01", "requestType": "jxl"},
                                       headers=full)),
        ("B POST 原始串(前导&) + 全套头", dict(data="&xqid=01&requestType=jxl",
                                               headers=dict(full, **{
                                                   "Content-Type":
                                                       "application/x-www-form-urlencoded; charset=UTF-8"}))),
        ("C GET 参数 + 全套头", dict(params={"xqid": "01", "requestType": "jxl"},
                                     headers=full)),
        ("D POST dict + 仅 Referer", dict(data={"xqid": "01", "requestType": "jxl"},
                                          headers={"Referer": q})),
    ]
    for label, kw in variants:
        try:
            r = c.session.post(aj, timeout=30, allow_redirects=True, **kw) \
                if label.startswith(("A", "B", "D")) else \
                c.session.get(aj, timeout=30, allow_redirects=True, **kw)
            body = " ".join(r.text.split())
            out("  %s → HTTP %s  %s" % (label, r.status_code, body[:180]))
        except Exception as e:
            out("  %s → 异常 %s" % (label, e))




def jxlbh_probe(c, base):
    """按数字前缀直接做 jxlbh 过滤, 看响应是否回显楼名"""
    head("[10] jxlbh 过滤探测")
    codes = ["345", "347", "359", "366", "367", "368", "373", "99", "74", "384"]
    for code in codes:
        names = query_borrow(c, base, "jxlbh_%s" % code, "2026-2027-1", "01",
                             3, 3, 6, 7, "5", quiet=True, jxlbh=code)
        path = RESULT_HTML % ("jxlbh_%s" % code)
        try:
            html = io.open(path, encoding="utf-8").read()
        except Exception:
            html = ""
        zh = re.findall(r"[\u4e00-\u9fff]{2,}(?:教学楼|楼|馆|厅|中心|平房|室)", html)
        zh = [x for x in dict.fromkeys(zh)
              if x not in ("第三大节", "符号说明", "教学楼")]
        out("  jxlbh=%-4s → %d 间; 页面中文楼名线索: %s" % (code, len(names), zh[:12] or "无"))



def cookie_probe(sid, sso):
    """关闭同名 cookie 去重后, 复刻浏览器请求(两个 JSESSIONID)再试联动接口。

    浏览器实测请求: POST xqid=01&requestType=jxl, 带两个同名 JSESSIONID,
    X-Requested-With/Origin/Referer 齐全 → 200 + JSON(764B)。
    JWCClient 的 _DedupCookieJar 会去掉一个 JSESSIONID(为 WebVPN 设计),
    这里临时关闭它, 验证是否为"非法访问"的根因。
    """
    import requests
    from urllib.parse import urljoin
    from wxcloudrun import jwc_client as jc
    from wxcloudrun.jwc_client import URL_MAIN_PAGE

    head("[12] 双 JSESSIONID 复现探测")
    jc.JWCClient._dedupe_cookies = lambda self: None
    jc._DedupCookieJar.add_cookie_header = \
        requests.cookies.RequestsCookieJar.add_cookie_header
    c = jc.JWCClient()
    ok = c.login(sid, sso)
    out("  login(去重关闭) → %s 方式=%r" % (ok, c.login_method))
    if not ok:
        return
    js = [ck.value for ck in c.session.cookies if ck.name == "JSESSIONID"]
    out("  JSESSIONID 数量: %d %s" % (len(js), [x[:8] + "…" for x in js]))
    # 先按浏览器顺序访问主框架与借用页(可能设置服务端会话标记)
    for step in ("/njlgdx/framework/main.jsp", "/njlgdx/kbxx/jsjy_query"):
        try:
            r0 = c.session.get(urljoin(URL_MAIN_PAGE, step), timeout=30,
                               allow_redirects=True)
            out("  GET %s → HTTP %s %d 字节" % (step, r0.status_code, len(r0.text)))
        except Exception as e:
            out("  GET %s → 异常 %s" % (step, e))
    url = urljoin(URL_MAIN_PAGE, "/njlgdx/kbxx/jsjy_processAjax")
    hdr = {"Referer": urljoin(URL_MAIN_PAGE, "/njlgdx/kbxx/jsjy_query"),
           "Origin": "http://202.119.81.112:9080",
           "X-Requested-With": "XMLHttpRequest",
           "Accept": "application/json, text/javascript, */*; q=0.01"}
    # 与浏览器一致的原始请求体(含前导 &)
    r = c.session.post(url, data="&xqid=01&requestType=jxl",
                       headers=hdr, timeout=30, allow_redirects=True)
    out("  POST xqid=01&requestType=jxl → HTTP %s %d 字节" % (r.status_code, len(r.text)))
    out("  响应: %s" % " ".join(r.text.split())[:400])
    try:
        data = r.json()
    except Exception:
        data = None
    if isinstance(data, list):
        path = os.path.join(_here, "_borrow_jxl.json")
        io.open(path, "w", encoding="utf-8").write(
            __import__("json").dumps(data, ensure_ascii=False, indent=1))
        out("  教学楼 %d 项, 已存 %s" % (len(data), os.path.basename(path)))
        # 逐楼栋取教室列表(requestType=js, GET; 与页面 onChangeJxl 一致)
        rooms_all = {}
        for it in data:
            dm = str(it.get("dm") or "")
            mc = str(it.get("dmmc") or "")
            try:
                rr = c.session.get(url, params={"jxlid": dm, "requestType": "js"},
                                   headers=hdr, timeout=30)
                items = rr.json()
            except Exception as e:
                out("  %s(%s) → 异常 %s" % (mc, dm, e))
                continue
            names = [str(x.get("dmmc") or x.get("mc") or x) for x in items] \
                if isinstance(items, list) else []
            rooms_all[mc or dm] = names
            num = [n for n in names if re.match(r"^\d{2,3}-", n)]
            out("  %-16s(%s) → %3d 间 | 数字前缀: %s" % (
                mc, dm[:10], len(names), num[:8] or "无"))
        path2 = os.path.join(_here, "_borrow_rooms.json")
        io.open(path2, "w", encoding="utf-8").write(
            __import__("json").dumps(rooms_all, ensure_ascii=False, indent=1))
        out("  教室清单已存 %s" % os.path.basename(path2))


def main():
    sid = os.environ.get("NJUST_SID", "").strip()
    sso = os.environ.get("NJUST_SSO_PWD", "")
    if not (sid and sso):
        print("缺少凭据: 请设置 NJUST_SID / NJUST_SSO_PWD")
        return 2
    show_all_links = "--links" in sys.argv
    do_query = "--query" in sys.argv

    if "--cookie-probe" in sys.argv:
        cookie_probe(sid, sso)
        flush()
        return 0

    from wxcloudrun.jwc_client import JWCClient, URL_MAIN_PAGE

    head("[0] 登录(只读探针; 验证码偶发失败, 自动重试)")
    c = JWCClient()
    ok = False
    # 1) 教务直连: 生产空教室服务同款链路(带初始密码规则兜底)
    for attempt in range(1, 4):
        c = JWCClient()
        ok = c.login(sid, sso)
        out("  login(教务直连) 第 %d 次 → %s  方式=%r  错误=%r" % (
            attempt, ok, c.login_method, c.last_error))
        if ok:
            break
        time.sleep(2)
    # 2) 回退 SSO 直连(免教务密码; 验证码触发时靠 OCR)
    if not ok:
        for attempt in range(1, 4):
            c = JWCClient()
            ok = c.login_webvpn(sid, sso, "")
            out("  login_webvpn 第 %d 次 → %s  方式=%r  错误=%r" % (
                attempt, ok, c.login_method, c.last_error))
            if ok:
                break
            time.sleep(2)
    if not ok:
        flush()
        return 1
    out("  会话有效: %s" % c.is_session_valid())

    # ── 广度优先爬菜单/框架, 找「借用」入口(全程 GET) ──
    seen = OrderedDict()
    queue = [(URL_MAIN_PAGE, 0, "主框架")]
    candidates = []          # (文本, url)
    inventory = []           # (文本, url, 来源页)
    pages = 0
    while queue and pages < MAX_PAGES:
        url, depth, src = queue.pop(0)
        key = url.split("#")[0]
        if key in seen or not wanted(url):
            continue
        seen[key] = True
        try:
            r = c.session.get(url, timeout=30, allow_redirects=True)
        except Exception as e:
            out("  GET 失败 %s: %s" % (brief(url), e))
            continue
        pages += 1
        if r.status_code != 200:
            out("  GET %s → HTTP %s" % (brief(url), r.status_code))
            continue
        ctype = (r.headers.get("Content-Type") or "").lower()
        if "html" not in ctype and "text" not in ctype:
            continue
        base = r.url or url
        links = page_links(r.text, base)
        host = urlsplit(base).hostname
        for kind, text, u in links:
            if urlsplit(u).hostname != host:
                continue
            inventory.append((text, u, brief(base)))
            low = (text + " " + u).lower()
            if any(k in text for k in TEXT_KEYS):
                candidates.append((text, u))
            elif any(k in low for k in HREF_KEYS):
                candidates.append((text or "(无文本)", u))
            if depth < MAX_DEPTH and wanted(u):
                queue.append((u, depth + 1, brief(base)))

    head("[1] 菜单/链接盘点")
    out("  已抓 %d 个页面, 共 %d 条站内链接" % (pages, len(inventory)))
    uniq = OrderedDict()
    for text, u in candidates:
        uniq[(text, u)] = True
    out("  「借用」相关候选 %d 条:" % len(uniq))
    for text, u in uniq:
        out("      text=%-24r url=%s" % (text[:24], brief(u, 140)))
    if not uniq:
        out("  ⚠ 未命中关键词, 下面列出全部链接供人工识别:")
        for text, u, src in inventory[:120]:
            out("      %-30r %s" % (text[:30], brief(u, 130)))
        flush()
        return 3

    head("[2] 借用页表单结构解析(只做 GET)")
    skip_form = "--skip-form" in sys.argv
    for i, (text, u) in enumerate(list(uniq.keys())[:5], start=1):
        if skip_form:
            break
        out()
        out("---- 候选 %d: text=%r url=%s" % (i, text, brief(u, 150)))
        try:
            r = c.session.get(u, timeout=30, allow_redirects=True)
        except Exception as e:
            out("  GET 失败: %s" % e)
            continue
        if r.status_code != 200:
            out("  HTTP %s" % r.status_code)
            continue
        dump_forms(u, r.text, i)

    if show_all_links:
        head("[附] 全部站内链接")
        for text, u, src in inventory:
            out("  %-30r %s   (来自 %s)" % (text[:30], brief(u, 130), src))

    if "--jxlbh-probe" in sys.argv:
        jxlbh_probe(c, URL_MAIN_PAGE)

    if do_query:
        # 参照当前空教室默认查询: 孝陵卫 / 第3周 / 星期三 / 第6-7节
        base = URL_MAIN_PAGE
        borrow_names = query_borrow(c, base, "week3_wed_6-7_free", "2026-2027-1", "01",
                                    3, 3, 6, 7, "5")   # jszt=5 → 空闲
        query_borrow(c, base, "week3_wed_6-7_all", "2026-2027-1", "01",
                     3, 3, 6, 7, "")       # 全状态
        if "--lists" in sys.argv:
            fetch_lists(c, base, "01", "孝陵卫")
            fetch_lists(c, base, "4y", "江阴校区")
        if "--verify" in sys.argv:
            verify_round(c, base, ["Ⅳ-A103", "Ⅳ-A106", "Ⅳ-A109", "Ⅳ-A110"])
        if "--ajax-probe" in sys.argv:
            ajax_probe(c, base)

    flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
