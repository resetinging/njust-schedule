# -*- coding: utf-8 -*-
"""生成「登录过程 + 各功能」演示 HTML（界面按小程序源码结构还原）。

用法（素材服务器已在 5000 端口运行）：
    ..\\.venv\\Scripts\\python.exe make_walkthrough.py
输出：..\\poster\\video\\walkthrough.html

- 课表 / 空教室两屏引用仓库里现成的真机截图（poster/assets/*.jpg）
- 其余界面按 .miniapp/components/*/index.wxml 的真实结构渲染，数据来自素材服务器
- 绩点/平均分沿用前端 utils/gpa.js 的口径
"""
import os
import sys

import requests

BASE = "http://127.0.0.1:5000"
DEMO_SID = "20260001"
DEMO_PWD = "123456"
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.abspath(os.path.join(HERE, "..", "poster", "video", "walkthrough.html"))

# ============================================================
# 绩点口径（照搬 .miniapp/utils/gpa.js）
# ============================================================
LEVEL_MAP = {'优': 4.0, '优秀': 4.0, '优+': 4.0, '优秀+': 4.0, '优-': 3.7, '优秀-': 3.7,
             '良+': 3.3, '良好+': 3.3, '良': 3.0, '良好': 3.0, '良-': 2.7, '良好-': 2.7,
             '中+': 2.3, '中等+': 2.3, '中': 2.0, '中等': 2.0, '中-': 1.5, '中等-': 1.5,
             '及格': 1.0, '通过': 1.0, '不及格': 0, '不通过': 0}
LEVEL_PCT = {'优': 90, '优秀': 90, '优+': 90, '优秀+': 90, '优-': 87, '优秀-': 87,
             '良+': 83, '良好+': 83, '良': 80, '良好': 80, '良-': 76, '良好-': 76,
             '中+': 73, '中等+': 73, '中': 70, '中等': 70, '中-': 66, '中等-': 66,
             '及格': 60, '通过': 60, '不及格': 0, '不通过': 0}
NON_GRADE_STATUS = ['缓考', '缺考', '免修', '作弊', '违纪', '取消', '旷考', '休学']
NON_GPA_NATURES = ['通识教育选修课']


def score_to_gp(score):
    s = str(score if score is not None else '').strip()
    if s in LEVEL_MAP:
        return LEVEL_MAP[s]
    if s in NON_GRADE_STATUS:
        return -1
    try:
        v = float(s)
    except ValueError:
        return -1
    for limit, gp in ((90, 4.0), (85, 3.7), (82, 3.3), (78, 3.0), (75, 2.7),
                      (72, 2.3), (68, 2.0), (64, 1.5), (60, 1.0)):
        if v >= limit:
            return gp
    return 0


def score_to_pct(score):
    s = str(score if score is not None else '').strip()
    if s in LEVEL_PCT:
        return LEVEL_PCT[s]
    if s in NON_GRADE_STATUS:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def calc_avg(grades):
    weighted, credits = 0.0, 0.0
    for g in grades:
        pct = score_to_pct(g.get("score"))
        if pct is None:
            continue
        credit = float(g.get("credit") or 0)
        wc = credit if credit > 0 else 1
        weighted += pct * wc
        if credit > 0:
            credits += credit
    if credits > 0:
        return round(weighted / credits, 2)
    return round(weighted / len(grades), 2) if grades and weighted > 0 else 0


def calc_gpa(grades, gpa_only=True):
    total_weighted, total_credits = 0.0, 0.0
    for g in grades:
        if gpa_only and (g.get("course_nature") or '').strip() in NON_GPA_NATURES:
            continue
        credit = float(g.get("credit") or 0)
        wc = credit if credit > 0 else 1
        gp = float(g.get("grade_point") or 0)
        if gp == 0:
            gp = score_to_gp(g.get("score"))
        if gp >= 0:
            total_weighted += wc * gp
            if credit > 0:
                total_credits += credit
    return round(total_weighted / total_credits, 2) if total_credits > 0 else 0


def total_credits(grades):
    return round(sum(float(g.get("credit") or 0) for g in grades), 1)


# ============================================================
# 数据
# ============================================================
def api(path, token=None, method="GET", **kw):
    headers = {"X-Auth-Token": token} if token else {}
    if method == "GET":
        r = requests.get(BASE + path, headers=headers, timeout=30, **kw)
    else:
        r = requests.post(BASE + path, headers=headers, json=kw.pop("json", {}), timeout=30)
    try:
        return r.json()
    except Exception:  # noqa: BLE001
        return {}


