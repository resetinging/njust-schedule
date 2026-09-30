"""
admin token 无状态签名测试(独立于冒烟测试)
==========================================
覆盖:
  1. 登录签发 v1.<exp>.<sig>, 密码错误拒发;
  2. 同一 SESSION_KEY/ADMIN_PASSWORD 下, 另一进程(模拟重启/多实例)可校验同一 token;
  3. 签名篡改 / 自行延长有效期 → 拒绝;
  4. 过期与旧格式(hex/任意字符串) token → 拒绝。

用法: python tests/admin_token_test.py
"""
import os
import subprocess
import sys

_here = os.path.dirname(os.path.abspath(__file__))
_db_path = os.path.join(_here, "admin_token_tmp.db").replace("\\", "/")
if os.path.exists(_db_path):
    os.remove(_db_path)
os.environ["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{_db_path}"
# 固定测试密钥(非生产值): 保证子进程与父进程派生同一签名密钥
os.environ["ADMIN_PASSWORD"] = "tmp-admin-pwd-for-test"
os.environ["SESSION_KEY"] = "MDEyMzQ1Njc4OWFiY2RlZjAxMjM0NTY3ODlhYmNkZWY="  # 32B, 与生产配置一致
os.environ.pop("MYSQL_USERNAME", None)
os.environ.pop("MYSQL_PASSWORD", None)

_root = os.path.dirname(_here)
sys.path.insert(0, _root)

from wxcloudrun import app  # noqa: E402
from wxcloudrun import admin as admin_mod  # noqa: E402

_client = app.test_client()
PASS, FAIL, FAILURES = 0, 0, []


def _ok(name: str, cond: bool, extra=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  [PASS] {name}")
    else:
        FAIL += 1
        FAILURES.append(name)
        print(f"  [FAIL] {name} {extra}")


print("== admin token 无状态签名 ==")

r = _client.post("/api/admin/login", json={"password": "bad"})
_ok("密码错误 401", r.status_code == 401, r.status_code)
r = _client.post("/api/admin/login", json={"password": os.environ["ADMIN_PASSWORD"]})
_ok("密码正确签发 token", r.status_code == 200, r.status_code)
_tok = (r.get_json() or {}).get("token", "")
_ok("token 格式 v1.<exp>.<sig>", _tok.startswith("v1.") and _tok.count(".") == 2, _tok)

_login = _client.get("/api/admin/check", headers={"X-Admin-Token": _tok}).get_json() or {}
_ok("token 通过 /api/admin/check", _login.get("logged_in") is True, _login)

_ver, _exp, _sig = _tok.split(".")
_bad_sig = f"{_ver}.{_exp}." + ("A" if _sig[0] != "A" else "B") + _sig[1:]
_ok("签名篡改 → 401",
    _client.get("/api/admin/summary", headers={"X-Admin-Token": _bad_sig}).status_code == 401)
_ok("有效期篡改(exp 不重签) → 401",
    _client.get("/api/admin/summary",
                headers={"X-Admin-Token": f"{_ver}.{int(_exp) + 3600}.{_sig}"}).status_code == 401)
_ok("过期 token → 401",
    _client.get("/api/admin/summary",
                headers={"X-Admin-Token": admin_mod._issue_admin_token(ttl=-1)}).status_code == 401)
_ok("旧格式 token → 401",
    _client.get("/api/admin/summary", headers={"X-Admin-Token": "dash-test-token"}).status_code == 401)

# 跨进程: 子进程用同一密钥独立校验该 token, 证明会话不依赖进程内存
_code = (
    "import os,sys;"
    "sys.path.insert(0, os.environ['ROOT']);"
    "from wxcloudrun.admin import _verify_admin_token as v;"
    "print('OK' if v(sys.argv[1]) else 'FAIL')"
)
_out = subprocess.run([sys.executable, "-c", _code, _tok],
                      capture_output=True, text=True,
                      env=dict(os.environ, ROOT=_root))
_ok("另一进程可校验同一 token(重启/多实例)",
    _out.stdout.strip() == "OK",
    (_out.returncode, _out.stdout[-200:], _out.stderr[-300:]))

print(f"\n结果: {PASS} 通过, {FAIL} 失败")
try:
    os.remove(_db_path)
except OSError:
    pass
if FAIL:
    print("失败项:", FAILURES)
    sys.exit(1)
print("admin token 测试全部通过 [OK]")
