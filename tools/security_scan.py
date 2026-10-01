# -*- coding: utf-8 -*-
"""统一安全/质量扫描入口。

用法:
    pip install -r requirements-dev.txt
    python tools/security_scan.py
"""
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = sys.executable


def run(name, args, allow_codes=()):
    print("\n==> " + name)
    print("    " + " ".join(args))
    proc = subprocess.run(args, cwd=ROOT)
    if proc.returncode != 0 and proc.returncode not in allow_codes:
        raise SystemExit("FAILED: %s (exit=%d)" % (name, proc.returncode))


def module_available(name):
    return subprocess.run(
        [PY, "-c", "import %s" % name],
        cwd=ROOT,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    ).returncode == 0


def main():
    missing = [m for m in ("pytest", "pip_audit", "bandit") if not module_available(m)]
    if missing:
        print("缺少开发依赖: " + ", ".join(missing))
        print("请先执行: %s -m pip install -r requirements-dev.txt" % PY)
        return 2

    run("Python 编译检查", [PY, "-m", "compileall", "-q", "wxcloudrun", "config.py"])
    run("凭据存储测试", [PY, "tests/credential_store_test.py"])
    run("会话存储测试", [PY, "tests/session_store_test.py"])
    run("管理端 token 测试", [PY, "tests/admin_token_test.py"])
    run("冒烟测试", [PY, "tests/smoke_test.py"])
    run("pytest", [PY, "-m", "pytest", "-q"], allow_codes=(5,))
    run("依赖漏洞扫描(pip-audit)", [PY, "-m", "pip_audit", "-r", "requirements.txt"])
    run("静态安全扫描(Bandit)",
        [PY, "-m", "bandit", "-r", "wxcloudrun", "-q", "--severity-level", "medium"])
    print("\n安全扫描全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