def collect():
    login = api("/api/login-webvpn", method="POST",
                json={"student_id": DEMO_SID, "password": DEMO_PWD})
    token = login.get("token", "")
    sem = login.get("semester", "")
    d = {
        "login": login,
        "status": api("/api/status", token),
        "courses": api("/api/courses?semester=" + sem, token).get("courses", []),
        "exams": api("/api/exams", token).get("exams", []),
        "evals": api("/api/evaluations", token).get("evaluations", []),
        "eval_courses": api("/api/eval-courses", token).get("courses", []),
        "grades": api("/api/grades", token).get("grades", []),
        "cet": api("/api/cet-scores", token).get("scores", []),
        "announcement": api("/api/announcement"),
        "eval_form": api("/api/eval-form?url=/demo/eval/1", token),
        "qr": api("/api/sso-qr/start", method="POST", json={"student_id": DEMO_SID}),
    }
    d["gpa"] = calc_gpa(d["grades"], True)
    d["avg"] = calc_avg(d["grades"])
    d["credits"] = total_credits(d["grades"])
    return d


# ============================================================
# 样式
# ============================================================
CSS = """
*{box-sizing:border-box}
body{margin:0;padding:30px 24px 60px;background:#EFEEF5;color:#2B2B33;
 font-family:-apple-system,BlinkMacSystemFont,"PingFang SC","Microsoft YaHei",Arial,sans-serif}
h1{font-size:23px;margin:0 0 6px}
.sub{color:#6B6B78;font-size:13px;margin-bottom:20px}
.steps{background:#fff;border-radius:14px;padding:16px 20px;margin-bottom:26px;font-size:13.5px;color:#4A4A56;line-height:1.85}
.steps b{color:#7C6BE8}
.flow{display:flex;flex-wrap:wrap;gap:22px}
.item{width:375px}
.cap{font-size:14px;font-weight:600;margin:0 0 8px 2px;color:#3A3A46}
.cap span{font-weight:400;color:#8A8A96;font-size:12.5px}
.phone{position:relative;width:375px;height:812px;background:#F7F6FB;border-radius:26px;overflow:hidden;
 box-shadow:0 10px 30px rgba(60,50,120,.18);display:flex;flex-direction:column}
.nav{height:88px;background:linear-gradient(135deg,#8B7BF0,#7C6BE8);color:#fff;flex:0 0 auto;
 display:flex;align-items:flex-end;justify-content:center;padding-bottom:12px;font-size:17px;font-weight:600;position:relative}
.nav .dots{position:absolute;right:16px;bottom:14px;width:76px;height:30px;border-radius:15px;background:rgba(255,255,255,.22);
 font-size:12px;display:flex;align-items:center;justify-content:center;letter-spacing:2px}
.nav .back{position:absolute;left:14px;bottom:12px;font-size:24px;line-height:1;opacity:.95}
.body{flex:1;overflow:hidden;padding:14px 12px}
.tabbar{height:58px;background:#fff;display:flex;align-items:center;justify-content:space-around;flex:0 0 auto}
.tabbar > div{display:flex;flex-direction:column;align-items:center}
.tabbar .ico{width:36px;height:36px;border-radius:50%;display:flex;align-items:center;justify-content:center;
 font-size:22px;filter:grayscale(100%) opacity(.55);transform:scale(.92)}
.tabbar .on .ico{background:#EFEBFC;filter:none;transform:scale(1.08)}
.tabbar .dot{width:4px;height:4px;border-radius:50%;background:transparent;margin-top:2px}
.tabbar .on .dot{background:#7C6BE8}
.card{background:#fff;border-radius:14px;padding:14px;margin-bottom:12px;box-shadow:0 1px 5px rgba(0,0,0,.04)}
.shot{width:375px;height:812px;object-fit:cover;border-radius:26px;box-shadow:0 10px 30px rgba(60,50,120,.18);display:block}
/* 公告 / 登录 */
.announce{background:#fff;border-radius:14px;padding:12px 14px;margin-bottom:12px}
.announce .head{display:flex;align-items:center;gap:6px;font-size:13px;color:#3A3A46}
.announce .new{background:#7C6BE8;color:#fff;font-size:10px;border-radius:6px;padding:1px 5px}
.announce .more{margin-left:auto;color:#7C6BE8;font-size:12px}
.announce .txt{font-size:12.5px;color:#6B6B78;line-height:1.7;margin-top:6px}
.announce .txt.clamp{display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
.login-title{font-size:18px;font-weight:600;text-align:center;margin:2px 0 4px}
.login-sub{font-size:12px;color:#9A9AA6;text-align:center;margin-bottom:14px}
.field{margin-bottom:12px}
.field label{font-size:12.5px;color:#5A5A66;display:block;margin-bottom:6px}
.inp{height:40px;border:1px solid #E4E2EE;border-radius:8px;background:#FAFAFA;display:flex;align-items:center;padding:0 12px;font-size:14px}
.inp .eye{margin-left:auto;color:#8A8A96}
.remember{display:flex;align-items:center;gap:8px;font-size:12.5px;color:#5A5A66;margin:4px 0 12px}
.switch{width:34px;height:20px;border-radius:10px;background:#7C6BE8;position:relative}
.switch:after{content:"";position:absolute;right:2px;top:2px;width:16px;height:16px;border-radius:50%;background:#fff}
.btn{height:42px;border-radius:8px;background:#7C6BE8;color:#fff;font-size:16px;display:flex;align-items:center;justify-content:center}
.btn.sm{height:36px;font-size:13px}
.link{text-align:center;color:#7C6BE8;font-size:13.5px;margin-top:14px}
.tip{text-align:center;color:#9A9AA6;font-size:12px;margin-top:12px}
.version{text-align:center;color:#BFBFC9;font-size:11px;margin-top:14px}
/* 扫码面板 */
.qr-box{background:#fff;border:1px solid #E4E2EE;border-radius:12px;padding:10px;width:268px;margin:0 auto 10px}
.qr-box img{width:246px;height:246px;display:block}
.qr-state{text-align:center;font-size:12.5px;color:#8A8A96;margin-bottom:12px}
.qr-note{text-align:center;font-size:11.5px;color:#9A9AA6;margin-top:8px}
.qr-links{display:flex;justify-content:space-around;margin-top:12px;font-size:13px;color:#7C6BE8}
/* page-hero（考试/评教顶部紫卡） */
.hero{background:linear-gradient(135deg,#8B7BF0,#7C6BE8);color:#fff;border-radius:14px;padding:14px 16px;
 display:flex;align-items:center;justify-content:space-between;margin-bottom:12px}
.hero .t{font-size:16px;font-weight:600;display:block}
.hero .s{font-size:12px;opacity:.9}
/* 考试 */
.cd-row{display:flex;gap:8px;margin-bottom:12px}
.cd-card{background:#fff;border-radius:12px;padding:10px;min-width:104px;text-align:center;box-shadow:0 1px 5px rgba(0,0,0,.04)}
.cd-num{font-size:19px;font-weight:700;color:#7C6BE8}
.cd-lb{font-size:10.5px;color:#9A9AA6}
.cd-course{font-size:12.5px;font-weight:600;margin-top:4px}
.cd-date{font-size:10.5px;color:#9A9AA6}
.date-hd{display:flex;justify-content:space-between;font-size:12px;color:#8A8A96;padding:8px 4px 6px}
.date-hd .tag{color:#E5484D}
.exam-card{background:#fff;border-radius:12px;padding:12px;margin-bottom:8px}
.exam-course{font-size:14px;font-weight:600}
.exam-meta{display:flex;flex-wrap:wrap;gap:8px;font-size:11.5px;color:#8A8A96;margin-top:6px}
/* 评教 */
.summary-bar{display:flex;justify-content:space-between;font-size:12.5px;color:#7C6BE8;margin-bottom:10px}
.batch{background:#fff;border-radius:14px;padding:14px;margin-bottom:10px}
.batch .hd{display:flex;justify-content:space-between;align-items:center}
.batch .tt{font-size:14.5px;font-weight:600}
.tag{font-size:11px;padding:3px 8px;border-radius:8px;background:#EFEDFB;color:#7C6BE8}
.batch .info{display:flex;align-items:center;gap:8px;margin-top:8px;font-size:11.5px;color:#9A9AA6}
.sem-tag{background:#F1EFFC;color:#7C6BE8;border-radius:6px;padding:2px 6px}
.course-card{background:#fff;border-radius:12px;padding:12px;margin-bottom:10px;display:flex;justify-content:space-between;align-items:center}
.course-card .nm{font-size:14px;font-weight:600}
.course-card .mt{font-size:11.5px;color:#9A9AA6;margin-top:4px}
.course-card .st{font-size:12px;color:#E09A3C}
.af-bar{display:flex;align-items:center;gap:7px;background:#fff;border-radius:12px;padding:10px 12px;font-size:11.5px;color:#6B6B78;margin-bottom:10px}
.af-inp{width:56px;height:28px;border:1px solid #E4E2EE;border-radius:8px;display:flex;align-items:center;justify-content:center;font-size:12.5px}
.ind{background:#fff;border-radius:12px;padding:12px;margin-bottom:10px}
.ind .nm{font-size:13px;color:#3A3A46;margin-bottom:8px}
.opts{display:flex;flex-wrap:wrap;gap:6px}
.opt{min-width:32px;height:28px;border-radius:8px;border:1px solid #E4E2EE;color:#6B6B78;font-size:12.5px;display:flex;align-items:center;justify-content:center;padding:0 7px}
.opt.on{background:#7C6BE8;border-color:#7C6BE8;color:#fff}
.form-actions{display:flex;gap:10px;margin-top:4px}
.form-actions .o{flex:1;height:40px;border:1px solid #D9D4F7;color:#7C6BE8;border-radius:8px;display:flex;align-items:center;justify-content:center;font-size:14px}
.form-actions .p{flex:1;height:40px;background:#7C6BE8;color:#fff;border-radius:8px;display:flex;align-items:center;justify-content:center;font-size:14px}
/* 成绩 */
.gpa-hero{background:linear-gradient(135deg,#8B7BF0,#7C6BE8);color:#fff;border-radius:14px;padding:16px;margin-bottom:12px}
.gpa-num{font-size:34px;font-weight:700;line-height:1.1}
.gpa-lb{font-size:11.5px;opacity:.92}
.seg-row{display:flex;gap:8px;margin-top:12px}
.seg{font-size:11.5px;padding:5px 10px;border-radius:10px;background:rgba(255,255,255,.22)}
.seg.on{background:#fff;color:#7C6BE8}
.pills{display:flex;gap:8px;margin-bottom:12px}
.pill{flex:1;background:#F1EFF8;border-radius:12px;padding:10px;text-align:center}
.pill .l{font-size:11px;color:#8A8A96;display:block}
.pill .v{font-size:16px;font-weight:600;color:#7C6BE8}
.cet-bar{background:#fff;border-radius:12px;padding:12px;margin-bottom:12px}
.cet-bar .t{font-size:13px;font-weight:600}
.cet-bar .d{font-size:11px;color:#9A9AA6;float:right}
.cet-line{font-size:12.5px;color:#6B6B78;margin-top:6px}
.sem-head{display:flex;align-items:center;gap:8px;font-size:13px;padding:8px 2px;color:#3A3A46}
.sem-head .gpa-tag{margin-left:auto;background:#F1EFFC;color:#7C6BE8;border-radius:6px;padding:2px 6px;font-size:11px}
.g-row{display:flex;align-items:center;gap:9px;padding:8px 2px;border-bottom:1px solid #F3F2F8;font-size:13px}
.g-row:last-child{border-bottom:none}
.chk{width:16px;height:16px;border:1px solid #D9D4F7;border-radius:4px;flex:0 0 auto;font-size:11px;color:#fff;text-align:center;line-height:16px}
.chk.on{background:#7C6BE8;border-color:#7C6BE8}
.g-name{font-size:13px}
.g-meta{font-size:11px;color:#9A9AA6;margin-top:2px}
.g-score{margin-left:auto;font-weight:600;color:#7C6BE8}
/* 我的 */
.user-card{background:linear-gradient(135deg,#8B7BF0,#7C6BE8);color:#fff;border-radius:14px;padding:14px;display:flex;align-items:center;gap:12px;margin-bottom:12px}
.avatar{width:46px;height:46px;border-radius:50%;background:rgba(255,255,255,.25);display:flex;align-items:center;justify-content:center;font-size:22px}
.user-name{font-size:16px;font-weight:600;display:block}
.user-id{font-size:12px;opacity:.9}
.info-card{background:#F4F3F9;border-radius:12px;padding:4px 12px;margin-bottom:12px}
.info-row{display:flex;justify-content:space-between;font-size:12.5px;padding:6px 0;color:#5A5A66}
.info-row .v{color:#2B2B33}
.action-list{background:#fff;border-radius:12px;padding:2px 12px;margin-bottom:12px}
.action-item{display:flex;justify-content:space-between;font-size:13px;padding:8px 0;border-bottom:1px solid #F4F3F9;color:#2B2B33}
.action-item:last-child{border-bottom:none}
.action-item .ar{color:#C4C4D0}
.fb-dot{background:#E5484D;color:#fff;font-size:10px;border-radius:9px;padding:1px 6px;line-height:1.5}
/* 「我的」页内容较多: 单独收紧间距, 保证首屏能看到全部条目 */
.me .announce{margin-bottom:8px;padding:10px 12px}
.me .announce .txt{margin-top:4px}
.me .user-card{margin-bottom:8px;padding:11px 12px}
.me .info-card{margin-bottom:8px;padding:2px 12px}
.me .info-row{padding:5px 0;font-size:12.5px}
.me .action-list{margin-bottom:8px}
.me .action-item{padding:7px 0;font-size:12.5px}
.me .setting-card{margin-bottom:8px;padding:10px 12px}
.me .btn-group{gap:6px;margin-bottom:8px}
.me .version{margin-top:10px}
/* 问题反馈弹窗 */
.fb-mask{position:absolute;inset:0;background:rgba(30,28,45,.45);display:flex;align-items:center;justify-content:center;padding:0 18px}
.fb-card{background:#fff;border-radius:16px;padding:16px;width:100%;box-shadow:0 12px 30px rgba(0,0,0,.2)}
.fb-head{display:flex;justify-content:space-between;align-items:center;margin-bottom:12px}
.fb-title{font-size:16px;font-weight:600}
.fb-close{color:#B9B9C6}
.fb-label{font-size:12.5px;color:#5A5A66;margin:10px 0 6px}
.type-tabs{display:flex;gap:8px}
.type-tab{font-size:12px;padding:6px 12px;border-radius:8px;background:#F4F3F9;color:#6B6B78}
.type-tab.on{background:#7C6BE8;color:#fff}
.fb-textarea{border:1px solid #E4E2EE;border-radius:10px;padding:10px;font-size:12.5px;color:#8A8A96;
 min-height:76px;background:#FAFAFA;line-height:1.6}
.fb-count{text-align:right;font-size:11px;color:#B9B9C6;margin:6px 0 10px}
.setting-card{background:#fff;border-radius:12px;padding:12px;margin-bottom:12px}
.setting-title{font-size:13px;color:#3A3A46}
.setting-value{font-size:13px;color:#7C6BE8;margin-top:6px}
.setting-hint{font-size:11px;color:#9A9AA6;margin-top:6px}
.btn-group{display:flex;flex-direction:column;gap:8px;margin-bottom:12px}
.btn-outline{height:38px;border:1px solid #D9D4F7;color:#7C6BE8;border-radius:8px;display:flex;align-items:center;justify-content:center;font-size:13.5px;background:#fff}
.logout{border:1px solid #F5C2C4;color:#E5484D;border-radius:8px;height:38px;display:flex;align-items:center;justify-content:center;font-size:13.5px;background:#fff}
.user-card{padding:12px}
.call{background:#1F1F28;color:#D8D8E0;border-radius:12px;padding:16px 18px;font-size:12.5px;line-height:1.85;
 font-family:Consolas,Menlo,monospace;white-space:pre-wrap;margin-top:26px}
"""


