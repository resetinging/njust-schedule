"""教务登录链路 — 本地测试

用法:
    # 仅离线校验改写算法(不需要凭据)
    python tests/webvpn_local_test.py

    # 完整链路
    $env:NJUST_SID="924101960123"
    $env:NJUST_SSO_PWD="<智慧理工密码>"
    $env:NJUST_JW_PWD="<教务密码, 可不填>"
    python tests/webvpn_local_test.py

覆盖:
  1. WebVPN 改写算法对网关真实接受过的向量逐字节一致
  2. 智慧理工 SSO 直连教务（indexsso.jsp）: 免教务密码、免验证码 → 课表
  3. WebVPN 网关备用通道: 会话建立 + 教务页面/验证码可达
  4. 直连链路回归: 8080 表单登录 + 验证码 OCR + 初始密码兜底
"""

import os
import sys

_here = os.path.dirname(os.path.abspath(__file__))
_root = os.path.dirname(_here)
sys.path.insert(0, _root)
sys.path.insert(0, os.path.join(_root, "wxcloudrun"))

os.environ.setdefault(
    "SQLALCHEMY_DATABASE_URI",
    "sqlite:///" + os.path.join(_here, "webvpn_tmp.db").replace("\\", "/"))

from wxcloudrun.webvpn import (  # noqa: E402
    VECTOR_HOST, VECTOR_TOKEN, WEBVPN_BASE, is_jw_url, remap_jw_url,
    to_proxy_url, wengine_token)

PASS, FAIL = "[OK]  ", "[FAIL]"
_results = []


def check(name, got, want):
    ok = got == want
    _results.append(ok)
    print(f"  {PASS if ok else FAIL} {name}")
    if not ok:
        print(f"        实际: {got}")
        print(f"        期望: {want}")


def info(name, detail=""):
    print(f"  [INFO] {name}" + (f"\n         {detail}" if detail else ""))


def head(title):
    print()
    print("=" * 72)
    print(title)
    print("=" * 72)


# ============================================================
# 1. 离线：WebVPN 改写算法
# ============================================================
head("[1] WebVPN 改写算法（离线，对照网关真实接受过的向量）")

check("token(202.119.81.113) 与实测一致", wengine_token(VECTOR_HOST), VECTOR_TOKEN)
check("IV 前缀 = hex('wrdvpnisthebest!')", wengine_token(VECTOR_HOST)[:32],
      "77726476706e69737468656265737421")

check("教务 URL → 网关 URL（bkjw，无端口）",
      to_proxy_url("http://bkjw.njust.edu.cn/njlgdx/framework/main.jsp"),
      f"{WEBVPN_BASE}/http/{wengine_token('bkjw.njust.edu.cn')}/njlgdx/framework/main.jsp")
check("校内 8080 映射到 bkjw 且丢端口 + 补前缀",
      to_proxy_url("http://202.119.81.113:8080/verifycode.servlet"),
      f"{WEBVPN_BASE}/http/{wengine_token('bkjw.njust.edu.cn')}/njlgdx/verifycode.servlet")
check("已是 /njlgdx 的路径不重复补前缀",
      to_proxy_url("http://202.119.81.112:9080/njlgdx/xskb/xskb_list.do?Ves632DSdyV=NEW_XSD_PYGL"),
      f"{WEBVPN_BASE}/http/{wengine_token('bkjw.njust.edu.cn')}"
      "/njlgdx/xskb/xskb_list.do?Ves632DSdyV=NEW_XSD_PYGL")
check("非教务主机不映射", to_proxy_url("https://ehall2.njust.edu.cn/index.html"),
      f"{WEBVPN_BASE}/https/{wengine_token('ehall2.njust.edu.cn')}/index.html")

# SSO 直连模式的统一入口改写
check("SSO 直连: 内网地址 → bkjw 统一入口",
      remap_jw_url("http://202.119.81.112:9080/njlgdx/xskb/xskb_list.do?a=1",
                   "http://bkjw.njust.edu.cn"),
      "http://bkjw.njust.edu.cn/njlgdx/xskb/xskb_list.do?a=1")
check("SSO 直连: 根路径补 /njlgdx",
      remap_jw_url("http://202.119.81.113:8080/verifycode.servlet",
                   "http://bkjw.njust.edu.cn"),
      "http://bkjw.njust.edu.cn/njlgdx/verifycode.servlet")
check("SSO 直连: https 源址不被降级回 http",
      remap_jw_url("https://bkjw.njust.edu.cn/njlgdx/kscj/cjcx_query?a=1",
                   "http://bkjw.njust.edu.cn"),
      "https://bkjw.njust.edu.cn/njlgdx/kscj/cjcx_query?a=1")

