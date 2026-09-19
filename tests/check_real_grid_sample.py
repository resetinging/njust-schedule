# -*- coding: utf-8 -*-
"""用真实保存的教务网格原文回归解析器(离线, 不联网)。

数据来源: python tests/read_classroom_form.py 会把最近一次响应存成
          tests/_classroom_grid_sample.html

用法: python tests/check_real_grid_sample.py [网格HTML路径]
"""
import io
import os
import sys

_here = os.path.dirname(os.path.abspath(__file__))
_root = os.path.dirname(_here)
sys.path.insert(0, _root)
sys.path.insert(0, os.path.join(_root, "wxcloudrun"))

# 导入 wxcloudrun 包会触发 db.create_all(); 用独立 sqlite 避免去连生产 MySQL
os.environ.setdefault(
    "SQLALCHEMY_DATABASE_URI",
    "sqlite:///" + os.path.join(_here, "smoke_tmp.db").replace("\\", "/"))

from wxcloudrun.jwc_client import ClassroomGridError, JWCClient  # noqa: E402


def main():
    p = sys.argv[1] if len(sys.argv) > 1 else os.path.join(_here, "_classroom_grid_sample.html")
    if not os.path.exists(p):
        print("找不到样本: %s" % p)
        print("先生成: python tests/read_classroom_form.py")
        return 2
    html = io.open(p, encoding="utf-8", errors="replace").read()
    print("样本: %s (%d 字节)" % (os.path.basename(p), len(html)))
    ok = 0
    for wd in range(1, 8):
        try:
            rooms = JWCClient.parse_free_classroom_grid(html, wd)
            print("  星期%d 空闲 %3d 间  前 6: %s" % (wd, len(rooms), rooms[:6]))
            ok += 1
        except ClassroomGridError as e:
            print("  星期%d 解析失败: %s" % (wd, e))
    print("结果: %d/7 个星期解析成功" % ok)
    return 0 if ok == 7 else 1


if __name__ == "__main__":
    sys.exit(main())