def phone(title, inner, tab=None, back=False, tabbar=True):
    tabs = ["📅", "📝", "📋", "🎓", "👤"]
    bar = "".join(
        f'<div class="{"on" if i == tab else ""}"><div class="ico">{t}</div>'
        f'<div class="dot"></div></div>'
        for i, t in enumerate(tabs))
    back_html = '<div class="back">‹</div>' if back else ''
    bar_html = f'<div class="tabbar">{bar}</div>' if tabbar else ''
    return (f'<div class="phone"><div class="nav">{back_html}{title}<div class="dots">••• ⊙</div></div>'
            f'<div class="body">{inner}</div>{bar_html}</div>')


def build_frames(d):
    login, ev, inds = d["login"], d["eval_form"], d["eval_form"].get("indicators", [])
    ann = d["announcement"].get("text", "")

    # ① 我的 · 未登录（公告 + 登录卡）
    f1 = (
        f'<div class="announce"><div class="head">📢 公告 <span class="new">新</span>'
        f'<span class="more">查看全文</span></div><div class="txt">{ann}</div></div>'
        '<div class="card"><div class="login-title">登录教务系统</div>'
        '<div class="login-sub">智慧理工统一认证</div>'
        f'<div class="field"><label>学号</label><div class="inp">{DEMO_SID}</div></div>'
        '<div class="field"><label>智慧理工密码</label><div class="inp">••••••••'
        '<svg class="eye" width="17" height="17" viewBox="0 0 24 24" fill="none"'
        ' stroke="#8A8A96" stroke-width="1.9" stroke-linecap="round">'
        '<path d="M2 12s3.6-6 10-6 10 6 10 6-3.6 6-10 6-10-6-10-6z"/>'
        '<circle cx="12" cy="12" r="2.6"/></svg></div></div>'
        '<div class="remember"><div class="switch"></div>记住学号和密码</div>'
        '<div class="btn">登 录</div><div class="link">扫码登录</div>'
        '<div class="tip">使用智慧理工统一认证账号，无需教务密码</div></div>'
        '<div class="version">v1.1.0 · build demo</div>')

    # ② 扫码登录面板
    f2 = ('<div class="card">'
          f'<div class="qr-box"><img src="data:image/png;base64,{d["qr"].get("qr_b64", "")}"></div>'
          '<div class="qr-state">等待扫码…</div>'
          '<div class="btn">保存到相册</div>'
          '<div class="qr-note">用微信「扫一扫」→ 相册，选择刚保存的二维码</div>'
          '<div class="qr-links"><span>刷新</span><span>我已确认</span><span>返回</span></div></div>')

    # ⑤ 考试：hero + 倒计时 + 日期分组 + 考试卡
    exams = d["exams"]
    exam_inner = ('<div class="hero"><div><span class="t">考试安排</span>'
                  f'<span class="s">共 {len(exams)} 场考试</span></div><span>🔄</span></div>')
    if exams:
        e0 = exams[0]
        # 倒计时: 按考试日期算天数(解析失败则显示 "—")
        days = "—"
        try:
            from datetime import date, datetime
            d0 = datetime.strptime(str(e0.get("date", ""))[:10], "%Y-%m-%d").date()
            days = max(0, (d0 - date.today()).days)
        except Exception:  # noqa: BLE001
            pass
        exam_inner += (f'<div class="cd-row"><div class="cd-card"><div class="cd-num">{days}</div>'
                       '<div class="cd-lb">天后</div>'
                       f'<div class="cd-course">{e0.get("course_name", "")}</div>'
                       f'<div class="cd-date">{e0.get("date", "")} {e0.get("time", "")}</div>'
                       '</div></div>')
    cur_date = None
    for e in exams:
        if e.get("date") != cur_date:
            cur_date = e.get("date")
            exam_inner += (f'<div class="date-hd"><span>{cur_date}</span>'
                           f'<span class="tag">即将开始</span></div>')
        exam_inner += ('<div class="exam-card">'
                       f'<div class="exam-course">{e.get("course_name", "")}</div>'
                       '<div class="exam-meta">'
                       f'<span>{e.get("time") or "待定"}</span>'
                       f'<span>{e.get("location") or "待定"}</span>'
                       f'<span>{e.get("type") or "期末考试"}</span>'
                       '</div></div>')

    # ⑥ 评教 · 批次列表
    batches = d["evals"]
    b_inner = ('<div class="hero"><div><span class="t">教学评价</span>'
               f'<span class="s">{len(batches)} 个批次</span></div><span>🔄</span></div>')
    for b in batches:
        b_inner += ('<div class="batch"><div class="hd">'
                    f'<span class="tt">{b.get("category") or "评教批次"}</span>'
                    f'<span class="tag">{"已完成" if b.get("is_done") else "待评教"}</span></div>'
                    '<div class="info">'
                    f'<span class="sem-tag">{b.get("semester", "")}</span>'
                    f'<span>{b.get("start_date", "")} ~ {b.get("end_date", "")}</span>'
                    '</div></div>')

    # ⑦ 评教 · 评价表单（课程 + 自动填写 + 指标）
    names = [c.get("name", "") for c in d["eval_courses"]]
    form_course = names[0] if names else "高等数学"
    f_inner = (f'<div class="summary-bar"><span>← 返回课程</span>'
               f'<span>{form_course}</span><span></span></div>')
    f_inner += ('<div class="af-bar"><span>期望分数:</span><span class="af-inp">85</span>'
                f'<span>（满分 100）</span><span style="margin-left:auto">'
                '<span class="btn sm" style="width:76px">自动填写</span></span></div>')
    for ind in inds[:4]:
        opts = "".join(f'<div class="opt{" on" if o.get("value") == "10" else ""}">{o.get("value")}</div>'
                       for o in ind.get("options", []))
        f_inner += (f'<div class="ind"><div class="nm">{ind.get("seq")}. {ind.get("label", "")}</div>'
                    f'<div class="opts">{opts}</div></div>')
    f_inner += ('<div class="form-actions"><div class="o">保存</div>'
                '<div class="p">提交评价</div></div>')

    # ⑧ 成绩：绩点大卡 + 胶囊 + 四六级 + 明细
    cet = d["cet"]
    cet_line = "｜".join(f'{c.get("type")} {int(float(c.get("score", 0)))}' for c in cet) or "暂无"
    g_inner = ('<div class="gpa-hero"><div class="gpa-num">' + f'{d["gpa"]}' + '</div>'
               f'<div class="gpa-lb">加权平均绩点（计内）· {len(d["grades"])} 门</div>'
               '<div class="seg-row"><span class="seg on">📋 奖学金/综测</span>'
               '<span class="seg">🎓 保研推免</span></div></div>')
    g_inner += ('<div class="pills">'
                f'<div class="pill"><span class="l">总学分</span><span class="v">{d["credits"]}</span></div>'
                f'<div class="pill"><span class="l">平均分</span><span class="v">{d["avg"]}</span></div>'
                f'<div class="pill"><span class="l">GPA</span><span class="v">{d["gpa"]}</span></div></div>')
    if cet:
        g_inner += (f'<div class="cet-bar"><span class="t">四六级成绩</span>'
                    f'<span class="d">{cet[0].get("exam_date", "")}</span>'
                    f'<div class="cet-line">{cet_line}</div></div>')
    g0 = d["grades"][0] if d["grades"] else {}
    sem_label = f'{(g0.get("academic_year") or "").strip()}-{(g0.get("semester") or "").strip()}'.strip("-") or "本学期"
    g_inner += (f'<div class="card"><div class="sem-head">🎓 {sem_label} '
                f'<span class="gpa-tag">GPA {d["gpa"]}</span>'
                f'<span style="color:#9A9AA6;font-size:11px">{len(d["grades"])} 门</span></div>')
    for g in d["grades"][:5]:
        g_inner += ('<div class="g-row"><div class="chk on">✓</div>'
                    f'<div><div class="g-name">{g.get("course_name", "")}</div>'
                    f'<div class="g-meta">{g.get("credit", "")} 学分｜{g.get("course_type", "")}</div></div>'
                    f'<div class="g-score">{g.get("score", "")}</div></div>')
    g_inner += '</div>'

    # ⑨ 我的 · 已登录
    me = (f'<div class="announce"><div class="head">📢 公告 <span class="new">新</span>'
          f'<span class="more">查看全文</span></div><div class="txt clamp">{ann}</div></div>'
          '<div class="user-card"><div class="avatar">👤</div><div>'
          f'<span class="user-name">{login.get("student_name", "")}</span>'
          f'<span class="user-id">{login.get("student_id", "")}</span></div></div>'
          '<div class="info-card">'
          f'<div class="info-row"><span>账号</span><span class="v">{login.get("student_id", "")}</span></div>'
          f'<div class="info-row"><span>姓名</span><span class="v">{login.get("student_name", "")}</span></div>'
          f'<div class="info-row"><span>当前学期</span><span class="v">{login.get("semester", "")}</span></div>'
          f'<div class="info-row"><span>成绩数量</span><span class="v">{len(d["grades"])} 门</span></div>'
          '</div>'
          '<div class="action-list">'
          '<div class="action-item"><span>空教室查询</span><span class="ar">›</span></div>'
          '<div class="action-item"><span>校历 &amp; 照片墙</span><span class="ar">›</span></div>'
          '<div class="action-item"><span>常用链接</span><span class="ar">›</span></div>'
          '<div class="action-item"><span>问题反馈</span><span class="ar">›</span></div>'
          '<div class="action-item"><span>我的反馈</span><span class="fb-dot">1</span></div>'
          '<div class="action-item"><span>清除缓存数据</span><span class="ar">›</span></div>'
          '</div>'
          '<div class="setting-card"><div class="setting-title">学期第一周周一</div>'
          '<div class="setting-value">2026-09-07</div>'
          '<div class="setting-hint">设置后课表将自动定位当前教学周并高亮今天</div></div>'
          '<div class="btn-group"><div class="btn">重新同步课表与成绩</div>'
          '<div class="btn-outline">查看成绩</div></div>'
          '<div class="logout">退出登录</div>'
          '<div class="version">v1.1.0 · build demo</div>')

    # ⑩ 问题反馈弹窗（真实结构：类型 tab + 内容 + 字数 + 提交）
    fb = ('<div class="fb-mask"><div class="fb-card">'
          '<div class="fb-head"><span class="fb-title">问题反馈</span>'
          '<span class="fb-close">✕</span></div>'
          '<div class="fb-label">反馈类型</div>'
          '<div class="type-tabs"><span class="type-tab on">功能建议</span>'
          '<span class="type-tab">问题/Bug</span><span class="type-tab">其他</span></div>'
          '<div class="fb-label">反馈内容</div>'
          '<div class="fb-textarea">希望空教室能收藏常用教学楼～</div>'
          '<div class="fb-count">16 / 500</div>'
          '<div class="btn">提交反馈</div>'
          '</div></div>')

    frames = [
        ("① 我的 · 登录", "输入学号 + 智慧理工密码，或点「扫码登录」", phone("课表助手", f1, 4)),
        ("② 扫码登录", "二维码可保存到相册，用微信扫一扫识别", phone("课表助手", f2, 4)),
        ("③ 课表", "登录成功后的主页（真机截图）", '<img class="shot" src="../assets/s1.jpg">'),
        ("④ 空教室查询", "按教学楼分组的空闲教室（真机截图）", '<img class="shot" src="../assets/s2.jpg">'),
        ("⑤ 考试安排", f"共 {len(exams)} 场，含倒计时与日期分组", phone("课表助手", exam_inner, 1)),
        ("⑥ 评教 · 批次", f"{len(batches)} 个批次，点击进入课程列表", phone("课表助手", b_inner, 2)),
        ("⑦ 评教 · 表单", f"{len(inds)} 项指标 × 每项 0-10 分（满分 100）", phone("课表助手", f_inner, 2)),
        ("⑧ 成绩", f"GPA {d['gpa']}｜平均分 {d['avg']}｜总学分 {d['credits']}", phone("课表助手", g_inner, 3)),
        ("⑨ 我的 · 已登录", "账号信息 / 快捷入口 / 校历设置 / 同步与退出",
         phone("课表助手", f'<div class="me">{me}</div>', 4)),
        ("⑩ 问题反馈", "类型选填 + 内容 + 字数 + 提交", 
         phone("课表助手", f'<div class="me">{me}</div>{fb}', 4)),
    ]
    return frames


