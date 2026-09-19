# -*- coding: utf-8 -*-
"""用真实保存的教室借用页结果原文回归解析器(离线, 不联网)。

数据来源: python tests/read_borrow_form.py --skip-form --query
          会把结果存成 tests/_borrow_result_<tag>.html
用法: python tests/check_real_borrow_sample.py [结果HTML路径]
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

from wxcloudrun.jwc_client import JWCClient  # noqa: E402


def main():
    p = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
        _here, "_borrow_result_week3_wed_6-7_free.html")
    if not os.path.exists(p):
        print("找不到样本: %s" % p)
        print("先生成: python tests/read_borrow_form.py --skip-form --query")
        return 2
    html = io.open(p, encoding="utf-8", errors="replace").read()
    rooms = JWCClient.parse_borrow_free_list(html)
    print("样本: %s (%d 字节)" % (os.path.basename(p), len(html)))
    print("空闲教室 %d 间; 前 10: %s" % (len(rooms), rooms[:10]))
    assert len(rooms) >= 150, "数量异常: %d" % len(rooms)
    assert all("(" not in r and ")" not in r for r in rooms), "容量后缀未去掉"
    bad = [r for r in rooms if r.startswith(
        ("347-", "359-", "366-", "367-", "368-", "373-", "99-", "74栋", "384栋",
         "线上", "其它教室"))]
    assert not bad, "未映射/非实体条目泄漏: %s" % bad
    assert any(r.startswith("Ⅳ教学楼-") for r in rooms), "缺少 Ⅳ教学楼 教室"
    assert any(r.startswith("东区平房-") for r in rooms), "缺少 东区平房 教室"
    print("结果: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
