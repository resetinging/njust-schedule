# -*- coding: utf-8 -*-
"""教务页面巡检 — 检查后端依赖的教务页面结构是否仍然兼容。

用途: 怀疑教务改版 / 出现解析异常时, 一条命令确认各页面解析是否正常。
凭据: 默认用服务账号(config.FREE_CLASSROOM_SID / FREE_CLASSROOM_PWD,
      密码缺省按初始规则 学号@Njust); 也可用 NJUST_SID / NJUST_SSO_PWD 覆盖。

用法: python tests/check_jw_pages.py
退出码: 0 = 全部正常; 1 = 有解析失败/异常; 2 = 缺凭据
"""
import json
import os
import sys
import time

_here = os.path.dirname(os.path.abspath(__file__))
_root = os.path.dirname(_here)
sys.path.insert(0, _root)
sys.path.insert(0, os.path.join(_root, "wxcloudrun"))

# 导入 wxcloudrun 会触发 db.create_all(): 用独立 sqlite 避免连生产 MySQL
os.environ.setdefault(
    "SQLALCHEMY_DATABASE_URI",
    "sqlite:///" + os.path.join(_here, "smoke_tmp.db").replace("\\", "/"))

import config  # noqa: E402
from wxcloudrun.jwc_client import JWCClient  # noqa: E402


def main():
    sid = (os.environ.get("NJUST_SID") or config.FREE_CLASSROOM_SID or "").strip()
    pwd = os.environ.get("NJUST_SSO_PWD") or config.FREE_CLASSROOM_PWD or \
        (f"{sid}@Njust" if sid else "")
    if not (sid and pwd):
        print("缺少凭据: 设置 NJUST_SID / NJUST_SSO_PWD, 或配置 FREE_CLASSROOM_SID / FREE_CLASSROOM_PWD")
        return 2

    c = JWCClient()
    t0 = time.time()
    ok = c.login(sid, pwd)
    print("登录: %s (方式=%s, %.1fs, last_error=%r)" % (
        ok, c.login_method, time.time() - t0, c.last_error))
    if not ok:
        return 1

    sems = c.get_semester_list()
    brief = sems if len(sems) <= 4 else [sems[0], sems[1], "…", sems[-2], sems[-1]]
    print("学期列表: %d 个 %s" % (len(sems), brief))
    try:
        cur = c._current_semester()
    except Exception:
        cur = ""
    if not cur and sems:
        cur = sems[-1]
    print("当前学期: %r" % cur)

    checks = [
        ("课表 get_schedule", lambda: c.get_schedule(cur)),
        ("考试 get_exams", lambda: c.get_exams(cur)),
        ("成绩 get_grades", lambda: c.get_grades(cur)),
        ("四六级 get_cet_scores", lambda: c.get_cet_scores()),
        ("评教 get_evaluations", lambda: c.get_evaluations(cur)),
        ("空教室 get_free_classrooms", lambda: c.get_free_classrooms(
            campus="孝陵卫", weekday=3, jc1=6, jc2=7, week=3, semester=cur)),
    ]
    failures = 0
    for name, fn in checks:
        t = time.time()
        try:
            r = fn()
        except Exception as e:
            print("%-28s 异常 %r" % (name, e))
            failures += 1
            continue
        err = c.last_error
        n = len(r) if isinstance(r, list) else \
            (len((r or {}).get("rooms") or []) if isinstance(r, dict) else -1)
        if err:
            failures += 1
        print("%-28s %-6s n=%-5s %.1fs last_error=%r" % (
            name, "OK" if not err else "解析失败", n, time.time() - t, err))
        if isinstance(r, list) and r:
            print("     sample: %s" % json.dumps(r[0], ensure_ascii=False)[:110])

    print("结果: %s" % ("全部正常" if not failures else "%d 项失败" % failures))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
