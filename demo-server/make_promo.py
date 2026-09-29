# -*- coding: utf-8 -*-
"""生成小程序图文宣传素材（1080×1440 竖版卡片 + 配套文案）。

用法（素材服务器已在 5000 端口运行）：
    ..\\.venv\\Scripts\\python.exe make_promo.py
输出：
    poster/promo/card-1.html … card-9.html   （每张一页，用 Edge 无头截图成 PNG）
    poster/promo/文案.md                       （标题、正文、话题标签）

界面部分复用 make_walkthrough 的组件，保证与小程序一致。
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(HERE))

import make_walkthrough as mw  # noqa: E402

OUT_DIR = os.path.abspath(os.path.join(HERE, "..", "poster", "promo"))

CARD_CSS = """
html,body{margin:0;padding:0}
body.card{width:1080px;height:1440px;overflow:hidden;background:#F4F3FA;
  font-family:-apple-system,BlinkMacSystemFont,"PingFang SC","Microsoft YaHei",Arial,sans-serif;
  color:#221F33;padding:64px 72px;display:flex;flex-direction:column}
.kicker{display:inline-block;background:rgba(124,107,232,.12);color:#7C6BE8;font-size:26px;
  padding:8px 20px;border-radius:999px;align-self:flex-start}
h2{font-size:64px;line-height:1.25;margin:26px 0 18px;letter-spacing:-1px}
h2 em{font-style:normal;color:#7C6BE8}
.pts{list-style:none;padding:0;margin:0 0 26px}
.pts li{font-size:30px;color:#4A4A56;line-height:1.7;padding-left:40px;position:relative}
.pts li:before{content:"";position:absolute;left:8px;top:18px;width:16px;height:16px;border-radius:50%;
  background:#7C6BE8;opacity:.85}
.phone-wrap{flex:1;display:flex;justify-content:center;align-items:flex-start;overflow:hidden}
.phone-wrap img.shot{max-height:100%;width:auto;display:block}
.phone-wrap > div{transform:scale(var(--s,1.2));transform-origin:top center}
.foot{font-size:26px;color:#8A8A96;text-align:center;margin-top:14px}
/* 封面（用 body.card.xxx 提高优先级，避免被 .card 背景覆盖） */
body.card.cover{background:linear-gradient(160deg,#8B7BF0 0%,#7C6BE8 45%,#6B5AD8 100%);color:#fff;justify-content:center}
body.card.cover h1{font-size:140px;margin:0 0 26px;line-height:1.15;letter-spacing:-2px}
body.card.cover .sub{font-size:40px;color:rgba(255,255,255,.95);margin-bottom:46px}
body.card.cover .foot{color:rgba(255,255,255,.85)}
.chips{display:flex;gap:16px;flex-wrap:wrap;margin-bottom:26px}
.chip{background:rgba(255,255,255,.22);border-radius:999px;padding:12px 26px;font-size:30px}
.chip.hot{background:#fff;color:#6B5AD8;font-weight:600}
body.card.cover .phone-wrap{align-items:flex-end}
body.card.cover .chips{margin-bottom:0}
body.card.cover .cta-bar{background:#fff;color:#2B2B33;border-radius:22px;
  display:flex;align-items:center;gap:34px;margin-top:76px;padding:28px 34px}
body.card.cover .cta-bar img{width:196px;height:196px;display:block;flex:none}
body.card.cover .cta-t{font-size:46px;font-weight:600;letter-spacing:-.5px}
body.card.cover .cta-s{font-size:30px;color:#8A8A96;margin-top:12px}
/* 照片墙（校园工具）界面 */
.gw{padding:10px;background:#F7F6FB;height:100%;box-sizing:border-box;overflow:hidden}
.gw-card{background:#fff;border-radius:14px;padding:12px;margin-bottom:12px;
  box-shadow:0 3px 12px rgba(87,74,160,.08)}
.gw-tt{font-size:16px;font-weight:700;color:#33304F;margin-bottom:8px}
.gw-img{width:100%;display:block;border-radius:8px;background:#F7F6FB}
/* 常用链接弹窗 */
.fb-card.links{max-height:606px;overflow:hidden;padding:15px 14px 13px}
.link-tip{font-size:11px;color:#8A87A8;line-height:1.5;margin-bottom:10px}
.link-group-title{font-size:12.5px;font-weight:700;color:#33304F;margin:8px 0 6px}
.link-row{display:flex;align-items:center;gap:9px;padding:8px 9px;background:#F7F6FB;
  border-radius:9px;margin-bottom:6px}
.link-main{flex:1;display:flex;flex-direction:column;gap:2px;min-width:0}
.link-name{font-size:13px;font-weight:600;color:#33304F}
.link-url{font-size:10.5px;color:#8A87A8;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.link-act{flex:none;font-size:12.5px;font-weight:600;color:#7C6BE8}
/* 尾卡 */
body.card.end{background:linear-gradient(160deg,#7C6BE8,#6B5AD8);color:#fff;justify-content:center;text-align:center;align-items:center}
body.card.end h2{font-size:76px;margin:0 0 20px}
body.card.end .search{background:#fff;color:#2B2B33;border-radius:18px;padding:26px 40px;font-size:36px;
  margin:20px 0 34px;display:flex;align-items:center;gap:18px}
body.card.end .search svg{display:block;flex:none}
body.card.end .steps{font-size:30px;line-height:2;opacity:.95;text-align:left}
body.card.end .or{font-size:28px;opacity:.85;margin:6px 0 14px}
body.card.end .code{width:300px;height:300px;background:#fff;border-radius:20px;padding:14px;
  display:flex;align-items:center;justify-content:center;margin-bottom:26px}
body.card.end .code img{width:272px;height:272px;display:block}
body.card.end .code .ph{color:#8A8A96;font-size:22px;line-height:1.7;text-align:center}
body.card.end .thanks{font-size:29px;color:rgba(255,255,255,.92);margin-top:24px;line-height:1.6}
"""


def card_page(css_class, inner, scale=1.2):
    return f"""<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">
<style>{mw.CSS}{CARD_CSS}</style></head>
<body class="card {css_class}" style="--s:{scale}">{inner}</body></html>
"""


def wrap_phone(html, scale=1.2):
    return f'<div class="phone-wrap" style="--s:{scale}">{html}</div>'


def _code_block() -> str:
    """小程序码：把图片放到 poster/promo/miniprogram-code.png|jpg 即自动嵌入，否则留占位。"""
    for ext in (".png", ".jpg", ".jpeg"):
        if os.path.exists(os.path.join(OUT_DIR, "miniprogram-code" + ext)):
            return f'<div class="code"><img src="miniprogram-code{ext}" alt="小程序码"></div>'
    return ('<div class="code"><div class="ph">小程序码<br>'
            '（放 poster/promo/miniprogram-code.png 后重新生成）</div></div>')


def build_cards(d, frames):
    """frames 顺序: ① 登录 ② 扫码 ③ 课表 ④ 空教室 ⑤ 考试 ⑥ 评教批次 ⑦ 评教表单 ⑧ 成绩 ⑨ 我的"""
    f_login = frames[0][2]
    f_lesson = frames[2][2]     # 真机截图（课表）
    f_room = frames[3][2]       # 真机截图（空教室）
    f_eval = frames[6][2]       # 评教表单
    f_grade = frames[7][2]      # 成绩

    gallery_inner = (
        '<div class="gw">'
        '<div class="gw-card"><div class="gw-tt">26-27年校历</div>'
        '<img class="gw-img" src="../../wxcloudrun/static/gallery/26-27年校历.png"></div>'
        '<div class="gw-card"><div class="gw-tt">孝陵卫地图</div>'
        '<img class="gw-img" src="../../wxcloudrun/static/gallery/孝陵卫地图.png"></div>'
        '</div>')

    _link_rows = [
        ("官网", "https://www.njust.edu.cn/"),
        ("统一身份认证平台", "https://ehall2.njust.edu.cn/"),
        ("教务处", "https://jwc.njust.edu.cn/"),
        ("研究生院", "https://gs.njust.edu.cn/"),
        ("图书馆", "https://lib.njust.edu.cn/"),
        ("WebVPN", "https://webvpn.njust.edu.cn/"),
        ("学校邮箱", "https://mail.njust.edu.cn/"),
        ("缴费平台", "https://cwcmh.njust.edu.cn/payment/pay/payment.jsp"),
        ("智慧团委", "https://zhtw.njust.edu.cn/"),
        ("X·Space", "https://xspace.njust.edu.cn/main.htm"),
        ("开放知识库", "https://njust.wiki/"),
    ]
    links_modal = (
        '<div class="fb-mask"><div class="fb-card links">'
        '<div class="fb-head"><span class="fb-title">常用链接</span>'
        '<span class="fb-close">✕</span></div>'
        '<div class="link-tip">点击复制链接，在浏览器粘贴打开 · 长按查看完整网址</div>'
        '<div class="link-group-title">🌐 校内服务（11）</div>'
        + "".join(
            f'<div class="link-row"><div class="link-main">'
            f'<span class="link-name">{n}</span><span class="link-url">{u}</span></div>'
            f'<span class="link-act">复制</span></div>'
            for n, u in _link_rows)
        + '<div class="link-group-title">📄 考试与学习（9）</div>'
        '</div></div>')
    my_with_links = frames[8][2].replace(
        '<div class="tabbar">', links_modal + '<div class="tabbar">', 1)

    cover = ('<h1>Njust课表</h1>'
             '<div class="sub">一键评教 · 课表 · 空教室 · 成绩，一个小程序搞定</div>'
             '<div class="chips"><span class="chip hot">一键评教</span>'
             '<span class="chip">自动定位本周</span>'
             '<span class="chip">空教室按楼看</span>'
             '<span class="chip">绩点一页看全</span></div>'
             + '<div class="cta-bar">'
               '<img src="miniprogram-code.jpg" alt="小程序码">'
               '<div><div class="cta-t">微信搜索「resetinging课表」</div>'
               '<div class="cta-s">或扫码打开小程序，登录一次长期有效</div></div>'
               '</div>')

    cards = [
        ("card-1", "cover", cover),
        ("card-2", "", '<div class="kicker">评教</div><h2>十几门课评教<em>一次点完</em></h2>'
                       '<ul class="pts"><li>设定目标分数，所有指标自动分配</li>'
                       '<li>多门课程批量提交，不用手点</li></ul>' + wrap_phone(f_eval, 1.15)
         + '<div class="foot">评教截止前不再手忙脚乱</div>'),
        ("card-3", "", '<div class="kicker">课表</div><h2>打开就是<em>本周课表</em></h2>'
                       '<ul class="pts"><li>自动定位教学周，今天高亮</li>'
                       '<li>上课时间、教室、老师一眼看到</li>'
                       '<li>多学期课程随时切换</li></ul>' + wrap_phone(f_lesson, 1.15)
         + '<div class="foot">上下班路上先看一眼，不再翻群文件</div>'),
        ("card-4", "", '<div class="kicker">空教室</div><h2>找自习室<em>不用问人</em></h2>'
                       '<ul class="pts"><li>选好星期和大节，按教学楼列空教室</li>'
                       '<li>四大教学楼置顶，按楼层排序</li>'
                       '<li>孝陵卫、江阴两个校区都支持</li></ul>' + wrap_phone(f_room, 1.15)
         + '<div class="foot">每天大节上课时后端自动更新</div>'),
        ("card-5", "", '<div class="kicker">成绩</div><h2>绩点、平均分、四六级<em>一页看全</em></h2>'
                       '<ul class="pts"><li>加权平均绩点大卡，含分学期明细</li>'
                       '<li>奖学金/综测、保研推免两种口径切换</li>'
                       '<li>四六级成绩自动折算</li></ul>' + wrap_phone(f_grade, 1.15)
         + '<div class="foot">成绩一出，绩点立刻更新</div>'),
        ("card-6", "", '<div class="kicker">照片墙</div><h2>校历和校区地图<em>随手翻</em></h2>'
                       '<ul class="pts"><li>全年校历、孝陵卫和江阴两个校区地图</li>'
                       '<li>大图分片加载，点开即看</li>'
                       '<li>看过一次，离线也能翻</li></ul>'
                       + wrap_phone(mw.phone("校园工具", gallery_inner, back=True, tabbar=False), 1.15)
         + '<div class="foot">校历和地图，一个页面全都有</div>'),
        ("card-7", "", '<div class="kicker">常用链接</div><h2>校内常用网站<em>一处收齐</em></h2>'
                       '<ul class="pts"><li>校内服务、考试学习，共 20 个常用入口</li>'
                       '<li>点击复制链接，浏览器粘贴打开</li>'
                       '<li>不用再翻收藏夹找网址</li></ul>'
                       + wrap_phone(my_with_links, 1.15)
         + '<div class="foot">常用的网站都在这里，复制即用</div>'),
        ("card-8", "", '<div class="kicker">登录</div><h2>智慧理工账号<em>直接登录</em></h2>'
                       '<ul class="pts"><li>用统一认证账号，不用教务密码</li>'
                       '<li>登录一次长期有效，日常免登录</li>'
                       '<li>也可以扫码登录</li></ul>' + wrap_phone(f_login, 1.15)
         + '<div class="foot">密码不做存储，服务器只保留登录状态</div>'),
    ]
    end = ('<h2>微信搜索<br>「resetinging课表」</h2>'
           '<div class="search">'
           '<svg width="34" height="34" viewBox="0 0 24 24" fill="none" stroke="#8A8A96"'
           ' stroke-width="2.2" stroke-linecap="round"><circle cx="11" cy="11" r="7"/>'
           '<path d="M16.4 16.4 21 21"/></svg> resetinging课表</div>'
           '<div class="or">或 扫描小程序二维码</div>'
           + _code_block() +
           '<div class="steps">1. 打开微信 → 搜索「resetinging课表」，或扫码<br>'
           '2. 进入小程序 → 用智慧理工账号登录<br>'
           '3. 课表、空教室、评教、成绩立刻可用</div>'
           '<div class="thanks">小程序还在持续更新，欢迎大家使用、提供建议</div>')
    cards.append(("card-9", "end", end))
    return cards


COPY = """# 小程序图文宣传文案

> 配图：`card-1.png`（封面）→ `card-2.png` … `card-9.png`（尾卡）

## 标题（任选）

- 期末评教不用一个个点，十几门课一次提交
- 课表、空教室、评教、成绩，一个小程序全包了
- 找自习室不用问人了，Njust课表

## 正文

开学后最烦的三件事：翻群找课表、找空教室问同学、评教一个个点。

做了个「Njust课表」，用智慧理工统一认证账号登录（不用教务密码）：

· **评教**：一键评教，可以设目标分数；多门课一次提交
· **课表**：打开就是本周，自动定位教学周，上课时间和教室一眼看到
· **空教室**：选好星期和大节，按教学楼列出来，孝陵卫和江阴都支持
· **照片墙**：校历和两个校区地图，随手翻看
· **常用链接**：校内服务、考试学习共 20 个入口，点击复制到浏览器打开
· **成绩**：绩点大卡 + 分学期明细，四六级自动折算，还能切奖学金/保研两种口径

后端每天大节上课时自动刷新空教室数据，成绩出来后打开就能看到最新绩点。
微信搜索「resetinging课表」，或扫下方小程序码即可使用。

## 话题标签

#课表 #空教室 #大学评教 #绩点 #大学生活

## 发布建议

- 平台：小红书 / 朋友圈 / 班级群；小红书用 3:4 竖图，卡片已按 1080×1440 输出
- 顺序：封面 → 评教 → 课表 → 空教室 → 成绩 → 照片墙 → 常用链接 → 登录 → 尾卡
- 封面标题已留白，若平台首图会裁切，可只发 card-1
"""


def main():
    try:
        import requests
        requests.get(mw.BASE + "/api/status", timeout=5)
    except Exception:  # noqa: BLE001
        print("素材服务器未运行，请先启动 demo-server/run.bat")
        return 1
    d = mw.collect()
    frames = mw.build_frames(d)
    os.makedirs(OUT_DIR, exist_ok=True)
    cards = build_cards(d, frames)
    for name, cls, inner in cards:
        with open(os.path.join(OUT_DIR, name + ".html"), "w", encoding="utf-8") as f:
            f.write(card_page(cls, inner))
    with open(os.path.join(OUT_DIR, "文案.md"), "w", encoding="utf-8") as f:
        f.write(COPY)
    print("已生成", len(cards), "张卡片 + 文案:", OUT_DIR)
    return 0


if __name__ == "__main__":
    sys.exit(main())
