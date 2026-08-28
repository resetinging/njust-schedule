"""
不同学期课表抓取验证（需校园网/VPN + 有效教务账号）
验证上一轮修复: HTML 学期提交 — 不同学期应返回不同课表。
用法: python tests/semester_schedule_test.py <学号> <密码>
"""
import os
import sys

# 避免 import 初始化 Flask app 时连 MySQL(本地无 MySQL): 用临时 SQLite
_tmp = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sem_tmp.db")
os.environ["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{_tmp.replace(os.sep, '/')}"

sys.path.insert(0, ".")
from wxcloudrun.jwc_client import JWCClient  # noqa: E402


def main():
    if len(sys.argv) < 3:
        print("用法: python tests/semester_schedule_test.py <学号> <密码>")
        sys.exit(1)
    sid, pwd = sys.argv[1], sys.argv[2]

    client = JWCClient()
    print("登录教务中(OCR 自动识别验证码)...")
    ok = client.login(sid, pwd)
    print(f"登录: {'✅ 成功' if ok else '❌ 失败'} method={client.login_method} err={client.last_error}")
    if not ok:
        sys.exit(1)

    sems = ["2026-2027-1", "2025-2026-2", "2026-2027-2"]
    results = {}
    for sem in sems:
        courses = client.get_schedule(sem)
        names = [c["name"] for c in courses[:6]]
        results[sem] = names
        print(f"\n[{sem}] 共 {len(courses)} 门:")
        for n in names:
            print(f"   - {n}")
        print(f"   last_error={client.last_error or '(无)'}")

    # 对比不同学期是否不同
    print("\n=== 结果对比 ===")
    base = results.get("2026-2027-1")
    for sem in sems[1:]:
        same = results[sem] == base if base else False
        print(f"2026-2027-1 vs {sem}: {'❌ 完全相同(疑似bug)' if same else '✅ 不同'}")

    # 若完全相同, 提示可能 HTML 未提交学期
    if base and all(results[s] == base for s in sems[1:]):
        print("\n⚠️ 各学期课表完全相同 → 大概率 HTML 路径未提交目标学期")
        print("   (API 可能一直失败而降级 HTML, 或教务 API/表单结构与预期不符)")
    else:
        print("\n✅ 不同学期课表有差异, 学期提交逻辑正常")


if __name__ == "__main__":
    main()