def build(d):
    """整页演示稿（各屏由 build_frames 提供, 便于图文推广复用）"""
    login = d["login"]
    exams, batches = d["exams"], d["evals"]
    inds, cet = d["eval_form"].get("indicators", []), d["cet"]
    frames = build_frames(d)
    cards = "".join(f'<div class="item"><div class="cap">{t} <span>{c}</span></div>{h}</div>'
                    for t, c, h in frames)

    call = (f'POST /api/login-webvpn  {{"student_id":"{DEMO_SID}","password":"••••"}}\n'
            f'  → 200  login_method={login.get("login_method")}  '
            f'student_name={login.get("student_name")}  semester={login.get("semester")}\n'
            f'  → token={str(login.get("token", ""))[:12]}…\n'
            f'GET  /api/courses       → {len(d["courses"])} 门课程\n'
            f'GET  /api/exams         → {len(exams)} 场考试\n'
            f'GET  /api/evaluations   → {len(batches)} 个评教批次\n'
            f'GET  /api/eval-form     → {len(inds)} 项指标 × '
            f'{len(inds[0].get("options", [])) if inds else 0} 档（满分 100）\n'
            f'GET  /api/grades        → {len(d["grades"])} 条成绩\n'
            f'GET  /api/cet-scores    → {len(cet)} 条四六级\n')

    return f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8"><title>课表助手 · 登录与功能演示</title>