check("is_jw_url(教务)", is_jw_url("http://202.119.81.112:9080/njlgdx/x.do"), True)
check("is_jw_url(非教务)", is_jw_url("https://ids.njust.edu.cn/authserver/login"), False)

# ============================================================
# 2. 智慧理工 SSO 直连（主路径：免教务密码、免验证码）
# ============================================================
SID = os.environ.get("NJUST_SID", "").strip()
SSO_PWD = os.environ.get("NJUST_SSO_PWD", "")
JW_PWD = os.environ.get("NJUST_JW_PWD", "")

head("[2] 智慧理工 SSO 直连教务（indexsso.jsp，免教务密码/验证码）")

if not (SID and SSO_PWD):
    print("  跳过：未设置 NJUST_SID / NJUST_SSO_PWD")
else:
    from wxcloudrun.jwc_client import JWCClient  # noqa: E402

    c = JWCClient()
    c.debug_log = []
    # ★ 教务密码故意留空：SSO 直连本就不该需要它
    ok = c.login_webvpn(SID, SSO_PWD, "")
    print(f"     login_webvpn(教务密码留空) → {ok}  方式={c.login_method!r}  "
          f"错误={c.last_error!r}")

    check("SSO 直连登录成功", ok, True)
    check("登录方式为 sso（未用到教务密码/验证码）", c.login_method, "sso")
    check("教务请求已统一改写到 SSO 入口", c.webvpn.remap_to, "https://bkjw.njust.edu.cn")

    courses = []
    if ok:
        courses = c.get_schedule()
        grades = c.get_grades()
        print(f"     课表 {len(courses)} 条 / 成绩 {len(grades)} 条")
        check("SSO 直连取到课表", len(courses) > 0, True)
        check("SSO 直连会话有效", c.is_session_valid(), True)

    if os.environ.get("WEBVPN_DUMP_LOG"):
        print("  ---- 诊断日志 ----")
        for line in c.debug_log[-18:]:
            print("   ", line)

# ============================================================
# 3. WebVPN 网关（备用：网络可达，不解决身份）
# ============================================================
head("[3] WebVPN 网关备用通道（只解决网络可达）")

if not (SID and SSO_PWD):
    print("  跳过：未设置 NJUST_SID / NJUST_SSO_PWD")
else:
    from wxcloudrun.jwc_client import JWCClient  # noqa: E402

    c2 = JWCClient()
    c2.debug_log = []
    c2.webvpn.log = c2._log
    check("SSO 登录成功（拿到 CASTGC）", c2._direct_sso_login(SID, SSO_PWD), True)
    check("CAS 换票建立 WebVPN 会话", c2.webvpn.authenticate(), True)
    check("/user/info 能查到已登录用户", bool(c2.webvpn.verify()), True)
    c2.webvpn.activate()

    page = c2.session.get("http://202.119.81.112:9080/njlgdx/framework/main.jsp", timeout=30)
    check("教务登录页经代理可达", page.status_code == 200 and "verifycode" in page.text, True)
    cap = c2.session.get("http://202.119.81.113:8080/verifycode.servlet", timeout=30)
    check("教务验证码经代理返回图片", JWCClient._looks_like_image(cap.content), True)

    info("代理无法替代教务登录（实测）",
         "网关不透传 POST body 到 /njlgdx/xk/Verifyservlet（收到空表单→「验证码不能为空」）；"
         "直连可用的根端点 /Logon.do 经网关 302 → /login")
    info("定位", "身份走 [2] 的 SSO 直连；本通道只在直连被墙时提供网络可达")

# ============================================================
# 4. 直连链路回归
# ============================================================
head("[4] 直连链路回归（8080 表单 + 验证码 OCR + 初始密码兜底 + 多入口）")

if not (SID and JW_PWD):
    print("  跳过：未设置 NJUST_SID / NJUST_JW_PWD")
else:
    from wxcloudrun.jwc_client import JWCClient  # noqa: E402

    c3 = JWCClient()
    c3.debug_log = []
    ok3 = c3.login(SID, JW_PWD)
    check("直连登录成功", ok3, True)
    if ok3:
        courses3 = c3.get_schedule()
        print(f"     课表 {len(courses3)} 条（入口={c3.logon_base}）")
        check("直连取到课表", len(courses3) > 0, True)

print()
print("=" * 72)
print(f"结果: {sum(_results)}/{len(_results)} 项通过")
print("=" * 72)
sys.exit(0 if all(_results) else 1)
