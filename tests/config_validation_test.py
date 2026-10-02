# -*- coding: utf-8 -*-
"""配置校验回归: 生产安全开关必须 fail-closed。"""
import base64
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def run(env):
    merged = os.environ.copy()
    merged.update(env)
    return subprocess.run(
        [sys.executable, "-c",
         "import config; config.validate(); print('ok')"],
        cwd=ROOT, env=merged, capture_output=True, text=True)


missing = run({
    "REQUIRE_SECURE_CONFIG": "1",
    "SESSION_KEY": "",
    "ADMIN_PASSWORD": "",
})
assert missing.returncode != 0 and "SESSION_KEY" in missing.stderr
print("  [PASS] 生产缺少 SESSION_KEY 时启动失败")

bad_key = run({
    "REQUIRE_SECURE_CONFIG": "1",
    "SESSION_KEY": "not-base64",
    "ADMIN_PASSWORD": "admin-test",
})
assert bad_key.returncode != 0 and "SESSION_KEY" in bad_key.stderr
print("  [PASS] 非法 SESSION_KEY 被拒绝")

valid = run({
    "REQUIRE_SECURE_CONFIG": "1",
    "SESSION_KEY": base64.b64encode(
        b"0123456789abcdef0123456789abcdef").decode(),
    "ADMIN_PASSWORD": "admin-test",
})
assert valid.returncode == 0 and "ok" in valid.stdout, valid.stderr
print("  [PASS] 合法生产配置通过校验")
print("配置校验测试全部通过 [OK]")