<style>{CSS}</style></head><body>
<h1>课表助手 · 登录过程与功能演示</h1>
<div class="sub">界面按小程序源码结构还原，数据取自素材服务器（演示账号 {DEMO_SID}）的真实接口返回；
课表、空教室两屏为真机截图。绩点口径与小程序一致（4.0 量表）。</div>
<div class="steps"><b>登录</b>：我的 → 输入学号 + 智慧理工密码（或扫码登录）→ 后端直连智慧理工统一认证 →
CAS 票据换教务会话 → 返回 token → 课表 / 考试 / 评教 / 成绩 同时可用。<br>
<b>演示环境</b>：{BASE}（演示账号 {DEMO_SID}，密码任意；课表、考试、成绩、评教均为种子数据）</div>
<div class="flow">{cards}</div>
<div class="call"># 本次演示实际调用的接口（素材服务器返回）
{call}</div>
</body></html>
"""


def main():
    try:
        requests.get(BASE + "/api/status", timeout=5)
    except Exception:  # noqa: BLE001
        print("素材服务器未运行，请先启动 demo-server/run.bat")
        return 1
    d = collect()
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(build(d))
    print("已生成:", OUT)
    print(f"  课表 {len(d['courses'])} / 考试 {len(d['exams'])} / 评教批次 {len(d['evals'])} / "
          f"指标 {len(d['eval_form'].get('indicators', []))} / 成绩 {len(d['grades'])} / "
          f"四六级 {len(d['cet'])} / GPA {d['gpa']} 平均分 {d['avg']} 学分 {d['credits']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
