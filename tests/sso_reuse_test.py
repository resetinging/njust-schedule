# -*- coding: utf-8 -*-
"""智慧理工 SSO 会话复用 / 认证节流 验证脚本。

验证目标(对应「减少智慧理工认证次数, 避免账号被冻结」):
  1. 首次登录 → 正常做一次 SSO 认证, 并把会话 cookie 持久化;
  2. 再次登录(即使密码填错) → 走持久化会话, 不再向智慧理工提交密码;
  3. 认证失败后进入冷却期 → 冷却期内第二次请求被直接拦截, 不打服务器。

用法:
    $env:NJUST_SID="924101960123"; $env:NJUST_SSO_PWD="<智慧理工密码>"
    python tests/sso_reuse_test.py
"""
import os
import sys

_here = os.path.dirname(os.path.abspath(__file__))
_root = os.path.dirname(_here)
sys.path.insert(0, _root)

# 必须在导入应用前指向独立临时库, 避免污染真实数据
_tmp_db = os.path.join(_here, "_sso_reuse.db").replace("\\", "/")
os.environ.setdefault("SQLALCHEMY_DATABASE_URI", "sqlite:///" + _tmp_db)

from wxcloudrun import app  # noqa: E402
from wxcloudrun.jwc_client import JWCClient  # noqa: E402

SID = os.environ.get("NJUST_SID", "").strip()
PWD = os.environ.get("NJUST_SSO_PWD", "")

_passed = 0
_failed = 0


def check(name, got, want):
    global _passed, _failed
    if got == want:
        _passed += 1
        print(f"  [PASS] {name}")
    else:
        _failed += 1
        print(f"  [FAIL] {name}\n         实际: {got!r}\n         期望: {want!r}")


def main() -> int:
    print("=" * 66)
    print("[1] 首次登录 → 持久化会话")
    print("=" * 66)
    c1 = JWCClient()
    ok1 = c1.login_webvpn(SID, PWD)
    check("首次登录成功", ok1, True)
    print(f"         方式={c1.login_method!r} 错误={c1.last_error!r}")

    print("=" * 66)
    print("[2] 二次登录(密码故意填错) → 必须命中持久化会话")
    print("=" * 66)
    c2 = JWCClient()
    ok2 = c2.login_webvpn(SID, "definitely-not-the-password")
    check("复用会话登录成功(未提交密码)", ok2, True)
    check("登录方式为 sso-cached", c2.login_method, "sso-cached")
    courses = c2.get_schedule() if ok2 else []
    print(f"         复用后取到课表 {len(courses)} 条")
    check("复用会话可直接取数据", len(courses) > 0, True)

    print("=" * 66)
    print("[3] 认证失败后的冷却期(用不存在的账号, 不影响真实账号)")
    print("=" * 66)
    c3 = JWCClient()
    ok3 = c3.login_webvpn("90000000000", "bad-password")
    check("假账号首次登录失败", ok3, False)
    c4 = JWCClient()
    ok4 = c4.login_webvpn("90000000000", "bad-password")
    check("冷却期内被拦截", ok4, False)
    check("提示为防冻结文案", "冻结" in (c4.last_error or ""), True)
    print(f"         提示: {c4.last_error!r}")

    print("=" * 66)
    print("[4] 退出登录 → 持久化会话必须被清除")
    print("=" * 66)
    from wxcloudrun.core import session_store
    before = session_store.load_session(SID)
    check("登出前存在持久化会话", bool(before), True)
    c2.logout()
    after = session_store.load_session(SID)
    check("登出后持久化会话已清除", after, None)

    print("=" * 66)
    print(f"结果: {_passed} 通过, {_failed} 失败")
    print("=" * 66)
    return 1 if _failed else 0


if __name__ == "__main__":
    if not (SID and PWD):
        print("跳过: 未设置 NJUST_SID / NJUST_SSO_PWD")
        raise SystemExit(0)
    with app.app_context():
        raise SystemExit(main())
