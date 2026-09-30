# -*- coding: utf-8 -*-
"""服务器端密码存储的用例(sqlite 跑, 不连教务)。

覆盖: 加密保存后可取回 / 库里搜不到明文 / 换学号解不开 / 连续失败自动删除 /
      未配置密钥时拒绝保存 / 清理后取不到。
"""
import base64
import os
import sys

os.environ.setdefault("SQLALCHEMY_DATABASE_URI", "sqlite:///credential_store_test.db")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["SESSION_KEY"] = base64.b64encode(os.urandom(32)).decode()

from wxcloudrun.core import credential_store as cs  # noqa: E402
from wxcloudrun import dao  # noqa: E402

SID = "924101960123"
PWD = "Secret@2026"
RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append(ok)
    line = ("  [PASS] " if ok else "  [FAIL] ") + name
    if detail and not ok:
        line += " -> " + str(detail)
    print(line)


def main():
    cs.drop(SID)
    check("初始取不到", cs.resolve(SID) is None)
    check("保存成功", cs.save(SID, PWD) is True)
    check("能取回原密码", cs.resolve(SID) == PWD, cs.resolve(SID))
    raw = dao.get_user_setting(SID, "credential", "")
    check("库里搜不到明文", PWD not in raw and len(raw) > 20, raw[:24])
    check("换学号解不开(AAD)", cs._load("924101960999") is None)
    cs.mark_used(SID)
    check("mark_used 后仍可取回", cs.resolve(SID) == PWD)
    cs.mark_fail(SID)
    cs.mark_fail(SID)
    check("失败 2 次仍保留", cs.resolve(SID) == PWD)
    cs.mark_fail(SID)
    check("失败 3 次自动删除", cs.resolve(SID) is None)
    cs.save(SID, PWD)
    cs.drop(SID)
    check("drop 后取不到", cs.resolve(SID) is None)
    os.environ["SESSION_KEY"] = ""
    import config as _cfg
    _cfg.SESSION_KEY = ""
    from wxcloudrun.core import cookie_crypto
    cookie_crypto._KEY_LOADED = False
    check("无密钥时拒绝保存(不落明文)", cs.save(SID, PWD) is False)
    bad = sum(1 for r in RESULTS if not r)
    print("\n结果: %d 通过, %d 失败" % (len(RESULTS) - bad, bad))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
